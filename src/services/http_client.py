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
    ):
        self._session: requests.Session | None = None
        self._lock = threading.Lock()

        # 扫描参数
        self._scan_delay = scan_delay
        self._scan_timeout = scan_timeout
        self._dir_scan_timeout = dir_scan_timeout
        self._last_progress_time: float = time.monotonic()
        self._dir_start_time: float = 0.0
        self._progress_lock = threading.Lock()

        # 失败统计
        self._failed_dirs = 0
        self._failed_dirs_lock = threading.Lock()
        self._error_dirs = 0
        self._error_dirs_lock = threading.Lock()

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
        pass

    def is_cancelled(self) -> bool:
        """是否已取消"""
        return False

    def set_cancel_flag(self, cancel_flag: threading.Event):
        """设置取消标志（由ScanService注入）"""
        self._cancel_flag = cancel_flag

    def _should_stop(self) -> bool:
        """检查是否应该停止"""
        if hasattr(self, '_cancel_flag') and self._cancel_flag.is_set():
            return True
        return self.is_timeout()

    def is_timeout(self) -> bool:
        """是否已超时（无进展超时）"""
        if self._scan_timeout <= 0:
            return False
        with self._progress_lock:
            return (time.monotonic() - self._last_progress_time) >= self._scan_timeout

    def _update_progress(self):
        """更新进展时间（发现新内容时调用）"""
        with self._progress_lock:
            self._last_progress_time = time.monotonic()

    def _is_dir_timeout(self) -> bool:
        """检查当前目录是否超时"""
        if self._dir_scan_timeout <= 0:
            return False
        with self._progress_lock:
            if self._dir_start_time <= 0:
                return False
            return (time.monotonic() - self._dir_start_time) >= self._dir_scan_timeout

    def _start_dir_timer(self):
        """启动目录级计时器"""
        with self._progress_lock:
            self._dir_start_time = time.monotonic()

    def _increment_error_dirs(self):
        """增加错误目录计数器"""
        with self._error_dirs_lock:
            self._error_dirs += 1

    def get_error_dirs_count(self) -> int:
        """获取错误目录数量"""
        with self._error_dirs_lock:
            return self._error_dirs

    def reset_progress(self):
        """重置进度计时器"""
        self._last_progress_time = time.monotonic()

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
            if self._is_dir_timeout():
                logger.warning("目录扫描超时，停止重试: %s", url)
                return None

            # 检查全局超时
            if self._should_stop():
                return None

            try:
                resp = session.get(url, timeout=60)
                resp.raise_for_status()
                resp.encoding = "utf-8"
                return resp.text
            except requests.HTTPError as e:
                status_code = e.response.status_code if e.response is not None else None

                # 获取重试配置
                retry_config = RetryPolicy.get_retry_config(status_code)
                max_retries = min(retries, retry_config["max_retries"])

                # 检查是否应该重试
                if attempt >= max_retries:
                    logger.error("获取页面失败(不再重试): %s -> %s", url, status_code)
                    if self.on_error:
                        self.on_error(f"获取页面失败: HTTP {status_code}")
                    with self._failed_dirs_lock:
                        self._failed_dirs += 1
                    return None

                # 计算延迟
                delay = RetryPolicy.calculate_delay(attempt, retry_config)
                logger.warning(
                    "获取页面重试 %d/%d: %s -> %s (等待 %.1f秒)",
                    attempt + 1, max_retries, url, status_code, delay
                )
                time.sleep(delay)
                attempt += 1

            except requests.ConnectionError as e:
                # 连接错误，可重试
                retry_config = RetryPolicy.get_retry_config(None)
                max_retries = min(retries, retry_config["max_retries"])

                if attempt >= max_retries:
                    logger.error("获取页面失败(连接错误): %s -> %s", url, e)
                    if self.on_error:
                        self.on_error(f"连接失败: {e}")
                    with self._failed_dirs_lock:
                        self._failed_dirs += 1
                    return None

                delay = RetryPolicy.calculate_delay(attempt, retry_config)
                logger.warning(
                    "获取页面重试 %d/%d: %s -> %s (等待 %.1f秒)",
                    attempt + 1, max_retries, url, e, delay
                )
                time.sleep(delay)
                attempt += 1

            except requests.Timeout as e:
                # 超时错误，可重试
                retry_config = RetryPolicy.get_retry_config(None)
                max_retries = min(retries, retry_config["max_retries"])

                if attempt >= max_retries:
                    logger.error("获取页面失败(超时): %s -> %s", url, e)
                    if self.on_error:
                        self.on_error(f"请求超时: {e}")
                    with self._failed_dirs_lock:
                        self._failed_dirs += 1
                    return None

                delay = RetryPolicy.calculate_delay(attempt, retry_config)
                logger.warning(
                    "获取页面重试 %d/%d: %s -> %s (等待 %.1f秒)",
                    attempt + 1, max_retries, url, e, delay
                )
                time.sleep(delay)
                attempt += 1

            except Exception as e:
                # 其他错误，保守重试
                retry_config = RetryPolicy.get_retry_config(None)
                max_retries = min(retries, retry_config["max_retries"])

                if attempt >= max_retries:
                    logger.error("获取页面失败: %s -> %s", url, e)
                    if self.on_error:
                        self.on_error(f"获取页面失败: {e}")
                    with self._failed_dirs_lock:
                        self._failed_dirs += 1
                    return None

                delay = RetryPolicy.calculate_delay(attempt, retry_config)
                logger.warning(
                    "获取页面重试 %d/%d: %s -> %s (等待 %.1f秒)",
                    attempt + 1, max_retries, url, e, delay
                )
                time.sleep(delay)
                attempt += 1

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
            try:
                resp = session.head(url, timeout=30, allow_redirects=True)
                # 服务器不支持 HEAD 或返回错误，回退到 GET
                if resp.status_code in (405, 501) or resp.status_code >= 400:
                    resp.close()
                    logger.debug("HEAD 返回 %d，回退 GET: %s", resp.status_code, url)
                    resp = session.get(url, stream=True, timeout=30)
                    resp.raise_for_status()
                    cl = resp.headers.get("content-length")
                    resp.close()
                    return int(cl) if cl else None
                resp.raise_for_status()
                cl = resp.headers.get("content-length")
                resp.close()
                return int(cl) if cl else None
            except requests.RequestException as e:
                logger.debug("获取文件大小失败 (第%d次): %s - %s", attempt + 1, url, e)
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
