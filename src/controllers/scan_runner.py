"""扫描工作线程运行器：批处理节流 + 进度日志 + 缓存同步"""

import logging
import threading
from collections.abc import Callable
from time import monotonic as _default_clock

from ..models import CacheManager, DownloadItem

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
FLUSH_INTERVAL = 0.1
PROGRESS_LOG_INTERVAL = 0.3
PROGRESS_DIR_INTERVAL = 5


class ScanRunner:
    """扫描工作线程体

    替代原先写在 worker 闭包内的计数/批处理/进度日志逻辑，用实例状态管理。
    clock 可注入（测试用），默认使用 time.monotonic。
    """

    def __init__(self, cache_manager: CacheManager, clock: Callable[[], float] | None = None):
        self._cache = cache_manager
        self._clock = clock or _default_clock
        self._cb_lock = threading.Lock()

        # 节流状态
        self._buffer: list[DownloadItem] = []
        self._last_flush = 0.0
        self._last_progress_log = 0.0
        self.file_count = 0
        self.dir_count = 0
        self.dirs_found = 0
        self.dirs_completed = 0

        # 回调（由控制器注入）
        self.on_item_found_batch: Callable[[list[DownloadItem]], None] | None = None
        self.on_progress: Callable[[int, int], None] | None = None
        self.on_log: Callable[[str, str], None] | None = None
        self.on_dir_scanned: Callable[[str], None] | None = None

    def _log(self, message: str, level: str = "info") -> None:
        if self.on_log:
            self.on_log(message, level)

    def handle_item(self, item: DownloadItem) -> None:
        """service.on_item_found 回调：缓存去重 + 计数 + 批量节流"""
        # 续扫去重：原子检查+添加，已存在的 item 不覆盖（避免并行竞态损坏 parent_id）
        if not self._cache.try_add_item(item):
            return

        # 发现目录时标记为未完成（扫描完成后会由 on_dir_scanned 标记为已完成）
        if item.is_dir:
            self._cache.mark_dir_unscanned(item.full_path)

        with self._cb_lock:
            if item.is_file:
                self.file_count += 1
            else:
                self.dir_count += 1
                self.dirs_found += 1

            self._buffer.append(item)

            if len(self._buffer) >= BATCH_SIZE or (self._clock() - self._last_flush) >= FLUSH_INTERVAL:
                self._drain_locked()

    def flush(self) -> None:
        """发射缓冲批量并更新进度（无缓冲时为空操作）"""
        with self._cb_lock:
            self._drain_locked()

    def _drain_locked(self) -> None:
        """发射缓冲批量（调用方必须持有 _cb_lock）"""
        if not self._buffer:
            return
        items = list(self._buffer)
        files, dirs = self.file_count, self.dir_count
        self._buffer = []
        self._last_flush = self._clock()

        if self.on_item_found_batch:
            self.on_item_found_batch(items)
        if self.on_progress:
            self.on_progress(files, dirs)

    def handle_dir_scanned(self, dir_path: str) -> None:
        """service.on_dir_scanned 回调：标记缓存 + 节流输出扫描进度"""
        self._cache.mark_dir_scanned(dir_path)
        if self.on_dir_scanned:
            self.on_dir_scanned(dir_path)

        with self._cb_lock:
            self.dirs_completed += 1
            now = self._clock()
            if (
                self.dirs_completed % PROGRESS_DIR_INTERVAL == 0
                or (now - self._last_progress_log) >= PROGRESS_LOG_INTERVAL
            ):
                if self.dirs_found > 0:
                    percent = (self.dirs_completed / self.dirs_found) * 100
                    self._log(
                        f"扫描进度: {self.dirs_completed}/{self.dirs_found} 个目录 ({percent:.1f}%)"
                        f" | 发现 {self.file_count} 个文件",
                        "info",
                    )
                else:
                    self._log(
                        f"扫描进度: 已完成 {self.dirs_completed} 个目录 | 发现 {self.file_count} 个文件",
                        "info",
                    )
                self._last_progress_log = now
