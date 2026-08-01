"""HTTP客户端 - 统一的HTTP请求和重试逻辑"""

import logging
import threading
import time
from collections.abc import Callable

import requests

from .retry_policy import RetryPolicy

logger = logging.getLogger(__name__)


class HttpClient:
    """HTTP客户端 - 统一的HTTP请求和重试逻辑"""

    def __init__(
        self,
        scan_delay: float = 0.02,
        scan_timeout: float = 300.0,
        dir_scan_timeout: float = 30.0,
        request_timeout: float = 60.0,
    ):
        self._session: requests.Session | None = None
        self._lock = threading.Lock()

        # 扫描参数
        self._scan_delay = scan_delay
        self._scan_timeout = scan_timeout
        self._dir_scan_timeout = dir_scan_timeout
        self._request_timeout = request_timeout
        self._last_progress_time: float = time.monotonic()
        self._dir_start_time: float = 0.0
        self._progress_lock = threading.Lock()

        # 失败统计
        self._failed_dirs = 0
        self._failed_dirs_lock = threading.Lock()
        self._error_dirs = 0
        self._error_dirs_lock = threading.Lock()

        # 取消标志（默认新建，可由 ScanService 注入共享事件）
        self._cancel_flag = threading.Event()

        # 回调函数
        self.on_error: Callable[[str], None] | None = None

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
        """取消操作"""
        self._cancel_flag.set()

    def is_cancelled(self) -> bool:
        """是否已取消"""
        return self._cancel_flag.is_set()

    def set_cancel_flag(self, cancel_flag: threading.Event):
        """设置取消标志（由ScanService注入）"""
        self._cancel_flag = cancel_flag

    def _should_stop(self) -> bool:
        """检查是否应该停止"""
        return self.is_cancelled() or self.is_timeout()

    def is_timeout(self) -> bool:
        """是否已超时（无进展超时）"""
        if self._scan_timeout <= 0:
            return False
        with self._progress_lock:
            return (time.monotonic() - self._last_progress_time) >= self._scan_timeout

    def touch_progress(self):
        """更新进展时间（发现新内容时调用）"""
        with self._progress_lock:
            self._last_progress_time = time.monotonic()

    def is_dir_timeout(self) -> bool:
        """检查当前目录是否超时"""
        if self._dir_scan_timeout <= 0:
            return False
        with self._progress_lock:
            if self._dir_start_time <= 0:
                return False
            return (time.monotonic() - self._dir_start_time) >= self._dir_scan_timeout

    def start_dir_timer(self):
        """启动目录级计时器"""
        with self._progress_lock:
            self._dir_start_time = time.monotonic()

    def increment_error_dirs(self):
        """增加错误目录计数器"""
        with self._error_dirs_lock:
            self._error_dirs += 1

    def get_error_dirs_count(self) -> int:
        """获取错误目录数量"""
        with self._error_dirs_lock:
            return self._error_dirs

    def get_failed_dirs_count(self) -> int:
        """获取失败目录数量"""
        with self._failed_dirs_lock:
            return self._failed_dirs

    def reset_progress(self):
        """重置进度计时器"""
        with self._progress_lock:
            self._last_progress_time = time.monotonic()
            self._dir_start_time = 0.0

    def _register_failure(self, url: str, reason: str) -> None:
        """记录一次失败（错误回调 + 失败目录计数）"""
        if self.on_error:
            self.on_error(f"获取页面失败: {reason}")
        with self._failed_dirs_lock:
            self._failed_dirs += 1
        logger.error("获取页面失败: %s -> %s", url, reason)

    def _handle_request_exception(self, url: str, retries: int, attempt: int, exc: requests.RequestException) -> bool:
        """处理请求异常，返回 True 表示已重试（继续循环），False 表示重试耗尽

        Args:
            attempt: 当前已尝试次数（0 起）
        """
        status_code: int | None = None
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            status_code = exc.response.status_code

        retry_config = RetryPolicy.get_retry_config(status_code)
        max_retries = min(retries, retry_config.max_retries)

        # 检查是否应该重试
        if attempt >= max_retries:
            reason = f"HTTP {status_code}" if status_code is not None else f"{exc.__class__.__name__}: {exc}"
            self._register_failure(url, reason)
            return False

        # 计算延迟并重试
        delay = RetryPolicy.calculate_delay(attempt, retry_config)
        logger.warning("获取页面重试 %d/%d: %s -> %s (等待 %.1f秒)", attempt + 1, max_retries, url, exc, delay)
        time.sleep(delay)
        return True

    def get_page(
        self,
        url: str,
        retries: int = 3,
        session: requests.Session | None = None,
    ) -> str | None:
        """获取页面内容（智能重试）

        Args:
            url: 请求URL
            retries: 最大重试次数
            session: 可选的session，不传则使用内置session
        """
        if session is None:
            session = self.session

        attempt = 0

        while attempt <= retries:
            # 检查目录级超时（优先级高于全局超时）
            if self.is_dir_timeout():
                logger.warning("目录扫描超时，停止重试: %s", url)
                return None

            # 检查全局超时
            if self._should_stop():
                return None

            try:
                resp = session.get(url, timeout=self._request_timeout)
                resp.raise_for_status()
                resp.encoding = "utf-8"
                return resp.text
            except requests.RequestException as e:
                if self._handle_request_exception(url, retries, attempt, e):
                    attempt += 1
                else:
                    return None

        return None

    def head_file_size(self, url: str, retries: int = 2) -> int | None:
        """发送 HEAD 请求获取文件大小，失败时回退到 GET（stream=True，只读 headers）

        Args:
            url: 文件URL
            retries: 最大重试次数

        Returns:
            文件大小（字节），失败返回 None
        """
        session = self.session
        for attempt in range(retries):
            cl, _ = fetch_file_info(session, url, self._request_timeout)
            if cl is not None:
                return cl
            if attempt < retries - 1:
                time.sleep(1)
        logger.warning("获取文件大小最终失败: %s", url)
        return None

    def close(self):
        """关闭session（原子，可重复调用）"""
        with self._lock:
            if self._session is not None:
                self._session.close()
                self._session = None


def fetch_file_info(session: requests.Session, url: str, timeout: float) -> tuple[int | None, str | None]:
    """HEAD 获取远端文件信息（Content-Length 与 Accept-Ranges），服务器不支持 HEAD 时回退 GET

    共享逻辑：下载服务与文件大小预取均使用此实现。

    Args:
        session: 复用的 requests.Session
        url: 文件URL
        timeout: 请求超时（秒）

    Returns:
        (content_length, accept_ranges) 或 (None, None)
    """
    try:
        resp = session.head(url, timeout=timeout, allow_redirects=True)
        # 部分服务器不支持 HEAD 或返回错误，回退到 GET
        if resp.status_code in (405, 501) or resp.status_code >= 400:
            resp.close()
            logger.debug("HEAD 返回 %d，回退 GET: %s", resp.status_code, url)
            resp = session.get(url, stream=True, timeout=timeout)
            resp.raise_for_status()
            cl = resp.headers.get("content-length")
            ar = resp.headers.get("accept-ranges")
            resp.close()
            return (int(cl) if cl else None, ar)
        resp.raise_for_status()
        cl = resp.headers.get("content-length")
        ar = resp.headers.get("accept-ranges")
        resp.close()
        return (int(cl) if cl else None, ar)
    except requests.RequestException as e:
        logger.warning("请求失败: %s -> %s", url, e)
        return (None, None)
    except (ValueError, TypeError) as e:
        logger.error("解析远端文件信息失败: %s -> %s", url, e)
        return (None, None)
    except OSError as e:
        logger.warning("文件信息请求IO错误: %s -> %s", url, e)
        return (None, None)
