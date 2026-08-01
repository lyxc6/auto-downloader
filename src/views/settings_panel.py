"""设置面板"""

from collections.abc import Callable

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    ComboBoxSettingCard,
    OptionsSettingCard,
    PrimaryPushButton,
    PushButton,
    SettingCard,
    SettingCardGroup,
    SmoothScrollArea,
    SpinBox,
    StrongBodyLabel,
    SwitchButton,
    Theme,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)
from qfluentwidgets.common.config import OptionsConfigItem, OptionsValidator

from .. import __version__
from ..models import AppConfig
from ..services.update_logic import GITHUB_RELEASES_URL

# 主题字符串 ↔ Fluent Theme 枚举映射（唯一真值源）
_THEME_TO_STR: dict[Theme, str] = {Theme.LIGHT: "light", Theme.DARK: "dark", Theme.AUTO: "auto"}
_STR_TO_THEME: dict[str, Theme] = {"light": Theme.LIGHT, "dark": Theme.DARK, "auto": Theme.AUTO}


class SpinBoxSettingCard(SettingCard):
    """自定义SpinBox设置卡片"""

    valueChanged = Signal(int)

    def __init__(self, min_val, max_val, step, icon, title, content=None, parent=None):
        super().__init__(icon, title, content, parent)
        self.spin_box = SpinBox(self)
        self.spin_box.setRange(min_val, max_val)
        self.spin_box.setSingleStep(step)
        self.spin_box.setMinimumWidth(120)

        self.hBoxLayout.addWidget(self.spin_box, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(16)

        self.spin_box.valueChanged.connect(self.valueChanged.emit)

    def setValue(self, value):
        self.spin_box.setValue(value)

    def value(self):
        return self.spin_box.value()


class FolderSettingCard(SettingCard):
    """自定义文件夹设置卡片"""

    folderChanged = Signal(str)

    def __init__(self, default_folder, icon, title, content=None, parent=None):
        super().__init__(icon, title, content, parent)
        self.folder = default_folder

        self.folder_label = BodyLabel(default_folder, self)
        self.folder_label.setMinimumWidth(200)

        self.contentLabel.hide()
        self.hBoxLayout.addWidget(self.folder_label)
        self.hBoxLayout.addSpacing(8)

        self.btn = PushButton("选择", self)
        self.btn.clicked.connect(self._select_folder)
        self.hBoxLayout.addWidget(self.btn)
        self.hBoxLayout.addSpacing(16)

    def _select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择下载目录", self.folder)
        if folder:
            self.folder = folder
            self.folder_label.setText(folder)
            self.folderChanged.emit(folder)

    def setFolder(self, folder):
        self.folder = folder
        self.folder_label.setText(folder)


class SettingsPanel(QWidget):
    """设置面板"""

    # 信号定义
    theme_changed = Signal(str)
    config_changed = Signal(dict)
    check_update_requested = Signal(str, str, str)  # channel, version, last_check_time

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsPanel")
        self.config = config
        self._setup_ui()

    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 滚动区域
        scroll_area = SmoothScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(20, 20, 20, 20)
        scroll_layout.setSpacing(15)

        # 标题
        title = StrongBodyLabel("设置")
        scroll_layout.addWidget(title)

        scroll_layout.addWidget(self._build_download_group())
        scroll_layout.addWidget(self._build_scan_group())
        scroll_layout.addWidget(self._build_ui_group())
        scroll_layout.addWidget(self._build_update_group())

        scroll_layout.addStretch()

        scroll_area.setWidget(scroll_widget)
        scroll_area.setStyleSheet("background: transparent;")
        scroll_area.viewport().setStyleSheet("background: transparent;")
        scroll_widget.setStyleSheet("background: transparent;")
        layout.addWidget(scroll_area)

        # 连接信号
        self._connect_signals()

    def _build_download_group(self) -> SettingCardGroup:
        """下载设置组"""
        download_group = SettingCardGroup("下载设置", self)

        self.folder_card = FolderSettingCard(
            self.config.download_dir, FIF.DOWNLOAD, "下载目录", "设置文件保存位置", self
        )

        self.workers_card = SpinBoxSettingCard(1, 10, 1, FIF.PEOPLE, "并发下载数", "同时下载的文件数量", self)
        self.workers_card.setValue(self.config.max_workers)

        self.retry_card = SpinBoxSettingCard(0, 10, 1, FIF.SYNC, "重试次数", "下载失败时的重试次数", self)
        self.retry_card.setValue(self.config.retry_times)

        self.timeout_card = SpinBoxSettingCard(30, 300, 10, FIF.STOP_WATCH, "超时时间(秒)", "下载超时时间", self)
        self.timeout_card.setValue(self.config.timeout)

        download_group.addSettingCard(self.folder_card)
        download_group.addSettingCard(self.workers_card)
        download_group.addSettingCard(self.retry_card)
        download_group.addSettingCard(self.timeout_card)

        return download_group

    def _build_scan_group(self) -> SettingCardGroup:
        """扫描设置组"""
        scan_group = SettingCardGroup("扫描设置", self)

        self.depth_card = SpinBoxSettingCard(1, 50, 1, FIF.TILES, "最大扫描深度", "递归扫描的最大深度", self)
        self.depth_card.setValue(self.config.max_depth)

        self.scan_workers_card = SpinBoxSettingCard(
            1, 10, 1, FIF.PEOPLE, "扫描并发数", "同时扫描的目录数量（并行模式生效）", self
        )
        self.scan_workers_card.setValue(self.config.scan_max_workers)

        self.scan_mode_config_item = OptionsConfigItem("scan", "scanMode", "dfs", OptionsValidator(["dfs", "bfs"]))
        self.scan_mode_card = ComboBoxSettingCard(
            self.scan_mode_config_item,
            FIF.TILES,
            "扫描模式",
            "深度优先逐目录深入，广度优先逐层扫描",
            texts=["深度优先", "广度优先"],
            parent=self,
        )
        self.scan_mode_config_item.value = self.config.scan_mode

        scan_group.addSettingCard(self.depth_card)
        scan_group.addSettingCard(self.scan_workers_card)
        scan_group.addSettingCard(self.scan_mode_card)

        return scan_group

    def _build_ui_group(self) -> SettingCardGroup:
        """界面设置组"""
        ui_group = SettingCardGroup("界面设置", self)

        self.themeConfigItem = OptionsConfigItem(
            "theme", "themeMode", Theme.AUTO, OptionsValidator([Theme.LIGHT, Theme.DARK, Theme.AUTO])
        )
        self.theme_card = OptionsSettingCard(
            self.themeConfigItem,
            FIF.PALETTE,
            "主题",
            "选择应用程序主题",
            texts=["浅色", "深色", "跟随系统"],
            parent=self,
        )

        self.themeConfigItem.value = _STR_TO_THEME.get(self.config.theme, Theme.AUTO)

        ui_group.addSettingCard(self.theme_card)
        return ui_group

    def _build_update_group(self) -> SettingCardGroup:
        """软件更新组"""
        update_group = SettingCardGroup("软件更新", self)

        # 版本信息卡片
        self.version_card = SettingCard(FIF.INFO, "当前版本", parent=self)
        self.version_value_label = BodyLabel(f"v{__version__}", self.version_card)
        self.github_btn = PushButton("GitHub", self.version_card)
        self.github_btn.clicked.connect(self._open_github_releases)
        self.version_card.hBoxLayout.addWidget(self.version_value_label, 0, Qt.AlignRight)
        self.version_card.hBoxLayout.addSpacing(8)
        self.version_card.hBoxLayout.addWidget(self.github_btn, 0, Qt.AlignRight)
        self.version_card.hBoxLayout.addSpacing(16)

        # 更新渠道卡片
        self.channel_config_item = OptionsConfigItem(
            "update", "channel", "stable", OptionsValidator(["stable", "test"])
        )
        self.channel_card = ComboBoxSettingCard(
            self.channel_config_item,
            FIF.SYNC,
            "更新渠道",
            "选择接收的更新类型",
            texts=["稳定版", "测试版"],
            parent=self,
        )
        self.channel_config_item.value = self.config.update_channel

        # 自动检查更新卡片
        self.auto_check_card = SettingCard(FIF.UPDATE, "自动检查更新", "启动时自动检查是否有新版本", self)
        self.auto_check_switch = SwitchButton(self.auto_check_card)
        self.auto_check_switch.setChecked(self.config.auto_check_update)
        self.auto_check_card.hBoxLayout.addWidget(self.auto_check_switch, 0, Qt.AlignRight)
        self.auto_check_card.hBoxLayout.addSpacing(16)

        # 检查更新按钮卡片
        self.check_btn_card = SettingCard(FIF.SYNC, "检查更新", "手动检查是否有新版本", self)
        self.check_btn = PrimaryPushButton("检查更新", self.check_btn_card)
        self.check_btn.setMinimumWidth(120)
        self.check_btn_card.hBoxLayout.addWidget(self.check_btn, 0, Qt.AlignRight)
        self.check_btn_card.hBoxLayout.addSpacing(16)

        update_group.addSettingCard(self.version_card)
        update_group.addSettingCard(self.channel_card)
        update_group.addSettingCard(self.auto_check_card)
        update_group.addSettingCard(self.check_btn_card)

        return update_group

    def _connect_signals(self):
        """连接信号（表驱动：卡片信号 → config 属性 + config_changed）"""
        # (信号源, config属性名) —— 变更值直接写入对应属性并通知
        bindings = [
            (self.workers_card.valueChanged, "max_workers"),
            (self.retry_card.valueChanged, "retry_times"),
            (self.timeout_card.valueChanged, "timeout"),
            (self.depth_card.valueChanged, "max_depth"),
            (self.scan_workers_card.valueChanged, "scan_max_workers"),
            (self.scan_mode_config_item.valueChanged, "scan_mode"),
            (self.channel_config_item.valueChanged, "update_channel"),
            (self.auto_check_switch.checkedChanged, "auto_check_update"),
        ]
        for signal, attr in bindings:
            signal.connect(self._make_config_handler(attr))

        self.folder_card.folderChanged.connect(self._make_config_handler("download_dir"))
        self.theme_card.optionChanged.connect(self._on_theme_changed)
        self.check_btn.clicked.connect(self._on_check_update_clicked)

    def _make_config_handler(self, attr: str) -> Callable:
        """生成配置变更处理器：写 config 属性并 emit config_changed"""

        def handler(value):
            setattr(self.config, attr, value)
            self.config_changed.emit({attr: value})

        return handler

    def _on_theme_changed(self, configItem):
        theme_value = configItem.value
        theme = _THEME_TO_STR.get(theme_value, "auto")
        self.config.theme = theme
        self.theme_changed.emit(theme)
        self.config_changed.emit({"theme": theme})

    def _on_check_update_clicked(self):
        """检查更新按钮点击"""
        self.check_btn.setEnabled(False)
        self.check_btn.setText("检查中...")
        self.check_update_requested.emit(self.config.update_channel, __version__, self.config.last_update_check_time)

    def on_check_update_finished(self):
        """更新检查完成（由外部调用）"""
        self.check_btn.setEnabled(True)
        self.check_btn.setText("检查更新")

    def on_update_downloading(self, percent: int = 0):
        """更新下载中（由外部调用）"""
        self.check_btn.setEnabled(False)
        if percent > 0:
            self.check_btn.setText(f"正在更新... {percent}%")
        else:
            self.check_btn.setText("正在更新...")

    def on_update_finished(self):
        """更新下载完成（由外部调用）"""
        self.check_btn.setEnabled(True)
        self.check_btn.setText("检查更新")

    def _open_github_releases(self):
        """打开 GitHub Releases 页面"""
        QDesktopServices.openUrl(QUrl(GITHUB_RELEASES_URL))
