"""日志组件"""

from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from qfluentwidgets import PlainTextEdit, Theme, isDarkTheme, qconfig

MAX_LOG_LINES = 2000

# 浅色 / 深色文字配色
_LIGHT = {
    "info": "#1e1e1e",
    "success": "#0f7b0f",
    "error": "#c42b1c",
    "warning": "#9d5d00",
    "header": "#0000ff",
    "dim": "#808080",
}
_DARK = {
    "info": "#d4d4d4",
    "success": "#6a9955",
    "error": "#f44747",
    "warning": "#cca700",
    "header": "#569cd6",
    "dim": "#808080",
}


class LogWidget(PlainTextEdit):
    """日志组件（基于 PlainTextEdit，自动适配主题）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Consolas", 9))
        self._messages: list[tuple[str, str]] = []
        qconfig.themeChanged.connect(self._on_theme_changed)

    def _get_colors(self) -> dict:
        return dict(_DARK if isDarkTheme() else _LIGHT)

    def _render_message(self, message: str, level: str):
        colors = self._get_colors()
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(colors.get(level, colors["info"])))
        if level == "header":
            fmt.setFontWeight(QFont.Weight.Bold)
        else:
            fmt.setFontWeight(QFont.Weight.Normal)
        cursor = self.textCursor()
        cursor.mergeCharFormat(fmt)
        self.appendPlainText(message)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def add_message(self, message: str, level: str = "info"):
        self._messages.append((message, level))
        if len(self._messages) > MAX_LOG_LINES:
            self._messages = self._messages[-MAX_LOG_LINES:]
            self.clear()
            self._render_all()
        else:
            self._render_message(message, level)

    def _on_theme_changed(self, _theme: Theme):
        self.clear()
        self._render_all()

    def _render_all(self):
        """渲染全部消息"""
        for msg, lvl in self._messages:
            self._render_message(msg, lvl)

    def clear(self):
        super().clear()
