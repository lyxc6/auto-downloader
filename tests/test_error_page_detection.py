"""错误页面检测相关测试"""

from unittest.mock import patch

import pytest

from src.services.scanner import ScanService


@pytest.fixture
def service():
    """创建 ScanService 实例"""
    return ScanService()


class TestErrorPageDetection:
    """测试错误页面检测功能"""

    def test_xml_parsing_failed_error(self, service):
        """测试检测 XML Parsing Failed 错误页面"""
        html = """
        <div style="margin-bottom:15px;padding:10px;background:#f8d7da;color:#721c24;border-radius:4px;">
            <strong>错误：</strong> XML Parsing Failed
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 0

    def test_other_server_error(self, service):
        """测试检测其他服务器错误页面"""
        html = """
        <div style="margin-bottom:15px;padding:10px;background:#f8d7da;color:#721c24;border-radius:4px;">
            <strong>错误：</strong> 服务器内部错误
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 0

    def test_normal_page_not_affected(self, service):
        """测试正常页面不受影响"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="?dir=folder1">folder1</a></li>
            <li style="margin:8px 0;"><a href="file1.txt">file1.txt</a></li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 2
        assert items[0] == ("dir", "folder1", "?dir=folder1")
        assert items[1] == ("file", "file1.txt", "file1.txt")

    def test_error_page_with_normal_content(self, service):
        """测试错误页面同时包含正常内容"""
        html = """
        <div style="margin-bottom:15px;padding:10px;background:#f8d7da;color:#721c24;border-radius:4px;">
            <strong>错误：</strong> XML Parsing Failed
        </div>
        <ul>
            <li><a href="file1.txt">📄 file1.txt</a></li>
        </ul>
        """
        items = service.parse_items(html)
        # 错误页面应该返回空列表，不解析后续内容
        assert len(items) == 0

    def test_empty_html(self, service):
        """测试空 HTML"""
        html = ""
        items = service.parse_items(html)
        assert len(items) == 0

    def test_html_without_error_div(self, service):
        """测试没有错误 div 的 HTML"""
        html = """
        <div style="margin-bottom:15px;padding:10px;background:#d4edda;color:#155724;border-radius:4px;">
            <strong>成功：</strong> 操作完成
        </div>
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="file1.txt">file1.txt</a></li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 1
        assert items[0] == ("file", "file1.txt", "file1.txt")


class TestErrorDirsCounter:
    """测试错误目录计数器"""

    def test_increment_error_dirs(self, service):
        """测试增加错误目录计数器"""
        initial_count = service.get_error_dirs_count()
        service._increment_error_dirs()
        service._increment_error_dirs()
        assert service.get_error_dirs_count() == initial_count + 2

    def test_get_error_dirs_count(self, service):
        """测试获取错误目录数量"""
        count = service.get_error_dirs_count()
        assert isinstance(count, int)
        assert count >= 0


class TestErrorPageDetectionIntegration:
    """测试错误页面检测集成"""

    def test_get_all_pages_internal_detects_error(self, service):
        """测试 _get_all_pages_internal 检测错误页面"""
        with patch.object(service, 'get_page') as mock_get:
            mock_get.return_value = """
            <div style="margin-bottom:15px;padding:10px;background:#f8d7da;color:#721c24;border-radius:4px;">
                <strong>错误：</strong> XML Parsing Failed
            </div>
            """

            initial_count = service.get_error_dirs_count()
            result = service._get_all_pages_internal("https://example.com", "test_dir")

            # 应该检测到错误页面并增加计数器
            assert service.get_error_dirs_count() == initial_count + 1
            # 应该返回空列表
            assert result == ([], [])

    def test_normal_page_not_increment_counter(self, service):
        """测试正常页面不增加错误计数器"""
        with patch.object(service, 'get_page') as mock_get:
            mock_get.return_value = """
            <div id="webdav-list">
                <li style="margin:8px 0;"><a href="file1.txt">file1.txt</a></li>
            </div>
            """

            initial_count = service.get_error_dirs_count()
            result = service._get_all_pages_internal("https://example.com", "test_dir")

            # 不应该增加错误计数器
            assert service.get_error_dirs_count() == initial_count
            # 应该返回文件列表
            assert len(result[1]) == 1
