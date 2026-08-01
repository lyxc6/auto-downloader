"""TreeIndex 勾选计数缓存测试 (Phase5)

验证:
- dir_file_count 在 load/add/remove 时正确维护
- 勾选计数缓存与 _compute_check_state 一致
- remove_children_of 后计数与勾选集同步清理
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.models import DownloadItem, ItemType
from src.views.widgets.tree_widget import DownloadTreeWidget


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _mk(iid: str, itype: ItemType) -> DownloadItem:
    return DownloadItem(
        item_id=iid,
        name=iid.split("/")[-1],
        url="",
        item_type=itype,
        parent_id="/".join(iid.split("/")[:-1]),
        full_path=iid,
    )


def _sample():
    return {
        "A": _mk("A", ItemType.DIR),
        "A/sub1": _mk("A/sub1", ItemType.DIR),
        "A/sub2": _mk("A/sub2", ItemType.DIR),
        "A/sub1/f1.txt": _mk("A/sub1/f1.txt", ItemType.FILE),
        "A/sub2/f2.txt": _mk("A/sub2/f2.txt", ItemType.FILE),
        "B": _mk("B", ItemType.DIR),
        "B/f3.txt": _mk("B/f3.txt", ItemType.FILE),
    }


def test_dir_file_count_after_load(qapp):
    tw = DownloadTreeWidget()
    tw.load_from_items(_sample())
    assert tw._index.dir_file_count("A") == 2
    assert tw._index.dir_file_count("A/sub1") == 1
    assert tw._index.dir_file_count("B") == 1
    assert tw._index.dir_file_count("") == 0


def test_dir_file_count_after_incremental_add(qapp):
    tw = DownloadTreeWidget()
    tw.load_from_items(_sample())
    tw.add_item(_mk("A/sub2/f2b.txt", ItemType.FILE))
    assert tw._index.dir_file_count("A") == 3
    assert tw._index.dir_file_count("A/sub2") == 2


def test_check_state_uses_counts(qapp):
    tw = DownloadTreeWidget()
    tw.load_from_items(_sample())
    tw.apply_checked_items({"A/sub1/f1.txt"})
    assert tw._compute_check_state("A") == Qt.CheckState.PartiallyChecked
    assert tw._checked_dir_count.get("A") == 1
    tw.apply_checked_items({"A/sub1/f1.txt", "A/sub2/f2.txt"})
    assert tw._compute_check_state("A") == Qt.CheckState.Checked
    assert tw._checked_dir_count.get("A") == 2
    tw.apply_checked_items(set())
    assert tw._compute_check_state("A") == Qt.CheckState.Unchecked
    assert tw._checked_dir_count.get("A") == 0


def test_remove_children_cleans_counts_and_checked(qapp):
    tw = DownloadTreeWidget()
    tw.load_from_items(_sample())
    tw._on_item_expanded(tw._items["A"])
    tw.apply_checked_items({"A/sub1/f1.txt", "A/sub2/f2.txt", "B/f3.txt"})

    removed = tw.remove_children_of("A")
    assert removed == {"A/sub1", "A/sub1/f1.txt", "A/sub2", "A/sub2/f2.txt"}
    assert tw._checked_set == {"B/f3.txt"}
    # A 自身保留且无后代文件
    assert tw._index.dir_file_count("A") == 0
    assert tw._compute_check_state("A") == Qt.CheckState.Unchecked


def test_select_all_deselect_all_counts(qapp):
    tw = DownloadTreeWidget()
    tw.load_from_items(_sample())
    tw.select_all()
    assert tw._checked_dir_count.get("A") == 2
    assert tw._checked_dir_count.get("B") == 1
    tw.deselect_all()
    # 计数归零（键保留，值 0 = 未勾选）
    assert all(v == 0 for v in tw._checked_dir_count.values())
    assert tw._compute_check_state("A") == Qt.CheckState.Unchecked
    assert tw._compute_check_state("B") == Qt.CheckState.Unchecked
