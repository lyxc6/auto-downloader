"""扫描服务"""

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
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
        self._http_client.touch_progress()

    def _is_dir_timeout(self) -> bool:
        """检查当前目录是否超时"""
        return self._http_client.is_dir_timeout()

    def _start_dir_timer(self):
        """启动目录级计时器"""
        self._http_client.start_dir_timer()

    def reset(self):
        """重置状态"""
        self._cancel_flag.clear()
        self._start_time = time.monotonic()
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
        self._http_client.increment_error_dirs()

    def get_error_dirs_count(self) -> int:
        """获取错误目录数量"""
        return self._http_client.get_error_dirs_count()

    def get_failed_dirs_count(self) -> int:
        """获取失败目录数量"""
        return self._http_client.get_failed_dirs_count()

    def _mark_dir_scanned(self, dir_path: str):
        """标记目录为已扫描（线程安全）"""
        with self._scanned_dirs_lock:
            self._scanned_dirs.add(dir_path)
        if self.on_dir_scanned:
            self.on_dir_scanned(dir_path)

    def _should_stop(self) -> bool:
        """检查是否应该停止扫描（取消或超时）"""
        return self.is_cancelled() or self.is_timeout()

    # ==================== 分页缓存方法 ====================

    def get_cached_page_info(self, base_url: str, dir_path: str, html: str) -> tuple[int, bool]:
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

    def get_all_pages(
        self, base_url: str, dir_path: str = "", raw_href: str = ""
    ) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]], bool]:
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

        from bs4 import BeautifulSoup

        soup1 = BeautifulSoup(html1, "html.parser")
        items1 = self._parser.parse_items_from_soup(soup1)

        # 检测服务器错误页面（返回200但内容为空）
        has_error = False
        if not items1 and html1 and self._parser.is_error_page_from_soup(soup1):
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
            self._fetch_pages_parallel(base_url, dir_path, session, total_pages, all_dirs, all_files, raw_href=raw_href)
        else:
            self._fetch_pages_serial(base_url, dir_path, session, total_pages, all_dirs, all_files, raw_href=raw_href)

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
            query = f"?dir={quote(quote(dir_path))}"
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
                logger.warning(
                    "目录扫描超时，停止获取后续页面: %s (已获取 %d/%d 页)", dir_path or "/", page - 1, total_pages
                )
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
            session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
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
                    executor.submit(self._fetch_single_page, base_url, dir_path, session, page, raw_href): page
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
        self, base_url: str, dir_path: str, session: requests.Session, page: int, raw_href: str = ""
    ) -> str | None:
        """获取单个页面（线程安全：使用独立 session）"""
        url = self._build_page_url(base_url, dir_path, page, raw_href=raw_href)
        # 创建独立 session，避免跨线程共享
        thread_session = requests.Session()
        thread_session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        try:
            return self._get_page_session(thread_session, url)
        finally:
            thread_session.close()

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
            return self._traverse_parallel(base_url, scan_mode, max_depth, max_workers, dir_path, parent_id)
        return self._traverse_serial(base_url, scan_mode, max_depth, dir_path, parent_id)

    # ==================== 统一遍历引擎 ====================
    # 任务编码: ("dir", dir_path, parent_id, depth, raw_href)  目录扫描任务
    #          ("files", dir_path, files)                     文件输出任务（DFS 延后输出用）
    # DFS 使用栈（pop 右端），BFS 使用队列（pop 左端），串行/并行共用同一套任务语义

    def _emit_dir_item(
        self, full_path: str, name: str, parent_id: str, items: list[DownloadItem], delay: float
    ) -> None:
        """创建目录项并发射回调"""
        item = self._create_item(
            item_id=full_path,
            name=name,
            url="",
            item_type=ItemType.DIR,
            parent_id=parent_id,
            full_path=full_path,
        )
        items.append(item)
        if self.on_item_found:
            self.on_item_found(item)
        if delay > 0:
            time.sleep(delay)

    def _emit_file_item(self, dir_path: str, name: str, file_url: str, items: list[DownloadItem], delay: float) -> None:
        """创建文件项并发射回调"""
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
        if delay > 0:
            time.sleep(delay)

    def _emit_files(self, dir_path: str, files: list, items: list[DownloadItem], delay: float) -> None:
        """批量输出文件项"""
        for name, file_url in files:
            if self._should_stop():
                break
            self._emit_file_item(dir_path, name, file_url, items, delay)

    def _traverse_serial(
        self, base_url: str, scan_mode: str, max_depth: int, dir_path: str = "", parent_id: str = ""
    ) -> list[DownloadItem]:
        """串行遍历引擎（DFS 栈 / BFS 队列）"""
        all_items: list[DownloadItem] = []
        is_dfs = scan_mode == "dfs"
        worklist: deque = deque()
        worklist.append(("dir", dir_path, parent_id, 0, ""))

        while worklist and not self._should_stop():
            task = worklist.pop() if is_dfs else worklist.popleft()

            # 文件输出任务（DFS 延后输出本目录文件）
            if task[0] == "files":
                self._emit_files(task[1], task[2], all_items, self._scan_delay)
                continue

            _, cur_path, _cur_parent, cur_depth, cur_href = task
            if cur_depth >= max_depth:
                continue
            if cur_path and self._is_dir_scanned(cur_path):
                continue

            dirs, files, has_error = self.get_all_pages(base_url, cur_path, raw_href=cur_href)
            is_empty = not dirs and not files
            self._log_scan_result(cur_path, dirs, files, is_empty, has_error)

            # 处理子目录并收集任务
            children: list[tuple] = []
            for full_path, name, child_href in dirs:
                if self._should_stop():
                    break
                self._emit_dir_item(full_path, name, cur_path, all_items, self._scan_delay)
                children.append(("dir", full_path, full_path, cur_depth + 1, child_href))

            if is_dfs:
                # 栈：文件任务压栈底（子目录全部处理后输出），子目录反向压栈保持 DFS 顺序
                worklist.append(("files", cur_path, files))
                worklist.extend(reversed(children))
            else:
                # 队列：子目录先入队，本目录文件立即输出（逐层顺序）
                worklist.extend(children)
                self._emit_files(cur_path, files, all_items, self._scan_delay)

            # 仅在无错误时标记为已扫描（错误时不标记，下次刷新可重试）
            if not self._should_stop() and not has_error:
                self._mark_dir_scanned(cur_path)

        return all_items

    def _traverse_parallel(
        self,
        base_url: str,
        scan_mode: str,
        max_depth: int,
        max_workers: int = 3,
        dir_path: str = "",
        parent_id: str = "",
    ) -> list[DownloadItem]:
        """并行遍历引擎（DFS 栈 / BFS 队列 + in-flight 限流，真实并发）"""
        all_items: list[DownloadItem] = []
        is_dfs = scan_mode == "dfs"
        worklist: deque = deque()
        worklist.append(("dir", dir_path, parent_id, 0, ""))
        root_dirs: list[str] = []  # 一级目录名（完成通知用）
        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            futures: dict = {}

            while (worklist or futures) and not self._should_stop():
                # 提交任务（in-flight ≤ max_workers，协调器不等待单个 future，实现真实并发）
                while worklist and len(futures) < max_workers and not self._should_stop():
                    task = worklist.pop() if is_dfs else worklist.popleft()

                    # 文件输出任务无 I/O，直接执行
                    if task[0] == "files":
                        self._emit_files(task[1], task[2], all_items, 0)
                        continue

                    _, cur_path, _cur_parent, cur_depth, cur_href = task
                    if cur_depth >= max_depth:
                        continue
                    if cur_path and self._is_dir_scanned(cur_path):
                        continue
                    future = executor.submit(self._get_all_pages_threadsafe, base_url, cur_path, cur_href)
                    futures[future] = task

                if not futures:
                    continue

                # 等待任一目录任务完成（轮询，及时响应取消/超时）
                done_set, _ = wait(futures, timeout=0.05, return_when=FIRST_COMPLETED)
                if not done_set:
                    continue
                done = done_set.pop()
                task = futures.pop(done)
                _, cur_path, _cur_parent, cur_depth, _cur_href = task

                try:
                    dirs, files, has_error = done.result()
                except Exception as e:
                    logger.error("扫描目录失败: %s -> %s", cur_path, e)
                    if self._scan_delay > 0:
                        time.sleep(self._scan_delay)
                    continue

                is_empty = not dirs and not files
                self._log_scan_result(cur_path, dirs, files, is_empty, has_error)

                # 记录一级目录（根目录的子目录）
                if cur_depth == 0:
                    for _full_path, name, _href in dirs:
                        root_dirs.append(name)

                children: list[tuple] = []
                for full_path, name, child_href in dirs:
                    if self._should_stop():
                        break
                    self._emit_dir_item(full_path, name, cur_path, all_items, 0)
                    children.append(("dir", full_path, full_path, cur_depth + 1, child_href))

                if is_dfs:
                    worklist.append(("files", cur_path, files))
                    worklist.extend(reversed(children))
                else:
                    worklist.extend(children)
                    self._emit_files(cur_path, files, all_items, 0)

                if not self._should_stop() and not has_error:
                    self._mark_dir_scanned(cur_path)

                # 每目录请求间隔，防止并发过高导致 503
                if self._scan_delay > 0:
                    time.sleep(self._scan_delay)

            # 一级目录完成通知
            if root_dirs and self.on_log:
                self.on_log(f"✓ 一级目录扫描完成 ({len(root_dirs)} 个): " + ", ".join(root_dirs), "success")
        finally:
            executor.shutdown(wait=False)

        return all_items

    def close(self):
        """关闭session（原子，可重复调用）"""
        self._http_client.close()
