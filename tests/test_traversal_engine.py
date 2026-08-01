"""统一遍历引擎回归测试

验证:
- 串行 DFS 输出顺序：子目录及后代全部输出后，才输出本目录文件
- 串行 BFS 输出顺序：逐层，目录项先于本目录文件
- 并行模式真实并发（in-flight 请求 ≥ 2，不再假并行）
- 无错误时目录全部标记为已扫描
"""

import threading
import time

from src.models.download_item import DownloadItem, ItemType
from src.services.scanner import ScanService

ROOT_DIRS = [("d1", "d1", "?dir=d1"), ("d2", "d2", "?dir=d2")]
ROOT_FILES = [("root.txt", "http://x/root.txt")]


def _fake_get_all_pages(base_url: str, dir_path: str, raw_href: str = ""):
    """固定目录结构：根 -> [d1, d2]（各有 1 个文件）"""
    if dir_path == "d1":
        return [], [("d1f.txt", "http://x/d1f.txt")], False
    if dir_path == "d2":
        return [], [("d2f.txt", "http://x/d2f.txt")], False
    return ROOT_DIRS, ROOT_FILES, False


def _service(delay: float = 0.0) -> ScanService:
    svc = ScanService(scan_delay=delay)
    svc.get_all_pages = _fake_get_all_pages
    svc._get_all_pages_threadsafe = _fake_get_all_pages
    return svc


def test_serial_dfs_output_order():
    """DFS 串行：子目录（含后代）先输出，本目录文件最后输出"""
    svc = _service()
    order: list[str] = []
    svc.on_item_found = lambda item: order.append(item.item_id)

    svc.scan("http://x", scan_mode="dfs", parallel=False, max_depth=10)

    assert order == ["d1", "d2", "d1/d1f.txt", "d2/d2f.txt", "root.txt"]


def test_serial_bfs_output_order():
    """BFS 串行：逐层输出，目录项先于本目录文件"""
    svc = _service()
    order: list[str] = []
    svc.on_item_found = lambda item: order.append(item.item_id)

    svc.scan("http://x", scan_mode="bfs", parallel=False, max_depth=10)

    assert order == ["d1", "d2", "root.txt", "d1/d1f.txt", "d2/d2f.txt"]


def test_parallel_dfs_true_concurrency():
    """并行 DFS：多个目录请求真实并发（修复假并行）"""
    svc = _service()
    svc.parallel_mode = True
    active = 0
    max_active = 0
    lock = threading.Lock()

    def slow_get_all_pages(base_url: str, dir_path: str, raw_href: str = ""):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.1)
        with lock:
            active -= 1
        return _fake_get_all_pages(base_url, dir_path, raw_href)

    svc._get_all_pages_threadsafe = slow_get_all_pages

    svc.scan("http://x", scan_mode="dfs", parallel=True, max_depth=10, max_workers=3)

    assert max_active >= 2, f"期望并发 ≥2，实际最大并发 {max_active}"


def test_parallel_bfs_true_concurrency():
    """并行 BFS：多个目录请求真实并发"""
    svc = _service()
    svc.parallel_mode = True
    active = 0
    max_active = 0
    lock = threading.Lock()

    def slow_get_all_pages(base_url: str, dir_path: str, raw_href: str = ""):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.1)
        with lock:
            active -= 1
        return _fake_get_all_pages(base_url, dir_path, raw_href)

    svc._get_all_pages_threadsafe = slow_get_all_pages

    svc.scan("http://x", scan_mode="bfs", parallel=True, max_depth=10, max_workers=3)

    assert max_active >= 2


def test_parallel_output_items_complete():
    """并行模式：输出项目集合与串行一致（顺序不保证）"""
    svc = _service()
    svc.parallel_mode = True
    ids: set[str] = set()
    svc.on_item_found = lambda item: ids.add(item.item_id)

    svc.scan("http://x", scan_mode="dfs", parallel=True, max_depth=10, max_workers=3)

    assert ids == {"d1", "d2", "d1/d1f.txt", "d2/d2f.txt", "root.txt"}


def test_all_dirs_marked_scanned():
    """无错误时：根与所有子目录均标记为已扫描"""
    svc = _service()
    svc.on_item_found = lambda _item: None

    svc.scan("http://x", scan_mode="dfs", parallel=False, max_depth=10)

    assert svc._scanned_dirs == {"", "d1", "d2"}


def test_scan_item_fields():
    """Item 字段正确性：目录 parent_id/full_path、文件 url"""
    svc = _service()
    collected: dict[str, DownloadItem] = {}
    svc.on_item_found = lambda item: collected.setdefault(item.item_id, item)

    svc.scan("http://x", scan_mode="dfs", parallel=False, max_depth=10)

    d1 = collected["d1"]
    assert d1.item_type == ItemType.DIR
    assert d1.parent_id == ""
    assert d1.full_path == "d1"
    assert d1.url == ""

    f = collected["d1/d1f.txt"]
    assert f.item_type == ItemType.FILE
    assert f.parent_id == "d1"
    assert f.full_path == "d1/d1f.txt"
    assert f.url == "http://x/d1f.txt"
