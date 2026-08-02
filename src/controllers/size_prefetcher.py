"""文件大小预取器：扫描过程中增量提交文件，并行 HEAD 预取文件大小（方案B：边扫边取）

与扫描合并的增量模式：
- start() 启动消费线程，并把缓存中已有 size<=0 的文件兜底入队
- submit(item) 由扫描线程在发现文件时调用（线程安全）
- done() 由扫描线程在扫描结束后调用，队列耗尽后发 completed
- cancel() 取消（扫描取消/超时时调用）
"""

import logging
import queue
import threading
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

import shiboken6
from PySide6.QtCore import QObject, Signal

from ..models import CacheManager, DownloadItem
from ..services.http_client import HttpClient

logger = logging.getLogger(__name__)

# 单次批量提交的文件数（有界窗口，避免一次性提交全部 futures 的内存放大）
BATCH_SIZE = 50
# 每批处理完毕后的取消/进度检查间隔
WINDOW_CHECK_INTERVAL = 0.05


class SizePrefetcher(QObject):
    """扫描过程中增量预取文件大小（边扫边取）"""

    progress = Signal(str, int)  # item_id, size（每完成一个文件）
    completed = Signal()  # 全部完成

    def __init__(self, cache_manager: CacheManager, log: Callable[[str, str], None], parent: QObject | None = None):
        super().__init__(parent)
        self._cache = cache_manager
        self._log = log
        self._cancel_flag = threading.Event()
        self._done_flag = threading.Event()  # 扫描已结束，不再有新文件入队
        self._queue: queue.Queue[DownloadItem] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._max_workers = 5  # 惰性启动时使用的并行线程数(由 start 覆盖)
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
        """启动预取消费线程（幂等：已在运行时忽略）

        Args:
            max_workers: 并行线程数
            dir_path: 指定目录路径（空=兜底收集全部，非空=只兜底收集该目录下的文件）
        """
        if self.is_running:
            logger.info("文件大小预取已在运行，忽略 start")
            return
        self._max_workers = max_workers

        # 兜底收集：缓存中已有 size<=0 的文件（缓存恢复/续扫场景）
        # 防御：缓存实现可能不提供 get_all_items（如测试替身），跳过兜底不阻塞扫描
        get_all = getattr(self._cache, "get_all_items", None)
        files_to_prefetch = []
        if callable(get_all):
            files_to_prefetch = [
                item
                for item in get_all()
                if item.is_file
                and item.size <= 0
                and item.url
                and (not dir_path or item.full_path.startswith(dir_path + "/"))
            ]
        for item in files_to_prefetch:
            self._queue.put(item)

        self._cancel_flag.clear()
        self._done_flag.clear()
        total = len(files_to_prefetch)
        if total:
            self._safe_log(f"正在获取文件大小... (0/{total})", "info")
            self._ensure_thread_started(max_workers)

    def _ensure_thread_started(self, max_workers: int) -> None:
        """惰性启动消费线程（仅在有实际待取文件时启动，避免空转线程残留）"""
        if self.is_running:
            return
        self._thread = threading.Thread(target=self._worker, args=(max_workers,), daemon=True)
        self._thread.start()

    def submit(self, item: DownloadItem) -> None:
        """扫描过程中提交新发现的文件（线程安全，首次提交时惰性启动线程）

        Args:
            item: 文件项（仅处理 is_file）
        """
        if self._cancel_flag.is_set() or self._done_flag.is_set():
            return
        if not item.is_file or not item.url or item.size > 0:
            return
        self._queue.put(item)
        self._ensure_thread_started(self._max_workers)

    def done(self) -> None:
        """标记扫描结束：队列耗尽后发 completed（幂等）"""
        self._done_flag.set()

    def _safe_log(self, message: str, level: str = "info") -> None:
        """安全日志：QObject 已销毁（测试收尾/应用关闭）时静默忽略"""
        try:
            self._log(message, level)
        except RuntimeError:
            pass

    def _safe_progress(self, item_id: str, size: int) -> None:
        """安全进度信号：QObject 已销毁时静默忽略"""
        try:
            self.progress.emit(item_id, size)
        except RuntimeError:
            pass

    def _safe_completed(self) -> None:
        """安全完成信号：QObject 已销毁时静默忽略"""
        try:
            self.completed.emit()
        except RuntimeError:
            pass

    def _object_alive(self) -> bool:
        """检测 Qt C++ 对象是否仍有效

        QApplication 销毁后 QObject 的 C++ 部分会被删除，Python 包装对象
        仍存活但无法 emit。线程在对象失效后必须尽快退出，否则跨测试/关闭
        场景会抛 "Signal source has been deleted" 污染事件循环。
        """
        try:
            return shiboken6.isValid(self)
        except Exception:
            return False

    def _worker(self, max_workers: int) -> None:
        """消费线程：有界窗口并行 HEAD，队列耗尽 + done 后退出"""
        completed = 0
        total_known = 0
        try:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures: dict = {}

                def head_one(item: DownloadItem) -> tuple[str, int | None]:
                    if self._cancel_flag.is_set():
                        return (item.item_id, None)
                    client = self._get_client()
                    size = client.head_file_size(item.url, retries=2)
                    return (item.item_id, size)

                while True:
                    # 取消或宿主 QObject 已销毁 → 退出
                    if self._cancel_flag.is_set() or not self._object_alive():
                        break

                    # 补足窗口
                    while len(futures) < max_workers:
                        try:
                            item = self._queue.get(timeout=WINDOW_CHECK_INTERVAL)
                        except queue.Empty:
                            break
                        futures[executor.submit(head_one, item)] = item
                        total_known += 1

                    # 队列空且已 done 且无在飞 → 结束
                    if not futures and self._done_flag.is_set() and self._queue.empty():
                        break

                    if not futures:
                        continue

                    done_set, _ = wait(futures, timeout=WINDOW_CHECK_INTERVAL, return_when=FIRST_COMPLETED)
                    if not done_set:
                        continue

                    for future in done_set:
                        futures.pop(future)
                        item_id, size = future.result()
                        completed += 1
                        if size is not None and size > 0:
                            self._cache.update_item_size(item_id, size)
                            self._safe_progress(item_id, size)
                        if completed % 20 == 0 or (self._done_flag.is_set() and completed == total_known):
                            self._safe_log(f"正在获取文件大小... ({completed}/{total_known})", "info")
        except Exception as e:
            logger.error("文件大小预取失败", exc_info=True)
            self._safe_log(f"文件大小预取失败: {e}", "error")
        finally:
            self._close_all_clients()
            try:
                self._cache.save()
            except Exception:
                logger.exception("预取完成时保存缓存失败")
            self._safe_completed()

    def _close_all_clients(self):
        """关闭本线程池创建的所有 HttpClient"""
        client = getattr(self._client_local, "client", None)
        if client is not None:
            client.close()
            self._client_local.client = None

    def cancel(self) -> None:
        """取消预取（扫描取消/超时时调用）"""
        self._cancel_flag.set()
        # 清空队列，让消费线程尽快退出
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
