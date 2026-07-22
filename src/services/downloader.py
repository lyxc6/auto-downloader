"""下载服务"""
import logging
import os
import time
import threading
import requests
from typing import Callable, Optional
from ..models import DownloadItem, DownloadStatus, DownloadStats

logger = logging.getLogger(__name__)


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
                    logger.warning("下载重试 %d/%d: %s -> %s", attempt + 1, self.retry_times, item.name, e)
                    time.sleep(2)
                    continue
                
                # 下载失败
                logger.error("下载失败: %s -> %s", item.name, e)
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
