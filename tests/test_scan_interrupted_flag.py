"""扫描中断标志回归测试

验证:
- 正常完成的扫描：last_scan_interrupted 为 False
- 取消的扫描：last_scan_interrupted 为 True（用于跳过取消后的 size 预取）
- 三个扫描入口都会清空中断标志（防止上次取消遗留）
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from src.controllers.scan_controller import ScanController
from src.models import AppConfig, CacheManager, DownloadItem, ItemType


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def _make_service(is_cancelled: bool = False, is_timeout: bool = False) -> MagicMock:
    svc = MagicMock()
    svc.scan.return_value = None
    svc.is_cancelled.return_value = is_cancelled
    svc.is_timeout.return_value = is_timeout
    svc.get_failed_dirs_count.return_value = 0
    svc.get_error_dirs_count.return_value = 0
    return svc


@pytest.fixture
def controller(monkeypatch):
    c = ScanController(AppConfig(), CacheManager(""))
    c._create_service = lambda: _make_service()
    return c


def _wait_scan_done(controller: ScanController, qapp):
    assert controller._thread is not None
    controller._thread.join(timeout=5)
    qapp.processEvents()  # 处理 worker 线程排队的信号


def test_normal_scan_not_interrupted(controller, qapp):
    """正常完成 → 中断标志为 False，且发出完成信号"""
    completed = []
    controller.scan_completed.connect(lambda *a: completed.append(a))
    controller.start_scan("http://x")
    _wait_scan_done(controller, qapp)
    assert controller.last_scan_interrupted is False
    assert len(completed) == 1


def test_cancelled_scan_sets_interrupted(controller, qapp):
    """取消 → 中断标志为 True（app 据此跳过 size 预取）"""
    controller._create_service = lambda: _make_service(is_cancelled=True)
    controller.start_scan("http://x")
    _wait_scan_done(controller, qapp)
    assert controller.last_scan_interrupted is True


def test_timeout_scan_sets_interrupted(controller, qapp):
    """超时 → 中断标志为 True"""
    controller._create_service = lambda: _make_service(is_timeout=True)
    controller.start_scan("http://x")
    _wait_scan_done(controller, qapp)
    assert controller.last_scan_interrupted is True


def test_start_scan_clears_previous_interrupted(controller, qapp):
    """入口清空：上次取消的遗留标志不会影响本次扫描"""
    controller._scan_interrupted.set()
    controller.start_scan("http://x")
    _wait_scan_done(controller, qapp)
    assert controller.last_scan_interrupted is False


def test_start_scan_with_cache_complete_path_clears_flag():
    """缓存完整直发完成路径也会清空中断标志"""
    cache = CacheManager("")
    cache.set_url("http://x")
    cache.add_item(
        DownloadItem(item_id="a.bin", name="a.bin", url="http://x/a.bin", item_type=ItemType.FILE, full_path="a.bin")
    )
    cache.set_scan_complete(True)
    c = ScanController(AppConfig(), cache)
    c._scan_interrupted.set()
    c.start_scan_with_cache("http://x")
    assert c.last_scan_interrupted is False
    assert c.is_scanning is False


def test_interrupted_flag_thread_safe():
    """标志基于 threading.Event，跨线程置位/读取安全"""
    c = ScanController(AppConfig(), CacheManager(""))
    c._scan_interrupted.set()
    assert c.last_scan_interrupted is True
    c._scan_interrupted.clear()
    assert c.last_scan_interrupted is False
