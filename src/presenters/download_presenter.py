"""下载流程 presenter：视图/控制器信号 → 队列面板 + 底部总进度条"""

import logging
from typing import Any

from PySide6.QtCore import QObject
from qfluentwidgets import InfoBar, InfoBarPosition

from ..controllers import DownloadController
from ..models import AppConfig, CacheManager, DownloadItem
from ..views.download_panel import DownloadPanel
from ..views.queue_panel import QueuePanel
from .auto_save import AutoSavePolicy

logger = logging.getLogger(__name__)


class DownloadPresenter(QObject):
    """下载流程 presenter：队列面板状态转换 + 总进度条累计"""

    def __init__(
        self,
        config: AppConfig,
        cache_manager: CacheManager,
        download_controller: DownloadController,
        view: DownloadPanel,
        queue_view: QueuePanel,
        auto_save: AutoSavePolicy,
    ):
        super().__init__()
        self._config = config
        self._cache_manager = cache_manager
        self._download_controller = download_controller
        self._view = view
        self._queue_view = queue_view
        self._auto_save = auto_save

        # 批次进度累计，用于底部总进度条
        self._dl_progress: dict[str, tuple[int, int]] = {}

        self._connect_signals()

    def _connect_signals(self):
        """接线：视图信号 → 本 presenter 槽，控制器信号 → 本 presenter 槽/视图方法"""
        view = self._view
        controller = self._download_controller

        # 视图 → presenter
        view.download_requested.connect(self._on_download_requested)
        view.stop_download_clicked.connect(controller.cancel_download)

        # 控制器信号 → 视图（无需状态转换，直连）
        controller.log_message.connect(view.add_log)
        controller.error_occurred.connect(lambda _item_id, msg: view.add_log(msg, "error"))

        # 控制器信号 → presenter 槽
        controller.progress_updated.connect(self._on_download_progress)
        controller.status_changed.connect(self._on_download_status)
        controller.batch_completed.connect(self._on_download_completed)
        controller.download_validated.connect(self._on_download_validated)

    # ==================== 下载请求 ====================

    def _on_download_requested(self):
        """下载请求处理"""
        # 从目录树取勾选文件
        checked_files = self._view.get_checked_files()

        if not checked_files:
            InfoBar.warning(
                title="警告", content="请先选择要下载的文件", parent=self._view, position=InfoBarPosition.TOP
            )
            return

        # 重置批次进度累计，用于底部总进度条
        self._dl_progress = {}

        # 设置下载状态
        self._view.set_downloading(True)
        self._auto_save.start()

        # 调用控制器（带验证）
        self._download_controller.start_download_with_validation(checked_files)

    def _on_download_validated(self, checked_files: list[DownloadItem]):
        """下载验证通过：添加到队列"""
        for item in checked_files:
            self._queue_view.add_item(item.item_id, item.name)

    # ==================== 下载结果回调 ====================

    def _on_download_progress(self, item_id: str, downloaded: int, total_size: int):
        """下载进度更新"""
        self._queue_view.update_progress(item_id, downloaded, total_size)

        # 累计各文件进度，驱动底部总进度条
        self._dl_progress[item_id] = (downloaded, total_size)
        sum_downloaded = sum(d for d, _ in self._dl_progress.values())
        sum_total = sum(t for _, t in self._dl_progress.values())
        self._view.update_progress(sum_downloaded, sum_total)

    def _on_download_status(self, item_id: str, status: str):
        """下载状态更新"""
        self._queue_view.update_status(item_id, status)

    def _on_download_completed(self, stats_dict: dict[str, Any]) -> None:
        """下载完成"""
        self._view.set_downloading(False)
        # 批次结束将总进度条置满（随后 set_downloading(False) 会隐藏它）
        self._view.update_progress(1, 1)
        self._dl_progress = {}
        self._cache_manager.save()
        logger.info("下载完成，缓存已保存")
        self._auto_save.stop_if_idle()
