"""勾选时实时更新已选统计回归测试 (#已选统计不更新)

验证:
- _on_checked_changed 存在并接受 checked_ids 集合
- 调用后 cache_manager.set_checked_items 被调用
- 调用后 download_panel.update_stats 被调用且 checked 参数正确
- 多次勾选/取消均触发更新
"""
from unittest.mock import MagicMock

from src.app import Application


def _make_app():
    obj = Application.__new__(Application)
    obj.cache_manager = MagicMock()
    obj.cache_manager.get_stats.return_value = {
        "total_files": 10, "total_dirs": 3, "checked_count": 2
    }
    obj.window = MagicMock()
    return obj


def test_on_checked_changed_exists_and_calls_set_checked():
    app = _make_app()
    app._on_checked_changed({"a.txt", "b.txt"})
    app.cache_manager.set_checked_items.assert_called_once_with({"a.txt", "b.txt"})


def test_on_checked_changed_updates_stats():
    """update_stats 应被调用且 checked 参数来自 get_stats"""
    app = _make_app()
    app._on_checked_changed({"a.txt", "b.txt"})
    app.window.downloadPanel.update_stats.assert_called_once()
    args = app.window.downloadPanel.update_stats.call_args.args
    assert args[2] == 2  # checked_count from get_stats


def test_on_checked_changed_empty_set():
    """取消全部勾选也应触发更新（checked=0）"""
    app = _make_app()
    app.cache_manager.get_stats.return_value = {
        "total_files": 10, "total_dirs": 3, "checked_count": 0
    }
    app._on_checked_changed(set())
    app.cache_manager.set_checked_items.assert_called_once_with(set())
    args = app.window.downloadPanel.update_stats.call_args.args
    assert args[2] == 0


def test_on_checked_changed_multiple_calls():
    """多次勾选/取消每次都触发更新"""
    app = _make_app()
    app._on_checked_changed({"a.txt"})
    app._on_checked_changed({"a.txt", "b.txt"})
    app._on_checked_changed(set())
    assert app.cache_manager.set_checked_items.call_count == 3
    assert app.window.downloadPanel.update_stats.call_count == 3


def test_on_checked_changed_preserves_total_files_dirs():
    """update_stats 的 total_files/total_dirs 应来自 get_stats"""
    app = _make_app()
    app._on_checked_changed({"a.txt"})
    args = app.window.downloadPanel.update_stats.call_args.args
    assert args[0] == 10  # total_files
    assert args[1] == 3   # total_dirs
