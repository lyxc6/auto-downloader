"""下载面板"""


from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QSplitter, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    StrongBodyLabel,
)

from ..models import AppConfig, DownloadItem
from .widgets.log_widget import LogWidget
from .widgets.tree_widget import DownloadTreeWidget


class DownloadPanel(QWidget):
    """下载面板"""

    # 信号定义
    scan_requested = Signal(str)  # url
    refresh_requested = Signal(str)  # 强制刷新url
    refresh_directory_requested = Signal(str)  # item_id：刷新单个目录
    download_requested = Signal()  # 开始下载
    stop_requested = Signal()  # 停止

    def __init__(self, config: AppConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("downloadPanel")
        self.config = config
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # 标题
        title_label = StrongBodyLabel("网站文件自动下载器")
        title_label.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        layout.addWidget(title_label)

        # URL输入区域
        url_card = CardWidget(self)
        url_layout = QHBoxLayout(url_card)
        url_layout.setContentsMargins(15, 15, 15, 15)
        url_layout.setSpacing(10)

        url_label = BodyLabel("目标URL:")
        self.url_input = LineEdit(self)
        self.url_input.setPlaceholderText("请输入目标网站URL")
        self.url_input.setText(self.config.last_url)

        self.scan_btn = PrimaryPushButton("扫描目录", self)
        self.refresh_btn = PushButton("刷新", self)
        self.stop_scan_btn = PushButton("停止扫描", self)
        self.stop_scan_btn.setEnabled(False)

        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_input, 1)
        url_layout.addWidget(self.scan_btn)
        url_layout.addWidget(self.refresh_btn)
        url_layout.addWidget(self.stop_scan_btn)

        layout.addWidget(url_card)

        # 主内容区域（使用分割器）
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # 左侧：目录树
        left_panel = CardWidget(self)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(10, 10, 10, 10)

        tree_header = QHBoxLayout()
        tree_label = StrongBodyLabel("目录树")
        tree_header.addWidget(tree_label)
        tree_header.addStretch()

        self.select_all_btn = PushButton("全选", self)
        self.deselect_all_btn = PushButton("取消全选", self)
        self.expand_btn = PushButton("展开", self)
        self.collapse_btn = PushButton("收起", self)

        tree_header.addWidget(self.select_all_btn)
        tree_header.addWidget(self.deselect_all_btn)
        tree_header.addWidget(self.expand_btn)
        tree_header.addWidget(self.collapse_btn)

        left_layout.addLayout(tree_header)

        self.tree_widget = DownloadTreeWidget(self)
        left_layout.addWidget(self.tree_widget)

        # 统计信息
        self.stats_label = CaptionLabel("文件: 0 | 目录: 0 | 已选: 0")
        left_layout.addWidget(self.stats_label)

        splitter.addWidget(left_panel)

        # 右侧：日志和预览
        right_panel = QWidget(self)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        # 日志区域
        log_card = CardWidget(self)
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(10, 10, 10, 10)

        log_label = StrongBodyLabel("操作日志")
        log_layout.addWidget(log_label)

        self.log_widget = LogWidget(self)
        log_layout.addWidget(self.log_widget)

        right_layout.addWidget(log_card, 1)

        splitter.addWidget(right_panel)
        splitter.setSizes([600, 400])

        layout.addWidget(splitter, 1)

        # 底部按钮区域
        bottom_card = CardWidget(self)
        bottom_layout = QHBoxLayout(bottom_card)
        bottom_layout.setContentsMargins(15, 15, 15, 15)
        bottom_layout.setSpacing(10)

        self.download_btn = PrimaryPushButton("开始下载", self)
        self.download_btn.setEnabled(False)
        self.stop_download_btn = PushButton("停止下载", self)
        self.stop_download_btn.setEnabled(False)
        self.clear_log_btn = PushButton("清空日志", self)

        # 进度条
        self.progress_bar = ProgressBar(self)
        self.progress_bar.setVisible(False)

        bottom_layout.addWidget(self.download_btn)
        bottom_layout.addWidget(self.stop_download_btn)
        bottom_layout.addWidget(self.clear_log_btn)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.progress_bar)

        layout.addWidget(bottom_card)

    def _connect_signals(self):
        """连接信号"""
        self.scan_btn.clicked.connect(self._on_scan_clicked)
        self.refresh_btn.clicked.connect(self._on_refresh_clicked)
        self.download_btn.clicked.connect(self.download_requested)
        self.stop_download_btn.clicked.connect(self.stop_requested)
        self.clear_log_btn.clicked.connect(self.log_widget.clear)
        self.select_all_btn.clicked.connect(self.tree_widget.select_all)
        self.deselect_all_btn.clicked.connect(self.tree_widget.deselect_all)
        self.expand_btn.clicked.connect(self.tree_widget.expand_all_items)
        self.collapse_btn.clicked.connect(self.tree_widget.collapse_all_items)
        self.tree_widget.refresh_dir_requested.connect(self.refresh_directory_requested)

    def _on_scan_clicked(self):
        """扫描按钮点击"""
        url = self.url_input.text().strip()
        if not url:
            InfoBar.error(title="错误", content="请输入目标URL", parent=self, position=InfoBarPosition.TOP)
            return
        self.scan_requested.emit(url)

    def _on_refresh_clicked(self):
        """刷新按钮点击"""
        url = self.url_input.text().strip()
        if not url:
            InfoBar.error(title="错误", content="请输入目标URL", parent=self, position=InfoBarPosition.TOP)
            return
        self.refresh_requested.emit(url)

    def set_scanning(self, is_scanning: bool):
        """设置扫描状态"""
        self.scan_btn.setEnabled(not is_scanning)
        self.refresh_btn.setEnabled(not is_scanning)
        self.stop_scan_btn.setEnabled(is_scanning)
        self.url_input.setEnabled(not is_scanning)

    def set_scan_button_mode(self, is_continue: bool):
        """切换扫描按钮模式：False=扫描目录, True=继续扫描"""
        self.scan_btn.setText("继续扫描" if is_continue else "扫描目录")

    def set_downloading(self, is_downloading: bool):
        """设置下载状态"""
        self.download_btn.setEnabled(not is_downloading)
        self.stop_download_btn.setEnabled(is_downloading)
        self.progress_bar.setVisible(is_downloading)

    def update_stats(self, total_files: int, total_dirs: int, checked: int, dirs_scanned: int = -1):
        """更新统计信息"""
        text = f"文件: {total_files} | 目录: {total_dirs} | 已选: {checked}"
        if dirs_scanned >= 0:
            text += f" | 扫描: {dirs_scanned}"
        self.stats_label.setText(text)

    def update_progress(self, current: int, total: int):
        """更新进度"""
        if total > 0:
            self.progress_bar.setValue(int(current / total * 100))

    def add_log(self, message: str, level: str = "info"):
        """添加日志"""
        self.log_widget.add_message(message, level)

    def add_item(self, item: DownloadItem):
        """添加目录树项目"""
        self.tree_widget.add_item(item)

    def add_items_batch(self, items: list[DownloadItem]) -> None:
        """批量添加目录树项目"""
        self.tree_widget.add_items_batch(items)

    def clear_tree(self):
        """清空目录树"""
        self.tree_widget.clear_all()
