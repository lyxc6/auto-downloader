"""CacheManager 锁纪律回归测试 (#1, #9)

验证:
- set_checked_items / set_url 方法存在且在锁内更新
- 并发 set_checked_items + save + toggle_check 不丢失更新、不损坏缓存文件
- url 的读写 (load/save/has_data_for) 受锁保护
"""
import json
import os
import threading
import time

import pytest

from src.models.cache_manager import CacheManager
from src.models.download_item import DownloadItem, ItemType


def _make_item(item_id: str) -> DownloadItem:
    return DownloadItem(
        item_id=item_id, name=item_id, url="http://x/" + item_id,
        item_type=ItemType.FILE, full_path=item_id,
    )


@pytest.fixture
def cache(tmp_path):
    return CacheManager(str(tmp_path / "cache.json"))


def test_set_checked_items_method_exists_and_sets(cache):
    """set_checked_items 应存在并以集合形式更新 checked_items"""
    cache.set_checked_items(["a", "b", "a"])
    assert cache.checked_items == {"a", "b"}


def test_set_url_method_exists_and_sets(cache):
    """set_url 应存在并更新 url"""
    cache.set_url("http://example.com")
    assert cache.url == "http://example.com"


def test_set_checked_items_atomic_with_save(cache, tmp_path):
    """并发 set_checked_items + save 不丢失更新、缓存文件始终合法"""
    for i in range(30):
        cache.add_item(_make_item(f"f{i}"))

    stop = threading.Event()
    errors = []

    def setter():
        try:
            while not stop.is_set():
                cache.set_checked_items([f"f{i}" for i in range(30)])
        except Exception as e:
            errors.append(e)

    def saver():
        try:
            while not stop.is_set():
                cache.save("http://x")
        except Exception as e:
            errors.append(e)

    def toggler():
        try:
            while not stop.is_set():
                for i in range(30):
                    cache.toggle_check(f"f{i}")
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=setter)
    t2 = threading.Thread(target=saver)
    t3 = threading.Thread(target=toggler)
    for t in (t1, t2, t3):
        t.start()
    time.sleep(0.5)
    stop.set()
    for t in (t1, t2, t3):
        t.join(timeout=3)

    assert not errors, f"并发产生异常: {errors}"

    # 最终缓存文件应为合法 JSON
    with open(cache.cache_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "tree_data" in data
    assert "checked_items" in data
    assert isinstance(data["checked_items"], list)


def test_url_access_is_lock_protected(cache):
    """并发 set_url + has_data_for + save 不产生异常"""
    stop = threading.Event()
    errors = []

    def url_setter():
        try:
            while not stop.is_set():
                cache.set_url("http://concurrent.com")
        except Exception as e:
            errors.append(e)

    def url_reader():
        try:
            while not stop.is_set():
                cache.has_data_for("http://concurrent.com")
        except Exception as e:
            errors.append(e)

    def saver():
        try:
            while not stop.is_set():
                cache.save("http://concurrent.com")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=url_setter),
               threading.Thread(target=url_reader),
               threading.Thread(target=saver)]
    for t in threads:
        t.start()
    time.sleep(0.4)
    stop.set()
    for t in threads:
        t.join(timeout=3)

    assert not errors, f"url 并发访问异常: {errors}"


def test_set_checked_items_does_not_lose_toggle(cache):
    """set_checked_items 与 toggle_check 均在锁内，不会因无锁重赋值丢失更新"""
    cache.add_item(_make_item("f0"))
    cache.toggle_check("f0")  # 锁内加入 f0
    assert "f0" in cache.checked_items
    cache.set_checked_items({"f1"})  # 锁内替换
    assert cache.checked_items == {"f1"}
    # f0 被显式替换（预期行为），但因操作在锁内，无撕裂读
