"""presenters 包：流程 presenter（视图状态转换 + 流程副作用）"""

from .auto_save import AutoSavePolicy
from .download_presenter import DownloadPresenter
from .scan_presenter import ScanPresenter

__all__ = ["AutoSavePolicy", "DownloadPresenter", "ScanPresenter"]
