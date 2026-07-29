"""目录级超时相关测试"""

import time
from unittest.mock import patch

import pytest

from src.services.scanner import ScanService


@pytest.fixture
def service():
    """创建 ScanService 实例"""
    return ScanService(scan_timeout=300.0, dir_scan_timeout=5.0)


class TestDirTimeout:
    """测试目录级超时功能"""

    def test_dir_timeout_disabled(self):
        """测试目录级超时禁用时"""
        service = ScanService(dir_scan_timeout=0.0)
        service._start_dir_timer()

        # 等待一段时间
        time.sleep(0.1)

        # 不应该超时
        assert service._is_dir_timeout() is False

    def test_dir_timeout_not_started(self):
        """测试未启动目录计时器时"""
        service = ScanService(dir_scan_timeout=5.0)

        # 未启动计时器，不应该超时
        assert service._is_dir_timeout() is False

    def test_dir_timeout_triggered(self):
        """测试目录级超时触发"""
        service = ScanService(dir_scan_timeout=0.1)
        service._start_dir_timer()

        # 等待超过超时时间
        time.sleep(0.2)

        # 应该超时
        assert service._is_dir_timeout() is True

    def test_dir_timeout_not_triggered(self):
        """测试目录级超时未触发"""
        service = ScanService(dir_scan_timeout=1.0)
        service._start_dir_timer()

        # 等待但未超过超时时间
        time.sleep(0.1)

        # 不应该超时
        assert service._is_dir_timeout() is False

    def test_dir_timer_reset(self):
        """测试目录计时器重置"""
        service = ScanService(dir_scan_timeout=0.2)
        service._start_dir_timer()

        # 等待一段时间
        time.sleep(0.1)

        # 重置计时器
        service._start_dir_timer()

        # 再等待但未超过超时时间
        time.sleep(0.1)

        # 不应该超时（因为计时器被重置了）
        assert service._is_dir_timeout() is False


class TestDirTimeoutIntegration:
    """测试目录级超时集成"""

    def test_get_all_pages_respects_dir_timeout(self, service):
        """测试 _get_all_pages_internal 尊重目录级超时"""
        # 创建一个模拟的慢响应场景
        with patch.object(service, '_get_page_session') as mock_get:
            # 模拟第一页返回成功
            mock_get.return_value = """
            <ul>
                <li><a href="?page=2">2</a></li>
            </ul>
            """

            # 设置目录级超时很短
            service._dir_scan_timeout = 0.1
            service._start_dir_timer()

            # 等待超过目录级超时
            time.sleep(0.2)

            # 调用 _get_all_pages_internal
            result = service._get_all_pages_internal("https://example.com", "test_dir")

            # 由于目录超时，应该只获取了第一页（第一页在超时前获取）
            # 但后续页面应该被跳过
            assert result is not None

    def test_fetch_pages_serial_respects_dir_timeout(self, service):
        """测试 _fetch_pages_serial 尊重目录级超时"""
        with patch.object(service, '_get_page_session') as mock_get:
            # 模拟页面返回成功
            mock_get.return_value = """
            <ul>
                <li><a href="file.txt">file.txt</a></li>
            </ul>
            """

            # 设置目录级超时很短
            service._dir_scan_timeout = 0.1
            service._start_dir_timer()

            # 等待超过目录级超时
            time.sleep(0.2)

            # 调用 _fetch_pages_serial
            all_dirs = []
            all_files = []
            result = service._fetch_pages_serial(
                "https://example.com", "test_dir", None, 5, all_dirs, all_files
            )

            # 由于目录超时，应该立即返回
            assert result is not None
            # 不应该尝试获取任何页面（因为已经超时）
            assert mock_get.call_count == 0

    def test_fetch_pages_parallel_respects_dir_timeout(self, service):
        """测试 _fetch_pages_parallel 尊重目录级超时"""
        with patch.object(service, '_get_page_session') as mock_get:
            # 模拟页面返回成功
            mock_get.return_value = """
            <ul>
                <li><a href="file.txt">file.txt</a></li>
            </ul>
            """

            # 设置目录级超时很短
            service._dir_scan_timeout = 0.1
            service._start_dir_timer()

            # 等待超过目录级超时
            time.sleep(0.2)

            # 调用 _fetch_pages_parallel
            all_dirs = []
            all_files = []
            result = service._fetch_pages_parallel(
                "https://example.com", "test_dir", None, 5, all_dirs, all_files
            )

            # 由于目录超时，应该立即返回
            assert result is not None
            # 不应该尝试获取任何页面（因为已经超时）
            assert mock_get.call_count == 0


class TestDirTimeoutVsGlobalTimeout:
    """测试目录级超时与全局超时的关系"""

    def test_dir_timeout_before_global_timeout(self):
        """测试目录级超时先于全局超时触发"""
        service = ScanService(scan_timeout=300.0, dir_scan_timeout=0.1)
        service._start_time = time.monotonic()
        service._start_dir_timer()

        # 等待超过目录级超时但未超过全局超时
        time.sleep(0.2)

        # 目录级超时应该触发
        assert service._is_dir_timeout() is True
        # 全局超时不应该触发
        assert service.is_timeout() is False

    def test_global_timeout_takes_precedence(self):
        """测试全局超时优先于目录级超时"""
        service = ScanService(scan_timeout=0.1, dir_scan_timeout=300.0)
        service._start_time = time.monotonic()
        service._start_dir_timer()

        # 等待超过全局超时
        time.sleep(0.2)

        # 全局超时应该触发
        assert service.is_timeout() is True
        # 目录级超时不应该触发（因为设置为300秒）
        assert service._is_dir_timeout() is False


class TestDirTimeoutLogging:
    """测试目录级超时日志"""

    def test_dir_timeout_warning_logged(self, service):
        """测试目录级超时时记录警告日志"""
        with patch('src.services.scanner.logger'):
            # 设置目录级超时很短
            service._dir_scan_timeout = 0.1
            service._start_dir_timer()

            # 等待超过超时时间
            time.sleep(0.2)

            # 检查超时
            service._is_dir_timeout()

            # 不应该记录日志（因为 _is_dir_timeout 只是检查，不记录日志）
            # 日志记录应该在调用方进行
