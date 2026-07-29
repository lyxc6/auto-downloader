"""分页缓存相关测试"""

import pytest

from src.services.scanner import ScanService


@pytest.fixture
def service():
    """创建 ScanService 实例"""
    return ScanService()


class TestPageCache:
    """测试分页缓存功能"""

    def test_cache_hit_returns_correct_value(self, service):
        """测试缓存命中返回正确值"""
        html = """
        <ul>
            <li><a href="?page=1">1</a></li>
            <li><a href="?page=2">2</a></li>
            <li><a href="?page=3">3</a></li>
        </ul>
        """
        # 首次调用，应解析并缓存
        result1 = service.get_total_pages(html, "test_dir")
        assert result1 == 3

        # 再次调用，应从缓存返回
        result2 = service.get_total_pages(html, "test_dir")
        assert result2 == 3

    def test_cache_mismatch_returns_actual_value(self, service):
        """测试缓存不匹配时返回实际值"""
        # 首次调用，缓存为 3 页
        html1 = """
        <ul>
            <li><a href="?page=1">1</a></li>
            <li><a href="?page=2">2</a></li>
            <li><a href="?page=3">3</a></li>
        </ul>
        """
        result1 = service.get_total_pages(html1, "test_dir")
        assert result1 == 3

        # 第二次调用，HTML 显示 5 页
        html2 = """
        <ul>
            <li><a href="?page=1">1</a></li>
            <li><a href="?page=2">2</a></li>
            <li><a href="?page=3">3</a></li>
            <li><a href="?page=4">4</a></li>
            <li><a href="?page=5">5</a></li>
        </ul>
        """
        result2 = service.get_total_pages(html2, "test_dir")
        # 应返回实际值 5，而非缓存值 3
        assert result2 == 5

    def test_cache_without_dir_path(self, service):
        """测试不带目录路径时不使用缓存"""
        html = """
        <ul>
            <li><a href="?page=1">1</a></li>
            <li><a href="?page=2">2</a></li>
        </ul>
        """
        result1 = service.get_total_pages(html, "")
        assert result1 == 2

        result2 = service.get_total_pages(html, "")
        assert result2 == 2

    def test_different_dirs_separate_cache(self, service):
        """测试不同目录使用独立缓存"""
        html1 = """
        <ul>
            <li><a href="?page=1">1</a></li>
            <li><a href="?page=2">2</a></li>
        </ul>
        """
        html2 = """
        <ul>
            <li><a href="?page=1">1</a></li>
            <li><a href="?page=2">2</a></li>
            <li><a href="?page=3">3</a></li>
        </ul>
        """
        result1 = service.get_total_pages(html1, "dir1")
        result2 = service.get_total_pages(html2, "dir2")

        assert result1 == 2
        assert result2 == 3

    def test_clear_cache(self, service):
        """测试清空缓存"""
        html = """
        <ul>
            <li><a href="?page=1">1</a></li>
            <li><a href="?page=2">2</a></li>
            <li><a href="?page=3">3</a></li>
        </ul>
        """
        # 首次调用，缓存为 3 页
        result1 = service.get_total_pages(html, "test_dir")
        assert result1 == 3

        # 清空缓存
        service.clear_page_cache()

        # 再次调用，应重新解析
        result2 = service.get_total_pages(html, "test_dir")
        assert result2 == 3


class TestStructureCache:
    """测试分页结构缓存"""

    def test_cache_key_generation(self, service):
        """测试缓存 key 生成"""
        key1 = service._get_dir_cache_key("https://example.com", "folder1")
        key2 = service._get_dir_cache_key("https://example.com", "folder2")
        key3 = service._get_dir_cache_key("https://example.com", "folder1")

        # 不同目录应生成不同 key
        assert key1 != key2
        # 相同目录应生成相同 key
        assert key1 == key3

    def test_content_hash_generation(self, service):
        """测试内容哈希生成"""
        html1 = """
        <ul>
            <li><a href="?page=1">1</a></li>
            <li><a href="?page=2">2</a></li>
        </ul>
        """
        html2 = """
        <ul>
            <li><a href="?page=1">1</a></li>
            <li><a href="?page=2">2</a></li>
            <li><a href="?page=3">3</a></li>
        </ul>
        """
        hash1 = service._get_content_hash(html1)
        hash2 = service._get_content_hash(html2)

        # 不同内容应生成不同哈希
        assert hash1 != hash2

    def test_cache_hit_returns_correct_value(self, service):
        """测试结构缓存命中返回正确值"""
        html = """
        <ul>
            <li><a href="?page=1">1</a></li>
            <li><a href="?page=2">2</a></li>
            <li><a href="?page=3">3</a></li>
        </ul>
        """
        # 首次调用，应解析并缓存
        total1, hit1 = service.get_cached_page_info("https://example.com", "test_dir", html)
        assert total1 == 3
        assert hit1 is False

        # 再次调用，应命中缓存
        total2, hit2 = service.get_cached_page_info("https://example.com", "test_dir", html)
        assert total2 == 3
        assert hit2 is True

    def test_cache_miss_when_content_changes(self, service):
        """测试内容变化时缓存失效"""
        html1 = """
        <ul>
            <li><a href="?page=1">1</a></li>
            <li><a href="?page=2">2</a></li>
        </ul>
        """
        html2 = """
        <ul>
            <li><a href="?page=1">1</a></li>
            <li><a href="?page=2">2</a></li>
            <li><a href="?page=3">3</a></li>
        </ul>
        """
        # 首次调用
        total1, hit1 = service.get_cached_page_info("https://example.com", "test_dir", html1)
        assert total1 == 2
        assert hit1 is False

        # 内容变化后调用
        total2, hit2 = service.get_cached_page_info("https://example.com", "test_dir", html2)
        assert total2 == 3
        assert hit2 is False


class TestParseTotalPages:
    """测试分页解析"""

    def test_parse_page_links(self, service):
        """测试从分页链接解析"""
        html = """
        <ul>
            <li><a href="?page=1">1</a></li>
            <li><a href="?page=2">2</a></li>
            <li><a href="?page=5">5</a></li>
        </ul>
        """
        result = service._parse_total_pages(html)
        assert result == 5

    def test_parse_page_class(self, service):
        """测试从分页容器解析"""
        html = """
        <div class="pagination">
            <span>1 / 3</span>
        </div>
        """
        result = service._parse_total_pages(html)
        assert result == 3

    def test_parse_semantic_text(self, service):
        """测试从语义关键词解析"""
        html = """
        <span>当前 1/4</span>
        """
        result = service._parse_total_pages(html)
        assert result == 4

    def test_default_single_page(self, service):
        """测试默认单页"""
        html = """
        <ul>
            <li><a href="file1.txt">file1.txt</a></li>
        </ul>
        """
        result = service._parse_total_pages(html)
        assert result == 1

    def test_empty_html(self, service):
        """测试空 HTML"""
        html = ""
        result = service._parse_total_pages(html)
        assert result == 1
