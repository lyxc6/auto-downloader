"""设置即时生效（下一批次）回归测试 (#14)

验证:
- Application 提供 _on_config_changed 槽，接受 changes dict 不抛异常
- 槽在配置更改后统一保存配置（AppConfig 为唯一真值源）
"""

from unittest.mock import MagicMock

from src.app import Application


def _make_app():
    obj = Application.__new__(Application)
    obj.window = MagicMock()
    obj.config = MagicMock()
    return obj


def test_on_config_changed_slot_exists_and_handles_dict():
    obj = _make_app()
    # 不应抛异常
    obj._on_config_changed({"max_workers": 5})
    obj._on_config_changed({"retry_times": 2, "timeout": 60})
    obj._on_config_changed({})


def test_on_config_changed_saves_config():
    """配置变更应触发统一落盘"""
    obj = _make_app()
    obj._on_config_changed({"max_workers": 5})
    obj.config.save.assert_called_once()


def test_on_config_changed_handles_all_known_keys():
    """对设置面板会 emit 的所有 key 均不抛异常"""
    obj = _make_app()
    for key in ("download_dir", "max_workers", "retry_times", "timeout", "max_depth"):
        obj._on_config_changed({key: 1})
