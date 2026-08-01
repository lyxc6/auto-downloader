"""文件大小预取器：扫描完成后并行 HEAD 预取文件大小"""

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..models import CacheManager, DownloadItem
from ..services.http_client import HttpClient

logger = logging.getLogger(__name__)


class SizePrefetcher:
    """扫描完成后，并行发送 HEAD 请求预取文件大小"""

    def __init__(self, cache_manager: CacheManager, log: Callable[[str, str], None]):
        self._cache = cache_manager
        self._log = log
        self._cancel_flag = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        """是否正在预取"""
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        max_workers: int = 5,
        dir_path: str = "",
        on_progress: Callable[[str, int], None] | None = None,
        on_completed: Callable[[], None] | None = None,
    ) -> None:
        """开始预取

        Args:
            max_workers: 并行线程数
            dir_path: 指定目录路径（空=预取全部，非空=只预取该目录下的文件）
            on_progress: (item_id, size) 进度回调
            on_completed: 全部完成回调
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
            http_client = HttpClient()
            try:

                def head_one(item: DownloadItem) -> tuple[str, int | None]:
                    if self._cancel_flag.is_set():
                        return (item.item_id, None)
                    size = http_client.head_file_size(item.url, retries=2)
                    return (item.item_id, size)

                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {executor.submit(head_one, item): item for item in files_to_prefetch}
                    for future in as_completed(futures):
                        if self._cancel_flag.is_set():
                            executor.shutdown(wait=False, cancel_futures=True)
                            break
                        item_id, size = future.result()
                        completed += 1
                        if size is not None and size > 0:
                            self._cache.update_item_size(item_id, size)
                            if on_progress:
                                on_progress(item_id, size)
                        if completed % 20 == 0 or completed == total:
                            self._log(f"正在获取文件大小... ({completed}/{total})", "info")
            except Exception as e:
                logger.error("文件大小预取失败", exc_info=True)
                self._log(f"文件大小预取失败: {e}", "error")
            finally:
                http_client.close()
                self._cache.save()
                if on_completed:
                    on_completed()

        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        """取消预取"""
        self._cancel_flag.set()
