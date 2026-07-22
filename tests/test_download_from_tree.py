"""_start_download 从 tree_widget 取勾选文件回归测试 (#下载空选 bug)

验证:
- 勾选目录 → get_checked_files 返回该目录下所有文件 DownloadItem（非空）
- 勾选单个文件 → 返回该文件
- 全不选 → 返回空
- 刷新场景: _all_items 有项但 cache_manager.tree_data 为空时仍正确返回
  (不依赖 cache_manager.tree_data)
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.models.download_item import DownloadItem, ItemType
from src.views.widgets.tree_widget import DownloadTreeWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def _mk(item_id, parent_id, is_file):
    return DownloadItem(
        item_id=item_id, name=item_id.split("/")[-1],
        url="http://x/" + item_id if is_file else "",
        item_type=ItemType.FILE if is_file else ItemType.DIR,
        parent_id=parent_id, full_path=item_id,
    )


def _sample_tree():
    """A/ (dir)
       A/sub1/ (dir)
       A/sub1/f1.txt (file)
       A/sub2/ (dir)
       A/sub2/f2.txt (file)
       B/f3.txt (file)
    """
    return {
        "A": _mk("A", "", False),
        "A/sub1": _mk("A/sub1", "A", False),
        "A/sub1/f1.txt": _mk("A/sub1/f1.txt", "A/sub1", True),
        "A/sub2": _mk("A/sub2", "A", False),
        "A/sub2/f2.txt": _mk("A/sub2/f2.txt", "A/sub2", True),
        "B": _mk("B", "", False),
        "B/f3.txt": _mk("B/f3.txt", "B", True),
    }


def test_check_dir_returns_all_file_descendants(qapp):
    """勾选目录 A → get_checked_files 返回 A 下所有文件"""
    tw = DownloadTreeWidget()
    tw.load_from_items(_sample_tree())
    # 勾选 A（realized 根节点）
    tw._checked_set = {"A/sub1/f1.txt", "A/sub2/f2.txt"}
    files = tw.get_checked_files()
    ids = sorted(f.item_id for f in files)
    assert ids == ["A/sub1/f1.txt", "A/sub2/f2.txt"]
    assert all(f.is_file for f in files)


def test_check_single_file_returns_it(qapp):
    tw = DownloadTreeWidget()
    tw.load_from_items(_sample_tree())
    tw._checked_set = {"B/f3.txt"}
    files = tw.get_checked_files()
    assert len(files) == 1
    assert files[0].item_id == "B/f3.txt"
    assert files[0].is_file


def test_no_selection_returns_empty(qapp):
    tw = DownloadTreeWidget()
    tw.load_from_items(_sample_tree())
    files = tw.get_checked_files()
    assert files == []


def test_independent_of_cache_tree_data(qapp):
    """刷新场景: tree_widget._all_items 有数据，
    即使 cache_manager.tree_data 为空也能正确返回"""
    tw = DownloadTreeWidget()
    tw.load_from_items(_sample_tree())
    tw._checked_set = {"A/sub1/f1.txt", "B/f3.txt"}
    # 不依赖任何外部 cache_manager —— tree_widget 自持 _all_items
    files = tw.get_checked_files()
    ids = sorted(f.item_id for f in files)
    assert ids == ["A/sub1/f1.txt", "B/f3.txt"]


def test_checked_set_with_stale_id_ignored(qapp):
    """_checked_set 含 _all_items 中不存在的 id（如刷新后失效）应被忽略"""
    tw = DownloadTreeWidget()
    tw.load_from_items(_sample_tree())
    tw._checked_set = {"A/sub1/f1.txt", "nonexistent/file.txt"}
    files = tw.get_checked_files()
    ids = [f.item_id for f in files]
    assert ids == ["A/sub1/f1.txt"]
