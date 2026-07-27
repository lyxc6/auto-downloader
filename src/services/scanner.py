"""扫描服务"""
import logging
import re
import time
import threading
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote
from typing import List, Tuple, Optional, Callable, Set, cast
from concurrent.futures import ThreadPoolExecutor, as_completed
from ..models import DownloadItem, ItemType

logger = logging.getLogger(__name__)


class ScanService:
    """扫描服务"""
    
    def __init__(self):
        self._session: Optional[requests.Session] = None
        self._cancel_flag = threading.Event()
        self._lock = threading.Lock()
        self._scanned_dirs: Set[str] = set()
        self._scanned_dirs_lock = threading.Lock()  # 保护 _scanned_dirs 的并发访问
        
        # 回调函数
        self.on_item_found: Optional[Callable[[DownloadItem], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_log: Optional[Callable[[str, str], None]] = None
        self.on_dir_scanned: Optional[Callable[[str], None]] = None
    
    @property
    def session(self) -> requests.Session:
        """获取或创建session"""
        with self._lock:
            if self._session is None:
                self._session = requests.Session()
                self._session.headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                })
            return self._session
    
    def cancel(self):
        """取消扫描"""
        self._cancel_flag.set()
    
    def is_cancelled(self) -> bool:
        """是否已取消"""
        return self._cancel_flag.is_set()
    
    def reset(self):
        """重置状态"""
        self._cancel_flag.clear()
    
    def set_scanned_dirs(self, dirs: Set[str]):
        """设置已扫描目录集合（续扫时跳过这些目录）"""
        self._scanned_dirs = set(dirs)
    
    def get_page(self, url: str, retries: int = 3) -> Optional[str]:
        """获取页面内容"""
        for i in range(retries + 1):
            if self.is_cancelled():
                return None

            try:
                resp = self.session.get(url, timeout=60)
                resp.raise_for_status()
                resp.encoding = "utf-8"
                return resp.text
            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else None
                # 4xx: 页面不存在或无权限，终止该路径，不重试
                if status is not None and 400 <= status < 500:
                    logger.warning("获取页面失败(4xx): %s -> %s", url, status)
                    if self.on_error:
                        self.on_error(f"页面不存在或无权限: {status}")
                    return None
                # 5xx: 服务端错误，重试
                if i < retries:
                    logger.warning("获取页面重试 %d/%d: %s -> %s", i + 1, retries, url, e)
                    time.sleep(2)
                    continue
                logger.error("获取页面失败: %s -> %s", url, e)
                if self.on_error:
                    self.on_error(f"获取页面失败: {e}")
                return None
            except Exception as e:
                if i < retries:
                    logger.warning("获取页面重试 %d/%d: %s -> %s", i + 1, retries, url, e)
                    time.sleep(2)
                    continue
                logger.error("获取页面失败: %s -> %s", url, e)
                if self.on_error:
                    self.on_error(f"获取页面失败: {e}")
                return None
    
    def parse_items(self, html: str) -> List[Tuple[str, str, str]]:
        """解析页面项目
        
        Returns:
            List of (type, name, href)
        """
        soup = BeautifulSoup(html, "html.parser")
        items: list[tuple[str, str, str]] = []
        
        for li in soup.select("li"):
            a = li.find("a")
            if not a:
                continue
            
            href = str(a.get("href", ""))
            text = a.get_text(strip=True)
            
            if not href or href == "#":
                continue
            if "flyingfry.cc" in href and "dir=" not in href:
                continue
            if "返回上级" in text:
                continue
            
            if text.startswith("📁"):
                items.append(("dir", text[2:].strip(), href))
            elif text.startswith("📄"):
                items.append(("file", text[2:].strip(), href))
        
        return items
    
    def get_total_pages(self, html: str) -> int:
        """获取总页数

        解析优先级：
        1. 分页链接 ``?page=N`` 中的最大页码（最可靠）
        2. 分页容器（class 含 pag/page）内的 ``N/M`` 文本
        3. 含分页语义关键词（当前/第 ... 页）的 ``N/M`` 文本
        4. 默认 1

        避免误匹配正文中的日期、版本号、比例等任意 ``N/M``。
        """
        soup = BeautifulSoup(html, "html.parser")

        # 1. 从分页链接提取最大页码
        max_page = 1
        for a in soup.find_all("a", href=True):
            href = str(a["href"])
            if "page=" in href:
                m = re.search(r'[?&]page=(\d+)', href)
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
                m = re.search(r'(\d+)\s*/\s*(\d+)', el.get_text(" "))
                if m:
                    return int(m.group(2))

        # 3. 含分页语义关键词的 N/M 文本回退
        text = soup.get_text(" ")
        m = re.search(r'(?:当前|第)\s*\d+\s*/\s*(\d+)', text)
        if m:
            return int(m.group(1))

        return 1
    
    def get_all_pages(
        self, 
        base_url: str, 
        dir_path: str = ""
    ) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
        """获取目录下所有项目
        
        Returns:
            (dirs, files) - dirs: [(full_path, name)], files: [(name, url)]
        """
        all_dirs: list[tuple[str, str]] = []
        all_files: list[tuple[str, str]] = []
        page = 1
        
        while True:
            if self.is_cancelled():
                break
            
            if dir_path:
                query = f"?dir={quote(dir_path)}"
                if page > 1:
                    query += f"&page={page}"
            else:
                query = f"?page={page}" if page > 1 else ""
            url = base_url + query
            
            html = self.get_page(url)
            if not html:
                break
            
            items = self.parse_items(html)
            
            for item_type, name, href in items:
                if item_type == "dir":
                    full_path = f"{dir_path}/{name}" if dir_path else name
                    if (full_path, name) not in all_dirs:
                        all_dirs.append((full_path, name))
                else:
                    file_url = urljoin(base_url, href)
                    if (name, file_url) not in all_files:
                        all_files.append((name, file_url))
            
            total = self.get_total_pages(html)
            if self.on_log:
                self.on_log(f"  获取页面 {page}/{total}", "dim")
            
            if page >= total:
                break
            
            page += 1
            time.sleep(0.15)
        
        return all_dirs, all_files
    
    def scan_directory(
        self,
        base_url: str,
        dir_path: str = "",
        parent_id: str = "",
        depth: int = 0,
        max_depth: int = 10
    ) -> List[DownloadItem]:
        """扫描目录"""
        items: list[DownloadItem] = []
        
        if depth > max_depth or self.is_cancelled():
            return items
        
        # 续扫：跳过已完全扫描的目录
        if dir_path in self._scanned_dirs:
            return items
        
        dirs, files = self.get_all_pages(base_url, dir_path)
        
        display_path = dir_path or "/"
        if self.on_log:
            if len(dirs) > 0 or len(files) > 0:
                self.on_log(f"正在扫描: {display_path}", "info")
            else:
                self.on_log(f"正在扫描: {display_path}  (空目录)", "dim")
        
        if self.on_log and (dirs or files):
            self.on_log(f"  ├─ 子目录: {len(dirs)} 个, 文件: {len(files)} 个", "info")
        
        # 处理目录
        for full_path, name in dirs:
            if self.is_cancelled():
                break
            
            item_id = full_path
            item = DownloadItem(
                item_id=item_id,
                name=name,
                url="",
                item_type=ItemType.DIR,
                parent_id=parent_id,
                full_path=full_path
            )
            items.append(item)
            
            if self.on_item_found:
                self.on_item_found(item)
            
            # 递归扫描子目录
            time.sleep(0.02)
            sub_items = self.scan_directory(
                base_url, full_path, item_id, depth + 1, max_depth
            )
            items.extend(sub_items)
        
        # 处理文件
        for name, file_url in files:
            if self.is_cancelled():
                break
            
            item_id = f"{dir_path}/{name}" if dir_path else name
            item = DownloadItem(
                item_id=item_id,
                name=name,
                url=file_url,
                item_type=ItemType.FILE,
                parent_id=parent_id,
                full_path=item_id
            )
            items.append(item)
            
            if self.on_item_found:
                self.on_item_found(item)
            
            time.sleep(0.02)
        
        # 标记当前目录为已完全扫描（仅在未取消时）
        if not self.is_cancelled():
            self._scanned_dirs.add(dir_path)
            if self.on_dir_scanned:
                self.on_dir_scanned(dir_path)
        
        return items
    
    def scan_directory_bfs(
        self,
        base_url: str,
        dir_path: str = "",
        parent_id: str = "",
        depth: int = 0,
        max_depth: int = 10
    ) -> List[DownloadItem]:
        """广度优先扫描目录（逐层扫描，先显示一级目录再逐层深入）"""
        from collections import deque
        
        all_items: list[DownloadItem] = []
        queue: deque[tuple[str, str, int]] = deque()
        queue.append((dir_path, parent_id, depth))
        
        while queue and not self.is_cancelled():
            current_level: list[tuple[str, str, int]] = []
            while queue:
                current_level.append(queue.popleft())
            
            for dir_path, parent_id, depth in current_level:
                if self.is_cancelled():
                    break
                if depth > max_depth:
                    continue
                if dir_path in self._scanned_dirs:
                    continue
                
                dirs, files = self.get_all_pages(base_url, dir_path)
                
                display_path = dir_path or "/"
                if self.on_log:
                    if len(dirs) > 0 or len(files) > 0:
                        self.on_log(f"正在扫描: {display_path}", "info")
                    else:
                        self.on_log(f"正在扫描: {display_path}  (空目录)", "dim")
                
                if self.on_log and (dirs or files):
                    self.on_log(f"  ├─ 子目录: {len(dirs)} 个, 文件: {len(files)} 个", "info")
                
                for full_path, name in dirs:
                    if self.is_cancelled():
                        break
                    
                    item_id = full_path
                    item = DownloadItem(
                        item_id=item_id,
                        name=name,
                        url="",
                        item_type=ItemType.DIR,
                        parent_id=parent_id,
                        full_path=full_path
                    )
                    all_items.append(item)
                    
                    if self.on_item_found:
                        self.on_item_found(item)
                    
                    queue.append((full_path, full_path, depth + 1))
                    time.sleep(0.02)
                
                for name, file_url in files:
                    if self.is_cancelled():
                        break
                    
                    item_id = f"{dir_path}/{name}" if dir_path else name
                    item = DownloadItem(
                        item_id=item_id,
                        name=name,
                        url=file_url,
                        item_type=ItemType.FILE,
                        parent_id=parent_id,
                        full_path=item_id
                    )
                    all_items.append(item)
                    
                    if self.on_item_found:
                        self.on_item_found(item)
                    
                    time.sleep(0.02)
                
                if not self.is_cancelled():
                    self._scanned_dirs.add(dir_path)
                    if self.on_dir_scanned:
                        self.on_dir_scanned(dir_path)
        
        return all_items
    
    def scan_directory_parallel(
        self,
        base_url: str,
        dir_path: str = "",
        parent_id: str = "",
        depth: int = 0,
        max_depth: int = 10,
        max_workers: int = 3
    ) -> List[DownloadItem]:
        """并行 DFS 扫描（逐层并行）"""
        all_items: list[DownloadItem] = []
        items_lock = threading.Lock()
        
        if depth > max_depth or self.is_cancelled():
            return all_items
        
        # 续扫：跳过已完全扫描的目录
        with self._scanned_dirs_lock:
            if dir_path in self._scanned_dirs:
                return all_items
        
        # 获取当前目录内容（使用独立 session）
        dirs, files = self._get_all_pages_threadsafe(base_url, dir_path)
        
        display_path = dir_path or "/"
        if self.on_log:
            if len(dirs) > 0 or len(files) > 0:
                self.on_log(f"正在扫描: {display_path}", "info")
            else:
                self.on_log(f"正在扫描: {display_path}  (空目录)", "dim")
        
        if self.on_log and (dirs or files):
            self.on_log(f"  ├─ 子目录: {len(dirs)} 个, 文件: {len(files)} 个", "info")
        
        # 处理当前目录的文件
        for name, file_url in files:
            if self.is_cancelled():
                break
            
            item_id = f"{dir_path}/{name}" if dir_path else name
            item = DownloadItem(
                item_id=item_id,
                name=name,
                url=file_url,
                item_type=ItemType.FILE,
                parent_id=parent_id,
                full_path=item_id
            )
            with items_lock:
                all_items.append(item)
            
            if self.on_item_found:
                self.on_item_found(item)
        
        # 处理当前目录的子目录
        for full_path, name in dirs:
            if self.is_cancelled():
                break
            
            item_id = full_path
            item = DownloadItem(
                item_id=item_id,
                name=name,
                url="",
                item_type=ItemType.DIR,
                parent_id=parent_id,
                full_path=full_path
            )
            with items_lock:
                all_items.append(item)
            
            if self.on_item_found:
                self.on_item_found(item)
        
        # 并行递归扫描子目录
        if not self.is_cancelled() and dirs:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {}
                for full_path, name in dirs:
                    if self.is_cancelled():
                        break
                    future = executor.submit(
                        self.scan_directory_parallel,
                        base_url, full_path, full_path,
                        depth + 1, max_depth, max_workers
                    )
                    futures[future] = full_path
                
                for future in as_completed(futures):
                    if self.is_cancelled():
                        break
                    try:
                        sub_items = future.result()
                        with items_lock:
                            all_items.extend(sub_items)
                    except Exception as e:
                        logger.error("并行扫描子目录失败: %s", e)
        
        # 标记当前目录为已完全扫描
        if not self.is_cancelled():
            with self._scanned_dirs_lock:
                self._scanned_dirs.add(dir_path)
            if self.on_dir_scanned:
                self.on_dir_scanned(dir_path)
        
        return all_items
    
    def scan_directory_bfs_parallel(
        self,
        base_url: str,
        dir_path: str = "",
        parent_id: str = "",
        depth: int = 0,
        max_depth: int = 10,
        max_workers: int = 3
    ) -> List[DownloadItem]:
        """并行 BFS 扫描（逐层并行）"""
        from collections import deque
        
        all_items: list[DownloadItem] = []
        items_lock = threading.Lock()
        queue: deque[tuple[str, str, int]] = deque()
        queue.append((dir_path, parent_id, depth))
        
        while queue and not self.is_cancelled():
            # 收集当前层任务
            current_level: list[tuple[str, str, int]] = []
            while queue:
                current_level.append(queue.popleft())
            
            # 并行处理当前层
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {}
                for path, pid, d in current_level:
                    if self.is_cancelled():
                        break
                    if d > max_depth:
                        continue
                    with self._scanned_dirs_lock:
                        if path in self._scanned_dirs:
                            continue
                    future = executor.submit(
                        self._scan_single_dir_threadsafe,
                        base_url, path, pid, d
                    )
                    futures[future] = (path, pid, d)
                
                # 等待当前层完成
                for future in as_completed(futures):
                    if self.is_cancelled():
                        break
                    try:
                        dirs, files = future.result()
                        path, pid, d = futures[future]
                        
                        # 处理文件
                        for name, file_url in files:
                            if self.is_cancelled():
                                break
                            item_id = f"{path}/{name}" if path else name
                            item = DownloadItem(
                                item_id=item_id,
                                name=name,
                                url=file_url,
                                item_type=ItemType.FILE,
                                parent_id=pid,
                                full_path=item_id
                            )
                            with items_lock:
                                all_items.append(item)
                            if self.on_item_found:
                                self.on_item_found(item)
                        
                        # 处理子目录并加入队列
                        for full_path, name in dirs:
                            if self.is_cancelled():
                                break
                            item_id = full_path
                            item = DownloadItem(
                                item_id=item_id,
                                name=name,
                                url="",
                                item_type=ItemType.DIR,
                                parent_id=pid,
                                full_path=full_path
                            )
                            with items_lock:
                                all_items.append(item)
                            if self.on_item_found:
                                self.on_item_found(item)
                            queue.append((full_path, full_path, d + 1))
                        
                        # 标记目录已扫描
                        if not self.is_cancelled():
                            with self._scanned_dirs_lock:
                                self._scanned_dirs.add(path)
                            if self.on_dir_scanned:
                                self.on_dir_scanned(path)
                    
                    except Exception as e:
                        logger.error("并行扫描目录失败: %s", e)
        
        return all_items
    
    def _get_all_pages_threadsafe(
        self,
        base_url: str,
        dir_path: str = ""
    ) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
        """线程安全的获取目录下所有项目（每线程独立 session）"""
        # 创建线程本地 session
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        
        all_dirs: list[tuple[str, str]] = []
        all_files: list[tuple[str, str]] = []
        page = 1
        
        try:
            while True:
                if self.is_cancelled():
                    break
                
                if dir_path:
                    query = f"?dir={quote(dir_path)}"
                    if page > 1:
                        query += f"&page={page}"
                else:
                    query = f"?page={page}" if page > 1 else ""
                url = base_url + query
                
                html = self._get_page_session(session, url)
                if not html:
                    break
                
                items = self.parse_items(html)
                
                for item_type, name, href in items:
                    if item_type == "dir":
                        full_path = f"{dir_path}/{name}" if dir_path else name
                        if (full_path, name) not in all_dirs:
                            all_dirs.append((full_path, name))
                    else:
                        file_url = urljoin(base_url, href)
                        if (name, file_url) not in all_files:
                            all_files.append((name, file_url))
                
                total = self.get_total_pages(html)
                if self.on_log:
                    self.on_log(f"  获取页面 {page}/{total}", "dim")
                
                if page >= total:
                    break
                
                page += 1
                time.sleep(0.15)
        finally:
            session.close()
        
        return all_dirs, all_files
    
    def _get_page_session(self, session: requests.Session, url: str, retries: int = 3) -> Optional[str]:
        """使用指定 session 获取页面内容"""
        for i in range(retries + 1):
            if self.is_cancelled():
                return None
            
            try:
                resp = session.get(url, timeout=60)
                resp.raise_for_status()
                resp.encoding = "utf-8"
                return resp.text
            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else None
                if status is not None and 400 <= status < 500:
                    logger.warning("获取页面失败(4xx): %s -> %s", url, status)
                    return None
                if i < retries:
                    logger.warning("获取页面重试 %d/%d: %s -> %s", i + 1, retries, url, e)
                    time.sleep(2)
                    continue
                logger.error("获取页面失败: %s -> %s", url, e)
                return None
            except Exception as e:
                if i < retries:
                    logger.warning("获取页面重试 %d/%d: %s -> %s", i + 1, retries, url, e)
                    time.sleep(2)
                    continue
                logger.error("获取页面失败: %s -> %s", url, e)
                return None
    
    def _scan_single_dir_threadsafe(
        self,
        base_url: str,
        dir_path: str,
        parent_id: str,
        depth: int
    ) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
        """线程安全的扫描单个目录（用于并行 BFS）"""
        return self._get_all_pages_threadsafe(base_url, dir_path)
    
    def close(self):
        """关闭session（原子，可重复调用）"""
        with self._lock:
            if self._session is not None:
                self._session.close()
                self._session = None
