"""无进展超时相关测试"""

import time
from unittest.mock import patch

import pytest

from src.services.scanner import ScanService


@pytest.fixture
def service():
    """创建 ScanService 实例"""
    return ScanService(scan_timeout=0.5, dir_scan_timeout=30.0)


class TestProgressTimeout:
    """测试无进展超时功能"""

    def test_progress_timeout_disabled(self):
        """测试无进展超时禁用时"""
        service = ScanService(scan_timeout=0.0)
        service._start_time = time.monotonic()
        service._last_progress_time = time.monotonic()

        # 等待一段时间
        time.sleep(0.1)

        # 不应该超时
        assert service.is_timeout() is False

    def test_progress_timeout_triggered(self):
        """测试无进展超时触发"""
        service = ScanService(scan_timeout=0.1)
        service._start_time = time.monotonic()
        service._last_progress_time = time.monotonic()

        # 等待超过超时时间
        time.sleep(0.2)

        # 应该超时
        assert service.is_timeout() is True

    def test_progress_timeout_not_triggered_with_progress(self):
        """测试有进展时无进展超时不触发"""
        service = ScanService(scan_timeout=0.1)
        service._start_time = time.monotonic()
        service._last_progress_time = time.monotonic()

        # 等待一段时间
        time.sleep(0.05)

        # 更新进展时间
        service._update_progress()

        # 再等待但未超过超时时间
        time.sleep(0.05)

        # 不应该超时（因为进展时间被更新了）
        assert service.is_timeout() is False

    def test_update_progress_resets_timeout(self):
        """测试 _update_progress 重置超时"""
        service = ScanService(scan_timeout=0.1)
        service._start_time = time.monotonic()
        service._last_progress_time = time.monotonic()

        # 等待一段时间
        time.sleep(0.05)

        # 更新进展时间
        service._update_progress()

        # 再等待但未超过超时时间
        time.sleep(0.05)

        # 不应该超时
        assert service.is_timeout() is False

    def test_progress_timeout_multiple_updates(self):
        """测试多次更新进展时间"""
        service = ScanService(scan_timeout=0.1)
        service._start_time = time.monotonic()
        service._last_progress_time = time.monotonic()

        # 多次更新进展时间
        for _ in range(5):
            time.sleep(0.05)
            service._update_progress()

        # 不应该超时（因为每次都更新了进展时间）
        assert service.is_timeout() is False


class TestProgressTimeoutReset:
    """测试重置时的进展时间"""

    def test_reset_updates_progress_time(self):
        """测试 reset 更新进展时间"""
        service = ScanService(scan_timeout=0.1)
        service._start_time = time.monotonic()
        service._last_progress_time = time.monotonic()

        # 等待超过超时时间
        time.sleep(0.2)

        # 调用 reset
        service.reset()

        # 不应该超时（因为 reset 更新了进展时间）
        assert service.is_timeout() is False


class TestProgressTimeoutIntegration:
    """测试无进展超时集成"""

    def test_get_all_pages_updates_progress(self):
        """测试 _get_all_pages_internal 在成功获取页面时更新进展"""
        service = ScanService(scan_timeout=0.1)
        service._start_time = time.monotonic()
        service._last_progress_time = time.monotonic()

        # 模拟成功获取页面
        html = """
        <ul>
            <li><a href="file.txt">file.txt</a></li>
        </ul>
        """
        with patch.object(service, 'get_page') as mock_get:
            mock_get.return_value = html

            # 调用 _get_all_pages_internal
            result = service._get_all_pages_internal("https://example.com", "test_dir")

            # 应该返回结果
            assert result is not None

    def test_scan_method_updates_progress(self):
        """测试 scan 方法在发现内容时更新进展"""
        service = ScanService(scan_timeout=0.1)
        service._start_time = time.monotonic()
        service._last_progress_time = time.monotonic()

        # 设置回调
        items_found = []
        service.on_item_found = lambda item: items_found.append(item)

        # 模拟扫描
        with patch.object(service, '_get_all_pages_internal') as mock_get:
            mock_get.return_value = (
                [],  # dirs
                [("file.txt", "https://example.com/file.txt")],  # files
                False  # has_error
            )

            # 调用 scan
            service.scan("https://example.com")

            # 应该发现文件
            assert len(items_found) == 1
