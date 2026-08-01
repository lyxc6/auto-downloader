"""主窗口"""

from PySide6.QtCore import QSize, Signal
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import FluentWindow, NavigationItemPosition, Theme, setTheme

from .. import WINDOW_TITLE
from ..models import AppConfig
from .download_panel import DownloadPanel
from .queue_panel import QueuePanel
from .settings_panel import SettingsPanel


class MainWindow(FluentWindow):
    """主窗口"""

    closing = Signal()

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config

        # 设置窗口属性
        self.setWindowTitle(WINDOW_TITLE)
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
        self.addSubInterface(self.downloadPanel, FIF.DOWNLOAD, "下载", position=NavigationItemPosition.TOP)

        self.addSubInterface(self.queuePanel, FIF.LIBRARY, "下载队列", position=NavigationItemPosition.TOP)

        self.addSubInterface(self.settingsPanel, FIF.SETTING, "设置", position=NavigationItemPosition.BOTTOM)

    def apply_theme(self, theme: str):
        """应用主题"""
        theme_map = {"dark": Theme.DARK, "light": Theme.LIGHT}
        setTheme(theme_map.get(theme, Theme.AUTO))

    def closeEvent(self, e):
        """关闭事件：通知应用层执行退出序列（尺寸持久化由 app.py 统一处理）"""
        self.closing.emit()
        e.accept()
