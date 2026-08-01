"""下载服务"""

import logging
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from ..models import DownloadItem, DownloadStats, DownloadStatus
from .http_client import fetch_file_info

logger = logging.getLogger(__name__)

CHUNK_SIZE = 65536  # 流式写入块大小（64KB）
RETRY_SLEEP = 2.0  # 重试间隔（秒）


class DownloadService:
    """下载服务"""

    def __init__(self, max_workers: int = 3, retry_times: int = 3, timeout: int = 120):
        self.max_workers = max_workers
        self.retry_times = retry_times
        self.timeout = timeout
        self._session: requests.Session | None = None
        self._cancel_flag = threading.Event()
        self._pause_flag = threading.Event()
        self._pause_flag.set()  # 初始为非暂停状态
        self._lock = threading.Lock()

        # 回调函数
        self.on_progress: Callable[[str, int, int], None] | None = None  # item_id, downloaded, total
        self.on_status_changed: Callable[[str, DownloadStatus], None] | None = None
        self.on_error: Callable[[str, str], None] | None = None
        self.on_complete: Callable[[str], None] | None = None

    @property
    def session(self) -> requests.Session:
        """获取或创建session"""
        with self._lock:
            if self._session is None:
                self._session = requests.Session()
                self._session.headers.update(
                    {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                )
            return self._session

    def cancel(self):
        """取消下载（同时解除暂停阻塞，使等待中的下载立即退出）"""
        self._cancel_flag.set()
        self._pause_flag.set()

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

    def _set_status(self, item: DownloadItem, status: DownloadStatus, error_msg: str = "") -> None:
        """更新状态并通知（统一状态变更入口）"""
        item.status = status
        if error_msg:
            item.error_message = error_msg
        if self.on_status_changed:
            self.on_status_changed(item.item_id, status)

    def _get_remote_size_and_ranges(self, url: str):
        """获取远端文件大小与是否支持 Range

        Returns:
            (content_length, accept_ranges) 或 (None, None)
        """
        return fetch_file_info(self.session, url, self.timeout)

    def _decide_resume(self, item: DownloadItem, local_path: str) -> tuple[int, bool]:
        """处理已存在文件：校验完整性，决定续传/跳过/重下

        Args:
            item: 下载项
            local_path: 本地文件路径

        Returns:
            (resume_from, should_skip)：resume_from 为断点偏移（0=全新下载），should_skip 表示直接跳过
        """
        if not os.path.exists(local_path):
            return 0, False

        local_size = os.path.getsize(local_path)
        if local_size <= 0:
            return 0, False

        remote_size, accept_ranges = self._get_remote_size_and_ranges(item.url)
        if remote_size is None:
            # 无 Content-Length，无法校验，保持跳过
            item.size = local_size
            self._set_status(item, DownloadStatus.SKIPPED)
            return 0, True
        if local_size == remote_size:
            # 完整，跳过
            item.size = local_size
            item.downloaded_size = local_size
            self._set_status(item, DownloadStatus.SKIPPED)
            return 0, True
        if local_size < remote_size and accept_ranges and "bytes" in accept_ranges.lower():
            # 断点续传
            item.size = remote_size
            item.downloaded_size = local_size
            return local_size, False

        # 损坏(本地>远端)或不支持 Range，删除重下
        try:
            os.remove(local_path)
        except OSError:
            pass
        return 0, False

    def _download_with_retry(self, item: DownloadItem, local_path: str, resume_from: int) -> bool:
        """流式下载（带重试与续传）

        Args:
            item: 下载项
            local_path: 本地文件路径
            resume_from: 断点偏移

        Returns:
            True 表示下载成功，False 表示失败/取消
        """
        for attempt in range(self.retry_times + 1):
            if self.is_cancelled():
                self._set_status(item, DownloadStatus.CANCELLED)
                return False

            # 续传模式下，每次重试根据当前文件实际大小重新计算断点
            if resume_from > 0 and os.path.exists(local_path):
                resume_from = os.path.getsize(local_path)

            resp = None
            try:
                headers: dict[str, str] = {}
                mode = "wb"
                start_downloaded = 0
                if resume_from > 0:
                    headers["Range"] = f"bytes={resume_from}-"
                    mode = "ab"
                    start_downloaded = resume_from

                resp = self.session.get(
                    item.url,
                    stream=True,
                    timeout=self.timeout,
                    headers=headers,
                )
                resp.raise_for_status()

                # 服务器忽略 Range 返回 200：覆盖重下
                if resume_from > 0 and resp.status_code == 200:
                    mode = "wb"
                    start_downloaded = 0
                    resume_from = 0

                # 计算总大小
                cl = int(resp.headers.get("content-length", 0))
                if resp.status_code == 206 and start_downloaded > 0:
                    total_size = cl + start_downloaded
                elif cl > 0:
                    total_size = cl
                else:
                    total_size = item.size
                item.size = total_size
                downloaded = start_downloaded

                with open(local_path, mode) as f:
                    for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                        if self.is_cancelled():
                            self._set_status(item, DownloadStatus.CANCELLED)
                            return False

                        self._pause_flag.wait()

                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            item.downloaded_size = downloaded

                            if self.on_progress:
                                self.on_progress(item.item_id, downloaded, total_size)

                # 下载完成
                self._set_status(item, DownloadStatus.COMPLETED)
                if self.on_complete:
                    self.on_complete(item.item_id)
                return True

            except Exception as e:
                if attempt < self.retry_times:
                    logger.warning("下载重试 %d/%d: %s -> %s", attempt + 1, self.retry_times, item.name, e)
                    time.sleep(RETRY_SLEEP)
                    continue

                # 下载失败
                logger.error("下载失败: %s -> %s", item.name, e)
                self._set_status(item, DownloadStatus.FAILED, str(e))
                if self.on_error:
                    self.on_error(item.item_id, str(e))
                return False
            finally:
                if resp is not None:
                    resp.close()

        return False

    def download_file(self, item: DownloadItem, download_dir: str) -> bool:
        """下载单个文件"""
        # 检查取消
        if self.is_cancelled():
            self._set_status(item, DownloadStatus.CANCELLED)
            return False

        # 等待暂停恢复
        self._pause_flag.wait()
        if self.is_cancelled():
            self._set_status(item, DownloadStatus.CANCELLED)
            return False

        # 构建本地路径
        local_path = os.path.join(download_dir, item.full_path)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        # 处理已存在文件：校验完整性，必要时续传/重下
        resume_from, should_skip = self._decide_resume(item, local_path)
        if should_skip:
            return True

        # 开始下载
        self._set_status(item, DownloadStatus.DOWNLOADING)
        return self._download_with_retry(item, local_path, resume_from)

    def download_batch(
        self,
        items: list[DownloadItem],
        download_dir: str,
        on_all_complete: Callable[[DownloadStats], None] | None = None,
    ) -> DownloadStats:
        """批量下载（并发，并发度由 max_workers 控制）"""
        stats = DownloadStats()
        stats.total_files = len(items)

        self.reset()

        # 每个 worker 操作 item 的轻量副本（仅复制下载所需字段），
        # 避免与 GUI 线程共享状态撕裂读，也避免 deepcopy 全量复制开销
        def worker(item: DownloadItem):
            local_item = DownloadItem(
                item_id=item.item_id,
                name=item.name,
                url=item.url,
                item_type=item.item_type,
                parent_id=item.parent_id,
                full_path=item.full_path,
                size=item.size,
            )
            success = self.download_file(local_item, download_dir)
            return item.item_id, success, local_item.status

        completed = 0
        failed = 0
        skipped = 0
        cancelled = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = [pool.submit(worker, it) for it in items]
            for fut in as_completed(futures):
                try:
                    _item_id, _success, status = fut.result()
                except Exception as e:
                    logger.error("下载任务异常: %s", e)
                    failed += 1
                    continue

                if status == DownloadStatus.COMPLETED:
                    completed += 1
                elif status == DownloadStatus.SKIPPED:
                    skipped += 1
                elif status == DownloadStatus.CANCELLED:
                    cancelled += 1
                else:
                    failed += 1

                # 取消：取消未启动的 future，运行中的由 download_file 内部检测退出
                if self.is_cancelled():
                    for f in futures:
                        f.cancel()
                    break

        stats.completed = completed
        stats.failed = failed
        stats.skipped = skipped
        stats.cancelled = cancelled

        if on_all_complete:
            on_all_complete(stats)

        return stats

    def close(self):
        """关闭session（原子，可重复调用）"""
        with self._lock:
            if self._session is not None:
                self._session.close()
                self._session = None
