"""取消下载状态回归测试 (P1-6)

验证:
- download_file 流式下载中被取消 → 状态置为 CANCELLED 且发出状态回调
- 取消时 download_batch 统计中 cancelled 单独计数，不计入 failed
- cancel() 解除暂停阻塞，暂停中的下载可立即退出
"""

import threading
from unittest.mock import MagicMock

import pytest

from src.models.download_item import DownloadItem, DownloadStatus, ItemType
from src.services.downloader import DownloadService


def _item(full_path: str = "a/b.bin", url: str = "http://x/b.bin") -> DownloadItem:
    return DownloadItem(item_id=full_path, name="b.bin", url=url, item_type=ItemType.FILE, full_path=full_path)


def _stream_resp(cancel_cb):
    """流式响应：先吐若干块，随后触发取消回调并再吐一块（命中循环内取消检查）"""
    r = MagicMock()
    r.status_code = 200
    r.headers = {}
    r.raise_for_status.return_value = None

    def gen():
        yield b"x" * 1024
        yield b"x" * 1024
        cancel_cb()
        yield b"x" * 1024

    r.iter_content.return_value = gen()
    return r


def _wait(seconds: float):
    """不受 time.sleep monkeypatch 影响的等待"""
    threading.Event().wait(seconds)


@pytest.fixture
def svc(monkeypatch):
    s = DownloadService(max_workers=1, retry_times=1, timeout=10)
    s._session = MagicMock()
    monkeypatch.setattr("src.services.downloader.time.sleep", lambda *_: None)
    return s


def test_download_file_cancel_sets_cancelled_status(svc, tmp_path):
    """流式下载中被取消：状态 CANCELLED，回调发出，返回 False"""
    item = _item()
    resp = _stream_resp(svc.cancel)
    svc._session.get.return_value = resp

    statuses = []
    svc.on_status_changed = lambda iid, st: statuses.append((iid, st))

    assert svc.download_file(item, str(tmp_path)) is False
    assert item.status == DownloadStatus.CANCELLED
    assert (item.item_id, DownloadStatus.CANCELLED) in statuses


def test_download_file_cancel_while_paused(svc, tmp_path):
    """暂停中取消：cancel() 解除暂停阻塞，任务立即以 CANCELLED 退出"""
    item = _item()
    svc.pause()

    statuses = []
    svc.on_status_changed = lambda iid, st: statuses.append((iid, st))

    done = threading.Event()
    result = {}

    def run():
        result["ok"] = svc.download_file(item, str(tmp_path))
        done.set()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    _wait(0.05)
    svc.cancel()
    assert done.wait(timeout=5)
    assert result["ok"] is False
    assert item.status == DownloadStatus.CANCELLED
    assert (item.item_id, DownloadStatus.CANCELLED) in statuses


def test_download_batch_cancel_counts_cancelled(svc, tmp_path):
    """批量下载取消：已启动项计入 cancelled，不产生 failed/completed"""
    svc.max_workers = 2
    done = threading.Event()
    real_download_file = svc.download_file
    # 每个 GET 弹出独立 resp（独立生成器），避免 worker 间共享导致竞态
    svc._session.get.side_effect = [_stream_resp(svc.cancel) for _ in range(4)]

    def fake(item, download_dir):
        return real_download_file(item, download_dir)

    svc.download_file = fake

    items = [_item(f"f{i}.bin") for i in range(4)]
    result = {}

    def run():
        result["stats"] = svc.download_batch(items, str(tmp_path))
        done.set()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    assert done.wait(timeout=5)
    stats = result["stats"]
    assert stats.cancelled > 0
    assert stats.failed == 0
    assert stats.completed == 0
