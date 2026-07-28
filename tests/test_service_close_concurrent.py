"""service.close() 原子化与关闭流程去竞态回归测试 (#6, #7)

验证:
- close() 在 self._lock 内执行（原子）
- session 属性在 self._lock 内创建（避免与 close 竞态/泄漏）
- close() 幂等，并发调用无异常
- controller 提供 lock 保护的公共 close_service()
- close_service() 在 _service 为 None 时安全
"""

import threading
from unittest.mock import MagicMock

import pytest

from src.controllers.download_controller import DownloadController
from src.controllers.scan_controller import ScanController
from src.models import AppConfig
from src.services.downloader import DownloadService
from src.services.scanner import ScanService

# ----------------------------- 服务层 close/session 原子性 -----------------------------


@pytest.mark.parametrize("make", [ScanService, lambda: DownloadService()])
def test_close_acquires_lock(make):
    """close() 应获取 self._lock，与持锁者互斥"""
    svc = make()
    svc._session = MagicMock()  # 使 close 有事可做
    done = threading.Event()

    def call_close():
        svc.close()
        done.set()

    with svc._lock:  # 主线程持锁
        t = threading.Thread(target=call_close)
        t.start()
        completed = done.wait(timeout=0.2)
        assert not completed, "close() 未获取 _lock，与锁纪律不一致"
    t.join(timeout=2)
    assert done.wait(timeout=2), "close() 持锁后未能完成"


@pytest.mark.parametrize("make", [ScanService, lambda: DownloadService()])
def test_session_property_acquires_lock(make):
    """session 属性应获取 self._lock，避免与 close 竞态造成泄漏/撕裂"""
    svc = make()
    svc._session = None  # 触发懒创建分支
    done = threading.Event()

    def get_sess():
        _ = svc.session
        done.set()

    with svc._lock:
        t = threading.Thread(target=get_sess)
        t.start()
        completed = done.wait(timeout=0.2)
        assert not completed, "session 属性未获取 _lock"
    t.join(timeout=2)
    assert done.wait(timeout=2)


@pytest.mark.parametrize("make", [ScanService, lambda: DownloadService()])
def test_close_idempotent_concurrent(make):
    """并发多次 close 不产生异常"""
    svc = make()
    svc._session = MagicMock()
    errors = []

    def closer():
        try:
            for _ in range(100):
                svc.close()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=closer) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert not errors, f"并发 close 异常: {errors}"
    assert svc._session is None


# ----------------------------- 控制器层 close_service -----------------------------


@pytest.fixture
def scan_ctrl():
    cfg = AppConfig()
    from src.models import CacheManager

    # close_service 测试不触发缓存 I/O，使用默认路径即可
    return ScanController(cfg, CacheManager(cfg.cache_file))


@pytest.fixture
def download_ctrl():
    return DownloadController(AppConfig())


def test_scan_controller_close_service_exists_and_lock_protected(scan_ctrl):
    """close_service() 应存在并获取 controller _lock"""
    done = threading.Event()

    def call():
        scan_ctrl.close_service()
        done.set()

    with scan_ctrl._lock:
        t = threading.Thread(target=call)
        t.start()
        completed = done.wait(timeout=0.2)
        assert not completed, "close_service() 未获取 _lock"
    t.join(timeout=2)
    assert done.wait(timeout=2)


def test_download_controller_close_service_exists_and_lock_protected(download_ctrl):
    done = threading.Event()

    def call():
        download_ctrl.close_service()
        done.set()

    with download_ctrl._lock:
        t = threading.Thread(target=call)
        t.start()
        completed = done.wait(timeout=0.2)
        assert not completed, "close_service() 未获取 _lock"
    t.join(timeout=2)
    assert done.wait(timeout=2)


def test_close_service_handles_none_service(scan_ctrl, download_ctrl):
    """_service 为 None 时 close_service() 不抛异常"""
    scan_ctrl.close_service()
    download_ctrl.close_service()
    assert scan_ctrl._service is None
    assert download_ctrl._service is None


def test_close_service_closes_and_clears(scan_ctrl):
    """close_service() 关闭 service 并置 None"""
    fake = MagicMock()
    scan_ctrl._service = fake
    scan_ctrl.close_service()
    fake.close.assert_called_once()
    assert scan_ctrl._service is None


def test_close_service_concurrent_safe(scan_ctrl):
    """并发 close_service() 无异常"""
    fake = MagicMock()
    scan_ctrl._service = fake
    errors = []

    def call():
        try:
            for _ in range(50):
                scan_ctrl.close_service()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=call) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=3)
    assert not errors, f"并发 close_service 异常: {errors}"
