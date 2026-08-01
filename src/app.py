"""应用主类：组合根 + 信号接线 + 关停管理（扫描/下载流程见 presenters，更新流程见 UpdateFlow）"""

import logging
import signal
import sys
import threading
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication
from qfluentwidgets import InfoBar, InfoBarPosition

from . import __version__
from .controllers import DownloadController, ScanController
from .models import AppConfig, CacheManager
from .presenters import AutoSavePolicy, DownloadPresenter, ScanPresenter
from .services import UpdateChecker, cleanup_old_exe
from .update_flow import UpdateFlow
from .utils.logger import setup_logging
from .views import MainWindow

logger = logging.getLogger(__name__)


class Application:
    """应用主类：组合根 + 信号接线 + 关停管理"""

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

        # 创建主窗口
        self.window = MainWindow(self.config)

        # 创建更新检查器与更新流程
        self.update_checker = UpdateChecker()
        self._update_flow = UpdateFlow(self.config, self.window, self.window.settingsPanel, self.update_checker)

        # 自动保存策略（扫描/下载任一活动进行中每 30s 保存缓存）
        self._auto_save = AutoSavePolicy(
            save=self.cache_manager.save,
            is_busy=lambda: self.scan_controller.is_scanning or self.download_controller.is_downloading,
        )

        # 创建流程 presenter（扫描/下载视图状态转换与副作用）
        self.scan_presenter = ScanPresenter(
            self.config, self.cache_manager, self.scan_controller, self.window.downloadPanel, self._auto_save
        )
        self.download_presenter = DownloadPresenter(
            self.config,
            self.cache_manager,
            self.download_controller,
            self.window.downloadPanel,
            self.window.queuePanel,
            self._auto_save,
        )

        # 连接剩余信号（设置面板 / 更新流程 / 关停）
        self._connect_signals()

        # SIGINT 安全化：信号处理器只置位事件，由主线程定时器轮询处理
        self._shutdown_event = threading.Event()
        self._shutdown_done = False
        self._shutdown_timer: QTimer | None = None
        signal.signal(signal.SIGINT, self._signal_handler)
        self._start_shutdown_poller()

    def _connect_signals(self):
        """连接信号（扫描/下载流程信号已由各 presenter 自行接线）"""
        # 设置面板信号
        self.window.settingsPanel.theme_changed.connect(self.window.apply_theme)
        self.window.settingsPanel.config_changed.connect(self._on_config_changed)
        self.window.settingsPanel.check_update_requested.connect(self._update_flow.on_check_update_requested)
        self.window.closing.connect(self._on_app_closing)

        # 更新检查器信号 → 更新流程
        self._update_flow.connect_signals()

    # ==================== 关停处理 ====================

    def _signal_handler(self, sig: int, frame: object) -> None:
        """信号处理器：只置位事件，不在信号上下文做 I/O 或退出"""
        self._shutdown_event.set()

    def _start_shutdown_poller(self):
        """启动主线程定时器轮询退出事件（每 200ms）"""
        timer = QTimer(self.window)
        timer.setInterval(200)
        timer.timeout.connect(self._check_shutdown)
        timer.start()
        self._shutdown_timer = timer

    def _check_shutdown(self):
        """主线程回调：事件置位时执行统一退出序列并退出事件循环（幂等）"""
        if not self._shutdown_event.is_set():
            return
        if self._shutdown():
            self.app.quit()

    def _on_app_closing(self):
        """窗口关闭：执行统一退出序列（事件循环随后自然结束）"""
        logger.info("窗口关闭，执行退出序列...")
        self._shutdown()

    def _shutdown(self) -> bool:
        """统一退出序列：保存缓存 → 取消进行中任务 → 关闭服务（幂等，主线程调用）

        Returns:
            True 表示本次执行了退出序列（重复调用返回 False）
        """
        if self._shutdown_done:
            return False
        self._shutdown_done = True
        if self._shutdown_timer is not None:
            self._shutdown_timer.stop()
        logger.info("应用退出，保存缓存...")
        self.cache_manager.save()
        self.scan_controller.cancel_size_prefetch()
        self.scan_controller.cancel_scan()
        self.download_controller.cancel_download()
        self.scan_controller.close_service()
        self.download_controller.close_service()
        logger.info("应用服务已关闭")
        return True

    # ==================== 配置变更 ====================

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
        self.scan_controller.load_cache_into_ui(self.config.last_url)
        self.scan_presenter.update_scan_button()

        # 启动时自动检查更新
        if self.config.auto_check_update:
            QTimer.singleShot(2000, self._auto_check_update)

        result = self.app.exec()
        logger.info("应用事件循环结束")
        return result

    def _auto_check_update(self):
        """启动时自动检查更新"""
        self._update_flow.auto_check(self.config.update_channel, __version__, self.config.last_update_check_time)
