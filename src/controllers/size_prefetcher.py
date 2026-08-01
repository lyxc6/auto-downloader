"""文件大小预取器：扫描完成后并行 HEAD 预取文件大小"""

import logging
import threading
from collections import deque
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from PySide6.QtCore import QObject, Signal

from ..models import CacheManager, DownloadItem
from ..services.http_client import HttpClient

logger = logging.getLogger(__name__)

# 单次批量提交的文件数（有界窗口，避免一次性提交全部 futures 的内存放大）
BATCH_SIZE = 50
# 每批处理完毕后的取消/进度检查间隔
WINDOW_CHECK_INTERVAL = 0.05


class SizePrefetcher(QObject):
    """扫描完成后，并行发送 HEAD 请求预取文件大小"""

    progress = Signal(str, int)  # item_id, size（每完成一个文件）
    completed = Signal()  # 全部完成

    def __init__(self, cache_manager: CacheManager, log: Callable[[str, str], None], parent: QObject | None = None):
        super().__init__(parent)
        self._cache = cache_manager
        self._log = log
        self._cancel_flag = threading.Event()
        self._thread: threading.Thread | None = None
        # 每线程独立 HttpClient（requests.Session 非线程安全）
        self._client_local = threading.local()

    def _get_client(self) -> HttpClient:
        """获取当前线程的 HttpClient（每线程独立实例）"""
        client = getattr(self._client_local, "client", None)
        if client is None:
            client = HttpClient()
            self._client_local.client = client
        return client

    @property
    def is_running(self) -> bool:
        """是否正在预取"""
        return self._thread is not None and self._thread.is_alive()

    def start(self, max_workers: int = 5, dir_path: str = "") -> None:
        """开始预取

        Args:
            max_workers: 并行线程数
            dir_path: 指定目录路径（空=预取全部，非空=只预取该目录下的文件）
        """
        # 防重复：如果已有 prefetch 在运行，先取消它
        thread = self._thread
        if thread is not None and thread.is_alive():
            logger.info("取消正在运行的文件大小预取任务")
            self.cancel()
            thread.join(timeout=2)

        # 收集需要预取大小的文件
        files_to_prefetch = [
            item
            for item in self._cache.get_all_items()
            if item.is_file
            and item.size <= 0
            and item.url
            and (not dir_path or item.full_path.startswith(dir_path + "/"))
        ]

        if not files_to_prefetch:
            return

        self._cancel_flag.clear()
        total = len(files_to_prefetch)
        self._log(f"正在获取文件大小... (0/{total})", "info")

        def _worker():
            completed = 0
            pending = deque(files_to_prefetch)
            try:
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # 有界窗口：最多在飞 max_workers 个 future，按批补足
                    futures = {}

                    def head_one(item: DownloadItem) -> tuple[str, int | None]:
                        if self._cancel_flag.is_set():
                            return (item.item_id, None)
                        client = self._get_client()
                        size = client.head_file_size(item.url, retries=2)
                        return (item.item_id, size)

                    while (pending or futures) and not self._cancel_flag.is_set():
                        # 补足窗口
                        while len(futures) < max_workers and pending:
                            item = pending.popleft()
                            futures[executor.submit(head_one, item)] = item

                        if not futures:
                            break

                        done_set, _ = wait(futures, timeout=WINDOW_CHECK_INTERVAL, return_when=FIRST_COMPLETED)
                        if not done_set:
                            continue

                        for future in done_set:
                            futures.pop(future)
                            item_id, size = future.result()
                            completed += 1
                            if size is not None and size > 0:
                                self._cache.update_item_size(item_id, size)
                                self.progress.emit(item_id, size)
                            if completed % 20 == 0 or completed == total:
                                self._log(f"正在获取文件大小... ({completed}/{total})", "info")
            except Exception as e:
                logger.error("文件大小预取失败", exc_info=True)
                self._log(f"文件大小预取失败: {e}", "error")
            finally:
                self._close_all_clients()
                self._cache.save()
                self.completed.emit()

        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()

    def _close_all_clients(self):
        """关闭本线程池创建的所有 HttpClient"""
        client = getattr(self._client_local, "client", None)
        if client is not None:
            client.close()
            self._client_local.client = None

    def cancel(self) -> None:
        """取消预取"""
        self._cancel_flag.set()
