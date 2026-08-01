"""LogWidget.clear() 回归测试 (P0-2)

验证:
- clear() 后 _messages 历史清空，界面文本为空
- 清空后添加新消息，旧消息不因主题切换/溢出重渲染而重现
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.views.widgets.log_widget import LogWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def widget(qapp):
    return LogWidget()


def test_clear_empties_messages_history(widget):
    widget.add_message("hello", "info")
    widget.add_message("world", "warning")
    assert len(widget._messages) == 2
    widget.clear()
    assert widget._messages == []
    assert widget.toPlainText() == ""


def test_clear_prevents_reappearance(widget):
    widget.add_message("old message", "info")
    widget.clear()
    widget.add_message("new message", "info")
    assert widget.toPlainText() == "new message"
    assert [m for m, _ in widget._messages] == ["new message"]
