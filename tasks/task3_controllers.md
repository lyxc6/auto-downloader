# 任务3：控制器层 (Controllers)

## 任务描述
创建项目的控制器层，连接模型和视图，处理业务逻辑。

## 文件清单
- `src/controllers/__init__.py`
- `src/controllers/download_controller.py`
- `src/controllers/scan_controller.py`

## 技术要求
- 使用PySide6的信号槽机制
- 线程安全的操作
- 进度和状态回调

## 依赖
- 需要 `src/models` 模块
- 需要 `src/services` 模块

---

## 文件1：src/controllers/download_controller.py

```python
"""下载控制器"""
import os
import sys
import threading
from typing import List, Optional
from PySide6.QtCore import QObject, Signal, Slot

from ..models import DownloadItem, DownloadStatus, DownloadStats, AppConfig
from ..services import DownloadService


class DownloadController(QObject):
    """下载控制器"""
    
    # 信号定义
    progress_updated = Signal(str, int, int)  # item_id, downloaded, total
    status_changed = Signal(str, str)          # item_id, status
    error_occurred = Signal(str, str)          # item_id, error_message
    item_completed = Signal(str)               # item_id
    batch_completed = Signal(dict)             # stats_dict
    log_message = Signal(str, str)             # message, level
    
    def __init__(self, config: AppConfig, parent=None):
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
                self.log_message.emit(f"下载出错: {e}", "error")
            finally:
                with self._lock:
                    self._is_downloading = False
                if self._service:
                    self._service.close()
        
        self._thread = threading.Thread(target=_download_worker, daemon=True)
        self._thread.start()
    
    def cancel_download(self):
        """取消下载"""
        if self._service:
            self._service.cancel()
            self.log_message.emit("正在取消下载...", "warning")
    
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
```

---

## 文件2：src/controllers/scan_controller.py

```python
"""扫描控制器"""
import threading
from typing import Optional
from PySide6.QtCore import QObject, Signal, Slot

from ..models import DownloadItem, AppConfig, CacheManager
from ..services import ScanService


class ScanController(QObject):
    """扫描控制器"""
    
    # 信号定义
    item_found = Signal(object)                # DownloadItem
    scan_progress = Signal(int, int)           # current, total
    scan_completed = Signal(int, int)          # files, dirs
    scan_error = Signal(str)                   # error_message
    log_message = Signal(str, str)             # message, level
    
    def __init__(self, config: AppConfig, cache_manager: CacheManager, parent=None):
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
        
        # 设置回调
        service.on_item_found = lambda item: self.item_found.emit(item)
        service.on_error = lambda msg: self.scan_error.emit(msg)
        
        return service
    
    def start_scan(self, url: str, max_depth: Optional[int] = None):
        """开始扫描"""
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
        
        def _scan_worker():
            try:
                self._service = self._create_service()
                
                file_count = 0
                dir_count = 0
                
                def on_item_found(item: DownloadItem):
                    nonlocal file_count, dir_count
                    
                    # 添加到缓存
                    self.cache_manager.add_item(item)
                    
                    if item.is_file:
                        file_count += 1
                    else:
                        dir_count += 1
                    
                    # 发送进度
                    self.scan_progress.emit(file_count, dir_count)
                
                # 设置回调
                self._service.on_item_found = on_item_found
                
                # 执行扫描
                items = self._service.scan_directory(
                    url, max_depth=max_depth
                )
                
                # 扫描完成
                self.scan_completed.emit(file_count, dir_count)
                
                self.log_message.emit("", "info")
                self.log_message.emit("=" * 50, "header")
                self.log_message.emit(f"扫描完成！", "success")
                self.log_message.emit(f"文件: {file_count}, 目录: {dir_count}", "info")
                self.log_message.emit("=" * 50, "header")
                
                # 保存缓存
                self.cache_manager.save(url)
                
            except Exception as e:
                self.scan_error.emit(str(e))
                self.log_message.emit(f"扫描失败: {e}", "error")
            finally:
                with self._lock:
                    self._is_scanning = False
                if self._service:
                    self._service.close()
        
        self._thread = threading.Thread(target=_scan_worker, daemon=True)
        self._thread.start()
    
    def cancel_scan(self):
        """取消扫描"""
        if self._service:
            self._service.cancel()
            self.log_message.emit("正在取消扫描...", "warning")
```

---

## 文件3：src/controllers/__init__.py

```python
"""控制器层"""
from .download_controller import DownloadController
from .scan_controller import ScanController

__all__ = ['DownloadController', 'ScanController']
```

---

## 验证标准

1. 所有文件无语法错误
2. 信号槽正确连接
3. 线程安全操作
4. 回调正常工作

## 测试命令

```bash
python -c "from src.controllers import *; print('Controllers OK')"
```
