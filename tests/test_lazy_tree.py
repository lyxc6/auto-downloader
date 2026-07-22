"""树形组件虚拟加载回归测试 (C11)

验证:
- load_from_items 仅 realize 根节点，不批量创建全部 QTreeWidgetItem
- itemExpanded 按需 populate 子节点
- 勾选真值源为 _checked_set，_compute_check_state 从集合+索引计算三态
- 未展开子树勾选级联正确
- get_checked_items O(1) 返回集合，与 realize 状态无关
- add_item 增量更新索引但不强制 realize
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.models import DownloadItem, ItemType
from src.views.widgets.tree_widget import DownloadTreeWidget


def _make_items() -> dict:
    items = {}

    def add(iid: str, itype: ItemType, size: int = 0):
        name = iid.split("/")[-1]
        items[iid] = DownloadItem(
            item_id=iid, name=name, url="", item_type=itype,
            parent_id="/".join(iid.split("/")[:-1]),
            full_path=iid, size=size,
        )

    add("A", ItemType.DIR)
    add("B", ItemType.DIR)
    add("A/sub1", ItemType.DIR)
    add("A/sub2", ItemType.DIR)
    add("A/sub1/file1.txt", ItemType.FILE, size=100)
    add("A/sub2/file2.txt", ItemType.FILE, size=200)
    add("B/file3.txt", ItemType.FILE, size=300)
    return items


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def tree(qapp):
    t = DownloadTreeWidget()
    t.load_from_items(_make_items())
    return t


def test_load_from_items_realizes_only_roots(tree):
    assert set(tree._items.keys()) == {"A", "B"}
    assert len(tree._all_items) == 7
    assert tree._loaded == set()


def test_expand_populates_children(tree):
    tree._on_item_expanded(tree._items["A"])
    assert "A/sub1" in tree._items
    assert "A/sub2" in tree._items
    assert "A/sub1/file1.txt" not in tree._items
    assert "A" in tree._loaded


def test_check_root_adds_all_file_descendants_to_set(tree):
    tree._items["A"].setCheckState(0, Qt.CheckState.Checked)
    assert tree._checked_set == {"A/sub1/file1.txt", "A/sub2/file2.txt"}


def test_get_checked_items_returns_set_regardless_of_realize(tree):
    tree._items["A"].setCheckState(0, Qt.CheckState.Checked)
    assert set(tree.get_checked_items()) == {"A/sub1/file1.txt", "A/sub2/file2.txt"}
    assert "A/sub1" not in tree._items


def test_compute_check_state_tristate(tree):
    tree.apply_checked_items({"A/sub1/file1.txt"})
    assert tree._compute_check_state("A") == Qt.CheckState.PartiallyChecked
    tree.apply_checked_items({"A/sub1/file1.txt", "A/sub2/file2.txt"})
    assert tree._compute_check_state("A") == Qt.CheckState.Checked
    tree.apply_checked_items(set())
    assert tree._compute_check_state("A") == Qt.CheckState.Unchecked


def test_apply_checked_items_refreshes_realized(tree):
    tree.apply_checked_items({"A/sub1/file1.txt"})
    assert tree._items["A"].checkState(0) == Qt.CheckState.PartiallyChecked


def test_select_all_adds_all_files(tree):
    tree.select_all()
    assert tree._checked_set == {"A/sub1/file1.txt", "A/sub2/file2.txt", "B/file3.txt"}


def test_deselect_all_clears(tree):
    tree.select_all()
    tree.deselect_all()
    assert tree._checked_set == set()


def test_add_item_incremental_updates_index(tree):
    new_item = DownloadItem(
        item_id="A/sub1/new.txt", name="new.txt", url="",
        item_type=ItemType.FILE, parent_id="A/sub1",
        full_path="A/sub1/new.txt", size=50,
    )
    tree.add_item(new_item)
    assert "A/sub1/new.txt" in tree._all_items
    assert "A/sub1/new.txt" in tree._children_index.get("A/sub1", [])
    assert "A/sub1/new.txt" not in tree._items
