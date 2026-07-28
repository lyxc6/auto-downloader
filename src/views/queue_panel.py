"""下载队列面板"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, 
    QTableWidgetItem
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from qfluentwidgets import (
    CardWidget, TableWidget, 
    ProgressBar, PushButton,
    StrongBodyLabel, BodyLabel, CaptionLabel,
    FluentIcon as FIF,
    TransparentPushButton,
    FluentSystemColor,
    qconfig, Theme
)


class QueuePanel(QWidget):
    """下载队列面板"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("queuePanel")
        self._items = {}  # item_id -> {"row": int, "status_item": QTableWidgetItem, "progress_bar": ProgressBar, "pct_item": QTableWidgetItem}
        self._stats = {"pending": 0, "completed": 0, "failed": 0, "skipped": 0, "downloading": 0}
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
        
        # 队列表格
        self.table_widget = TableWidget(self)
        self.table_widget.setColumnCount(4)
        self.table_widget.setHorizontalHeaderLabels(["名称", "状态", "进度", ""])
        self.table_widget.setColumnWidth(0, 400)
        self.table_widget.setColumnWidth(1, 80)
        self.table_widget.setColumnWidth(2, 200)
        self.table_widget.setColumnWidth(3, 50)
        self.table_widget.verticalHeader().setVisible(False)
        self.table_widget.setEditTriggers(TableWidget.NoEditTriggers)
        self.table_widget.setSelectionBehavior(TableWidget.SelectRows)
        layout.addWidget(self.table_widget)
        
        # 连接信号
        self.clear_btn.clicked.connect(self.clear)
    
    def add_item(self, item_id: str, name: str):
        """添加队列项"""
        if item_id in self._items:
            return
        
        row = self.table_widget.rowCount()
        self.table_widget.insertRow(row)
        
        # 名称列
        name_item = QTableWidgetItem(name)
        self.table_widget.setItem(row, 0, name_item)
        
        # 状态列
        status_item = QTableWidgetItem("等待中")
        status_item.setForeground(QColor("gray"))
        self.table_widget.setItem(row, 1, status_item)
        
        # 进度条列
        progress_bar = ProgressBar(self.table_widget)
        progress_bar.setFixedWidth(200)
        self.table_widget.setCellWidget(row, 2, progress_bar)
        
        # 进度百分比列
        pct_item = QTableWidgetItem("0%")
        pct_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.table_widget.setItem(row, 3, pct_item)
        
        # 存储映射
        self._items[item_id] = {
            "row": row,
            "status_item": status_item,
            "progress_bar": progress_bar,
            "pct_item": pct_item,
            "status": "pending",
        }
        
        self._stats["pending"] += 1
        self._update_stats_labels()
    
    def update_progress(self, item_id: str, downloaded: int, total: int):
        """更新进度"""
        if item_id not in self._items:
            return
        info = self._items[item_id]
        if total > 0:
            percent = int(downloaded / total * 100)
            info["progress_bar"].setValue(percent)
            info["pct_item"].setText(f"{percent}%")
    
    def update_status(self, item_id: str, status: str):
        """更新状态"""
        if item_id not in self._items:
            return
        info = self._items[item_id]
        
        # 更新旧状态计数
        old_status = info.get("status")
        if old_status and old_status in self._stats:
            self._stats[old_status] -= 1
        
        # 设置新状态
        status_map = {
            "pending":     ("等待中", FluentSystemColor.CRITICAL_BACKGROUND),
            "downloading": ("下载中", FluentSystemColor.CRITICAL_FOREGROUND),
            "completed":   ("已完成", FluentSystemColor.SUCCESS_FOREGROUND),
            "failed":      ("失败",   FluentSystemColor.CRITICAL_FOREGROUND),
            "skipped":     ("已跳过", FluentSystemColor.CAUTION_FOREGROUND),
        }
        text, color_enum = status_map.get(status, ("未知", FluentSystemColor.CRITICAL_BACKGROUND))
        info["status_item"].setText(text)
        info["status_item"].setForeground(QColor(color_enum.color().name()))
        info["status"] = status
        
        # 更新新状态计数
        if status in self._stats:
            self._stats[status] += 1
        
        self._update_stats_labels()
    
    def clear(self):
        """清空列表"""
        self.table_widget.setRowCount(0)
        self._items.clear()
        self._stats = {"pending": 0, "completed": 0, "failed": 0, "skipped": 0, "downloading": 0}
        self._update_stats_labels()
    
    def _update_stats_labels(self):
        """更新统计标签"""
        total = len(self._items)
        self.total_label.setText(f"总计: {total}")
        self.completed_label.setText(f"已完成: {self._stats.get('completed', 0)}")
        self.failed_label.setText(f"失败: {self._stats.get('failed', 0)}")
        self.pending_label.setText(f"等待中: {self._stats.get('pending', 0)}")
    
    def _on_theme_changed(self, _theme: Theme):
        """主题切换：刷新所有可见状态标签颜色"""
        status_map = {
            "pending":     ("等待中", FluentSystemColor.CRITICAL_BACKGROUND),
            "downloading": ("下载中", FluentSystemColor.CRITICAL_FOREGROUND),
            "completed":   ("已完成", FluentSystemColor.SUCCESS_FOREGROUND),
            "failed":      ("失败",   FluentSystemColor.CRITICAL_FOREGROUND),
            "skipped":     ("已跳过", FluentSystemColor.CAUTION_FOREGROUND),
        }
        for info in self._items.values():
            status = info.get("status")
            if status and status in status_map:
                text, color_enum = status_map[status]
                info["status_item"].setText(text)
                info["status_item"].setForeground(QColor(color_enum.color().name()))
