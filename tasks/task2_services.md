# 任务2：服务层 (Services)

## 任务描述
创建项目的服务层，实现核心业务逻辑：下载服务和扫描服务。

## 文件清单
- `src/services/__init__.py`
- `src/services/downloader.py`
- `src/services/scanner.py`

## 技术要求
- 线程安全的下载和扫描操作
- 支持取消操作
- 进度回调
- 错误重试机制

## 依赖
- 需要 `src/models` 模块

---

## 文件1：src/services/downloader.py

```python
"""下载服务"""
import os
import time
import threading
import requests
from typing import Callable, Optional
from ..models import DownloadItem, DownloadStatus, DownloadStats


class DownloadService:
    """下载服务"""
    
    def __init__(self, max_workers: int = 3, retry_times: int = 3, timeout: int = 120):
        self.max_workers = max_workers
        self.retry_times = retry_times
        self.timeout = timeout
        self._session: Optional[requests.Session] = None
        self._cancel_flag = threading.Event()
        self._pause_flag = threading.Event()
        self._pause_flag.set()  # 初始为非暂停状态
        self._lock = threading.Lock()
        
        # 回调函数
        self.on_progress: Optional[Callable[[str, int, int], None]] = None  # item_id, downloaded, total
        self.on_status_changed: Optional[Callable[[str, DownloadStatus], None]] = None
        self.on_error: Optional[Callable[[str, str], None]] = None
        self.on_complete: Optional[Callable[[str], None]] = None
    
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
        """取消下载"""
        self._cancel_flag.set()
    
    def pause(self):
        """暂停下载"""
        self._pause_flag.clear()
    
    def resume(self):
        """恢复下载"""
        self._pause_flag.set()
    
    def is_cancelled(self) -> bool:
        """是否已取消"""
        return self._cancel_flag.is_set()
    
    def is_paused(self) -> bool:
        """是否暂停"""
        return not self._pause_flag.is_set()
    
    def reset(self):
        """重置状态"""
        self._cancel_flag.clear()
        self._pause_flag.set()
    
    def download_file(self, item: DownloadItem, download_dir: str) -> bool:
        """下载单个文件"""
        item_id = item.item_id
        
        # 检查取消
        if self.is_cancelled():
            return False
        
        # 等待暂停恢复
        self._pause_flag.wait()
        
        # 构建本地路径
        local_path = os.path.join(download_dir, item.full_path)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        
        # 检查文件是否已存在
        if os.path.exists(local_path):
            size = os.path.getsize(local_path)
            if size > 0:
                item.status = DownloadStatus.SKIPPED
                if self.on_status_changed:
                    self.on_status_changed(item_id, DownloadStatus.SKIPPED)
                return True
        
        # 开始下载
        item.status = DownloadStatus.DOWNLOADING
        if self.on_status_changed:
            self.on_status_changed(item_id, DownloadStatus.DOWNLOADING)
        
        for attempt in range(self.retry_times + 1):
            if self.is_cancelled():
                return False
            
            try:
                resp = self.session.get(
                    item.url, 
                    stream=True, 
                    timeout=self.timeout
                )
                resp.raise_for_status()
                
                # 获取文件大小
                total_size = int(resp.headers.get("content-length", 0))
                item.size = total_size
                downloaded = 0
                
                with open(local_path, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if self.is_cancelled():
                            f.close()
                            return False
                        
                        self._pause_flag.wait()
                        
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            item.downloaded_size = downloaded
                            
                            if self.on_progress:
                                self.on_progress(item_id, downloaded, total_size)
                
                # 下载完成
                item.status = DownloadStatus.COMPLETED
                if self.on_status_changed:
                    self.on_status_changed(item_id, DownloadStatus.COMPLETED)
                if self.on_complete:
                    self.on_complete(item_id)
                return True
                
            except Exception as e:
                if attempt < self.retry_times:
                    time.sleep(2)
                    continue
                
                # 下载失败
                item.status = DownloadStatus.FAILED
                item.error_message = str(e)
                if self.on_status_changed:
                    self.on_status_changed(item_id, DownloadStatus.FAILED)
                if self.on_error:
                    self.on_error(item_id, str(e))
                return False
        
        return False
    
    def download_batch(
        self, 
        items: list, 
        download_dir: str,
        on_all_complete: Optional[Callable] = None
    ) -> DownloadStats:
        """批量下载"""
        stats = DownloadStats()
        stats.total_files = len(items)
        
        self.reset()
        
        for item in items:
            if self.is_cancelled():
                break
            
            success = self.download_file(item, download_dir)
            
            if success:
                if item.status == DownloadStatus.COMPLETED:
                    stats.completed += 1
                elif item.status == DownloadStatus.SKIPPED:
                    stats.skipped += 1
            else:
                stats.failed += 1
        
        if on_all_complete:
            on_all_complete(stats)
        
        return stats
    
    def close(self):
        """关闭session"""
        if self._session:
            self._session.close()
            self._session = None
```

---

## 文件2：src/services/scanner.py

```python
"""扫描服务"""
import re
import time
import threading
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote
from typing import List, Tuple, Optional, Callable
from ..models import DownloadItem, ItemType


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
                    time.sleep(2)
                    continue
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
```

---

## 文件3：src/services/__init__.py

```python
"""服务层"""
from .downloader import DownloadService
from .scanner import ScanService

__all__ = ['DownloadService', 'ScanService']
```

---

## 验证标准

1. 所有文件无语法错误
2. 下载服务支持取消和暂停
3. 扫描服务支持递归扫描
4. 回调函数正常工作

## 测试命令

```bash
python -c "from src.services import *; print('Services OK')"
```
