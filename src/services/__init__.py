"""服务层（纯 Python，无 Qt 依赖；更新检查见 src/update/）"""

from .downloader import DownloadService
from .html_parser import HtmlParser
from .http_client import HttpClient
from .page_cache import PageCache
from .retry_policy import RetryConfig, RetryPolicy
from .scanner import ScanService
from .update_logic import cleanup_old_exe

__all__ = [
    "DownloadService",
    "HtmlParser",
    "HttpClient",
    "PageCache",
    "RetryConfig",
    "RetryPolicy",
    "ScanService",
    "cleanup_old_exe",
]
