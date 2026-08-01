"""更新检查/下载流程管理"""

import logging

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QDesktopServices
from qfluentwidgets import InfoBar, InfoBarPosition, MessageBox

from ..models import AppConfig
from ..services.update_logic import GITHUB_RELEASES_URL
from ..views.settings_panel import SettingsPanel
from .checker import UpdateChecker

logger = logging.getLogger(__name__)

INFO_DURATION = 3000  # 常规通知时长（毫秒）
SUCCESS_DURATION = 2000  # 成功通知时长（毫秒）
ERROR_DURATION = 5000  # 错误通知时长（毫秒）
NOTES_PREVIEW_LEN = 200  # 更新说明预览长度


class UpdateFlow(QObject):
    """更新流程：检查通知 → 自动下载替换 / 手动下载对话框"""

    def __init__(
        self,
        config: AppConfig,
        window,
        settings_panel: SettingsPanel,
        checker: UpdateChecker,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.config = config
        self._window = window
        self._settings_panel = settings_panel
        self._checker = checker
        self._pending_update_url = ""
        self._pending_update_notes = ""

    def connect_signals(self) -> None:
        """连接更新检查器信号"""
        self._checker.check_finished.connect(self._on_check_finished)
        self._checker.check_error.connect(self._on_check_error)
        self._checker.download_progress.connect(self._on_download_progress)
        self._checker.download_finished.connect(self._on_download_finished)
        self._checker.download_error.connect(self._on_download_error)

    def check_update(self, channel: str, version: str, last_check_time: str):
        """发起更新检查（手动/自动共用）"""
        self._checker.check_update(channel, version, last_check_time)

    def _on_check_finished(self, result: dict):
        """更新检查完成"""
        self._settings_panel.on_check_update_finished()

        if result.get("error"):
            InfoBar.warning(
                title="检查更新",
                content=result["error"],
                parent=self._window,
                position=InfoBarPosition.TOP,
                duration=INFO_DURATION,
            )
            return

        if result.get("has_update"):
            version = result.get("version") or ""
            url = result.get("url") or ""
            download_url = result.get("download_url") or ""
            notes = result.get("notes") or ""

            # 更新上次检查时间
            self.config.last_update_check_time = self._checker.get_current_check_time()
            self.config.save()

            if download_url:
                # 自动下载更新
                self._settings_panel.on_update_downloading()
                InfoBar.info(
                    title="发现新版本",
                    content=f"发现新版本 v{version}，正在下载...",
                    parent=self._window,
                    position=InfoBarPosition.TOP,
                    duration=INFO_DURATION,
                )
                self._pending_update_url = url
                self._pending_update_notes = notes
                self._checker.download_and_update(download_url)
            else:
                # 无下载地址，弹出手动下载对话框
                self._show_manual_update_dialog(url, version, notes)
        else:
            InfoBar.info(
                title="检查更新",
                content="已是最新版本",
                parent=self._window,
                position=InfoBarPosition.TOP,
                duration=SUCCESS_DURATION,
            )

    def _show_manual_update_dialog(self, url: str, version: str, notes: str):
        """显示手动下载对话框"""
        notes = notes or ""
        preview = notes[:NOTES_PREVIEW_LEN]
        if len(notes) > NOTES_PREVIEW_LEN:
            preview += "..."
        dialog = MessageBox("发现新版本", f"发现新版本 v{version}\n\n{preview}", self._window)
        dialog.yesButton.setText("前往下载")
        dialog.cancelButton.setText("取消")

        if dialog.exec():
            QDesktopServices.openUrl(QUrl(url))

    def _on_download_progress(self, percent: int):
        """更新下载进度"""
        self._settings_panel.on_update_downloading(percent)

    def _on_download_finished(self):
        """更新下载完成，执行替换重启"""
        self._settings_panel.on_update_finished()
        InfoBar.success(
            title="更新完成",
            content="新版本已下载完成，正在重启...",
            parent=self._window,
            position=InfoBarPosition.TOP,
            duration=SUCCESS_DURATION,
        )

    def _on_download_error(self, error_msg: str):
        """更新下载失败，弹出手动下载对话框"""
        self._settings_panel.on_update_finished()
        self._show_manual_update_dialog(
            self._pending_update_url or GITHUB_RELEASES_URL, "最新", self._pending_update_notes
        )
        InfoBar.warning(
            title="下载失败",
            content=f"自动下载失败: {error_msg}，请手动下载",
            parent=self._window,
            position=InfoBarPosition.TOP,
            duration=ERROR_DURATION,
        )

    def _on_check_error(self, error_msg: str):
        """更新检查失败"""
        self._settings_panel.on_check_update_finished()
        InfoBar.warning(
            title="检查更新",
            content=f"检查失败: {error_msg}",
            parent=self._window,
            position=InfoBarPosition.TOP,
            duration=INFO_DURATION,
        )
