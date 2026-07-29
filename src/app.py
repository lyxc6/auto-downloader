"""应用主类"""

import logging
import signal
import sys
import threading
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication
from qfluentwidgets import InfoBar, InfoBarPosition, MessageDialog

from . import __version__
from .controllers import DownloadController, ScanController
from .models import AppConfig, CacheManager, DownloadItem
from .services import UpdateChecker, cleanup_old_exe
from .services.update_checker import GITHUB_RELEASES_URL
from .utils.logger import setup_logging
from .views import MainWindow

logger = logging.getLogger(__name__)


class Application:
    """应用主类"""

    def __init__(self):
        # 初始化日志
        setup_logging()
        logger.info("应用启动")

        # 清理旧版本残留文件
        cleanup_old_exe()

        # 设置高DPI支持
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

        # 创建QApplication
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("网站文件自动下载器")
        self.app.setApplicationVersion(__version__)

        # 加载配置
        self.config = AppConfig.load()

        # 创建缓存管理器
        self.cache_manager = CacheManager(self.config.cache_file)
        self.cache_manager.load()

        # 创建控制器
        self.download_controller = DownloadController(self.config)
        self.scan_controller = ScanController(self.config, self.cache_manager)

        # 创建更新检查器
        self.update_checker = UpdateChecker()

        # 创建主窗口
        self.window = MainWindow(self.config)

        # 连接信号
        self._connect_signals()

        # SIGINT 安全化：信号处理器只置位事件，由主线程定时器轮询处理
        self._shutdown_event = threading.Event()
        self._shutdown_done = False
        self._shutdown_timer: QTimer | None = None
        signal.signal(signal.SIGINT, self._signal_handler)
        self._start_shutdown_poller()

        self._auto_save_timer = QTimer(self.window)
        self._auto_save_timer.setInterval(30000)
        self._auto_save_timer.timeout.connect(self.cache_manager.save)

        # URL 输入防抖定时器（用于更新扫描按钮状态）
        self._scan_button_debounce_timer = QTimer(self.window)
        self._scan_button_debounce_timer.setSingleShot(True)
        self._scan_button_debounce_timer.setInterval(500)
        self._scan_button_debounce_timer.timeout.connect(self._update_scan_button)

    def _connect_signals(self):
        """连接信号"""
        # 下载面板信号
        download_panel = self.window.downloadPanel

        # 扫描信号：视图层 → 控制器
        download_panel.scan_requested.connect(self._on_scan_requested)
        download_panel.refresh_requested.connect(self._on_refresh_requested)
        download_panel.refresh_directory_requested.connect(self._on_directory_refresh_requested)
        download_panel.stop_scan_btn.clicked.connect(self.scan_controller.cancel_scan)

        # 下载信号：视图层 → 控制器
        download_panel.download_requested.connect(self._on_download_requested)
        download_panel.stop_download_btn.clicked.connect(self.download_controller.cancel_download)

        # 控制器信号 → 视图层
        self.scan_controller.items_found.connect(download_panel.add_items_batch)
        self.scan_controller.log_message.connect(download_panel.add_log)
        self.scan_controller.scan_progress.connect(self._on_scan_progress)
        self.scan_controller.scan_completed.connect(self._on_scan_completed)
        self.scan_controller.scan_error.connect(self._on_scan_error)
        self.scan_controller.dir_scanned.connect(self.window.downloadPanel.tree_widget.mark_dir_scanned)

        # 缓存相关信号
        self.scan_controller.cache_load_completed.connect(self._on_cache_load_completed)

        self.download_controller.log_message.connect(download_panel.add_log)
        self.download_controller.progress_updated.connect(self._on_download_progress)
        self.download_controller.status_changed.connect(self._on_download_status)
        self.download_controller.batch_completed.connect(self._on_download_completed)
        self.download_controller.download_validated.connect(self._on_download_validated)

        # 设置面板信号
        self.window.settingsPanel.theme_changed.connect(self.window.apply_theme)
        self.window.settingsPanel.config_changed.connect(self._on_config_changed)
        self.window.settingsPanel.check_update_requested.connect(self._on_check_update_requested)
        self.window.closing.connect(self._on_app_closing)

        # 更新检查器信号
        self.update_checker.check_finished.connect(self._on_update_check_finished)
        self.update_checker.check_error.connect(self._on_update_check_error)
        self.update_checker.download_progress.connect(self._on_update_download_progress)
        self.update_checker.download_finished.connect(self._on_update_download_finished)
        self.update_checker.download_error.connect(self._on_update_download_error)

        self.window.downloadPanel.tree_widget.set_check_sync_callback(self._on_checked_changed)

        # URL 输入变化 → 防抖更新扫描按钮状态
        self.window.downloadPanel.url_input.textChanged.connect(self._on_url_text_changed)

    def _start_auto_save(self):
        self._auto_save_timer.start()

    def _stop_auto_save_if_idle(self):
        if not self.scan_controller.is_scanning and not self.download_controller.is_downloading:
            self._auto_save_timer.stop()

    def _on_checked_changed(self, checked_ids: set[str]) -> None:
        """勾选状态变化：同步到缓存并实时更新已选统计"""
        self.cache_manager.set_checked_items(checked_ids)
        stats = self.cache_manager.get_stats()
        self.window.downloadPanel.update_stats(stats["total_files"], stats["total_dirs"], stats["checked_count"])

    def _on_url_text_changed(self):
        """URL 输入变化防抖 → 更新扫描按钮状态"""
        self._scan_button_debounce_timer.start()

    def _update_scan_button(self):
        """根据缓存状态更新扫描按钮文字（扫描目录 / 继续扫描）"""
        url = self.window.downloadPanel.url_input.text().strip()
        has_cache = self.cache_manager.has_data_for(url)
        scan_done = self.cache_manager.is_scan_complete()
        self.window.downloadPanel.set_scan_button_mode(has_cache and not scan_done)

    def _auto_load_cache(self):
        """启动时自动加载缓存目录树到 UI"""
        url = self.config.last_url
        if url and self.cache_manager.has_data_for(url):
            logger.info("启动时自动加载缓存: %s", url)
            self.scan_controller.cache_load_completed.emit(
                self.cache_manager.get_tree_data_snapshot(), self.cache_manager.checked_items
            )

    # ==================== 扫描相关回调 ====================

    def _on_scan_requested(self, url: str):
        """扫描请求处理"""
        if self.scan_controller.is_scanning:
            return

        self.config.last_url = url
        self.config.save()

        self.window.downloadPanel.log_widget.clear()
        self.window.downloadPanel.set_scanning(True)
        self.window.downloadPanel.download_btn.setEnabled(False)
        self._start_auto_save()

        # 默认启用并行扫描（scan_max_workers > 1 时）
        parallel = self.config.scan_max_workers > 1
        self.scan_controller.start_scan_with_cache(url, self.config.scan_mode, parallel=parallel)

    def _on_refresh_requested(self, url: str):
        """刷新请求处理"""
        if self.scan_controller.is_scanning:
            return

        # 清除 Widget 内部数据，防止僵尸节点残留
        tw = self.window.downloadPanel.tree_widget
        checked_backup = set(self.cache_manager.checked_items)
        tw.clear_all()
        tw._checked_set = checked_backup  # 恢复已选集，新到达节点能正确显示勾选状态

        self.config.last_url = url
        self.config.save()

        self.window.downloadPanel.log_widget.clear()
        self.window.downloadPanel.set_scanning(True)
        self.window.downloadPanel.download_btn.setEnabled(False)
        self._start_auto_save()

        # 默认启用并行扫描
        parallel = self.config.scan_max_workers > 1
        self.scan_controller.start_refresh(url, self.config.scan_mode, parallel=parallel)

    def _on_directory_refresh_requested(self, item_id: str):
        """目录刷新请求处理"""
        item = self.cache_manager.get_item(item_id)
        if item is None or not item.is_dir:
            return

        base_url = self.cache_manager.url
        if not base_url:
            InfoBar.error(
                title="错误", content="无有效URL，请先执行一次扫描", parent=self.window, position=InfoBarPosition.TOP
            )
            return

        # 删除子节点
        tw = self.window.downloadPanel.tree_widget
        tw.remove_children_of(item_id)
        tw.mark_loaded(item_id)

        # 更新统计
        stats = self.cache_manager.get_stats()
        self.window.downloadPanel.update_stats(stats["total_files"], stats["total_dirs"], stats["checked_count"])

        self.window.downloadPanel.set_scanning(True)
        self.window.downloadPanel.download_btn.setEnabled(False)
        self._start_auto_save()

        parallel = self.config.scan_max_workers > 1
        self.scan_controller.start_directory_refresh(base_url, item_id, item.full_path, item.parent_id, self.config.scan_mode, parallel=parallel)

    def _on_cache_load_completed(self, tree_data: dict, checked_items: set):
        """缓存加载完成：更新视图层"""
        self.window.downloadPanel.clear_tree()
        self.window.downloadPanel.tree_widget.load_from_items(tree_data)
        self.window.downloadPanel.tree_widget.apply_checked_items(checked_items)

        stats = self.cache_manager.get_stats()
        self.window.downloadPanel.update_stats(stats["total_files"], stats["total_dirs"], stats["checked_count"])
        self.window.downloadPanel.download_btn.setEnabled(stats["total_files"] > 0)
        self._update_scan_button()

        # 显示目录扫描状态
        self.window.downloadPanel.tree_widget.apply_scan_status(self.cache_manager.get_unscanned_dirs())

    def _on_scan_progress(self, files: int, dirs: int):
        """扫描进度更新"""
        self.window.downloadPanel.update_stats(files, dirs, len(self.cache_manager.checked_items))

    def _on_scan_completed(self, file_count: int, dir_count: int):
        """扫描完成"""
        self.window.downloadPanel.set_scanning(False)
        self.window.downloadPanel.download_btn.setEnabled(file_count > 0)

        # 更新统计
        stats = self.cache_manager.get_stats()
        self.window.downloadPanel.update_stats(stats["total_files"], stats["total_dirs"], stats["checked_count"])

        self._stop_auto_save_if_idle()
        self._update_scan_button()

        # 刷新目录扫描状态
        self.window.downloadPanel.tree_widget.apply_scan_status(self.cache_manager.get_unscanned_dirs())

    def _on_scan_error(self, error_msg: str):
        """扫描失败"""
        self._stop_auto_save_if_idle()

    # ==================== 下载相关回调 ====================

    def _on_download_requested(self):
        """下载请求处理"""
        # 从目录树取勾选文件
        checked_files = self.window.downloadPanel.tree_widget.get_checked_files()

        if not checked_files:
            InfoBar.warning(
                title="警告", content="请先选择要下载的文件", parent=self.window, position=InfoBarPosition.TOP
            )
            return

        # 设置下载状态
        self.window.downloadPanel.set_downloading(True)
        self._start_auto_save()

        # 调用控制器（带验证）
        self.download_controller.start_download_with_validation(checked_files)

    def _on_download_validated(self, checked_files: list[DownloadItem]):
        """下载验证通过：添加到队列"""
        for item in checked_files:
            self.window.queuePanel.add_item(item.item_id, item.name)

    def _on_download_progress(self, item_id: str, downloaded: int, total_size: int):
        """下载进度更新"""
        self.window.queuePanel.update_progress(item_id, downloaded, total_size)

    def _on_download_status(self, item_id: str, status: str):
        """下载状态更新"""
        self.window.queuePanel.update_status(item_id, status)

    def _on_download_completed(self, stats_dict: dict[str, Any]) -> None:
        """下载完成"""
        self.window.downloadPanel.set_downloading(False)
        self.cache_manager.save()
        logger.info("下载完成，缓存已保存")
        self._stop_auto_save_if_idle()

    # ==================== 其他回调 ====================

    def _on_check_update_requested(self, channel: str, version: str, last_check_time: str):
        """手动检查更新请求"""
        self.update_checker.check_update(channel, version, last_check_time)

    def _on_update_check_finished(self, result: dict):
        """更新检查完成"""
        self.window.settingsPanel.on_check_update_finished()

        if result.get("error"):
            InfoBar.warning(
                title="检查更新",
                content=result["error"],
                parent=self.window,
                position=InfoBarPosition.TOP,
                duration=3000,
            )
            return

        if result.get("has_update"):
            version = result.get("version", "")
            url = result.get("url", "")
            download_url = result.get("download_url", "")
            notes = result.get("notes", "")

            # 更新上次检查时间
            self.config.last_update_check_time = self.update_checker.get_current_check_time()
            self.config.save()

            if download_url:
                # 自动下载更新
                self.window.settingsPanel.on_update_downloading()
                InfoBar.info(
                    title="发现新版本",
                    content=f"发现新版本 v{version}，正在下载...",
                    parent=self.window,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                )
                self._pending_update_url = url
                self._pending_update_notes = notes
                self.update_checker.download_and_update(download_url)
            else:
                # 无下载地址，弹出手动下载对话框
                self._show_manual_update_dialog(url, version, notes)
        else:
            InfoBar.info(
                title="检查更新",
                content="已是最新版本",
                parent=self.window,
                position=InfoBarPosition.TOP,
                duration=2000,
            )

    def _show_manual_update_dialog(self, url: str, version: str, notes: str):
        """显示手动下载对话框"""
        dialog = MessageDialog(
            "发现新版本",
            f"发现新版本 v{version}\n\n{notes[:200]}{'...' if len(notes) > 200 else ''}",
            self.window,
        )
        dialog.yesButton.setText("前往下载")
        dialog.cancelButton.setText("取消")

        if dialog.exec():
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl(url))

    def _on_update_download_progress(self, percent: int):
        """更新下载进度"""
        self.window.settingsPanel.on_update_downloading(percent)

    def _on_update_download_finished(self):
        """更新下载完成，执行替换重启"""
        self.window.settingsPanel.on_update_finished()
        InfoBar.success(
            title="更新完成",
            content="新版本已下载完成，正在重启...",
            parent=self.window,
            position=InfoBarPosition.TOP,
            duration=2000,
        )

    def _on_update_download_error(self, error_msg: str):
        """更新下载失败，弹出手动下载对话框"""
        self.window.settingsPanel.on_update_finished()
        url = getattr(self, "_pending_update_url", GITHUB_RELEASES_URL)
        notes = getattr(self, "_pending_update_notes", "")
        self._show_manual_update_dialog(url, "最新", notes)
        InfoBar.warning(
            title="下载失败",
            content=f"自动下载失败: {error_msg}，请手动下载",
            parent=self.window,
            position=InfoBarPosition.TOP,
            duration=5000,
        )

    def _on_update_check_error(self, error_msg: str):
        """更新检查失败"""
        self.window.settingsPanel.on_check_update_finished()
        InfoBar.warning(
            title="检查更新",
            content=f"检查失败: {error_msg}",
            parent=self.window,
            position=InfoBarPosition.TOP,
            duration=3000,
        )

    def _signal_handler(self, sig: int, frame: object) -> None:
        """信号处理器：只置位事件，不在信号上下文做 I/O 或退出"""
        self._shutdown_event.set()

    def _start_shutdown_poller(self):
        """启动主线程定时器轮询退出事件（每 200ms）"""
        self._shutdown_timer = QTimer(self.window)
        self._shutdown_timer.setInterval(200)
        self._shutdown_timer.timeout.connect(self._check_shutdown)
        self._shutdown_timer.start()

    def _check_shutdown(self):
        """主线程回调：事件置位时保存缓存、关闭服务、退出应用（幂等）"""
        if self._shutdown_done:
            return
        if not self._shutdown_event.is_set():
            return
        self._shutdown_done = True
        if self._shutdown_timer is not None:
            self._shutdown_timer.stop()
        logger.info("收到退出信号，保存缓存...")
        self.cache_manager.save()
        self.scan_controller.close_service()
        self.download_controller.close_service()
        logger.info("应用退出")
        self.app.quit()

    def _on_app_closing(self):
        """应用关闭前保存"""
        logger.info("窗口关闭，保存缓存...")
        self.cache_manager.save()
        self.scan_controller.cancel_scan()
        self.download_controller.cancel_download()
        self.scan_controller.close_service()
        self.download_controller.close_service()

    def _on_config_changed(self, changes: dict[str, Any]) -> None:
        """配置变更通知：设置已保存，下一批次下载/扫描生效"""
        logger.info("配置已更改，下次操作生效: %s", changes)
        try:
            InfoBar.success(
                title="设置",
                content="已保存，下次下载/扫描应用新设置",
                parent=self.window,
                position=InfoBarPosition.TOP,
                duration=2000,
            )
        except Exception:
            # InfoBar 在无可用父窗口时可能失败，忽略 UI 提示不影响配置保存
            pass

    def run(self) -> int:
        """运行应用"""
        logger.info("显示主窗口")
        self.window.show()

        # 启动时清理旧版本残留
        cleanup_old_exe()

        # 启动时自动加载缓存目录树
        self._auto_load_cache()
        self._update_scan_button()

        # 启动时自动检查更新
        if self.config.auto_check_update:
            QTimer.singleShot(2000, self._auto_check_update)

        result = self.app.exec()
        logger.info("应用事件循环结束")
        return result

    def _auto_check_update(self):
        """启动时自动检查更新"""
        self.update_checker.check_update(self.config.update_channel, __version__, self.config.last_update_check_time)
