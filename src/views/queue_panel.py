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
    TransparentPushButton,
    FluentSystemColor,
    qconfig, Theme
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
            "pending":     ("等待中", FluentSystemColor.CRITICAL_BACKGROUND),
            "downloading": ("下载中", FluentSystemColor.CRITICAL_FOREGROUND),
            "completed":   ("已完成", FluentSystemColor.SUCCESS_FOREGROUND),
            "failed":      ("失败",   FluentSystemColor.CRITICAL_FOREGROUND),
            "skipped":     ("已跳过", FluentSystemColor.CAUTION_FOREGROUND),
        }
        text, color_enum = status_map.get(status, ("未知", FluentSystemColor.CRITICAL_BACKGROUND))
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color_enum.color().name()};")


class QueuePanel(QWidget):
    """下载队列面板"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("queuePanel")
        self._items = {}  # item_id -> QueueItemWidget
        self._setup_ui()
        qconfig.themeChanged.connect(self._on_theme_changed)
    
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
    
    def _on_theme_changed(self, _theme: Theme):
        """主题切换：刷新所有可见状态标签颜色"""
        for widget in self._items.values():
            current_text = widget.status_label.text()
            # 反查当前状态以重新应用颜色
            for status_key, (text, _) in {
                "pending": ("等待中", None),
                "downloading": ("下载中", None),
                "completed": ("已完成", None),
                "failed": ("失败", None),
                "skipped": ("已跳过", None),
            }.items():
                if current_text == text:
                    widget.set_status(status_key)
                    break
