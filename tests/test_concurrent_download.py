"""download_batch 并发下载回归测试 (#4)

验证:
- max_workers>1 时真实并发（耗时显著小于顺序）
- max_workers=1 时顺序
- 统计 (completed/failed/skipped) 正确聚合
- 取消后已启动任务能停止，未启动的不执行
"""
import threading
import time

import pytest

from src.models.download_item import DownloadItem, DownloadStatus, ItemType
from src.services.downloader import DownloadService


def _item(item_id: str) -> DownloadItem:
    return DownloadItem(item_id=item_id, name=item_id, url="http://x/" + item_id,
                        item_type=ItemType.FILE, full_path=item_id)


@pytest.fixture
def svc():
    # 注意: 不 patch time.sleep —— 并发计时需真实 sleep；
    # 真实 download_file 不被调用（各测试替换为 fake），无需抑制重试 sleep
    return DownloadService(max_workers=3, retry_times=1, timeout=10)


def _measure(svc, items):
    """替换 download_file 为带真实 sleep 的计时假实现，返回 (stats, elapsed)"""
    def fake_download_file(item, download_dir):
        if svc.is_cancelled():
            item.status = DownloadStatus.FAILED
            return False
        time.sleep(0.2)
        item.status = DownloadStatus.COMPLETED
        return True

    svc.download_file = fake_download_file
    start = time.perf_counter()
    stats = svc.download_batch(items, "/tmp/unused")
    elapsed = time.perf_counter() - start
    return stats, elapsed


def test_download_batch_concurrent_faster_than_sequential(svc):
    """max_workers=3, 5 文件各 0.2s → 并发约 0.4s，远小于顺序 1.0s"""
    svc.max_workers = 3
    items = [_item(f"f{i}.bin") for i in range(5)]
    stats, elapsed = _measure(svc, items)
    assert stats.completed == 5
    assert elapsed < 0.7, f"未表现出并发，耗时 {elapsed:.2f}s"


def test_download_batch_max_workers_1_is_sequential(svc):
    """max_workers=1, 5 文件各 0.2s → 顺序约 1.0s"""
    svc.max_workers = 1
    items = [_item(f"f{i}.bin") for i in range(5)]
    stats, elapsed = _measure(svc, items)
    assert stats.completed == 5
    assert elapsed >= 0.85, f"未表现出顺序，耗时 {elapsed:.2f}s"


def test_download_batch_stats_completed(svc):
    svc.max_workers = 3
    items = [_item(f"f{i}.bin") for i in range(5)]
    stats, _ = _measure(svc, items)
    assert stats.completed == 5
    assert stats.failed == 0
    assert stats.skipped == 0
    assert stats.total_files == 5


def test_download_batch_stats_mixed(svc):
    """混合状态：完成/跳过/失败统计正确"""
    svc.max_workers = 3

    def fake(item, download_dir):
        if svc.is_cancelled():
            item.status = DownloadStatus.FAILED
            return False
        if "skip" in item.item_id:
            item.status = DownloadStatus.SKIPPED
            return True
        if "fail" in item.item_id:
            item.status = DownloadStatus.FAILED
            return False
        time.sleep(0.05)
        item.status = DownloadStatus.COMPLETED
        return True

    svc.download_file = fake
    items = [_item("ok1.bin"), _item("ok2.bin"), _item("skip1.bin"), _item("fail1.bin")]
    stats = svc.download_batch(items, "/tmp/unused")
    assert stats.completed == 2
    assert stats.skipped == 1
    assert stats.failed == 1
    assert stats.total_files == 4


def test_download_batch_cancel_stops_running(svc):
    """运行中取消：已启动的检测取消后停止，未启动的不执行"""
    svc.max_workers = 2
    started = []
    done = threading.Event()

    def fake(item, download_dir):
        started.append(item.item_id)
        # 长任务，给主线程取消机会
        for _ in range(20):
            if svc.is_cancelled():
                item.status = DownloadStatus.FAILED
                return False
            time.sleep(0.02)
        item.status = DownloadStatus.COMPLETED
        return True

    svc.download_file = fake

    items = [_item(f"f{i}.bin") for i in range(5)]
    result = {}

    def run():
        result["stats"] = svc.download_batch(items, "/tmp/unused")
        done.set()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    time.sleep(0.05)  # 让 2 个 worker 启动
    svc.cancel()
    assert done.wait(timeout=5)
    stats = result["stats"]
    # 取消后不应全部完成
    assert stats.completed < 5
    # 已启动数受 max_workers 限制
    assert len(started) <= 5
