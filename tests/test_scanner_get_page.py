"""ScanService.get_page 状态校验回归测试 (#5)

验证:
- 200 返回页面文本
- 4xx 直接返回 None，不重试
- 5xx 重试满次数后返回 None
- 网络错误重试满次数后返回 None
"""

from unittest.mock import MagicMock

import pytest
import requests

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
def svc(monkeypatch):
    s = ScanService()
    # 注入 mock session（绕过懒创建）
    s._session = MagicMock()
    # 跳过重试间的真实 sleep，加速测试
    monkeypatch.setattr("src.services.scanner.time.sleep", lambda *_: None)
    return s


def test_get_page_returns_text_on_200(svc):
    svc._session.get.return_value = _fake_response(200, "<html>ok</html>")
    assert svc.get_page("http://x") == "<html>ok</html>"


def test_get_page_4xx_returns_none_without_retry(svc):
    """4xx 应立即返回 None，只请求一次"""
    svc._session.get.return_value = _fake_response(404, "<html>404 Not Found</html>", raise_http=True)
    result = svc.get_page("http://x", retries=3)
    assert result is None
    # 4xx 不重试：只调用一次
    assert svc._session.get.call_count == 1


def test_get_page_403_returns_none_without_retry(svc):
    svc._session.get.return_value = _fake_response(403, "<html>forbidden</html>", raise_http=True)
    assert svc.get_page("http://x", retries=3) is None
    assert svc._session.get.call_count == 1


def test_get_page_5xx_retries_then_none(svc):
    """5xx 应重试 retries 次，最终返回 None"""
    svc._session.get.return_value = _fake_response(503, "<html>server error</html>", raise_http=True)
    result = svc.get_page("http://x", retries=3)
    assert result is None
    # 重试 3 次 + 首次 = 4 次
    assert svc._session.get.call_count == 4


def test_get_page_network_error_retries_then_none(svc):
    """网络异常应重试后返回 None"""
    svc._session.get.side_effect = requests.ConnectionError("boom")
    result = svc.get_page("http://x", retries=2)
    assert result is None
    assert svc._session.get.call_count == 3


def test_get_page_cancelled_returns_none(svc):
    """取消标志置位后立即返回 None"""
    svc.cancel()
    result = svc.get_page("http://x", retries=3)
    assert result is None
    # 取消后不应发起请求
    assert svc._session.get.call_count == 0


def test_get_page_5xx_then_200_succeeds(svc):
    """5xx 后重试成功应返回文本"""
    svc._session.get.side_effect = [
        _fake_response(500, "err", raise_http=True),
        _fake_response(200, "<html>ok</html>"),
    ]
    result = svc.get_page("http://x", retries=3)
    assert result == "<html>ok</html>"
    assert svc._session.get.call_count == 2
