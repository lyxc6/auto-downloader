"""分页缓存管理"""

import hashlib
import logging
import threading

from bs4 import BeautifulSoup

from .html_parser import HtmlParser

logger = logging.getLogger(__name__)


class PageCache:
    """分页缓存管理

    使用内容哈希校验的缓存：解析结果与分页相关的内容哈希绑定，
    页面内容变化时缓存自动失效（无需每次重新解析）。
    """

    def __init__(self, max_cache_size: int = 1000):
        # 分页结构缓存：hash(url) -> (total_pages, content_hash)
        self._structure_cache: dict[str, tuple[int, str]] = {}
        self._structure_cache_lock = threading.Lock()
        self._max_cache_size = max_cache_size

        self._parser = HtmlParser()

    def _get_dir_cache_key(self, base_url: str, dir_path: str) -> str:
        """生成目录缓存key"""
        full_url = f"{base_url}?dir={dir_path}" if dir_path else base_url
        return hashlib.md5(full_url.encode()).hexdigest()

    def _evict_if_full(self):
        """容量不足时淘汰最旧的缓存（简单 FIFO）"""
        if len(self._structure_cache) >= self._max_cache_size:
            oldest_key = next(iter(self._structure_cache))
            del self._structure_cache[oldest_key]

    def get_page_count(self, base_url: str, dir_path: str, soup: BeautifulSoup) -> int:
        """获取总页数（带内容哈希缓存，复用已解析的 soup）

        Args:
            base_url: 基础URL
            dir_path: 目录路径（空=根目录，不缓存）
            soup: 已解析的页面 DOM（调用方复用，避免重复解析）

        Returns:
            总页数
        """
        return self._query(base_url, dir_path, soup)[0]

    def get_cached_page_info(self, base_url: str, dir_path: str, html: str) -> tuple[int, bool]:
        """获取缓存的分页信息（HTML 字符串版，内部解析）

        Returns:
            (total_pages, is_cache_hit)
        """
        soup = BeautifulSoup(html, "html.parser")
        return self._query(base_url, dir_path, soup)

    def _query(self, base_url: str, dir_path: str, soup: BeautifulSoup) -> tuple[int, bool]:
        """核心查询：命中哈希缓存则直接返回，否则解析并写入缓存

        Returns:
            (total_pages, is_cache_hit)
        """
        cache_key = self._get_dir_cache_key(base_url, dir_path)

        # 根目录不缓存
        if not dir_path:
            return self._parser.get_total_pages_from_soup(soup), False

        content_hash = self._parser.get_content_hash_from_soup(soup)

        # 查缓存：内容哈希一致才命中
        with self._structure_cache_lock:
            if cache_key in self._structure_cache:
                cached_pages, cached_hash = self._structure_cache[cache_key]
                if cached_hash == content_hash:
                    return cached_pages, True
                # 内容变化，缓存失效
                del self._structure_cache[cache_key]

        # 解析总页数
        total = self._parser.get_total_pages_from_soup(soup)

        # 写入缓存
        with self._structure_cache_lock:
            self._evict_if_full()
            self._structure_cache[cache_key] = (total, content_hash)

        return total, False

    def clear(self):
        """清空所有缓存"""
        with self._structure_cache_lock:
            self._structure_cache.clear()
