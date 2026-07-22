"""SIGINT 信号处理器安全化回归测试 (#8)

验证:
- _signal_handler 只设置 _shutdown_event，不做 I/O、不直接退出
- _check_shutdown 在事件置位时保存缓存、关闭服务、退出应用，且只触发一次
- 事件未置位时 _check_shutdown 不做任何事
"""
import threading
from unittest.mock import MagicMock

import pytest

from src.app import Application


@pytest.fixture
def app_obj():
    """部分构造 Application，仅注入测试所需依赖，避免完整 GUI 与真实 QApplication"""
    obj = Application.__new__(Application)
    obj.app = MagicMock()
    obj.cache_manager = MagicMock()
    obj.scan_controller = MagicMock()
    obj.download_controller = MagicMock()
    obj.config = MagicMock()
    obj.config.last_url = "http://x"
    obj._shutdown_event = threading.Event()
    obj._shutdown_done = False
    obj._shutdown_timer = MagicMock()
    return obj


def test_has_shutdown_event(app_obj):
    assert hasattr(app_obj, "_shutdown_event")
    assert app_obj._shutdown_event.is_set() is False


def test_signal_handler_only_sets_event(app_obj):
    """信号处理器只置位事件，不直接保存/退出"""
    app_obj._signal_handler(None, None)
    assert app_obj._shutdown_event.is_set() is True
    # 不应在信号处理器中直接做 I/O
    app_obj.cache_manager.save.assert_not_called()
    app_obj.app.quit.assert_not_called()


def test_check_shutdown_saves_and_quits_once(app_obj):
    """事件置位后 _check_shutdown 保存+关闭服务+退出，且只触发一次"""
    app_obj._shutdown_event.set()
    app_obj._check_shutdown()
    app_obj.cache_manager.save.assert_called_once_with("http://x")
    app_obj.scan_controller.close_service.assert_called_once()
    app_obj.download_controller.close_service.assert_called_once()
    app_obj.app.quit.assert_called_once()
    # 第二次调用应幂等，不重复保存/退出
    app_obj._check_shutdown()
    assert app_obj.cache_manager.save.call_count == 1
    assert app_obj.app.quit.call_count == 1


def test_check_shutdown_noop_when_event_not_set(app_obj):
    """事件未置位时 _check_shutdown 不做任何事"""
    app_obj._check_shutdown()
    app_obj.cache_manager.save.assert_not_called()
    app_obj.app.quit.assert_not_called()
