"""分页缓存管理"""

import hashlib
import logging
import threading

from .html_parser import HtmlParser

logger = logging.getLogger(__name__)


class PageCache:
    """分页缓存管理"""

    def __init__(self, max_cache_size: int = 1000):
        self._page_cache: dict[str, int] = {}
        self._page_cache_lock = threading.Lock()

        # 分页结构缓存：hash(url) -> (total_pages, content_hash)
        self._structure_cache: dict[str, tuple[int, str]] = {}
        self._structure_cache_lock = threading.Lock()
        self._max_cache_size = max_cache_size

        self._parser = HtmlParser()

    def _get_dir_cache_key(self, base_url: str, dir_path: str) -> str:
        """生成目录缓存key"""
        full_url = f"{base_url}?dir={dir_path}" if dir_path else base_url
        return hashlib.md5(full_url.encode()).hexdigest()

    def get_cached_page_info(
        self, base_url: str, dir_path: str, html: str
    ) -> tuple[int, bool]:
        """获取缓存的分页信息

        Returns:
            (total_pages, is_cache_hit)
        """
        cache_key = self._get_dir_cache_key(base_url, dir_path)
        content_hash = self._parser.get_content_hash(html)

        with self._structure_cache_lock:
            if cache_key in self._structure_cache:
                cached_pages, cached_hash = self._structure_cache[cache_key]
                if cached_hash == content_hash:
                    return cached_pages, True
                else:
                    # 内容变化，需要重新解析
                    del self._structure_cache[cache_key]

        # 解析总页数
        total = self._parser.get_total_pages(html)

        # 缓存结果
        with self._structure_cache_lock:
            if len(self._structure_cache) >= self._max_cache_size:
                # 简单策略：删除最旧的缓存
                oldest_key = next(iter(self._structure_cache))
                del self._structure_cache[oldest_key]
            self._structure_cache[cache_key] = (total, content_hash)

        return total, False

    def get_page_count(self, dir_path: str, html: str) -> int:
        """获取总页数（带缓存）

        解析优先级：
        1. 缓存命中
        2. 分页链接 ``?page=N`` 中的最大页码（最可靠）
        3. 分页容器（class 含 pag/page）内的 ``N/M`` 文本
        4. 含分页语义关键词（当前/第 ... 页）的 ``N/M`` 文本
        5. 默认 1
        """
        # 检查缓存
        if dir_path:
            with self._page_cache_lock:
                if dir_path in self._page_cache:
                    cached = self._page_cache[dir_path]
                    # 验证缓存是否仍然有效
                    actual = self._parser.get_total_pages(html)
                    if actual != cached:
                        logger.warning(
                            "分页缓存不匹配: dir=%s, cached=%d, actual=%d",
                            dir_path, cached, actual
                        )
                        # 更新缓存并返回实际值
                        self._page_cache[dir_path] = actual
                        return actual
                    return cached

        # 解析总页数
        total = self._parser.get_total_pages(html)

        # 缓存结果
        if dir_path:
            with self._page_cache_lock:
                self._page_cache[dir_path] = total

        return total

    def clear(self):
        """清空所有缓存"""
        with self._page_cache_lock:
            self._page_cache.clear()
        with self._structure_cache_lock:
            self._structure_cache.clear()
