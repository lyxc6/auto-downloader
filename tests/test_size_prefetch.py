"""文件大小预取功能测试"""

import threading
from unittest.mock import MagicMock, patch

from src.models.cache_manager import CacheManager
from src.models.download_item import DownloadItem, ItemType
from src.services.http_client import HttpClient


class TestHttpClientHeadFileSize:
    """测试 HttpClient.head_file_size 方法"""

    def test_head_returns_content_length(self):
        """HEAD 请求返回 Content-Length"""
        client = HttpClient()
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-length": "12345"}
        mock_session.head.return_value = mock_resp
        client._session = mock_session

        result = client.head_file_size("https://example.com/file.txt")

        assert result == 12345
        mock_resp.close.assert_called_once()

    def test_head_no_content_length(self):
        """HEAD 请求没有 Content-Length"""
        client = HttpClient()
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_session.head.return_value = mock_resp
        client._session = mock_session

        result = client.head_file_size("https://example.com/file.txt")

        assert result is None

    def test_head_405_falls_back_to_get(self):
        """HEAD 返回 405 时回退到 GET"""
        client = HttpClient()
        mock_session = MagicMock()
        mock_head_resp = MagicMock()
        mock_head_resp.status_code = 405
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.headers = {"content-length": "5678"}
        mock_session.head.return_value = mock_head_resp
        mock_session.get.return_value = mock_get_resp
        client._session = mock_session

        result = client.head_file_size("https://example.com/file.txt")

        assert result == 5678
        mock_get_resp.close.assert_called()

    def test_head_404_falls_back_to_get(self):
        """HEAD 返回 404 时回退到 GET"""
        client = HttpClient()
        mock_session = MagicMock()
        mock_head_resp = MagicMock()
        mock_head_resp.status_code = 404
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.headers = {"content-length": "9999"}
        mock_session.head.return_value = mock_head_resp
        mock_session.get.return_value = mock_get_resp
        client._session = mock_session

        result = client.head_file_size("https://example.com/file.txt")

        assert result == 9999
        mock_get_resp.close.assert_called()

    def test_head_exception_retries(self):
        """HEAD 请求异常重试"""
        import requests as _requests

        client = HttpClient()
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-length": "999"}
        mock_session.head.side_effect = [
            _requests.ConnectionError("Connection error"),
            mock_resp,
        ]
        client._session = mock_session

        with patch("src.services.http_client.time.sleep"):
            result = client.head_file_size("https://example.com/file.txt", retries=2)

        assert result == 999


class TestCacheManagerUpdateItemSize:
    """测试 CacheManager.update_item_size 方法"""

    def test_update_existing_item(self):
        """更新已存在项目的大小"""
        cm = CacheManager("/tmp/test_cache.json")
        item = DownloadItem(
            item_id="file1",
            name="file1.txt",
            url="https://example.com/file1.txt",
            item_type=ItemType.FILE,
            parent_id="",
            full_path="file1.txt",
            size=0,
        )
        cm.add_item(item)

        result = cm.update_item_size("file1", 12345)
        assert result is True
        assert cm.get_item("file1").size == 12345

    def test_update_nonexistent_item(self):
        """更新不存在的项目"""
        cm = CacheManager("/tmp/test_cache.json")
        result = cm.update_item_size("nonexistent", 12345)
        assert result is False

    def test_update_is_thread_safe(self):
        """并发更新线程安全"""
        cm = CacheManager("/tmp/test_cache.json")
        for i in range(100):
            item = DownloadItem(
                item_id=f"file{i}",
                name=f"file{i}.txt",
                url="",
                item_type=ItemType.FILE,
                parent_id="",
                full_path=f"file{i}.txt",
            )
            cm.add_item(item)

        errors = []

        def updater(item_id, size):
            try:
                cm.update_item_size(item_id, size)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=updater, args=(f"file{i}", i * 100)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        for i in range(100):
            assert cm.get_item(f"file{i}").size == i * 100


class TestDownloadItemSizeField:
    """测试 DownloadItem.size 字段"""

    def test_size_default_is_zero(self):
        """默认大小为0"""
        item = DownloadItem(
            item_id="f1", name="test.txt", url="", item_type=ItemType.FILE, parent_id="", full_path="test.txt"
        )
        assert item.size == 0

    def test_size_mutable(self):
        """size 字段可修改"""
        item = DownloadItem(
            item_id="f1", name="test.txt", url="", item_type=ItemType.FILE, parent_id="", full_path="test.txt"
        )
        item.size = 1024
        assert item.size == 1024

    def test_size_persists_in_dict(self):
        """size 在 to_dict/from_dict 中保持"""
        item = DownloadItem(
            item_id="f1",
            name="test.txt",
            url="",
            item_type=ItemType.FILE,
            parent_id="",
            full_path="test.txt",
            size=2048,
        )
        d = item.to_dict()
        item2 = DownloadItem.from_dict(d)
        assert item2.size == 2048
