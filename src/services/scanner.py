"""扫描服务"""

import hashlib
import logging
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import ClassVar, cast
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

from ..models import DownloadItem, ItemType

logger = logging.getLogger(__name__)


class RetryPolicy:
    """重试策略"""

    # 可重试的HTTP状态码
    RETRYABLE_STATUS_CODES: ClassVar[set[int]] = {429, 500, 502, 503, 504}

    # 不可重试的HTTP状态码
    NON_RETRYABLE_STATUS_CODES: ClassVar[set[int]] = {400, 401, 403, 404, 405, 410}

    @staticmethod
    def get_retry_config(status_code: int | None) -> dict:
        """根据状态码获取重试配置"""
        if status_code is None:
            # 网络错误，可重试
            return {
                "max_retries": 3,
                "base_delay": 1.0,
                "max_delay": 10.0,
                "exponential_base": 2,
            }

        if status_code in RetryPolicy.NON_RETRYABLE_STATUS_CODES:
            # 不可重试错误
            return {
                "max_retries": 0,
                "base_delay": 0,
                "max_delay": 0,
                "exponential_base": 1,
            }

        if status_code in RetryPolicy.RETRYABLE_STATUS_CODES:
            # 可重试错误
            if status_code == 429:
                # 限流错误，使用更长的延迟
                return {
                    "max_retries": 5,
                    "base_delay": 2.0,
                    "max_delay": 30.0,
                    "exponential_base": 2,
                }
            else:
                # 服务器错误
                return {
                    "max_retries": 3,
                    "base_delay": 1.0,
                    "max_delay": 10.0,
                    "exponential_base": 2,
                }

        # 未知错误，保守重试
        return {
            "max_retries": 2,
            "base_delay": 1.0,
            "max_delay": 5.0,
            "exponential_base": 2,
        }

    @staticmethod
    def calculate_delay(attempt: int, config: dict) -> float:
        """计算重试延迟"""
        delay = config["base_delay"] * (config["exponential_base"] ** attempt)
        return min(delay, config["max_delay"])


class ScanService:
    """扫描服务 - 统一扫描引擎，支持 DFS/BFS × 串行/并行"""

    def __init__(
        self,
        scan_delay: float = 0.02,
        scan_timeout: float = 300.0,
        dir_scan_timeout: float = 30.0,
    ):
        self._session: requests.Session | None = None
        self._cancel_flag = threading.Event()
        self._lock = threading.Lock()
        self._scanned_dirs: set[str] = set()
        self._scanned_dirs_lock = threading.Lock()

        # 扫描参数
        self._scan_delay = scan_delay
        self._scan_timeout = scan_timeout
        self._dir_scan_timeout = dir_scan_timeout
        self._start_time: float = time.monotonic()
        self._dir_start_time: float = 0.0
        self._last_progress_time: float = time.monotonic()

        # 回调函数
        self.on_item_found: Callable[[DownloadItem], None] | None = None
        self.on_error: Callable[[str], None] | None = None
        self.on_log: Callable[[str, str], None] | None = None
        self.on_dir_scanned: Callable[[str], None] | None = None

        # 并行模式控制
        self.parallel_mode = False
        self.on_progress_update: Callable[[int, int], None] | None = None
        self._parallel_dirs_completed = 0
        self._progress_lock = threading.Lock()

        # 失败统计
        self._failed_dirs = 0
        self._failed_dirs_lock = threading.Lock()
        self._error_dirs = 0
        self._error_dirs_lock = threading.Lock()

        # 分页信息缓存：dir_path -> total_pages
        self._page_cache: dict[str, int] = {}
        self._page_cache_lock = threading.Lock()

        # 分页结构缓存：hash(url) -> (total_pages, content_hash)
        self._structure_cache: dict[str, tuple[int, str]] = {}
        self._structure_cache_lock = threading.Lock()
        self._max_cache_size = 1000

    @property
    def session(self) -> requests.Session:
        """获取或创建session"""
        with self._lock:
            if self._session is None:
                self._session = requests.Session()
                self._session.headers.update(
                    {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                )
            return self._session

    def cancel(self):
        """取消扫描"""
        self._cancel_flag.set()

    def is_cancelled(self) -> bool:
        """是否已取消"""
        return self._cancel_flag.is_set()

    def is_timeout(self) -> bool:
        """是否已超时（无进展超时）"""
        if self._scan_timeout <= 0:
            return False
        return (time.monotonic() - self._last_progress_time) >= self._scan_timeout

    def _update_progress(self):
        """更新进展时间（发现新内容时调用）"""
        self._last_progress_time = time.monotonic()

    def _is_dir_timeout(self) -> bool:
        """检查当前目录是否超时"""
        if self._dir_scan_timeout <= 0:
            return False
        if self._dir_start_time <= 0:
            return False
        return (time.monotonic() - self._dir_start_time) >= self._dir_scan_timeout

    def _start_dir_timer(self):
        """启动目录级计时器"""
        self._dir_start_time = time.monotonic()

    def reset(self):
        """重置状态"""
        self._cancel_flag.clear()
        self._start_time = time.monotonic()
        self._last_progress_time = time.monotonic()
        self._parallel_dirs_completed = 0

    def set_scanned_dirs(self, dirs: set[str]):
        """设置已扫描目录集合（续扫时跳过这些目录）"""
        with self._scanned_dirs_lock:
            self._scanned_dirs = set(dirs)

    # ==================== 公共辅助方法 ====================

    def _create_item(
        self,
        item_id: str,
        name: str,
        url: str,
        item_type: ItemType,
        parent_id: str,
        full_path: str,
    ) -> DownloadItem:
        """创建 DownloadItem 对象"""
        return DownloadItem(
            item_id=item_id,
            name=name,
            url=url,
            item_type=item_type,
            parent_id=parent_id,
            full_path=full_path,
        )

    def _log_scan_result(self, dir_path: str, dirs: list, files: list, is_empty: bool = False):
        """记录扫描结果日志"""
        display_path = dir_path or "/"
        if self.on_log:
            if is_empty:
                self.on_log(f"正在扫描: {display_path}  (空目录)", "dim")
            else:
                self.on_log(f"正在扫描: {display_path}", "info")
            if dirs or files:
                self.on_log(f"  ├─ 子目录: {len(dirs)} 个, 文件: {len(files)} 个", "info")

    def _is_dir_scanned(self, dir_path: str) -> bool:
        """检查目录是否已扫描（线程安全）"""
        with self._scanned_dirs_lock:
            return dir_path in self._scanned_dirs

    def _increment_error_dirs(self):
        """增加错误目录计数器"""
        with self._error_dirs_lock:
            self._error_dirs += 1

    def get_error_dirs_count(self) -> int:
        """获取错误目录数量"""
        with self._error_dirs_lock:
            return self._error_dirs

    def _mark_dir_scanned(self, dir_path: str):
        """标记目录为已扫描（线程安全）"""
        with self._scanned_dirs_lock:
            self._scanned_dirs.add(dir_path)
        if self.on_dir_scanned:
            self.on_dir_scanned(dir_path)

    def _emit_dir_complete(self):
        """并行模式下，每完成一个目录递增计数器并触发进度回调"""
        if not self.parallel_mode:
            return
        with self._progress_lock:
            self._parallel_dirs_completed += 1
            count = self._parallel_dirs_completed
        if self.on_progress_update:
            self.on_progress_update(count, 0)

    def _should_stop(self) -> bool:
        """检查是否应该停止扫描（取消或超时）"""
        return self.is_cancelled() or self.is_timeout()

    # ==================== 分页缓存方法 ====================

    def _get_dir_cache_key(self, base_url: str, dir_path: str) -> str:
        """生成目录缓存key"""
        full_url = f"{base_url}?dir={dir_path}" if dir_path else base_url
        return hashlib.md5(full_url.encode()).hexdigest()

    def _get_content_hash(self, html: str) -> str:
        """计算内容哈希"""
        soup = BeautifulSoup(html, "html.parser")

        # 提取分页相关元素
        page_elements = []
        for a in soup.find_all("a", href=True):
            href = str(a["href"])
            if "page=" in href:
                page_elements.append(href)

        # 提取分页容器
        for el in soup.find_all(True):
            raw_cls = cast("str | list[str]", el.get("class") or [])
            cls: list[str] = [raw_cls] if isinstance(raw_cls, str) else raw_cls
            cls_str = " ".join(cls).lower() if cls else ""
            if "pag" in cls_str or "page" in cls_str:
                page_elements.append(el.get_text(" "))

        content = "|".join(sorted(page_elements))
        return hashlib.md5(content.encode()).hexdigest()

    def get_cached_page_info(
        self, base_url: str, dir_path: str, html: str
    ) -> tuple[int, bool]:
        """获取缓存的分页信息

        Returns:
            (total_pages, is_cache_hit)
        """
        cache_key = self._get_dir_cache_key(base_url, dir_path)
        content_hash = self._get_content_hash(html)

        with self._structure_cache_lock:
            if cache_key in self._structure_cache:
                cached_pages, cached_hash = self._structure_cache[cache_key]
                if cached_hash == content_hash:
                    return cached_pages, True
                else:
                    # 内容变化，需要重新解析
                    del self._structure_cache[cache_key]

        # 解析总页数
        total = self._parse_total_pages(html)

        # 缓存结果
        with self._structure_cache_lock:
            if len(self._structure_cache) >= self._max_cache_size:
                # 简单策略：删除最旧的缓存
                oldest_key = next(iter(self._structure_cache))
                del self._structure_cache[oldest_key]
            self._structure_cache[cache_key] = (total, content_hash)

        return total, False

    def clear_page_cache(self):
        """清空分页缓存"""
        with self._page_cache_lock:
            self._page_cache.clear()
        with self._structure_cache_lock:
            self._structure_cache.clear()

    # ==================== HTTP 请求方法 ====================

    def get_page(self, url: str, retries: int = 3) -> str | None:
        """获取页面内容（智能重试）"""
        attempt = 0

        while attempt <= retries:
            if self._should_stop():
                return None

            try:
                resp = self.session.get(url, timeout=60)
                resp.raise_for_status()
                resp.encoding = "utf-8"
                return resp.text
            except requests.HTTPError as e:
                status_code = e.response.status_code if e.response is not None else None

                # 获取重试配置
                retry_config = RetryPolicy.get_retry_config(status_code)
                max_retries = min(retries, retry_config["max_retries"])

                # 检查是否应该重试
                if attempt >= max_retries:
                    logger.error("获取页面失败(不再重试): %s -> %s", url, status_code)
                    if self.on_error:
                        self.on_error(f"获取页面失败: HTTP {status_code}")
                    return None

                # 计算延迟
                delay = RetryPolicy.calculate_delay(attempt, retry_config)
                logger.warning(
                    "获取页面重试 %d/%d: %s -> %s (等待 %.1f秒)",
                    attempt + 1, max_retries, url, status_code, delay
                )
                time.sleep(delay)
                attempt += 1

            except requests.ConnectionError as e:
                # 连接错误，可重试
                retry_config = RetryPolicy.get_retry_config(None)
                max_retries = min(retries, retry_config["max_retries"])

                if attempt >= max_retries:
                    logger.error("获取页面失败(连接错误): %s -> %s", url, e)
                    if self.on_error:
                        self.on_error(f"连接失败: {e}")
                    return None

                delay = RetryPolicy.calculate_delay(attempt, retry_config)
                logger.warning(
                    "获取页面重试 %d/%d: %s -> %s (等待 %.1f秒)",
                    attempt + 1, max_retries, url, e, delay
                )
                time.sleep(delay)
                attempt += 1

            except requests.Timeout as e:
                # 超时错误，可重试
                retry_config = RetryPolicy.get_retry_config(None)
                max_retries = min(retries, retry_config["max_retries"])

                if attempt >= max_retries:
                    logger.error("获取页面失败(超时): %s -> %s", url, e)
                    if self.on_error:
                        self.on_error(f"请求超时: {e}")
                    return None

                delay = RetryPolicy.calculate_delay(attempt, retry_config)
                logger.warning(
                    "获取页面重试 %d/%d: %s -> %s (等待 %.1f秒)",
                    attempt + 1, max_retries, url, e, delay
                )
                time.sleep(delay)
                attempt += 1

            except Exception as e:
                # 其他错误，保守重试
                retry_config = RetryPolicy.get_retry_config(None)
                max_retries = min(retries, retry_config["max_retries"])

                if attempt >= max_retries:
                    logger.error("获取页面失败: %s -> %s", url, e)
                    if self.on_error:
                        self.on_error(f"获取页面失败: {e}")
                    return None

                delay = RetryPolicy.calculate_delay(attempt, retry_config)
                logger.warning(
                    "获取页面重试 %d/%d: %s -> %s (等待 %.1f秒)",
                    attempt + 1, max_retries, url, e, delay
                )
                time.sleep(delay)
                attempt += 1

        return None

    def _get_page_session(self, session: requests.Session, url: str, retries: int = 3) -> str | None:
        """使用指定 session 获取页面内容（智能重试，线程安全）"""
        attempt = 0

        while attempt <= retries:
            # 检查目录级超时（优先级高于全局超时）
            if self._is_dir_timeout():
                logger.warning("目录扫描超时，停止重试: %s", url)
                return None

            # 检查全局超时
            if self._should_stop():
                return None

            try:
                resp = session.get(url, timeout=60)
                resp.raise_for_status()
                resp.encoding = "utf-8"
                return resp.text
            except requests.HTTPError as e:
                status_code = e.response.status_code if e.response is not None else None

                # 获取重试配置
                retry_config = RetryPolicy.get_retry_config(status_code)
                max_retries = min(retries, retry_config["max_retries"])

                # 检查是否应该重试
                if attempt >= max_retries:
                    logger.error("获取页面失败(不再重试): %s -> %s", url, status_code)
                    if self.on_error:
                        self.on_error(f"获取页面失败: HTTP {status_code}")
                    with self._failed_dirs_lock:
                        self._failed_dirs += 1
                    return None

                # 计算延迟
                delay = RetryPolicy.calculate_delay(attempt, retry_config)
                logger.warning(
                    "获取页面重试 %d/%d: %s -> %s (等待 %.1f秒)",
                    attempt + 1, max_retries, url, status_code, delay
                )
                time.sleep(delay)
                attempt += 1

            except requests.ConnectionError as e:
                # 连接错误，可重试
                retry_config = RetryPolicy.get_retry_config(None)
                max_retries = min(retries, retry_config["max_retries"])

                if attempt >= max_retries:
                    logger.error("获取页面失败(连接错误): %s -> %s", url, e)
                    if self.on_error:
                        self.on_error(f"连接失败: {e}")
                    with self._failed_dirs_lock:
                        self._failed_dirs += 1
                    return None

                delay = RetryPolicy.calculate_delay(attempt, retry_config)
                logger.warning(
                    "获取页面重试 %d/%d: %s -> %s (等待 %.1f秒)",
                    attempt + 1, max_retries, url, e, delay
                )
                time.sleep(delay)
                attempt += 1

            except requests.Timeout as e:
                # 超时错误，可重试
                retry_config = RetryPolicy.get_retry_config(None)
                max_retries = min(retries, retry_config["max_retries"])

                if attempt >= max_retries:
                    logger.error("获取页面失败(超时): %s -> %s", url, e)
                    if self.on_error:
                        self.on_error(f"请求超时: {e}")
                    with self._failed_dirs_lock:
                        self._failed_dirs += 1
                    return None

                delay = RetryPolicy.calculate_delay(attempt, retry_config)
                logger.warning(
                    "获取页面重试 %d/%d: %s -> %s (等待 %.1f秒)",
                    attempt + 1, max_retries, url, e, delay
                )
                time.sleep(delay)
                attempt += 1

            except Exception as e:
                # 其他错误，保守重试
                retry_config = RetryPolicy.get_retry_config(None)
                max_retries = min(retries, retry_config["max_retries"])

                if attempt >= max_retries:
                    logger.error("获取页面失败: %s -> %s", url, e)
                    if self.on_error:
                        self.on_error(f"获取页面失败: {e}")
                    with self._failed_dirs_lock:
                        self._failed_dirs += 1
                    return None

                delay = RetryPolicy.calculate_delay(attempt, retry_config)
                logger.warning(
                    "获取页面重试 %d/%d: %s -> %s (等待 %.1f秒)",
                    attempt + 1, max_retries, url, e, delay
                )
                time.sleep(delay)
                attempt += 1

        return None

    # ==================== HTML 解析方法 ====================

    def parse_items(self, html: str) -> list[tuple[str, str, str]]:
        """解析页面项目

        Returns:
            List of (type, name, href)
        """
        soup = BeautifulSoup(html, "html.parser")
        items: list[tuple[str, str, str]] = []

        # 检测服务端错误页面
        error_div = soup.find("div", style=lambda s: s and "background:#f8d7da" in s)
        if error_div:
            error_text = error_div.get_text(strip=True)
            if "错误" in error_text or "XML Parsing Failed" in error_text:
                logger.warning("检测到服务端错误页面: %s", error_text)
                return items

        # 严格模式：必须找到 #webdav-list 容器
        webdav_list = soup.find(id="webdav-list")
        if not webdav_list:
            logger.warning("未找到 #webdav-list 容器")
            return items

        # 遍历 #webdav-list 下的 li 元素，宽松匹配 style 包含 margin:8px
        for li in webdav_list.find_all("li", style=lambda s: s and "margin:8px" in s):
            a = li.find("a")
            if not a:
                continue

            href = str(a.get("href", ""))
            text = a.get_text(strip=True)

            if not href or href == "#":
                continue
            if "返回上级" in text:
                continue

            # 根据 href 判断类型
            if "dir=" in href:
                items.append(("dir", text, href))
            else:
                items.append(("file", text, href))

        return items

    def get_total_pages(self, html: str, dir_path: str = "") -> int:
        """获取总页数（带缓存）

        解析优先级：
        1. 分页链接 ``?page=N`` 中的最大页码（最可靠）
        2. 分页容器（class 含 pag/page）内的 ``N/M`` 文本
        3. 含分页语义关键词（当前/第 ... 页）的 ``N/M`` 文本
        4. 默认 1
        """
        # 检查缓存
        if dir_path:
            with self._page_cache_lock:
                if dir_path in self._page_cache:
                    cached = self._page_cache[dir_path]
                    # 验证缓存是否仍然有效
                    actual = self._parse_total_pages(html)
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
        total = self._parse_total_pages(html)

        # 缓存结果
        if dir_path:
            with self._page_cache_lock:
                self._page_cache[dir_path] = total

        return total

    def _parse_total_pages(self, html: str) -> int:
        """解析总页数（原始逻辑）"""
        soup = BeautifulSoup(html, "html.parser")

        # 1. 从分页链接提取最大页码
        max_page = 1
        for a in soup.find_all("a", href=True):
            href = str(a["href"])
            if "page=" in href:
                m = re.search(r"[?&]page=(\d+)", href)
                if m:
                    p = int(m.group(1))
                    if p > max_page:
                        max_page = p
        if max_page > 1:
            return max_page

        # 2. 从分页容器（class 含 pag/page）内的 N/M 提取
        for el in soup.find_all(True):
            raw_cls = cast("str | list[str]", el.get("class") or [])
            cls: list[str] = [raw_cls] if isinstance(raw_cls, str) else raw_cls
            cls_str = " ".join(cls).lower() if cls else ""
            if "pag" in cls_str or "page" in cls_str:
                m = re.search(r"(\d+)\s*/\s*(\d+)", el.get_text(" "))
                if m:
                    return int(m.group(2))

        # 3. 含分页语义关键词的 N/M 文本回退
        text = soup.get_text(" ")
        m = re.search(r"(?:当前|第)\s*\d+\s*/\s*(\d+)", text)
        if m:
            return int(m.group(1))

        return 1

    # ==================== 分页获取方法 ====================

    def get_all_pages(self, base_url: str, dir_path: str = "") -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """获取目录下所有项目（串行模式）"""
        return self._get_all_pages_internal(base_url, dir_path, session=None)

    def _get_all_pages_threadsafe(
        self, base_url: str, dir_path: str = ""
    ) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """获取目录下所有项目（并行模式，每线程独立 session）"""
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        try:
            return self._get_all_pages_internal(base_url, dir_path, session=session)
        finally:
            session.close()

    def _get_all_pages_internal(
        self,
        base_url: str,
        dir_path: str = "",
        session: requests.Session | None = None,
    ) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """获取目录下所有项目（内部实现）"""
        all_dirs: list[tuple[str, str]] = []
        all_files: list[tuple[str, str]] = []

        # 启动目录级计时器
        self._start_dir_timer()

        # 1. 获取第1页，确定总页数
        url1 = self._build_page_url(base_url, dir_path, 1)
        html1 = self._get_page_session(session, url1) if session is not None else self.get_page(url1)
        if not html1:
            return all_dirs, all_files

        # 检查目录级超时
        if self._is_dir_timeout():
            logger.warning("目录扫描超时，跳过: %s", dir_path or "/")
            return all_dirs, all_files

        items1 = self.parse_items(html1)

        # 检测服务器错误页面（返回200但内容为空）
        if not items1 and html1:
            error_div = BeautifulSoup(html1, "html.parser").find("div", style=lambda s: s and "background:#f8d7da" in s)
            if error_div:
                self._increment_error_dirs()
                logger.warning("检测到服务器错误页面: %s", dir_path or "/")

        self._merge_items(items1, dir_path, base_url, all_dirs, all_files)

        total_pages = self.get_total_pages(html1, dir_path)
        if self.on_log and not self.parallel_mode:
            self.on_log(f"  获取页面 1/{total_pages}", "dim")

        if total_pages <= 1:
            return all_dirs, all_files

        # 2. 并行获取剩余页面（仅在并行模式下）
        if self.parallel_mode and total_pages > 2:
            return self._fetch_pages_parallel(
                base_url, dir_path, session, total_pages, all_dirs, all_files
            )
        else:
            return self._fetch_pages_serial(
                base_url, dir_path, session, total_pages, all_dirs, all_files
            )

    def _build_page_url(self, base_url: str, dir_path: str, page: int) -> str:
        """构建页面URL"""
        if dir_path:
            query = f"?dir={quote(dir_path)}"
            if page > 1:
                query += f"&page={page}"
        else:
            query = f"?page={page}" if page > 1 else ""
        return base_url + query

    def _merge_items(
        self,
        items: list[tuple[str, str, str]],
        dir_path: str,
        base_url: str,
        all_dirs: list,
        all_files: list,
    ):
        """合并页面项目到总列表"""
        for item_type, name, href in items:
            if item_type == "dir":
                full_path = f"{dir_path}/{name}" if dir_path else name
                if (full_path, name) not in all_dirs:
                    all_dirs.append((full_path, name))
            else:
                file_url = urljoin(base_url, href)
                if (name, file_url) not in all_files:
                    all_files.append((name, file_url))

    def _fetch_pages_serial(
        self,
        base_url: str,
        dir_path: str,
        session: requests.Session | None,
        total_pages: int,
        all_dirs: list,
        all_files: list,
    ) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """串行获取多页"""
        for page in range(2, total_pages + 1):
            # 检查目录级超时（优先级高于全局超时）
            if self._is_dir_timeout():
                logger.warning("目录扫描超时，停止获取后续页面: %s (已获取 %d/%d 页)",
                              dir_path or "/", page - 1, total_pages)
                break

            # 检查全局超时
            if self._should_stop():
                break

            url = self._build_page_url(base_url, dir_path, page)
            html = self._get_page_session(session, url) if session is not None else self.get_page(url)
            if not html:
                break

            items = self.parse_items(html)
            self._merge_items(items, dir_path, base_url, all_dirs, all_files)

            if self.on_log and not self.parallel_mode:
                self.on_log(f"  获取页面 {page}/{total_pages}", "dim")

            time.sleep(self._scan_delay)

        return all_dirs, all_files

    def _fetch_pages_parallel(
        self,
        base_url: str,
        dir_path: str,
        session: requests.Session | None,
        total_pages: int,
        all_dirs: list,
        all_files: list,
    ) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """并行获取多页"""
        # 检查目录级超时
        if self._is_dir_timeout():
            logger.warning("目录扫描超时，跳过并行获取: %s", dir_path or "/")
            return all_dirs, all_files

        # 创建独立session用于并行请求
        if session is None:
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            close_session = True
        else:
            close_session = False

        try:
            # 准备页面任务
            page_tasks = list(range(2, total_pages + 1))
            page_results: dict[int, list[tuple[str, str, str]]] = {}

            # 使用较小的线程池，避免过多并发
            max_workers = min(len(page_tasks), 3)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_page = {
                    executor.submit(
                        self._fetch_single_page, base_url, dir_path, session, page
                    ): page
                    for page in page_tasks
                }

                for future in as_completed(future_to_page):
                    # 检查目录级超时
                    if self._is_dir_timeout():
                        logger.warning("目录扫描超时，取消并行获取: %s", dir_path or "/")
                        break
                    # 检查全局超时
                    if self._should_stop():
                        break
                    page = future_to_page[future]
                    try:
                        html = future.result()
                        if html:
                            items = self.parse_items(html)
                            page_results[page] = items
                            if self.on_log and not self.parallel_mode:
                                self.on_log(f"  获取页面 {page}/{total_pages}", "dim")
                    except Exception as e:
                        logger.warning("并行获取页面 %d 失败: %s", page, e)

            # 按页码顺序合并结果
            for page in sorted(page_results.keys()):
                items = page_results[page]
                self._merge_items(items, dir_path, base_url, all_dirs, all_files)

            return all_dirs, all_files
        finally:
            if close_session:
                session.close()

    def _fetch_single_page(
        self, base_url: str, dir_path: str,
        session: requests.Session, page: int
    ) -> str | None:
        """获取单个页面"""
        url = self._build_page_url(base_url, dir_path, page)
        return self._get_page_session(session, url)

    # ==================== 主扫描方法 ====================

    def scan(
        self,
        base_url: str,
        scan_mode: str = "dfs",
        parallel: bool = False,
        max_depth: int = 10,
        max_workers: int = 3,
        dir_path: str = "",
        parent_id: str = "",
    ) -> list[DownloadItem]:
        """统一扫描入口

        Args:
            base_url: 扫描基础URL
            scan_mode: "dfs" 深度优先 / "bfs" 广度优先
            parallel: 是否并行扫描
            max_depth: 最大递归深度
            max_workers: 并行工作线程数
            dir_path: 要扫描的子目录路径（空=从根目录开始）
            parent_id: 子目录的父item_id

        Returns:
            扫描到的所有项目列表
        """
        self.reset()
        self._start_time = time.monotonic()

        if parallel:
            if scan_mode == "bfs":
                return self._scan_bfs_parallel(base_url, max_depth, max_workers, dir_path, parent_id)
            else:
                return self._scan_dfs_parallel(base_url, max_depth, max_workers, dir_path, parent_id)
        else:
            if scan_mode == "bfs":
                return self._scan_bfs(base_url, max_depth, dir_path, parent_id)
            else:
                return self._scan_dfs(base_url, max_depth, dir_path, parent_id)

    # ==================== DFS 串行扫描 ====================

    def _scan_dfs(
        self, base_url: str, max_depth: int, dir_path: str = "", parent_id: str = "", depth: int = 0
    ) -> list[DownloadItem]:
        """深度优先串行扫描"""
        items: list[DownloadItem] = []

        if depth > max_depth or self._should_stop():
            return items

        if dir_path and self._is_dir_scanned(dir_path):
            return items

        dirs, files = self.get_all_pages(base_url, dir_path)
        is_empty = not dirs and not files
        self._log_scan_result(dir_path, dirs, files, is_empty)

        # 处理子目录
        for full_path, name in dirs:
            if self._should_stop():
                break

            item = self._create_item(
                item_id=full_path,
                name=name,
                url="",
                item_type=ItemType.DIR,
                parent_id=dir_path,
                full_path=full_path,
            )
            items.append(item)

            if self.on_item_found:
                self.on_item_found(item)

            time.sleep(self._scan_delay)
            sub_items = self._scan_dfs(base_url, max_depth, full_path, full_path, depth + 1)
            items.extend(sub_items)

        # 处理文件
        for name, file_url in files:
            if self._should_stop():
                break

            item_id = f"{dir_path}/{name}" if dir_path else name
            item = self._create_item(
                item_id=item_id,
                name=name,
                url=file_url,
                item_type=ItemType.FILE,
                parent_id=dir_path,
                full_path=item_id,
            )
            items.append(item)

            if self.on_item_found:
                self.on_item_found(item)

            time.sleep(self._scan_delay)

        # 标记当前目录为已完全扫描
        if not self._should_stop():
            self._mark_dir_scanned(dir_path)

        return items

    # ==================== BFS 串行扫描 ====================

    def _scan_bfs(
        self, base_url: str, max_depth: int, dir_path: str = "", parent_id: str = "", depth: int = 0
    ) -> list[DownloadItem]:
        """广度优先串行扫描（逐层扫描，先显示一级目录再逐层深入）"""
        all_items: list[DownloadItem] = []
        queue: deque[tuple[str, str, int]] = deque()
        queue.append((dir_path, parent_id, depth))

        while queue and not self._should_stop():
            current_level: list[tuple[str, str, int]] = []
            while queue:
                current_level.append(queue.popleft())

            for current_path, _current_parent, current_depth in current_level:
                if self._should_stop():
                    break
                if current_depth > max_depth:
                    continue
                if current_path and self._is_dir_scanned(current_path):
                    continue

                dirs, files = self.get_all_pages(base_url, current_path)
                is_empty = not dirs and not files
                self._log_scan_result(current_path, dirs, files, is_empty)

                # 处理子目录并加入队列
                for full_path, name in dirs:
                    if self._should_stop():
                        break

                    item = self._create_item(
                        item_id=full_path,
                        name=name,
                        url="",
                        item_type=ItemType.DIR,
                        parent_id=current_path,
                        full_path=full_path,
                    )
                    all_items.append(item)

                    if self.on_item_found:
                        self.on_item_found(item)

                    queue.append((full_path, full_path, current_depth + 1))
                    time.sleep(self._scan_delay)

                # 处理文件
                for name, file_url in files:
                    if self._should_stop():
                        break

                    item_id = f"{current_path}/{name}" if current_path else name
                    item = self._create_item(
                        item_id=item_id,
                        name=name,
                        url=file_url,
                        item_type=ItemType.FILE,
                        parent_id=current_path,
                        full_path=item_id,
                    )
                    all_items.append(item)

                    if self.on_item_found:
                        self.on_item_found(item)

                    time.sleep(self._scan_delay)

                # BFS即时标记：每个目录扫描完成后立即标记
                if not self._should_stop():
                    self._mark_dir_scanned(current_path)

        return all_items

    # ==================== DFS 并行扫描 ====================

    def _scan_dfs_parallel(
        self, base_url: str, max_depth: int, max_workers: int = 3, dir_path: str = "", parent_id: str = ""
    ) -> list[DownloadItem]:
        """深度优先并行扫描"""
        all_items: list[DownloadItem] = []
        items_lock = threading.Lock()
        executor = ThreadPoolExecutor(max_workers=max_workers)

        try:
            self._scan_dfs_parallel_recursive(
                base_url, dir_path, parent_id, 0, max_depth, max_workers, executor, all_items, items_lock
            )
        finally:
            executor.shutdown(wait=False)

        return all_items

    def _scan_dfs_parallel_recursive(
        self,
        base_url: str,
        dir_path: str,
        parent_id: str,
        depth: int,
        max_depth: int,
        max_workers: int,
        executor: ThreadPoolExecutor,
        all_items: list[DownloadItem],
        items_lock: threading.Lock,
    ):
        """DFS 并行扫描递归实现"""
        if depth > max_depth or self._should_stop():
            return

        if dir_path and self._is_dir_scanned(dir_path):
            return

        # 获取当前目录内容
        dirs, files = self._get_all_pages_threadsafe(base_url, dir_path)
        is_empty = not dirs and not files
        self._log_scan_result(dir_path, dirs, files, is_empty)

        # 处理当前目录的文件
        for name, file_url in files:
            if self._should_stop():
                break

            item_id = f"{dir_path}/{name}" if dir_path else name
            item = self._create_item(
                item_id=item_id,
                name=name,
                url=file_url,
                item_type=ItemType.FILE,
                parent_id=dir_path,
                full_path=item_id,
            )
            with items_lock:
                all_items.append(item)

            if self.on_item_found:
                self.on_item_found(item)

        # 处理当前目录的子目录
        for full_path, name in dirs:
            if self._should_stop():
                break

            item = self._create_item(
                item_id=full_path,
                name=name,
                url="",
                item_type=ItemType.DIR,
                parent_id=dir_path,
                full_path=full_path,
            )
            with items_lock:
                all_items.append(item)

            if self.on_item_found:
                self.on_item_found(item)

        # 并行递归扫描子目录
        if not self._should_stop() and dirs:
            futures = {}
            root_futures: dict = {}

            for full_path, name in dirs:
                if self._should_stop():
                    break
                future = executor.submit(
                    self._scan_dfs_parallel_recursive,
                    base_url,
                    full_path,
                    full_path,
                    depth + 1,
                    max_depth,
                    max_workers,
                    executor,
                    all_items,
                    items_lock,
                )
                futures[future] = full_path
                if depth == 0:
                    root_futures[future] = (full_path, name)

            for future in as_completed(futures):
                if self._should_stop():
                    break
                try:
                    future.result()
                except Exception as e:
                    logger.error("并行扫描子目录失败: %s", e)
                finally:
                    self._emit_dir_complete()
                    # 添加请求间隔，防止并发过高导致503
                    if self._scan_delay > 0:
                        time.sleep(self._scan_delay)

            # 一级目录全部完成通知
            if not self._should_stop() and root_futures and self.on_log:
                completed_roots = [name for _, name in root_futures.values()]
                self.on_log(f"✓ 一级目录扫描完成 ({len(completed_roots)} 个): " + ", ".join(completed_roots), "success")

        # 标记当前目录为已完全扫描
        if not self._should_stop():
            self._mark_dir_scanned(dir_path)

    # ==================== BFS 并行扫描 ====================

    def _scan_bfs_parallel(
        self, base_url: str, max_depth: int, max_workers: int = 3, dir_path: str = "", parent_id: str = ""
    ) -> list[DownloadItem]:
        """广度优先并行扫描（逐层并行）"""
        all_items: list[DownloadItem] = []
        items_lock = threading.Lock()
        queue: deque[tuple[str, str, int]] = deque()
        queue.append((dir_path, parent_id, 0))

        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            root_dirs: list[str] = []

            while queue and not self._should_stop():
                # 收集当前层任务
                current_level: list[tuple[str, str, int]] = []
                while queue:
                    current_level.append(queue.popleft())

                # 并行处理当前层
                futures = {}
                for path, pid, d in current_level:
                    if self._should_stop():
                        break
                    if d > max_depth:
                        continue
                    if path and self._is_dir_scanned(path):
                        continue
                    future = executor.submit(self._scan_single_dir_threadsafe, base_url, path)
                    futures[future] = (path, pid, d)

                # 等待当前层完成
                for future in as_completed(futures):
                    if self._should_stop():
                        break
                    try:
                        dirs, files = future.result()
                        path, pid, d = futures[future]

                        # 记录一级目录
                        if d == 1 and path not in root_dirs:
                            root_dirs.append(path)

                        # 处理文件
                        for name, file_url in files:
                            if self._should_stop():
                                break
                            item_id = f"{path}/{name}" if path else name
                            item = self._create_item(
                                item_id=item_id,
                                name=name,
                                url=file_url,
                                item_type=ItemType.FILE,
                                parent_id=path,
                                full_path=item_id,
                            )
                            with items_lock:
                                all_items.append(item)
                            if self.on_item_found:
                                self.on_item_found(item)

                        # 处理子目录并加入队列
                        for full_path, name in dirs:
                            if self._should_stop():
                                break
                            item = self._create_item(
                                item_id=full_path,
                                name=name,
                                url="",
                                item_type=ItemType.DIR,
                                parent_id=path,
                                full_path=full_path,
                            )
                            with items_lock:
                                all_items.append(item)
                            if self.on_item_found:
                                self.on_item_found(item)
                            queue.append((full_path, full_path, d + 1))

                        # BFS即时标记：每个目录扫描完成后立即标记
                        if not self._should_stop():
                            self._mark_dir_scanned(path)

                        # 输出当前目录的扫描日志
                        is_empty = not dirs and not files
                        self._log_scan_result(path, dirs, files, is_empty)

                    except Exception as e:
                        logger.error("并行扫描目录失败: %s", e)
                    finally:
                        self._emit_dir_complete()
                        # 添加请求间隔，防止并发过高导致503
                        if self._scan_delay > 0:
                            time.sleep(self._scan_delay)

                # 一层完成通知
                if not self._should_stop() and root_dirs and not queue and self.on_log:
                    root_names = [p.split("/")[-1] for p in root_dirs]
                    self.on_log(f"✓ 一级目录扫描完成 ({len(root_names)} 个): " + ", ".join(root_names), "success")

        finally:
            executor.shutdown(wait=False)

        return all_items

    def _scan_single_dir_threadsafe(
        self, base_url: str, dir_path: str
    ) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """线程安全的扫描单个目录（用于并行 BFS）"""
        return self._get_all_pages_threadsafe(base_url, dir_path)

    def close(self):
        """关闭session（原子，可重复调用）"""
        with self._lock:
            if self._session is not None:
                self._session.close()
                self._session = None
