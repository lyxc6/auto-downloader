"""扫描服务"""
import logging
import re
import time
import threading
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote
from typing import List, Tuple, Optional, Callable
from ..models import DownloadItem, ItemType

logger = logging.getLogger(__name__)


class ScanService:
    """扫描服务"""
    
    def __init__(self):
        self._session: Optional[requests.Session] = None
        self._cancel_flag = threading.Event()
        self._lock = threading.Lock()
        
        # 回调函数
        self.on_item_found: Optional[Callable[[DownloadItem], None]] = None
        self.on_progress: Optional[Callable[[int, int], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_log: Optional[Callable[[str, str], None]] = None
    
    @property
    def session(self) -> requests.Session:
        """获取或创建session"""
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
    
    def get_page(self, url: str, retries: int = 3) -> Optional[str]:
        """获取页面内容"""
        for i in range(retries + 1):
            if self.is_cancelled():
                return None
            
            try:
                resp = self.session.get(url, timeout=60)
                resp.encoding = "utf-8"
                return resp.text
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
        items = []
        
        for li in soup.select("li"):
            a = li.find("a")
            if not a:
                continue
            
            href = a.get("href", "")
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
        """获取总页数"""
        match = re.search(r'(\d+)/(\d+)', html)
        if match:
            return int(match.group(2))
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
        all_dirs = []
        all_files = []
        page = 1
        
        while True:
            if self.is_cancelled():
                break
            
            params = f"?dir={quote(dir_path)}" if dir_path else ""
            page_param = f"&page={page}" if page > 1 else ""
            url = base_url + params + page_param
            
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
        items = []
        
        if depth > max_depth or self.is_cancelled():
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
        
        return items
    
    def close(self):
        """关闭session"""
        if self._session:
            self._session.close()
            self._session = None
