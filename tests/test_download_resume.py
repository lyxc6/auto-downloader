"""download_file 断点续传与完整性校验回归测试 (#3)

验证:
- 完整文件 (本地大小 == Content-Length) 跳过
- 半文件 (本地 < CL) 且服务器支持 Range: 续传追加
- 半文件但服务器不支持 Range: 删除重下
- 损坏文件 (本地 > CL): 删除重下
- 服务器无 Content-Length: 保持跳过
- 服务器忽略 Range 返回 200: 覆盖重下
- 新文件正常下载
"""

from unittest.mock import MagicMock

import pytest

from src.models.download_item import DownloadItem, DownloadStatus, ItemType
from src.services.downloader import DownloadService


def _item(full_path: str = "a/b.bin", url: str = "http://x/b.bin") -> DownloadItem:
    return DownloadItem(item_id=full_path, name="b.bin", url=url, item_type=ItemType.FILE, full_path=full_path)


def _stream_resp(status: int, chunks, content_length=None, accept_ranges=None):
    r = MagicMock()
    r.status_code = status
    r.headers = {}
    if content_length is not None:
        r.headers["content-length"] = str(content_length)
    if accept_ranges is not None:
        r.headers["accept-ranges"] = accept_ranges
    r.iter_content.return_value = iter(chunks)
    r.raise_for_status.return_value = None
    return r


def _head_resp(status: int, content_length=None, accept_ranges=None, raise_http=False):
    r = MagicMock()
    r.status_code = status
    r.headers = {}
    if content_length is not None:
        r.headers["content-length"] = str(content_length)
    if accept_ranges is not None:
        r.headers["accept-ranges"] = accept_ranges
    if raise_http:
        import requests

        r.raise_for_status.side_effect = requests.HTTPError("head", response=r)
    else:
        r.raise_for_status.return_value = None
    return r


@pytest.fixture
def svc(monkeypatch):
    s = DownloadService(max_workers=1, retry_times=1, timeout=10)
    s._session = MagicMock()
    monkeypatch.setattr("src.services.downloader.time.sleep", lambda *_: None)
    return s


def test_complete_file_skipped(svc, tmp_path):
    """本地大小 == CL → SKIPPED，不发起 GET"""
    local = tmp_path / "a" / "b.bin"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"\x00" * 1000)
    svc._session.head.return_value = _head_resp(200, content_length=1000, accept_ranges="bytes")

    item = _item()
    ok = svc.download_file(item, str(tmp_path))

    assert ok and item.status == DownloadStatus.SKIPPED
    svc._session.get.assert_not_called()
    assert local.stat().st_size == 1000


def test_partial_resume_with_range(svc, tmp_path):
    """本地 500 < CL 1000 且支持 Range → 续传追加到 1000，COMPLETED"""
    local = tmp_path / "a" / "b.bin"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"\x00" * 500)
    svc._session.head.return_value = _head_resp(200, content_length=1000, accept_ranges="bytes")
    # Range 请求返回 206，剩余 500 字节
    svc._session.get.return_value = _stream_resp(206, [b"\x01" * 500], content_length=500)

    item = _item()
    ok = svc.download_file(item, str(tmp_path))

    assert ok and item.status == DownloadStatus.COMPLETED
    assert local.stat().st_size == 1000
    # 应发送 Range 头
    _, kwargs = svc._session.get.call_args
    assert kwargs.get("headers", {}).get("Range") == "bytes=500-"
    assert item.downloaded_size == 1000
    assert item.size == 1000


def test_partial_no_range_support_delete_redownload(svc, tmp_path):
    """本地 500 < CL 1000 但不支持 Range → 删除重下 1000"""
    local = tmp_path / "a" / "b.bin"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"\x00" * 500)
    svc._session.head.return_value = _head_resp(200, content_length=1000, accept_ranges="none")
    svc._session.get.return_value = _stream_resp(200, [b"\x02" * 1000], content_length=1000)

    item = _item()
    ok = svc.download_file(item, str(tmp_path))

    assert ok and item.status == DownloadStatus.COMPLETED
    assert local.stat().st_size == 1000
    # 全新下载，不应有 Range 头
    _, kwargs = svc._session.get.call_args
    assert "Range" not in kwargs.get("headers", {})
    # 内容应是全新的 \x02，不含旧 \x00
    assert local.read_bytes() == b"\x02" * 1000


def test_corrupt_oversize_delete_redownload(svc, tmp_path):
    """本地 1200 > CL 1000 → 删除重下 1000"""
    local = tmp_path / "a" / "b.bin"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"\x00" * 1200)
    svc._session.head.return_value = _head_resp(200, content_length=1000, accept_ranges="bytes")
    svc._session.get.return_value = _stream_resp(200, [b"\x03" * 1000], content_length=1000)

    item = _item()
    ok = svc.download_file(item, str(tmp_path))

    assert ok and item.status == DownloadStatus.COMPLETED
    assert local.stat().st_size == 1000
    assert local.read_bytes() == b"\x03" * 1000


def test_no_content_length_skipped(svc, tmp_path):
    """服务器无 Content-Length → 无法校验，保持跳过"""
    local = tmp_path / "a" / "b.bin"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"\x00" * 500)
    svc._session.head.return_value = _head_resp(200, content_length=None, accept_ranges="bytes")

    item = _item()
    ok = svc.download_file(item, str(tmp_path))

    assert ok and item.status == DownloadStatus.SKIPPED
    svc._session.get.assert_not_called()


def test_resume_server_ignores_range(svc, tmp_path):
    """本地 500，发了 Range 但服务器返回 200(忽略) → 覆盖重下 1000"""
    local = tmp_path / "a" / "b.bin"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"\x00" * 500)
    svc._session.head.return_value = _head_resp(200, content_length=1000, accept_ranges="bytes")
    svc._session.get.return_value = _stream_resp(200, [b"\x04" * 1000], content_length=1000)

    item = _item()
    ok = svc.download_file(item, str(tmp_path))

    assert ok and item.status == DownloadStatus.COMPLETED
    assert local.stat().st_size == 1000
    assert local.read_bytes() == b"\x04" * 1000


def test_new_file_downloads_normally(svc, tmp_path):
    """无本地文件 → 正常下载 100 字节"""
    local = tmp_path / "a" / "b.bin"
    svc._session.get.return_value = _stream_resp(200, [b"\x05" * 100], content_length=100)

    item = _item()
    ok = svc.download_file(item, str(tmp_path))

    assert ok and item.status == DownloadStatus.COMPLETED
    assert local.stat().st_size == 100
    # 新文件不发 HEAD（无文件可校验）
    svc._session.head.assert_not_called()
    _, kwargs = svc._session.get.call_args
    assert "Range" not in kwargs.get("headers", {})


def test_empty_local_file_redownloads(svc, tmp_path):
    """本地 0 字节空文件 → 正常下载"""
    local = tmp_path / "a" / "b.bin"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"")
    svc._session.get.return_value = _stream_resp(200, [b"\x06" * 100], content_length=100)

    item = _item()
    ok = svc.download_file(item, str(tmp_path))

    assert ok and item.status == DownloadStatus.COMPLETED
    assert local.stat().st_size == 100
