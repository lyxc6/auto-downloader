"""扫描信号批量+时间窗节流回归测试 (C12)

验证:
- items_found 批量信号替代 per-item item_found
- buffer 满 50 项 emit 一次
- 距上次 flush >= 100ms 时 emit
- 扫描结束 flush 剩余 buffer
- scan_progress 节流到批量 cadence（不再 per-item）
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt

from src.controllers import scan_controller as scan_module
from src.controllers.scan_controller import ScanController
from src.models import DownloadItem, ItemType


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def advance(self, dt):
        self.now += dt


class FakeService:
    def __init__(self, script, clock):
        self.script = script
        self.clock = clock
        self.on_item_found = None
        self.on_error = None
        self.on_log = None
        self.on_dir_scanned = None

    def scan_directory(self, url, max_depth=10):
        for action in self.script:
            if action[0] == "item":
                self.on_item_found(action[1])
            elif action[0] == "advance":
                self.clock.advance(action[1])
        return []

    def close(self):
        pass

    def cancel(self):
        pass

    def is_cancelled(self):
        return False

    def set_scanned_dirs(self, dirs):
        pass


def _fake_item(i):
    return DownloadItem(
        item_id=f"f{i}", name=f"f{i}", url=f"http://x/f{i}",
        item_type=ItemType.FILE, full_path=f"f{i}", size=10,
    )


@pytest.fixture
def make_controller(monkeypatch):
    def _make(script, clock):
        config = type("C", (), {"max_depth": 5})()
        cache = type("C", (), {
            "add_item": lambda self, item: None,
            "has_item": lambda self, item_id: False,
            "save": lambda self, url="": True,
            "mark_dir_scanned": lambda self, dp: None,
            "set_scan_complete": lambda self, complete: None,
        })()
        ctrl = ScanController(config, cache)

        monkeypatch.setattr(scan_module, "monotonic", clock.monotonic)

        def fake_create_service():
            svc = FakeService(script, clock)
            svc.on_error = lambda msg: ctrl.scan_error.emit(msg)
            svc.on_log = lambda msg, level: ctrl.log_message.emit(msg, level)
            return svc

        monkeypatch.setattr(ctrl, "_create_service", fake_create_service)
        return ctrl

    return _make


def _run_and_join(ctrl):
    ctrl.start_scan("http://x")
    ctrl._thread.join(timeout=10)
    assert not ctrl._thread.is_alive(), "扫描线程未在超时内结束"


def test_batch_emits_at_50(make_controller):
    clock = FakeClock()
    script = [("item", _fake_item(i)) for i in range(50)]
    ctrl = make_controller(script, clock)
    items_found = []
    ctrl.items_found.connect(
        lambda items: items_found.append(items), Qt.DirectConnection
    )
    _run_and_join(ctrl)
    assert len(items_found) == 1
    assert len(items_found[0]) == 50


def test_batch_emits_at_100ms(make_controller):
    clock = FakeClock()
    script = [("item", _fake_item(i)) for i in range(10)]
    script.append(("advance", 0.1))
    script.append(("item", _fake_item(10)))
    ctrl = make_controller(script, clock)
    items_found = []
    ctrl.items_found.connect(
        lambda items: items_found.append(items), Qt.DirectConnection
    )
    _run_and_join(ctrl)
    assert len(items_found) == 1
    assert len(items_found[0]) == 11


def test_flush_remaining_on_complete(make_controller):
    clock = FakeClock()
    script = [("item", _fake_item(i)) for i in range(30)]
    ctrl = make_controller(script, clock)
    items_found = []
    ctrl.items_found.connect(
        lambda items: items_found.append(items), Qt.DirectConnection
    )
    _run_and_join(ctrl)
    assert len(items_found) == 1
    assert len(items_found[0]) == 30


def test_progress_throttled_to_batch(make_controller):
    clock = FakeClock()
    script = [("item", _fake_item(i)) for i in range(50)]
    ctrl = make_controller(script, clock)
    progress = []
    ctrl.scan_progress.connect(
        lambda f, d: progress.append((f, d)), Qt.DirectConnection
    )
    _run_and_join(ctrl)
    assert len(progress) == 1
