"""主窗口"""
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QIcon

from qfluentwidgets import (
    FluentWindow, 
    NavigationInterface,
    NavigationItemPosition,
    FluentIcon as FIF,
    Theme, 
    setTheme
)

from .download_panel import DownloadPanel
from .settings_panel import SettingsPanel
from .queue_panel import QueuePanel
from ..models import AppConfig


class MainWindow(FluentWindow):
    """主窗口"""
    
    closing = Signal()
    
    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        
        # 设置窗口属性
        self.setWindowTitle("网站文件自动下载器")
        self.resize(config.window_width, config.window_height)
        self.setMinimumSize(QSize(900, 600))
        
        # 创建面板
        self.downloadPanel = DownloadPanel(config, self)
        self.queuePanel = QueuePanel(self)
        self.settingsPanel = SettingsPanel(config, self)
        
        # 初始化导航
        self._init_navigation()
        
        # 应用主题
        self.apply_theme(config.theme)
    
    def _init_navigation(self):
        """初始化导航栏"""
        # 添加导航项
        self.addSubInterface(
            self.downloadPanel,
            FIF.DOWNLOAD,
            "下载",
            position=NavigationItemPosition.TOP
        )
        
        self.addSubInterface(
            self.queuePanel,
            FIF.LIBRARY,
            "下载队列",
            position=NavigationItemPosition.TOP
        )
        
        self.addSubInterface(
            self.settingsPanel,
            FIF.SETTING,
            "设置",
            position=NavigationItemPosition.BOTTOM
        )
    
    def apply_theme(self, theme: str):
        """应用主题"""
        if theme == "dark":
            setTheme(Theme.DARK)
        elif theme == "light":
            setTheme(Theme.LIGHT)
        else:
            setTheme(Theme.AUTO)
    
    def closeEvent(self, e):
        """关闭事件"""
        self.closing.emit()
        self.config.window_width = self.width()
        self.config.window_height = self.height()
        self.config.save()
        e.accept()
