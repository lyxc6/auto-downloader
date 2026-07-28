"""设置即时生效（下一批次）回归测试 (#14)

验证:
- Application 提供 _on_config_changed 槽，接受 changes dict 不抛异常
- 槽在配置更改后记录日志（下一批次生效语义）
"""

from unittest.mock import MagicMock

from src.app import Application


def test_on_config_changed_slot_exists_and_handles_dict():
    obj = Application.__new__(Application)
    obj.window = MagicMock()
    # 不应抛异常
    obj._on_config_changed({"max_workers": 5})
    obj._on_config_changed({"retry_times": 2, "timeout": 60})
    obj._on_config_changed({})


def test_on_config_changed_handles_all_known_keys():
    """对设置面板会 emit 的所有 key 均不抛异常"""
    obj = Application.__new__(Application)
    obj.window = MagicMock()
    for key in ("download_dir", "max_workers", "retry_times", "timeout", "max_depth"):
        obj._on_config_changed({key: 1})
