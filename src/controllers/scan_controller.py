"""扫描控制器"""
import logging
import threading
from time import monotonic
from typing import Optional, Set
from PySide6.QtCore import QObject, Signal

from ..models import DownloadItem, AppConfig, CacheManager
from ..services import ScanService

logger = logging.getLogger(__name__)


class ScanController(QObject):
    """扫描控制器"""
    
    # 信号定义
    items_found = Signal(list)               # List[DownloadItem]（批量）
    scan_progress = Signal(int, int)         # current, total
    scan_completed = Signal(int, int)        # files, dirs
    scan_error = Signal(str)                 # error_message
    log_message = Signal(str, str)           # message, level
    
    def __init__(self, config: AppConfig, cache_manager: CacheManager, parent: QObject | None = None):
        super().__init__(parent)
        self.config = config
        self.cache_manager = cache_manager
        self._service: Optional[ScanService] = None
        self._thread: Optional[threading.Thread] = None
        self._is_scanning = False
        self._lock = threading.Lock()
    
    @property
    def is_scanning(self) -> bool:
        """是否正在扫描"""
        with self._lock:
            return self._is_scanning
    
    def _create_service(self) -> ScanService:
        """创建扫描服务"""
        service = ScanService()
        
        # 设置回调（on_item_found 在 start_scan 中按批次覆盖）
        service.on_error = lambda msg: self.scan_error.emit(msg)
        service.on_log = lambda msg, level: self.log_message.emit(msg, level)
        
        return service
    
    def start_scan(self, url: str, max_depth: Optional[int] = None, scanned_dirs: Optional[Set[str]] = None, scan_mode: str = "dfs"):
        """开始扫描
        
        Args:
            url: 扫描目标 URL
            max_depth: 最大递归深度
            scanned_dirs: 已扫描目录集合（续扫时跳过这些目录）
            scan_mode: 扫描模式 "dfs" 深度优先 / "bfs" 广度优先
        """
        with self._lock:
            if self._is_scanning:
                self.log_message.emit("扫描已在进行中", "warning")
                return
            self._is_scanning = True
        
        if max_depth is None:
            max_depth = self.config.max_depth
        
        self.log_message.emit("=" * 50, "header")
        self.log_message.emit("开始扫描目录结构", "header")
        self.log_message.emit("=" * 50, "header")
        
        logger.info("开始扫描: %s (深度=%d)", url, max_depth)
        
        def _scan_worker():
            try:
                self._service = self._create_service()
                
                # 续扫：传入已扫描目录集合
                if scanned_dirs:
                    self._service.set_scanned_dirs(scanned_dirs)
                
                file_count = 0
                dir_count = 0
                buffer: list[DownloadItem] = []
                last_flush = monotonic()
                BATCH_SIZE = 50
                FLUSH_INTERVAL = 0.1
                
                def on_item_found(item: DownloadItem):
                    nonlocal file_count, dir_count, last_flush, buffer
                    
                    # 续扫去重：已存在的 item 不重复计数/不重复入 buffer
                    if self.cache_manager.has_item(item.item_id):
                        self.cache_manager.add_item(item)
                        return
                    
                    # 添加到缓存
                    self.cache_manager.add_item(item)
                    
                    if item.is_file:
                        file_count += 1
                    else:
                        dir_count += 1
                    
                    buffer.append(item)
                    
                    if len(buffer) >= BATCH_SIZE or (monotonic() - last_flush) >= FLUSH_INTERVAL:
                        self.items_found.emit(buffer)
                        self.scan_progress.emit(file_count, dir_count)
                        buffer = []
                        last_flush = monotonic()
                
                # 设置回调
                self._service.on_item_found = on_item_found
                self._service.on_dir_scanned = lambda dp: self.cache_manager.mark_dir_scanned(dp)
                
                # 执行扫描
                if scan_mode == "bfs":
                    _ = self._service.scan_directory_bfs(
                        url, max_depth=max_depth
                    )
                else:
                    _ = self._service.scan_directory(
                        url, max_depth=max_depth
                    )
                
                # flush 剩余 buffer
                if buffer:
                    self.items_found.emit(buffer)
                    self.scan_progress.emit(file_count, dir_count)
                    buffer = []
                
                # 标记扫描完成状态（仅在未取消时）
                if not self._service.is_cancelled():
                    self.cache_manager.set_scan_complete(True)
                
                # 扫描完成
                self.scan_completed.emit(file_count, dir_count)
                
                logger.info("扫描完成: 文件=%d 目录=%d", file_count, dir_count)
                
                self.log_message.emit("", "info")
                self.log_message.emit("=" * 50, "header")
                self.log_message.emit(f"扫描完成！", "success")
                self.log_message.emit(f"文件: {file_count}, 目录: {dir_count}", "info")
                self.log_message.emit("=" * 50, "header")
                
                # 保存缓存
                self.cache_manager.save()
                
            except Exception as e:
                logger.error("扫描失败", exc_info=True)
                self.scan_error.emit(str(e))
                self.log_message.emit(f"扫描失败: {e}", "error")
            finally:
                with self._lock:
                    self._is_scanning = False
                    if self._service is not None:
                        self._service.close()
                        self._service = None

        self._thread = threading.Thread(target=_scan_worker, daemon=True)
        self._thread.start()

    def start_directory_scan(self, base_url: str, dir_path: str, parent_id: str):
        """扫描单个目录（不递归到根，只扫描指定目录及其子目录）

        Args:
            base_url: 根 URL（如 https://example.com/index.php/224.html）
            dir_path: 要扫描的目录路径（如 写真）
            parent_id: 该目录的父 item_id
        """
        with self._lock:
            if self._is_scanning:
                self.log_message.emit("扫描已在进行中", "warning")
                return
            self._is_scanning = True

        self.log_message.emit(f"刷新目录: {dir_path or '/'}", "header")
        logger.info("开始单目录扫描: %s (dir=%s)", base_url, dir_path)

        def _dir_scan_worker():
            try:
                self._service = self._create_service()

                file_count = 0
                dir_count = 0
                buffer: list[DownloadItem] = []
                last_flush = monotonic()
                BATCH_SIZE = 50
                FLUSH_INTERVAL = 0.1

                def on_item_found(item: DownloadItem):
                    nonlocal file_count, dir_count, last_flush, buffer
                    if self.cache_manager.has_item(item.item_id):
                        self.cache_manager.add_item(item)
                        return
                    self.cache_manager.add_item(item)
                    if item.is_file:
                        file_count += 1
                    else:
                        dir_count += 1
                    buffer.append(item)
                    if len(buffer) >= BATCH_SIZE or (monotonic() - last_flush) >= FLUSH_INTERVAL:
                        self.items_found.emit(buffer)
                        self.scan_progress.emit(file_count, dir_count)
                        buffer = []
                        last_flush = monotonic()

                self._service.on_item_found = on_item_found
                self._service.on_dir_scanned = lambda dp: self.cache_manager.mark_dir_scanned(dp)

                self._service.scan_directory(
                    base_url, dir_path=dir_path, parent_id=parent_id,
                    depth=0, max_depth=self.config.max_depth
                )

                if buffer:
                    self.items_found.emit(buffer)
                    self.scan_progress.emit(file_count, dir_count)
                    buffer = []

                self.scan_completed.emit(file_count, dir_count)
                logger.info("单目录扫描完成: 文件=%d 目录=%d", file_count, dir_count)

                self.log_message.emit(f"目录刷新完成: 文件 {file_count}, 目录 {dir_count}", "success")
                self.cache_manager.save()

            except Exception as e:
                logger.error("目录扫描失败", exc_info=True)
                self.scan_error.emit(str(e))
                self.log_message.emit(f"目录扫描失败: {e}", "error")
            finally:
                with self._lock:
                    self._is_scanning = False
                    if self._service is not None:
                        self._service.close()
                        self._service = None

        self._thread = threading.Thread(target=_dir_scan_worker, daemon=True)
        self._thread.start()

    def cancel_scan(self):
        """取消扫描"""
        if self._service:
            self._service.cancel()
            logger.warning("用户取消扫描")
            self.log_message.emit("正在取消扫描...", "warning")

    def close_service(self):
        """关闭扫描服务（线程安全，可在应用关闭时调用）"""
        with self._lock:
            if self._service is not None:
                self._service.close()
                self._service = None
