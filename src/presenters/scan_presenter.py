"""扫描流程 presenter：视图/控制器信号 → 面板状态转换 + 扫描后副作用（大小预取）"""

import logging

from PySide6.QtCore import QObject, QTimer
from qfluentwidgets import InfoBar, InfoBarPosition

from ..controllers import ScanController
from ..models import AppConfig, CacheManager
from ..views.download_panel import DownloadPanel
from .auto_save import AutoSavePolicy

logger = logging.getLogger(__name__)


class ScanPresenter(QObject):
    """扫描流程 presenter：面板状态转换、扫描按钮防抖、扫描完成后的大小预取"""

    def __init__(
        self,
        config: AppConfig,
        cache_manager: CacheManager,
        scan_controller: ScanController,
        view: DownloadPanel,
        auto_save: AutoSavePolicy,
    ):
        super().__init__()
        self._config = config
        self._cache_manager = cache_manager
        self._scan_controller = scan_controller
        self._view = view
        self._auto_save = auto_save

        # URL 输入防抖定时器（用于更新扫描按钮状态）
        self._scan_button_debounce_timer = QTimer(self)
        self._scan_button_debounce_timer.setSingleShot(True)
        self._scan_button_debounce_timer.setInterval(500)
        self._scan_button_debounce_timer.timeout.connect(self.update_scan_button)

        self._connect_signals()

    def _connect_signals(self):
        """接线：视图信号 → 本 presenter 槽，控制器信号 → 本 presenter 槽/视图方法"""
        view = self._view
        controller = self._scan_controller

        # 视图 → presenter
        view.scan_requested.connect(self._on_scan_requested)
        view.refresh_requested.connect(self._on_refresh_requested)
        view.refresh_directory_requested.connect(self._on_directory_refresh_requested)
        view.stop_scan_clicked.connect(controller.cancel_scan)
        view.checked_changed.connect(self._on_checked_changed)
        view.url_text_changed.connect(self._on_url_text_changed)

        # 控制器信号 → 视图（无需状态转换，直连）
        controller.items_found.connect(view.add_items_batch)
        controller.log_message.connect(view.add_log)
        controller.dir_scanned.connect(view.apply_dir_scanned)

        # 控制器信号 → presenter 槽
        controller.scan_progress.connect(self._on_scan_progress)
        controller.scan_completed.connect(self._on_scan_completed)
        controller.scan_error.connect(self._on_scan_error)
        controller.cache_load_completed.connect(self._on_cache_load_completed)
        controller.size_prefetch_progress.connect(self._on_size_prefetch_progress)
        controller.size_prefetch_completed.connect(self._on_size_prefetch_completed)

    # ==================== 勾选同步与按钮状态 ====================

    def _on_checked_changed(self, checked_ids: set[str]) -> None:
        """勾选状态变化：同步到缓存并实时更新已选统计"""
        self._cache_manager.set_checked_items(checked_ids)
        stats = self._cache_manager.get_stats()
        self._view.update_stats(stats.total_files, stats.total_dirs, stats.checked_count)

    def _on_url_text_changed(self):
        """URL 输入变化防抖 → 更新扫描按钮状态"""
        self._scan_button_debounce_timer.start()

    def update_scan_button(self):
        """根据缓存状态更新扫描按钮文字（扫描目录 / 继续扫描）"""
        url = self._view.get_url_text()
        has_cache = self._cache_manager.has_data_for(url)
        scan_done = self._cache_manager.is_scan_complete()
        self._view.set_scan_button_mode(has_cache and not scan_done)

    # ==================== 扫描请求 ====================

    def _on_scan_requested(self, url: str):
        """扫描请求处理"""
        if self._scan_controller.is_scanning:
            return

        self._config.last_url = url
        self._config.save()

        self._view.clear_log()
        self._view.set_scanning(True)
        self._view.set_download_enabled(False)
        self._auto_save.start()

        # 默认启用并行扫描（scan_max_workers > 1 时）
        parallel = self._config.scan_max_workers > 1
        self._scan_controller.start_scan_with_cache(url, self._config.scan_mode, parallel=parallel)

    def _on_refresh_requested(self, url: str):
        """刷新请求处理"""
        if self._scan_controller.is_scanning:
            return

        # 清除 Widget 内部数据，防止僵尸节点残留
        checked_backup = self._cache_manager.checked_items_snapshot()
        self._view.prepare_refresh(checked_backup)

        self._config.last_url = url
        self._config.save()

        self._view.clear_log()
        self._view.set_scanning(True)
        self._view.set_download_enabled(False)
        self._auto_save.start()

        # 默认启用并行扫描
        parallel = self._config.scan_max_workers > 1
        self._scan_controller.start_refresh(url, self._config.scan_mode, parallel=parallel)

    def _on_directory_refresh_requested(self, item_id: str):
        """目录刷新请求处理"""
        item = self._cache_manager.get_item(item_id)
        if item is None or not item.is_dir:
            return

        base_url = self._cache_manager.url
        if not base_url:
            InfoBar.error(
                title="错误", content="无有效URL，请先执行一次扫描", parent=self._view, position=InfoBarPosition.TOP
            )
            return

        # 删除子节点
        self._view.prepare_directory_refresh(item_id)

        # 更新统计
        stats = self._cache_manager.get_stats()
        self._view.update_stats(stats.total_files, stats.total_dirs, stats.checked_count)

        self._view.set_scanning(True)
        self._view.set_download_enabled(False)
        self._auto_save.start()

        parallel = self._config.scan_max_workers > 1
        self._scan_controller.start_directory_refresh(
            base_url, item_id, item.full_path, item.parent_id, self._config.scan_mode, parallel=parallel
        )

    # ==================== 扫描结果回调 ====================

    def _on_cache_load_completed(self, tree_data: dict, checked_items: set):
        """缓存加载完成：更新视图层"""
        self._view.apply_cache_loaded(tree_data, checked_items)

        stats = self._cache_manager.get_stats()
        self._view.update_stats(stats.total_files, stats.total_dirs, stats.checked_count)
        self._view.set_download_enabled(stats.total_files > 0)
        self.update_scan_button()

        # 显示目录扫描状态
        self._view.apply_scan_status(self._cache_manager.get_unscanned_dirs())

    def _on_scan_progress(self, files: int, dirs: int):
        """扫描进度更新"""
        self._view.update_stats(files, dirs, self._cache_manager.checked_count())

    def _on_scan_completed(self, file_count: int, dir_count: int, dir_path: str = ""):
        """扫描完成"""
        self._view.set_scanning(False)
        self._view.set_download_enabled(file_count > 0)

        # 更新统计
        stats = self._cache_manager.get_stats()
        self._view.update_stats(stats.total_files, stats.total_dirs, stats.checked_count)

        self._auto_save.stop_if_idle()
        self.update_scan_button()

        # 刷新目录扫描状态
        self._view.apply_scan_status(self._cache_manager.get_unscanned_dirs())

        # 方案B：大小预取已随扫描启动（边扫边取），无需在此额外启动；
        # 扫描正常完成时 controller 已调用 prefetch.done()，队列耗尽后发 completed

    def _on_scan_error(self, error_msg: str):
        """扫描失败"""
        self._view.set_scanning(False)
        self._auto_save.stop_if_idle()
        InfoBar.warning(
            title="扫描失败",
            content=error_msg,
            position=InfoBarPosition.TOP_RIGHT,
            isClosable=True,
            duration=5000,
            parent=self._view,
        )

    def _on_size_prefetch_progress(self, item_id: str, size: int):
        """文件大小预取进度：更新单个节点的大小显示"""
        self._view.update_item_size(item_id)

    def _on_size_prefetch_completed(self):
        """文件大小预取完成"""
        self._auto_save.stop_if_idle()
        stats = self._cache_manager.get_stats()
        self._view.update_stats(stats.total_files, stats.total_dirs, stats.checked_count)
