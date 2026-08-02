"""边扫边取:SizePrefetcher 增量队列模式测试

方案 B:扫描过程中发现文件即提交预取,扫描结束 done() 后队列耗尽发 completed。
"""

import os
import threading
import time
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.controllers.size_prefetcher import SizePrefetcher
from src.models import CacheManager, DownloadItem, ItemType


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def _make_item(item_id: str, size: int = 0, url: str = "http://x/{}".format("f")) -> DownloadItem:
    return DownloadItem(
        item_id=item_id,
        name=item_id,
        url=url,
        item_type=ItemType.FILE,
        parent_id="",
        full_path=item_id,
        size=size,
    )


def _connect_direct(prefetch: SizePrefetcher, on_progress=None, on_completed=None):
    """直接连接信号（worker 线程 emit，无需事件循环派发）"""
    if on_progress:
        prefetch.progress.connect(on_progress, Qt.ConnectionType.DirectConnection)
    if on_completed:
        prefetch.completed.connect(on_completed, Qt.ConnectionType.DirectConnection)


class TestSizePrefetcherIncremental:
    """增量队列模式核心行为"""

    def test_start_with_backlog_collects_existing_files(self, qapp, tmp_path):
        """start() 兜底:收集缓存中已有 size<=0 的文件入队并完成"""
        cm = CacheManager(str(tmp_path / "cache.json"))
        cm.try_add_item(_make_item("a.bin", size=0, url="http://x/a.bin"))
        cm.try_add_item(_make_item("b.bin", size=0, url="http://x/b.bin"))
        cm.try_add_item(_make_item("c.bin", size=100, url="http://x/c.bin"))  # 已取大小的跳过

        prefetch = SizePrefetcher(cm, lambda *a: None)
        progress = []
        done = threading.Event()
        _connect_direct(prefetch, on_progress=lambda iid, size: progress.append((iid, size)), on_completed=done.set)

        with patch.object(SizePrefetcher, "_get_client") as mock_get:
            client = MagicMock()
            client.head_file_size.side_effect = lambda url, retries=2: {"http://x/a.bin": 10, "http://x/b.bin": 20}[url]
            mock_get.return_value = client

            prefetch.start(max_workers=2)
            prefetch.done()

            assert done.wait(timeout=5), "completed 信号未在超时内发出"

        assert cm.get_item("a.bin").size == 10
        assert cm.get_item("b.bin").size == 20
        assert cm.get_item("c.bin").size == 100  # 不被重新获取

    def test_submit_during_scan_then_done(self, qapp, tmp_path):
        """扫描中 submit 的文件也会被预取;done 后队列耗尽发 completed"""
        cm = CacheManager(str(tmp_path / "cache.json"))
        prefetch = SizePrefetcher(cm, lambda *a: None)
        progress = []
        done = threading.Event()
        _connect_direct(prefetch, on_progress=lambda iid, size: progress.append((iid, size)), on_completed=done.set)

        with patch.object(SizePrefetcher, "_get_client") as mock_get:
            client = MagicMock()
            client.head_file_size.return_value = 42
            mock_get.return_value = client

            prefetch.start(max_workers=1)
            # 模拟扫描线程陆续提交（真实流程中 handle_item 已先将 item 加入缓存）
            for fid in ("f1", "f2"):
                cm.try_add_item(_make_item(fid, url="http://x/" + fid))
                prefetch.submit(cm.get_item(fid))
            prefetch.done()

            assert done.wait(timeout=5), "completed 信号未发出"

        assert cm.get_item("f1").size == 42
        assert cm.get_item("f2").size == 42
        assert len(progress) == 2

    def test_done_before_start_is_noop(self, qapp):
        """从未 start 时 done() 不产生异常"""
        cm = CacheManager("")
        prefetch = SizePrefetcher(cm, lambda *a: None)
        prefetch.done()  # 不应抛异常

    def test_cancel_stops_processing(self, qapp, tmp_path):
        """cancel 后不再处理新提交"""
        cm = CacheManager(str(tmp_path / "cache.json"))
        prefetch = SizePrefetcher(cm, lambda *a: None)

        with patch.object(SizePrefetcher, "_get_client") as mock_get:
            client = MagicMock()
            client.head_file_size.return_value = 7
            mock_get.return_value = client

            prefetch.start(max_workers=1)
            prefetch.cancel()
            # 模拟扫描线程提交（真实流程中 handle_item 已先将 item 加入缓存）
            cm.try_add_item(_make_item("f1", url="http://x/f1"))
            prefetch.submit(cm.get_item("f1"))
            prefetch.done()

            time.sleep(0.3)

        assert cm.get_item("f1").size == 0  # 未处理

    def test_dir_path_filter_on_start(self, qapp, tmp_path):
        """start(dir_path=...) 只兜底收集该目录下的文件"""
        cm = CacheManager(str(tmp_path / "cache.json"))
        cm.try_add_item(_make_item("sub/a.bin", url="http://x/sub/a.bin"))
        cm.try_add_item(_make_item("other/b.bin", url="http://x/other/b.bin"))

        prefetch = SizePrefetcher(cm, lambda *a: None)
        done = threading.Event()
        _connect_direct(prefetch, on_completed=done.set)

        with patch.object(SizePrefetcher, "_get_client") as mock_get:
            client = MagicMock()
            client.head_file_size.return_value = 5
            mock_get.return_value = client

            prefetch.start(max_workers=2, dir_path="sub")
            prefetch.done()
            assert done.wait(timeout=5)

        assert cm.get_item("sub/a.bin").size == 5
        assert cm.get_item("other/b.bin").size == 0  # 目录外不处理


class TestPrefetchLifecycleIntegration:
    """ScanController 集成:扫描 worker 管理 prefetch 生命周期"""

    def test_scan_submits_files_and_done_on_complete(self, qapp, monkeypatch, tmp_path):
        """正常扫描:文件经 runner 提交给 prefetch,扫描结束 done"""
        from src.controllers.scan_controller import ScanController
        from src.models import AppConfig

        cm = CacheManager(str(tmp_path / "cache.json"))
        controller = ScanController(AppConfig(), cm)

        # mock service:scan 时通过 on_item_found 回调提交文件
        def fake_scan(url, scan_mode=None, parallel=None, max_depth=None, max_workers=None, dir_path="", parent_id=""):
            svc = controller._service
            for name in ("f1.bin", "f2.bin"):
                svc.on_item_found(
                    DownloadItem(
                        item_id=name,
                        name=name,
                        url="http://x/" + name,
                        item_type=ItemType.FILE,
                        parent_id="",
                        full_path=name,
                    )
                )
            svc.on_item_found(
                DownloadItem(item_id="d1", name="d1", url="", item_type=ItemType.DIR, parent_id="", full_path="d1")
            )

        svc = MagicMock()
        svc.scan.side_effect = fake_scan
        svc.is_cancelled.return_value = False
        svc.is_timeout.return_value = False
        svc.get_failed_dirs_count.return_value = 0
        svc.get_error_dirs_count.return_value = 0
        controller._create_service = lambda: svc

        completed = []
        controller.size_prefetch_completed.connect(lambda: completed.append(True), Qt.ConnectionType.DirectConnection)

        with patch.object(SizePrefetcher, "_get_client") as mock_get:
            client = MagicMock()
            client.head_file_size.return_value = 99
            mock_get.return_value = client

            controller.start_scan("http://x")
            assert controller._thread is not None
            controller._thread.join(timeout=5)
            qapp.processEvents()

            # 等待 prefetch 完成
            deadline = 5
            while not completed and deadline > 0:
                time.sleep(0.1)
                qapp.processEvents()
                deadline -= 0.1

        assert cm.get_item("f1.bin").size == 99
        assert cm.get_item("f2.bin").size == 99
        assert completed, "prefetch completed 未发出"

    def test_cancelled_scan_cancels_prefetch(self, qapp, tmp_path):
        """取消扫描:prefetch 被取消,不再处理提交"""
        from src.controllers.scan_controller import ScanController
        from src.models import AppConfig

        cm = CacheManager(str(tmp_path / "cache.json"))
        controller = ScanController(AppConfig(), cm)

        svc = MagicMock()
        svc.scan.side_effect = lambda **kw: None
        svc.is_cancelled.return_value = True
        svc.is_timeout.return_value = False
        svc.get_failed_dirs_count.return_value = 0
        svc.get_error_dirs_count.return_value = 0
        controller._create_service = lambda: svc

        with patch.object(SizePrefetcher, "_get_client") as mock_get:
            client = MagicMock()
            client.head_file_size.return_value = 55
            mock_get.return_value = client

            controller.start_scan("http://x")
            assert controller._thread is not None
            controller._thread.join(timeout=5)
            qapp.processEvents()

        # 取消时 prefetch 应被 cancel(不再处理文件)
        assert controller._prefetch._cancel_flag.is_set()
