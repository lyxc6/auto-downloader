"""DownloadPresenter 总进度增量累计回归测试 (Phase5)

验证:
- _on_download_progress 增量维护总进度，结果与全量求和一致
- item 中途 total 变化（续传）时累计仍正确
- 下载完成后累计清零
"""

from unittest.mock import MagicMock

from src.presenters import DownloadPresenter


def _make_presenter():
    obj = DownloadPresenter.__new__(DownloadPresenter)
    obj._dl_progress = {}
    obj._dl_sum_downloaded = 0
    obj._dl_sum_total = 0
    obj._queue_view = MagicMock()
    obj._view = MagicMock()
    obj._cache_manager = MagicMock()
    obj._auto_save = MagicMock()
    return obj


def test_incremental_sum_matches_full_sum():
    p = _make_presenter()
    # 三个文件各自推进
    p._on_download_progress("a", 10, 100)
    p._on_download_progress("b", 20, 200)
    p._on_download_progress("c", 30, 300)
    p._on_download_progress("a", 50, 100)  # a 继续推进

    assert p._dl_sum_downloaded == 100  # 50+20+30
    assert p._dl_sum_total == 600
    p._view.update_progress.assert_called_with(100, 600)


def test_total_change_mid_download():
    """续传场景 total 变化：差值修正累计"""
    p = _make_presenter()
    p._on_download_progress("a", 10, 100)
    p._on_download_progress("a", 90, 150)  # total 从 100 变 150

    assert p._dl_sum_downloaded == 90
    assert p._dl_sum_total == 150


def test_reset_on_complete():
    p = _make_presenter()
    p._on_download_progress("a", 10, 100)
    p._on_download_completed({})
    assert p._dl_progress == {}
    assert p._dl_sum_downloaded == 0
    assert p._dl_sum_total == 0
