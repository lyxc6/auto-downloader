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
            "header": "#569cd6",
            "dim": "#808080"
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
