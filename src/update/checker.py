"""更新检查/下载（Qt worker + 编排；纯逻辑见 services.update_logic）"""

import logging
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime

import requests
from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..services.update_logic import (
    GITHUB_API_URL,
    GITHUB_RELEASES_URL,
    OLD_EXE_NAME,
    TEMP_EXE_NAME,
    compare_versions,
    extract_download_url,
    get_exe_dir,
    get_exe_path,
    is_newer_test_release,
    parse_version,
)

logger = logging.getLogger(__name__)


class UpdateCheckWorker(QThread):
    """后台更新检查工作线程"""

    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, channel: str, current_version: str, last_check_time: str = ""):
        super().__init__()
        self.channel = channel
        self.current_version = current_version
        self.last_check_time = last_check_time

    def run(self):
        try:
            response = requests.get(GITHUB_API_URL, timeout=10)
            response.raise_for_status()
            releases = response.json()

            if not releases:
                self.finished.emit({"has_update": False})
                return

            if self.channel == "stable":
                self._check_stable(releases)
            else:
                self._check_test(releases)

        except requests.RequestException as e:
            logger.error("检查更新失败: %s", e)
            self.error.emit(f"网络请求失败: {e}")
        except Exception as e:
            logger.error("检查更新时发生错误: %s", e)
            self.error.emit(f"检查失败: {e}")

    def _emit_result(self, release: dict, has_update: bool) -> None:
        """发射统一的检查结果"""
        tag = release.get("tag_name") or ""
        self.finished.emit(
            {
                "has_update": has_update,
                "version": tag.lstrip("v") if tag else "",
                "tag": tag,
                "url": release.get("html_url") or GITHUB_RELEASES_URL,
                "download_url": extract_download_url(release),
                "notes": release.get("body") or "",
                "published_at": release.get("published_at") or "",
            }
        )

    def _check_stable(self, releases: list):
        """检查稳定版更新"""
        stable_releases = [r for r in releases if not r.get("prerelease", False) and not r.get("draft", False)]

        if not stable_releases:
            self.finished.emit({"has_update": False})
            return

        latest = stable_releases[0]
        remote_version = (latest.get("tag_name") or "").lstrip("v")

        if parse_version(remote_version) is None:
            logger.error("版本解析失败: %s", remote_version)
            self.finished.emit({"has_update": False, "error": "版本号格式错误"})
            return

        has_update = compare_versions(self.current_version, remote_version)
        self._emit_result(latest, has_update)

    def _check_test(self, releases: list):
        """检查测试版更新"""
        test_releases = [r for r in releases if r.get("prerelease", False) and not r.get("draft", False)]

        if not test_releases:
            self.finished.emit({"has_update": False})
            return

        latest = test_releases[0]
        published_at = latest.get("published_at") or ""
        has_update = is_newer_test_release(published_at, self.last_check_time)
        self._emit_result(latest, has_update)


class UpdateDownloadWorker(QThread):
    """后台下载更新工作线程"""

    progress = Signal(int)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, download_url: str):
        super().__init__()
        self.download_url = download_url

    def run(self):
        try:
            exe_dir = get_exe_dir()
            temp_path = exe_dir / TEMP_EXE_NAME

            logger.info("开始下载更新: %s", self.download_url)
            response = requests.get(self.download_url, stream=True, timeout=30)
            try:
                response.raise_for_status()

                total_size = int(response.headers.get("content-length", 0))
                downloaded = 0

                with open(temp_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                percent = int(downloaded * 100 / total_size)
                                self.progress.emit(percent)

                logger.info("下载完成: %s (%d bytes)", temp_path, downloaded)
                self.finished.emit(str(temp_path))
            finally:
                response.close()

        except requests.RequestException as e:
            logger.error("下载更新失败: %s", e)
            self.error.emit(f"下载失败: {e}")
            self._cleanup_temp()
        except Exception as e:
            logger.error("下载更新时发生错误: %s", e)
            self.error.emit(f"下载失败: {e}")
            self._cleanup_temp()

    def _cleanup_temp(self):
        """清理临时文件"""
        temp_path = get_exe_dir() / TEMP_EXE_NAME
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def perform_update(launcher: Callable[[list[str]], object] | None = None) -> None:
    """执行更新替换并重启应用

    调用顺序：rename 当前 exe → rename 新 exe → 启动新进程 → 退出当前进程

    Args:
        launcher: 进程启动器（可注入以便测试），默认 subprocess.Popen
    """
    exe_dir = get_exe_dir()
    exe_path = get_exe_path()
    temp_path = exe_dir / TEMP_EXE_NAME
    old_path = exe_dir / OLD_EXE_NAME
    if launcher is None:
        launcher = subprocess.Popen

    if not temp_path.exists():
        logger.error("更新文件不存在: %s", temp_path)
        return

    if not getattr(sys, "frozen", False):
        logger.warning("开发模式下跳过自动更新替换")
        return

    try:
        # 1. 删除旧版本残留
        if old_path.exists():
            old_path.unlink()

        # 2. 重命名当前 exe（Windows 下可重命名正在运行的 exe）
        if exe_path.exists():
            exe_path.rename(old_path)
            logger.info("已重命名当前版本: %s -> %s", exe_path, old_path)

        # 3. 重命名新 exe 为正式名称
        temp_path.rename(exe_path)
        logger.info("已替换为新版本: %s", exe_path)

        # 4. 启动新进程
        if getattr(sys, "frozen", False):
            launcher([str(exe_path)])
        else:
            launcher([sys.executable, str(exe_path)])
        logger.info("已启动新版本进程")

        # 5. 退出当前进程
        import os

        os._exit(0)

    except Exception as e:
        logger.error("更新替换失败: %s", e)
        # 尝试恢复：如果当前 exe 已被 rename 但新 exe 还没 rename
        if not exe_path.exists() and old_path.exists() and temp_path.exists():
            try:
                temp_path.unlink()
                old_path.rename(exe_path)
                logger.info("已恢复原版本")
            except OSError:
                pass


class UpdateChecker(QObject):
    """更新检查器"""

    check_finished = Signal(dict)
    check_error = Signal(str)
    download_progress = Signal(int)
    download_finished = Signal()
    download_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: UpdateCheckWorker | None = None
        self._download_worker: UpdateDownloadWorker | None = None

    @Slot(str, str, str)
    def check_update(self, channel: str, current_version: str, last_check_time: str = ""):
        """检查更新

        Args:
            channel: "stable" 或 "test"
            current_version: 当前版本号（如 "2.0.0"）
            last_check_time: 上次检查时间（ISO格式）
        """
        if self._worker and self._worker.isRunning():
            logger.warning("更新检查正在进行中，跳过")
            return

        self._worker = UpdateCheckWorker(channel, current_version, last_check_time)
        self._worker.finished.connect(self._on_check_finished)
        self._worker.error.connect(self._on_check_error)
        self._worker.start()

    def download_and_update(self, download_url: str):
        """下载更新并执行替换

        Args:
            download_url: 下载地址
        """
        if self._download_worker and self._download_worker.isRunning():
            logger.warning("下载更新正在进行中，跳过")
            return

        self._download_worker = UpdateDownloadWorker(download_url)
        self._download_worker.progress.connect(self.download_progress.emit)
        self._download_worker.finished.connect(self._on_download_finished)
        self._download_worker.error.connect(self._on_download_error)
        self._download_worker.start()

    @Slot(dict)
    def _on_check_finished(self, result: dict):
        """检查完成"""
        self.check_finished.emit(result)

    @Slot(str)
    def _on_check_error(self, error_msg: str):
        """检查失败"""
        self.check_error.emit(error_msg)

    @Slot(str)
    def _on_download_finished(self, file_path: str):
        """下载完成，执行更新"""
        self.download_finished.emit()
        perform_update()

    @Slot(str)
    def _on_download_error(self, error_msg: str):
        """下载失败"""
        self.download_error.emit(error_msg)

    def get_current_check_time(self) -> str:
        """获取当前时间的ISO格式字符串"""
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
