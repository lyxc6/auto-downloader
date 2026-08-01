"""扫描失败目录计数回归测试

验证:
- HttpClient.get_failed_dirs_count() 正确返回失败计数（404 不可重试路径触发）
- ScanService.get_failed_dirs_count() 正确转发
- 扫描收尾段使用的两个 getter 均存在于 ScanService（防止属性缺失回归）
"""

from unittest.mock import MagicMock

import pytest
import requests

from src.services.http_client import HttpClient
from src.services.scanner import ScanService


def _fake_response(status: int, text: str, raise_http: bool = False) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.encoding = "utf-8"
    if raise_http:
        r.raise_for_status.side_effect = requests.HTTPError("status", response=r)
    else:
        r.raise_for_status.return_value = None
    return r


@pytest.fixture
def client(monkeypatch):
    c = HttpClient()
    c._session = MagicMock()
    monkeypatch.setattr("src.services.http_client.time.sleep", lambda *_: None)
    return c


def test_failed_dirs_count_increments_on_404(client):
    """404 不可重试：立即失败并计入 failed_dirs"""
    client._session.get.return_value = _fake_response(404, "<html>404</html>", raise_http=True)
    assert client.get_page("http://x", retries=3) is None
    assert client.get_failed_dirs_count() == 1


def test_failed_dirs_count_zero_initially(client):
    assert client.get_failed_dirs_count() == 0


def test_scan_service_forwards_failed_dirs_count():
    svc = ScanService()
    fake_http = MagicMock()
    fake_http.get_failed_dirs_count.return_value = 3
    svc._http_client = fake_http
    assert svc.get_failed_dirs_count() == 3


def test_scan_service_exposes_both_summary_getters():
    """扫描收尾段依赖的两个 getter 必须存在"""
    svc = ScanService()
    assert callable(svc.get_failed_dirs_count)
    assert callable(svc.get_error_dirs_count)
