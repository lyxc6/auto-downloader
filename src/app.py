"""应用主类"""
import logging
import sys
import signal
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from .utils.logger import setup_logging
from .models import AppConfig, CacheManager
from .controllers import DownloadController, ScanController
from .views import MainWindow

logger = logging.getLogger(__name__)


class Application:
    """应用主类"""
    
    def __init__(self):
        # 初始化日志
        setup_logging()
        logger.info("应用启动")
        
        # 创建QApplication
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("网站文件自动下载器")
        self.app.setApplicationVersion("2.0.0")
        
        # 设置高DPI支持
        self.app.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        
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
        
        # 连接信号
        self._connect_signals()
        
        # 设置信号处理（Ctrl+C）
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _connect_signals(self):
        """连接信号"""
        # 下载面板信号
        download_panel = self.window.downloadPanel
        
        # 扫描信号
        download_panel.scan_requested.connect(self._start_scan)
        download_panel.refresh_requested.connect(self._start_refresh)
        download_panel.stop_scan_btn.clicked.connect(self.scan_controller.cancel_scan)
        
        # 下载信号
        download_panel.download_requested.connect(self._start_download)
        download_panel.stop_download_btn.clicked.connect(self.download_controller.cancel_download)
        
        # 控制器信号
        self.scan_controller.item_found.connect(
            lambda item: self.window.downloadPanel.add_item(item)
        )
        self.scan_controller.log_message.connect(download_panel.add_log)
        self.scan_controller.scan_progress.connect(
            lambda f, d: download_panel.update_stats(f, d, len(self.cache_manager.checked_items))
        )
        self.scan_controller.scan_completed.connect(self._on_scan_completed)
        
        self.download_controller.log_message.connect(download_panel.add_log)
        self.download_controller.progress_updated.connect(
            lambda id, dl, total: self.window.queuePanel.update_progress(id, dl, total)
        )
        self.download_controller.status_changed.connect(
            lambda id, status: self.window.queuePanel.update_status(id, status)
        )
        self.download_controller.batch_completed.connect(self._on_download_completed)
        
        # 设置面板信号
        self.window.settingsPanel.theme_changed.connect(self.window._apply_theme)
        self.window.closing.connect(self._on_app_closing)
    
    def _start_scan(self, url: str):
        """开始扫描"""
        self.config.last_url = url
        self.config.save()
        
        self.window.downloadPanel.log_widget.clear()
        
        # 相同URL且有缓存数据，直接从缓存恢复
        if self.cache_manager.has_data_for(url):
            logger.info("使用缓存数据恢复目录树: %s", url)
            self.window.downloadPanel.clear_tree()
            items = self.cache_manager.get_all_items()
            for item in items:
                self.window.downloadPanel.add_item(item)
            stats = self.cache_manager.get_stats()
            self.window.downloadPanel.update_stats(
                stats['total_files'], stats['total_dirs'], stats['checked_count']
            )
            self.window.downloadPanel.download_btn.setEnabled(stats['total_files'] > 0)
            self.window.downloadPanel.add_log("=" * 50, "header")
            self.window.downloadPanel.add_log("从缓存加载目录结构", "info")
            self.window.downloadPanel.add_log(f"文件: {stats['total_files']}, 目录: {stats['total_dirs']}", "info")
            self.window.downloadPanel.add_log("=" * 50, "header")
            return
        
        self.window.downloadPanel.set_scanning(True)
        self.window.downloadPanel.clear_tree()
        
        self.scan_controller.start_scan(url)
    
    def _start_refresh(self, url: str):
        """强制刷新扫描（忽略缓存，保留已选状态）"""
        self.config.last_url = url
        self.config.save()
        
        self.window.downloadPanel.log_widget.clear()
        self.window.downloadPanel.set_scanning(True)
        self.window.downloadPanel.clear_tree()
        
        logger.info("强制刷新扫描: %s", url)
        self.scan_controller.start_scan(url)
    
    def _on_scan_completed(self, file_count: int, dir_count: int):
        """扫描完成"""
        self.window.downloadPanel.set_scanning(False)
        self.window.downloadPanel.download_btn.setEnabled(file_count > 0)
        
        # 更新统计
        stats = self.cache_manager.get_stats()
        self.window.downloadPanel.update_stats(
            stats['total_files'],
            stats['total_dirs'],
            stats['checked_count']
        )
    
    def _start_download(self):
        """开始下载"""
        # 从目录树同步勾选状态到缓存
        tree_checked = self.window.downloadPanel.tree_widget.get_checked_items()
        self.cache_manager.set_checked_items(tree_checked)
        
        # 获取选中的文件
        checked_files = self.cache_manager.get_checked_files()
        
        if not checked_files:
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.warning(
                title="警告",
                content="请先选择要下载的文件",
                parent=self.window,
                position=InfoBarPosition.TOP
            )
            return
        
        # 添加到队列
        for item in checked_files:
            self.window.queuePanel.add_item(item.item_id, item.name)
        
        # 开始下载
        self.window.downloadPanel.set_downloading(True)
        self.download_controller.start_download(checked_files)
    
    def _on_download_completed(self, stats_dict: dict):
        """下载完成"""
        self.window.downloadPanel.set_downloading(False)
        self.cache_manager.save(self.config.last_url)
        logger.info("下载完成，缓存已保存")
    
    def _signal_handler(self, sig, frame):
        """信号处理器"""
        logger.info("收到退出信号，保存缓存...")
        self.cache_manager.save(self.config.last_url)
        logger.info("应用退出")
        sys.exit(0)
    
    def _on_app_closing(self):
        """应用关闭前保存"""
        logger.info("窗口关闭，保存缓存...")
        self.cache_manager.save(self.config.last_url)
        if self.scan_controller._service:
            self.scan_controller._service.close()
        if self.download_controller._service:
            self.download_controller._service.close()
    
    def run(self) -> int:
        """运行应用"""
        logger.info("显示主窗口")
        self.window.show()
        result = self.app.exec()
        logger.info("应用事件循环结束")
        return result
