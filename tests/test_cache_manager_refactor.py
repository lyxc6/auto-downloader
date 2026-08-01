"""CacheManager 原子加载/宽容反序列化测试 (Phase2)"""

import json
import os

from src.models.cache_manager import CacheManager
from src.models.download_item import CacheStats, DownloadItem, ItemType


def _write_cache(tmp_path, data: dict) -> str:
    path = str(tmp_path / "cache.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


def _item(iid: str) -> DownloadItem:
    return DownloadItem(
        item_id=iid,
        name=iid.split("/")[-1],
        url=f"http://x/{iid}",
        item_type=ItemType.FILE,
        parent_id="/".join(iid.split("/")[:-1]),
        full_path=iid,
    )


def test_load_bad_items_skipped_rest_loaded(tmp_path):
    """坏条目跳过，不影响整体加载"""
    path = _write_cache(
        tmp_path,
        {
            "url": "http://x",
            "tree_data": {
                "good.txt": {
                    "item_id": "good.txt",
                    "name": "good.txt",
                    "url": "u",
                    "item_type": "file",
                    "parent_id": "",
                    "full_path": "good.txt",
                },
                "bad.txt": {"item_id": "bad.txt", "item_type": "garbage"},
            },
            "checked_items": ["good.txt", "ghost.txt"],
            "scanned_dirs": [],
            "unscanned_dirs": [],
            "scan_complete": False,
        },
    )
    cm = CacheManager(path)
    assert cm.load() is True
    assert cm.has_item("good.txt")
    assert not cm.has_item("bad.txt")
    # 宽容：checked_items 中不存在的 id 保留（由 cleanup_checked 负责剔除）
    assert cm.checked_items_snapshot() == {"good.txt", "ghost.txt"}


def test_load_unknown_enum_falls_back(tmp_path):
    """未知枚举值回退默认，不抛异常"""
    path = _write_cache(
        tmp_path,
        {
            "url": "u",
            "tree_data": {
                "f.txt": {
                    "item_id": "f.txt",
                    "name": "f.txt",
                    "url": "u",
                    "item_type": "weird",
                    "parent_id": "",
                    "full_path": "f.txt",
                    "status": "weird",
                }
            },
            "checked_items": [],
            "scanned_dirs": [],
            "unscanned_dirs": [],
            "scan_complete": False,
        },
    )
    cm = CacheManager(path)
    assert cm.load() is True
    item = cm.get_item("f.txt")
    assert item is not None
    assert item.item_type == ItemType.FILE  # 回退默认
    assert item.status.name == "PENDING"


def test_save_writes_version_and_unique_tmp(tmp_path):
    """保存写入 version 字段，且不残留临时文件"""
    path = str(tmp_path / "cache.json")
    cm = CacheManager(path)
    cm.try_add_item(_item("a.txt"))
    assert cm.save() is True

    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["version"] == 1

    leftovers = [n for n in os.listdir(tmp_path) if n.endswith(".tmp")]
    assert leftovers == []


def test_get_stats_returns_typed_cache_stats(tmp_path):
    """get_stats 返回 CacheStats 类型化对象"""
    cm = CacheManager(str(tmp_path / "cache.json"))
    cm.try_add_item(_item("d/a.txt"))
    cm.try_add_item(
        DownloadItem(
            item_id="d",
            name="d",
            url="",
            item_type=ItemType.DIR,
            parent_id="",
            full_path="d",
        )
    )
    cm.set_checked_items({"d/a.txt"})
    stats = cm.get_stats()
    assert isinstance(stats, CacheStats)
    assert stats.total_files == 1
    assert stats.total_dirs == 1
    assert stats.checked_count == 1


def test_remove_directory_descendants_linear(tmp_path):
    """子树删除：O(N) 索引实现，正确清理计数/勾选/扫描状态"""
    cm = CacheManager(str(tmp_path / "cache.json"))
    # 目录 d 下：sub 目录 + 2 文件；根：独立文件
    items = {
        "d": DownloadItem(item_id="d", name="d", url="", item_type=ItemType.DIR, parent_id="", full_path="d"),
        "d/sub": DownloadItem(
            item_id="d/sub", name="sub", url="", item_type=ItemType.DIR, parent_id="d", full_path="d/sub"
        ),
        "d/sub/f1.txt": _item("d/sub/f1.txt"),
        "d/f2.txt": _item("d/f2.txt"),
        "root.txt": _item("root.txt"),
    }
    for it in items.values():
        cm.try_add_item(it)
    cm.set_checked_items({"d/sub/f1.txt", "root.txt"})
    cm.mark_dir_unscanned("d/sub")
    cm.mark_dir_scanned("d")

    removed = cm.remove_directory_descendants("d")

    assert removed == {"d/sub", "d/sub/f1.txt", "d/f2.txt"}
    assert not cm.has_item("d/sub")
    assert cm.has_item("d")  # 目录自身保留
    assert cm.has_item("root.txt")
    assert cm.checked_items_snapshot() == {"root.txt"}
    assert cm.get_unscanned_dirs() == set()
    stats = cm.get_stats()
    assert stats.total_files == 1
    assert stats.total_dirs == 1  # 目录自身保留


def test_checked_items_snapshot_isolation(tmp_path):
    """快照返回副本，外部修改不影响内部"""
    cm = CacheManager(str(tmp_path / "cache.json"))
    cm.set_checked_items({"a"})
    snap = cm.checked_items_snapshot()
    snap.add("b")
    assert cm.checked_count() == 1
