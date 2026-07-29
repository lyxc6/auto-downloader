"""扫描服务"""

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote, urljoin

import requests

from ..models import DownloadItem, ItemType
from .html_parser import HtmlParser
from .http_client import HttpClient
from .page_cache import PageCache

logger = logging.getLogger(__name__)


class ScanService:
    """扫描服务 - 统一扫描引擎，支持 DFS/BFS × 串行/并行"""

    def __init__(
        self,
        scan_delay: float = 0.02,
        scan_timeout: float = 300.0,
        dir_scan_timeout: float = 30.0,
    ):
        # 组件
        self._http_client = HttpClient(scan_delay, scan_timeout, dir_scan_timeout)
        self._parser = HtmlParser()
        self._page_cache = PageCache()

        # 扫描参数
        self._scan_delay = scan_delay

        # 状态管理
        self._cancel_flag = threading.Event()
        self._start_time: float = time.monotonic()

        # 已扫描目录
        self._scanned_dirs: set[str] = set()
        self._scanned_dirs_lock = threading.Lock()

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

        # 注入取消标志到http_client
        self._http_client.set_cancel_flag(self._cancel_flag)

    @property
    def session(self) -> requests.Session:
        """获取或创建session"""
        return self._http_client.session

    def cancel(self):
        """取消扫描"""
        self._cancel_flag.set()

    def is_cancelled(self) -> bool:
        """是否已取消"""
        return self._cancel_flag.is_set()

    def is_timeout(self) -> bool:
        """是否已超时（无进展超时）"""
        return self._http_client.is_timeout()

    def _update_progress(self):
        """更新进展时间（发现新内容时调用）"""
        self._http_client._update_progress()

    def _is_dir_timeout(self) -> bool:
        """检查当前目录是否超时"""
        return self._http_client._is_dir_timeout()

    def _start_dir_timer(self):
        """启动目录级计时器"""
        self._http_client._start_dir_timer()

    def reset(self):
        """重置状态"""
        self._cancel_flag.clear()
        self._start_time = time.monotonic()
        self._parallel_dirs_completed = 0
        self._http_client.reset_progress()

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

    def _log_scan_result(self, dir_path: str, dirs: list, files: list, is_empty: bool = False, has_error: bool = False):
        """记录扫描结果日志"""
        display_path = dir_path or "/"
        if self.on_log:
            if has_error:
                self.on_log(f"正在扫描: {display_path}  (服务器错误，稍后重试)", "warning")
            elif is_empty:
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
        self._http_client._increment_error_dirs()

    def get_error_dirs_count(self) -> int:
        """获取错误目录数量"""
        return self._http_client.get_error_dirs_count()

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

    def get_cached_page_info(
        self, base_url: str, dir_path: str, html: str
    ) -> tuple[int, bool]:
        """获取缓存的分页信息

        Returns:
            (total_pages, is_cache_hit)
        """
        return self._page_cache.get_cached_page_info(base_url, dir_path, html)

    def clear_page_cache(self):
        """清空分页缓存"""
        self._page_cache.clear()

    # ==================== HTTP 请求方法 ====================

    def get_page(self, url: str, retries: int = 3) -> str | None:
        """获取页面内容（智能重试）"""
        return self._http_client.get_page(url, retries)

    def _get_page_session(self, session: requests.Session, url: str, retries: int = 3) -> str | None:
        """使用指定 session 获取页面内容（智能重试，线程安全）"""
        return self._http_client.get_page(url, retries, session)

    # ==================== HTML 解析方法 ====================

    def parse_items(self, html: str) -> list[tuple[str, str, str]]:
        """解析页面项目

        Returns:
            List of (type, name, href)
        """
        return self._parser.parse_items(html)

    def get_total_pages(self, html: str, dir_path: str = "") -> int:
        """获取总页数（带缓存）"""
        return self._page_cache.get_page_count(dir_path, html)

    # ==================== 分页获取方法 ====================

    def get_all_pages(self, base_url: str, dir_path: str = "", raw_href: str = "") -> tuple[list[tuple[str, str, str]], list[tuple[str, str]], bool]:
        """获取目录下所有项目（串行模式）

        Returns:
            (dirs, files, has_error)
        """
        return self._get_all_pages_internal(base_url, dir_path, session=None, raw_href=raw_href)

    def _get_all_pages_threadsafe(
        self, base_url: str, dir_path: str = "", raw_href: str = ""
    ) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]], bool]:
        """获取目录下所有项目（并行模式，每线程独立 session）

        Returns:
            (dirs, files, has_error)
        """
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        try:
            return self._get_all_pages_internal(base_url, dir_path, session=session, raw_href=raw_href)
        finally:
            session.close()

    def _get_all_pages_internal(
        self,
        base_url: str,
        dir_path: str = "",
        session: requests.Session | None = None,
        raw_href: str = "",
    ) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]], bool]:
        """获取目录下所有项目（内部实现）

        Returns:
            (dirs, files, has_error) - dirs为三元组(full_path, name, raw_href)
        """
        all_dirs: list[tuple[str, str, str]] = []
        all_files: list[tuple[str, str]] = []

        # 启动目录级计时器
        self._start_dir_timer()

        # 1. 获取第1页，确定总页数
        url1 = self._build_page_url(base_url, dir_path, 1, raw_href=raw_href)
        html1 = self._get_page_session(session, url1) if session is not None else self.get_page(url1)
        if not html1:
            return all_dirs, all_files, True

        # 检查目录级超时
        if self._is_dir_timeout():
            logger.warning("目录扫描超时，跳过: %s", dir_path or "/")
            return all_dirs, all_files, True

        items1 = self.parse_items(html1)

        # 检测服务器错误页面（返回200但内容为空）
        has_error = False
        if not items1 and html1 and self._parser.is_error_page(html1):
            self._increment_error_dirs()
            has_error = True
            logger.warning("检测到服务器错误页面: %s", dir_path or "/")

        self._merge_items(items1, dir_path, base_url, all_dirs, all_files)

        total_pages = self.get_total_pages(html1, dir_path)
        if self.on_log and not self.parallel_mode:
            self.on_log(f"  获取页面 1/{total_pages}", "dim")

        if total_pages <= 1:
            return all_dirs, all_files, has_error

        # 2. 并行获取剩余页面（仅在并行模式下）
        if self.parallel_mode and total_pages > 2:
            self._fetch_pages_parallel(
                base_url, dir_path, session, total_pages, all_dirs, all_files, raw_href=raw_href
            )
        else:
            self._fetch_pages_serial(
                base_url, dir_path, session, total_pages, all_dirs, all_files, raw_href=raw_href
            )

        return all_dirs, all_files, has_error

    def _build_page_url(self, base_url: str, dir_path: str, page: int, raw_href: str = "") -> str:
        """构建页面URL

        Args:
            base_url: 基础URL
            dir_path: 目录路径（逻辑路径）
            page: 页码
            raw_href: 服务器返回的原始href（双重编码），优先使用
        """
        if raw_href:
            # 使用服务器返回的原始href，保持编码格式一致
            if page > 1:
                sep = "&" if "?" in raw_href else "?"
                return base_url + raw_href + f"{sep}page={page}"
            return base_url + raw_href
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
        """合并页面项目到总列表

        Returns dirs as (full_path, name, raw_href) 三元组，保留原始href用于URL构建
        """
        for item_type, name, href in items:
            if item_type == "dir":
                full_path = f"{dir_path}/{name}" if dir_path else name
                if not any(d[0] == full_path for d in all_dirs):
                    all_dirs.append((full_path, name, href))
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
        raw_href: str = "",
    ) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]]]:
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

            url = self._build_page_url(base_url, dir_path, page, raw_href=raw_href)
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
        raw_href: str = "",
    ) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]]]:
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
                        self._fetch_single_page, base_url, dir_path, session, page, raw_href
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
        session: requests.Session, page: int, raw_href: str = ""
    ) -> str | None:
        """获取单个页面"""
        url = self._build_page_url(base_url, dir_path, page, raw_href=raw_href)
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
        self, base_url: str, max_depth: int, dir_path: str = "", parent_id: str = "", depth: int = 0, raw_href: str = ""
    ) -> list[DownloadItem]:
        """深度优先串行扫描"""
        items: list[DownloadItem] = []

        if depth > max_depth or self._should_stop():
            return items

        if dir_path and self._is_dir_scanned(dir_path):
            return items

        dirs, files, has_error = self.get_all_pages(base_url, dir_path, raw_href=raw_href)
        is_empty = not dirs and not files
        self._log_scan_result(dir_path, dirs, files, is_empty, has_error)

        # 处理子目录
        for full_path, name, child_href in dirs:
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
            sub_items = self._scan_dfs(base_url, max_depth, full_path, full_path, depth + 1, raw_href=child_href)
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

        # 仅在无错误时标记为已扫描（错误时不标记，下次刷新可重试）
        if not self._should_stop() and not has_error:
            self._mark_dir_scanned(dir_path)

        return items

    # ==================== BFS 串行扫描 ====================

    def _scan_bfs(
        self, base_url: str, max_depth: int, dir_path: str = "", parent_id: str = "", depth: int = 0, raw_href: str = ""
    ) -> list[DownloadItem]:
        """广度优先串行扫描（逐层扫描，先显示一级目录再逐层深入）"""
        all_items: list[DownloadItem] = []
        queue: deque[tuple[str, str, int, str]] = deque()
        queue.append((dir_path, parent_id, depth, raw_href))

        while queue and not self._should_stop():
            current_level: list[tuple[str, str, int, str]] = []
            while queue:
                current_level.append(queue.popleft())

            for current_path, _current_parent, current_depth, current_href in current_level:
                if self._should_stop():
                    break
                if current_depth > max_depth:
                    continue
                if current_path and self._is_dir_scanned(current_path):
                    continue

                dirs, files, has_error = self.get_all_pages(base_url, current_path, raw_href=current_href)
                is_empty = not dirs and not files
                self._log_scan_result(current_path, dirs, files, is_empty, has_error)

                # 处理子目录并加入队列
                for full_path, name, child_href in dirs:
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

                    queue.append((full_path, full_path, current_depth + 1, child_href))
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

                # BFS即时标记：每个目录扫描完成后立即标记（错误时不标记）
                if not self._should_stop() and not has_error:
                    self._mark_dir_scanned(current_path)

        return all_items

    # ==================== DFS 并行扫描 ====================

    def _scan_dfs_parallel(
        self, base_url: str, max_depth: int, max_workers: int = 3, dir_path: str = "", parent_id: str = "", raw_href: str = ""
    ) -> list[DownloadItem]:
        """深度优先并行扫描"""
        all_items: list[DownloadItem] = []
        items_lock = threading.Lock()
        executor = ThreadPoolExecutor(max_workers=max_workers)

        try:
            self._scan_dfs_parallel_recursive(
                base_url, dir_path, parent_id, 0, max_depth, max_workers, executor, all_items, items_lock, raw_href=raw_href
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
        raw_href: str = "",
    ):
        """DFS 并行扫描递归实现"""
        if depth > max_depth or self._should_stop():
            return

        if dir_path and self._is_dir_scanned(dir_path):
            return

        # 获取当前目录内容
        dirs, files, has_error = self._get_all_pages_threadsafe(base_url, dir_path, raw_href=raw_href)
        is_empty = not dirs and not files
        self._log_scan_result(dir_path, dirs, files, is_empty, has_error)

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
        for full_path, name, _child_href in dirs:
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

            for full_path, name, child_href in dirs:
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
                    raw_href=child_href,
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

        # 仅在无错误时标记为已扫描（错误时不标记，下次刷新可重试）
        if not self._should_stop() and not has_error:
            self._mark_dir_scanned(dir_path)

    # ==================== BFS 并行扫描 ====================

    def _scan_bfs_parallel(
        self, base_url: str, max_depth: int, max_workers: int = 3, dir_path: str = "", parent_id: str = "", raw_href: str = ""
    ) -> list[DownloadItem]:
        """广度优先并行扫描（逐层并行）"""
        all_items: list[DownloadItem] = []
        items_lock = threading.Lock()
        queue: deque[tuple[str, str, int, str]] = deque()
        queue.append((dir_path, parent_id, 0, raw_href))

        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            root_dirs: list[str] = []

            while queue and not self._should_stop():
                # 收集当前层任务
                current_level: list[tuple[str, str, int, str]] = []
                while queue:
                    current_level.append(queue.popleft())

                # 并行处理当前层
                futures = {}
                for path, pid, d, cur_href in current_level:
                    if self._should_stop():
                        break
                    if d > max_depth:
                        continue
                    if path and self._is_dir_scanned(path):
                        continue
                    future = executor.submit(self._scan_single_dir_threadsafe, base_url, path, cur_href)
                    futures[future] = (path, pid, d)

                # 等待当前层完成
                for future in as_completed(futures):
                    if self._should_stop():
                        break
                    try:
                        dirs, files, has_error = future.result()
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
                        for full_path, name, child_href in dirs:
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
                            queue.append((full_path, full_path, d + 1, child_href))

                        # BFS即时标记：每个目录扫描完成后立即标记（错误时不标记）
                        if not self._should_stop() and not has_error:
                            self._mark_dir_scanned(path)

                        # 输出当前目录的扫描日志
                        is_empty = not dirs and not files
                        self._log_scan_result(path, dirs, files, is_empty, has_error)

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
        self, base_url: str, dir_path: str, raw_href: str = ""
    ) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]]]:
        """线程安全的扫描单个目录（用于并行 BFS）"""
        return self._get_all_pages_threadsafe(base_url, dir_path, raw_href=raw_href)

    def close(self):
        """关闭session（原子，可重复调用）"""
        self._http_client.close()
