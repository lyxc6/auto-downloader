"""下载控制器"""
import logging
import os
import sys
import threading
from typing import List, Optional
from PySide6.QtCore import QObject, Signal

from ..models import DownloadItem, AppConfig
from ..services import DownloadService

logger = logging.getLogger(__name__)


class DownloadController(QObject):
    """下载控制器"""
    
    # 信号定义
    progress_updated = Signal(str, int, int)  # item_id, downloaded, total
    status_changed = Signal(str, str)          # item_id, status
    error_occurred = Signal(str, str)          # item_id, error_message
    item_completed = Signal(str)               # item_id
    batch_completed = Signal(dict)             # stats_dict
    log_message = Signal(str, str)             # message, level
    
    def __init__(self, config: AppConfig, parent: QObject | None = None):
        super().__init__(parent)
        self.config = config
        self._service: Optional[DownloadService] = None
        self._thread: Optional[threading.Thread] = None
        self._is_downloading = False
        self._lock = threading.Lock()
    
    @property
    def is_downloading(self) -> bool:
        """是否正在下载"""
        with self._lock:
            return self._is_downloading
    
    def _get_download_dir(self) -> str:
        """获取下载目录"""
        if getattr(sys, 'frozen', False):
            return os.path.join(os.path.dirname(sys.executable), self.config.download_dir)
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            self.config.download_dir
        )
    
    def _create_service(self) -> DownloadService:
        """创建下载服务"""
        service = DownloadService(
            max_workers=self.config.max_workers,
            retry_times=self.config.retry_times,
            timeout=self.config.timeout
        )
        
        # 设置回调
        service.on_progress = lambda id, dl, total: self.progress_updated.emit(id, dl, total)
        service.on_status_changed = lambda id, status: self.status_changed.emit(id, status.value)
        service.on_error = lambda id, msg: self.error_occurred.emit(id, msg)
        service.on_complete = lambda id: self.item_completed.emit(id)
        
        return service
    
    def start_download(self, items: List[DownloadItem]):
        """开始下载"""
        with self._lock:
            if self._is_downloading:
                self.log_message.emit("下载已在进行中", "warning")
                return
            self._is_downloading = True
        
        download_dir = self._get_download_dir()
        os.makedirs(download_dir, exist_ok=True)
        
        logger.info("开始下载 %d 个文件 -> %s", len(items), download_dir)
        self.log_message.emit(f"开始下载 {len(items)} 个文件", "info")
        self.log_message.emit(f"下载目录: {download_dir}", "info")
        
        def _download_worker():
            try:
                self._service = self._create_service()
                stats = self._service.download_batch(items, download_dir)
                
                # 发送完成信号
                self.batch_completed.emit(stats.to_dict())
                
                self.log_message.emit("", "info")
                self.log_message.emit("=" * 50, "header")
                self.log_message.emit(f"下载完成！", "success")
                self.log_message.emit(
                    f"成功: {stats.completed}, 失败: {stats.failed}, 跳过: {stats.skipped}",
                    "info"
                )
                self.log_message.emit("=" * 50, "header")
                
            except Exception as e:
                logger.error("下载出错", exc_info=True)
                self.log_message.emit(f"下载出错: {e}", "error")
            finally:
                with self._lock:
                    self._is_downloading = False
                    if self._service is not None:
                        self._service.close()
                        self._service = None

        self._thread = threading.Thread(target=_download_worker, daemon=True)
        self._thread.start()

    def cancel_download(self):
        """取消下载"""
        if self._service:
            self._service.cancel()
            logger.warning("用户取消下载")
            self.log_message.emit("正在取消下载...", "warning")

    def close_service(self):
        """关闭下载服务（线程安全，可在应用关闭时调用）"""
        with self._lock:
            if self._service is not None:
                self._service.close()
                self._service = None
    
    def pause_download(self):
        """暂停下载"""
        if self._service:
            self._service.pause()
            self.log_message.emit("下载已暂停", "warning")
    
    def resume_download(self):
        """恢复下载"""
        if self._service:
            self._service.resume()
            self.log_message.emit("下载已恢复", "info")
