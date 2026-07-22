# 任务4：视图层 (Views) - Fluent UI

## 任务描述
创建项目的视图层，使用PySide6-Fluent-Widgets实现Win11风格界面。

## 文件清单
- `src/views/__init__.py`
- `src/views/main_window.py`
- `src/views/download_panel.py`
- `src/views/settings_panel.py`
- `src/views/queue_panel.py`
- `src/views/widgets/__init__.py`
- `src/views/widgets/log_widget.py`
- `src/views/widgets/tree_widget.py`

## 技术要求
- 使用PySide6 + PySide6-Fluent-Widgets
- 响应式布局
- 明暗主题支持
- 中文界面

## 依赖
- 需要 `src/models` 模块
- 需要 `src/controllers` 模块
- 需要安装 `PySide6` 和 `PySide6-Fluent-Widgets`

---

## 文件1：src/views/main_window.py

```python
"""主窗口"""
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QSize
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
        self._apply_theme(config.theme)
    
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
    
    def _apply_theme(self, theme: str):
        """应用主题"""
        if theme == "dark":
            setTheme(Theme.DARK)
        elif theme == "light":
            setTheme(Theme.LIGHT)
        else:
            setTheme(Theme.AUTO)
    
    def closeEvent(self, event):
        """关闭事件"""
        # 保存窗口大小
        self.config.window_width = self.width()
        self.config.window_height = self.height()
        self.config.save()
        event.accept()
```

---

## 文件2：src/views/download_panel.py

```python
"""下载面板"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QSplitter, QFrame
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from qfluentwidgets import (
    PrimaryPushButton, PushButton, LineEdit, 
    ProgressBar, TreeWidget, ScrollArea,
    CardWidget, IconWidget, BodyLabel,
    CaptionLabel, StrongBodyLabel,
    FluentIcon as FIF,
    InfoBar, InfoBarPosition
)

from ..models import AppConfig, DownloadItem, ItemType
from .widgets.log_widget import LogWidget


class DownloadPanel(QWidget):
    """下载面板"""
    
    # 信号定义
    scan_requested = Signal(str)           # url
    download_requested = Signal()          # 开始下载
    stop_requested = Signal()              # 停止
    
    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
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
        self.stop_scan_btn = PushButton("停止扫描", self)
        self.stop_scan_btn.setEnabled(False)
        
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_input, 1)
        url_layout.addWidget(self.scan_btn)
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
        self.deselect_all_btn = PushButton("反选", self)
        self.expand_btn = PushButton("展开", self)
        self.collapse_btn = PushButton("收起", self)
        
        tree_header.addWidget(self.select_all_btn)
        tree_header.addWidget(self.deselect_all_btn)
        tree_header.addWidget(self.expand_btn)
        tree_header.addWidget(self.collapse_btn)
        
        left_layout.addLayout(tree_header)
        
        self.tree_widget = TreeWidget(self)
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
        self.download_btn.clicked.connect(self.download_requested)
        self.stop_download_btn.clicked.connect(self.stop_requested)
        self.clear_log_btn.clicked.connect(self.log_widget.clear)
    
    def _on_scan_clicked(self):
        """扫描按钮点击"""
        url = self.url_input.text().strip()
        if not url:
            InfoBar.error(
                title="错误",
                content="请输入目标URL",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return
        self.scan_requested.emit(url)
    
    def set_scanning(self, is_scanning: bool):
        """设置扫描状态"""
        self.scan_btn.setEnabled(not is_scanning)
        self.stop_scan_btn.setEnabled(is_scanning)
        self.url_input.setEnabled(not is_scanning)
    
    def set_downloading(self, is_downloading: bool):
        """设置下载状态"""
        self.download_btn.setEnabled(not is_downloading)
        self.stop_download_btn.setEnabled(is_downloading)
        self.progress_bar.setVisible(is_downloading)
    
    def update_stats(self, total_files: int, total_dirs: int, checked: int):
        """更新统计信息"""
        self.stats_label.setText(
            f"文件: {total_files} | 目录: {total_dirs} | 已选: {checked}"
        )
    
    def update_progress(self, current: int, total: int):
        """更新进度"""
        if total > 0:
            self.progress_bar.setValue(int(current / total * 100))
    
    def add_log(self, message: str, level: str = "info"):
        """添加日志"""
        self.log_widget.add_message(message, level)
```

---

## 文件3：src/views/settings_panel.py

```python
"""设置面板"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from PySide6.QtCore import Qt, Signal

from qfluentwidgets import (
    CardWidget, SettingCardGroup,
    SwitchSettingCard, ComboBoxSettingCard,
    SpinBoxSettingCard, FolderSettingCard,
    StrongBodyLabel, BodyLabel,
    FluentIcon as FIF,
    OptionsSettingCard
)

from ..models import AppConfig


class SettingsPanel(QWidget):
    """设置面板"""
    
    # 信号定义
    theme_changed = Signal(str)
    config_changed = Signal(dict)
    
    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._setup_ui()
    
    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 标题
        title = StrongBodyLabel("设置")
        layout.addWidget(title)
        
        # 下载设置组
        download_group = SettingCardGroup("下载设置", self)
        
        self.folder_card = FolderSettingCard(
            self.config.download_dir,
            "下载目录",
            "设置文件保存位置",
            self
        )
        
        self.workers_card = SpinBoxSettingCard(
            1, 10, 1,
            "并发下载数",
            "同时下载的文件数量",
            self
        )
        self.workers_card.setValue(self.config.max_workers)
        
        self.retry_card = SpinBoxSettingCard(
            0, 10, 1,
            "重试次数",
            "下载失败时的重试次数",
            self
        )
        self.retry_card.setValue(self.config.retry_times)
        
        self.timeout_card = SpinBoxSettingCard(
            30, 300, 10,
            "超时时间(秒)",
            "下载超时时间",
            self
        )
        self.timeout_card.setValue(self.config.timeout)
        
        download_group.addSettingCard(self.folder_card)
        download_group.addSettingCard(self.workers_card)
        download_group.addSettingCard(self.retry_card)
        download_group.addSettingCard(self.timeout_card)
        
        layout.addWidget(download_group)
        
        # 扫描设置组
        scan_group = SettingCardGroup("扫描设置", self)
        
        self.depth_card = SpinBoxSettingCard(
            1, 50, 1,
            "最大扫描深度",
            "递归扫描的最大深度",
            self
        )
        self.depth_card.setValue(self.config.max_depth)
        
        scan_group.addSettingCard(self.depth_card)
        
        layout.addWidget(scan_group)
        
        # 界面设置组
        ui_group = SettingCardGroup("界面设置", self)
        
        self.theme_card = OptionsSettingCard(
            "theme",
            FIF.PALETTE,
            "主题",
            "选择应用程序主题",
            texts=["浅色", "深色", "跟随系统"],
            parent=self
        )
        
        ui_group.addSettingCard(self.theme_card)
        
        layout.addWidget(ui_group)
        
        layout.addStretch()
        
        # 连接信号
        self._connect_signals()
    
    def _connect_signals(self):
        """连接信号"""
        self.folder_card.folderChanged.connect(self._on_folder_changed)
        self.workers_card.valueChanged.connect(self._on_workers_changed)
        self.retry_card.valueChanged.connect(self._on_retry_changed)
        self.timeout_card.valueChanged.connect(self._on_timeout_changed)
        self.depth_card.valueChanged.connect(self._on_depth_changed)
        self.theme_card.optionChanged.connect(self._on_theme_changed)
    
    def _on_folder_changed(self, folder: str):
        self.config.download_dir = folder
        self.config.save()
        self.config_changed.emit({"download_dir": folder})
    
    def _on_workers_changed(self, value: int):
        self.config.max_workers = value
        self.config.save()
        self.config_changed.emit({"max_workers": value})
    
    def _on_retry_changed(self, value: int):
        self.config.retry_times = value
        self.config.save()
        self.config_changed.emit({"retry_times": value})
    
    def _on_timeout_changed(self, value: int):
        self.config.timeout = value
        self.config.save()
        self.config_changed.emit({"timeout": value})
    
    def _on_depth_changed(self, value: int):
        self.config.max_depth = value
        self.config.save()
        self.config_changed.emit({"max_depth": value})
    
    def _on_theme_changed(self, option: str):
        theme_map = {"浅色": "light", "深色": "dark", "跟随系统": "auto"}
        theme = theme_map.get(option, "auto")
        self.config.theme = theme
        self.config.save()
        self.theme_changed.emit(theme)
```

---

## 文件4：src/views/queue_panel.py

```python
"""下载队列面板"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, 
    QListWidgetItem, QStackedWidget
)
from PySide6.QtCore import Qt

from qfluentwidgets import (
    CardWidget, ListWidget, 
    ProgressBar, PushButton,
    StrongBodyLabel, BodyLabel, CaptionLabel,
    FluentIcon as FIF,
    TransparentPushButton
)


class QueueItemWidget(QWidget):
    """队列项组件"""
    
    def __init__(self, item_id: str, name: str, parent=None):
        super().__init__(parent)
        self.item_id = item_id
        self._setup_ui(name)
    
    def _setup_ui(self, name: str):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        
        # 文件信息
        info_layout = QVBoxLayout()
        
        self.name_label = BodyLabel(name)
        self.status_label = CaptionLabel("等待中")
        self.status_label.setStyleSheet("color: gray;")
        
        info_layout.addWidget(self.name_label)
        info_layout.addWidget(self.status_label)
        
        layout.addLayout(info_layout, 1)
        
        # 进度条
        self.progress_bar = ProgressBar(self)
        self.progress_bar.setFixedWidth(200)
        layout.addWidget(self.progress_bar)
        
        # 进度标签
        self.progress_label = CaptionLabel("0%")
        self.progress_label.setFixedWidth(50)
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.progress_label)
    
    def update_progress(self, downloaded: int, total: int):
        """更新进度"""
        if total > 0:
            percent = int(downloaded / total * 100)
            self.progress_bar.setValue(percent)
            self.progress_label.setText(f"{percent}%")
    
    def set_status(self, status: str):
        """设置状态"""
        status_map = {
            "pending": ("等待中", "gray"),
            "downloading": ("下载中", "#0078d4"),
            "completed": ("已完成", "#107c10"),
            "failed": ("失败", "#d13438"),
            "skipped": ("已跳过", "#ff8c00"),
        }
        text, color = status_map.get(status, ("未知", "gray"))
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color};")


class QueuePanel(QWidget):
    """下载队列面板"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = {}  # item_id -> QueueItemWidget
        self._setup_ui()
    
    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 标题区域
        header_layout = QHBoxLayout()
        
        title = StrongBodyLabel("下载队列")
        header_layout.addWidget(title)
        header_layout.addStretch()
        
        self.clear_btn = TransparentPushButton("清空列表", self)
        self.clear_btn.setIcon(FIF.DELETE)
        header_layout.addWidget(self.clear_btn)
        
        layout.addLayout(header_layout)
        
        # 统计信息
        stats_card = CardWidget(self)
        stats_layout = QHBoxLayout(stats_card)
        stats_layout.setContentsMargins(15, 10, 15, 10)
        
        self.total_label = BodyLabel("总计: 0")
        self.completed_label = BodyLabel("已完成: 0")
        self.failed_label = BodyLabel("失败: 0")
        self.pending_label = BodyLabel("等待中: 0")
        
        stats_layout.addWidget(self.total_label)
        stats_layout.addWidget(self.completed_label)
        stats_layout.addWidget(self.failed_label)
        stats_layout.addWidget(self.pending_label)
        stats_layout.addStretch()
        
        layout.addWidget(stats_card)
        
        # 队列列表
        self.list_widget = ListWidget(self)
        layout.addWidget(self.list_widget)
        
        # 连接信号
        self.clear_btn.clicked.connect(self.clear)
    
    def add_item(self, item_id: str, name: str):
        """添加队列项"""
        if item_id in self._items:
            return
        
        widget = QueueItemWidget(item_id, name, self)
        self._items[item_id] = widget
        
        item = QListWidgetItem(self.list_widget)
        item.setSizeHint(widget.sizeHint())
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, widget)
        
        self._update_stats()
    
    def update_progress(self, item_id: str, downloaded: int, total: int):
        """更新进度"""
        if item_id in self._items:
            self._items[item_id].update_progress(downloaded, total)
    
    def update_status(self, item_id: str, status: str):
        """更新状态"""
        if item_id in self._items:
            self._items[item_id].set_status(status)
            self._update_stats()
    
    def clear(self):
        """清空列表"""
        self.list_widget.clear()
        self._items.clear()
        self._update_stats()
    
    def _update_stats(self):
        """更新统计"""
        total = len(self._items)
        completed = sum(1 for w in self._items.values() 
                       if w.status_label.text() == "已完成")
        failed = sum(1 for w in self._items.values() 
                    if w.status_label.text() == "失败")
        pending = sum(1 for w in self._items.values() 
                     if w.status_label.text() == "等待中")
        
        self.total_label.setText(f"总计: {total}")
        self.completed_label.setText(f"已完成: {completed}")
        self.failed_label.setText(f"失败: {failed}")
        self.pending_label.setText(f"等待中: {pending}")
```

---

## 文件5：src/views/widgets/log_widget.py

```python
"""日志组件"""
from PySide6.QtWidgets import QTextEdit, QVBoxLayout, QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor, QTextCursor

from qfluentwidgets import ScrollArea


class LogWidget(ScrollArea):
    """日志组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        """设置UI"""
        self.setWidgetResizable(True)
        
        content = QWidget()
        self.setWidget(content)
        
        layout = QVBoxLayout(content)
        layout.setContentsMargins(5, 5, 5, 5)
        
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("Consolas", 9))
        self.text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: none;
                padding: 5px;
            }
        """)
        
        layout.addWidget(self.text_edit)
        
        # 颜色配置
        self._colors = {
            "info": "#d4d4d4",
            "success": "#6a9955",
            "error": "#f44747",
            "warning": "#cca700",
            "header": "#569cd6"
        }
    
    def add_message(self, message: str, level: str = "info"):
        """添加消息"""
        color = self._colors.get(level, "#d4d4d4")
        
        # 设置颜色
        self.text_edit.setTextColor(QColor(color))
        
        # 添加消息
        if level == "header":
            self.text_edit.setFontWeight(QFont.Weight.Bold)
        else:
            self.text_edit.setFontWeight(QFont.Weight.Normal)
        
        self.text_edit.append(message)
        
        # 滚动到底部
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.text_edit.setTextCursor(cursor)
    
    def clear(self):
        """清空日志"""
        self.text_edit.clear()
```

---

## 文件6：src/views/widgets/tree_widget.py

```python
"""树形组件扩展"""
from PySide6.QtWidgets import QTreeWidgetItem
from PySide6.QtCore import Qt

from qfluentwidgets import TreeWidget

from ...models import DownloadItem, ItemType


class DownloadTreeWidget(TreeWidget):
    """下载树形组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = {}  # item_id -> QTreeWidgetItem
        self.setHeaderLabels(["名称", "类型", "大小"])
        self.setColumnWidth(0, 300)
        self.setColumnWidth(1, 80)
        self.setColumnWidth(2, 100)
    
    def add_item(self, item: DownloadItem):
        """添加项目"""
        if item.item_id in self._items:
            return
        
        # 创建树项
        tree_item = QTreeWidgetItem()
        tree_item.setText(0, item.name)
        tree_item.setText(1, "📁" if item.is_dir else "📄")
        tree_item.setText(2, self._format_size(item.size) if item.is_file else "")
        
        # 设置数据
        tree_item.setData(0, Qt.ItemDataRole.UserRole, item.item_id)
        
        # 添加到父节点或根节点
        if item.parent_id and item.parent_id in self._items:
            parent_item = self._items[item.parent_id]
            parent_item.addChild(tree_item)
        else:
            self.addTopLevelItem(tree_item)
        
        self._items[item.item_id] = tree_item
    
    def toggle_check(self, item_id: str):
        """切换选中状态"""
        if item_id in self._items:
            item = self._items[item_id]
            is_checked = item.checkState(0) == Qt.CheckState.Checked
            item.setCheckState(
                0, 
                Qt.CheckState.Unchecked if is_checked else Qt.CheckState.Checked
            )
    
    def is_checked(self, item_id: str) -> bool:
        """是否选中"""
        if item_id in self._items:
            return self._items[item_id].checkState(0) == Qt.CheckState.Checked
        return False
    
    def get_checked_items(self) -> list:
        """获取所有选中项"""
        checked = []
        for item_id, item in self._items.items():
            if item.checkState(0) == Qt.CheckState.Checked:
                checked.append(item_id)
        return checked
    
    def select_all(self):
        """全选"""
        for item in self._items.values():
            item.setCheckState(0, Qt.CheckState.Checked)
    
    def deselect_all(self):
        """反选"""
        for item in self._items.values():
            is_checked = item.checkState(0) == Qt.CheckState.Checked
            item.setCheckState(
                0,
                Qt.CheckState.Unchecked if is_checked else Qt.CheckState.Checked
            )
    
    def expand_all_items(self):
        """展开所有"""
        self.expandAll()
    
    def collapse_all_items(self):
        """收起所有"""
        self.collapseAll()
    
    def clear_all(self):
        """清空所有"""
        self.clear()
        self._items.clear()
    
    @staticmethod
    def _format_size(size: int) -> str:
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"
```

---

## 文件7：src/views/__init__.py 和 src/views/widgets/__init__.py

```python
# src/views/__init__.py
"""视图层"""
from .main_window import MainWindow
from .download_panel import DownloadPanel
from .settings_panel import SettingsPanel
from .queue_panel import QueuePanel

__all__ = ['MainWindow', 'DownloadPanel', 'SettingsPanel', 'QueuePanel']
```

```python
# src/views/widgets/__init__.py
"""自定义组件"""
from .log_widget import LogWidget
from .tree_widget import DownloadTreeWidget

__all__ = ['LogWidget', 'DownloadTreeWidget']
```

---

## 验证标准

1. 所有文件无语法错误
2. 界面组件正确显示
3. 主题切换正常
4. 信号槽正确连接

## 测试命令

```bash
python -c "from src.views import *; print('Views OK')"
```
