"""更新检查服务"""
import logging
from datetime import datetime, timezone
from typing import Optional

import requests
from packaging.version import Version
from PySide6.QtCore import QObject, QThread, Signal, Slot

logger = logging.getLogger(__name__)

GITHUB_API_URL = "https://api.github.com/repos/lyxc6/auto-downloader/releases"
GITHUB_RELEASES_URL = "https://github.com/lyxc6/auto-downloader/releases"


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
    
    def _check_stable(self, releases: list):
        """检查稳定版更新"""
        stable_releases = [
            r for r in releases
            if not r.get("prerelease", False) and not r.get("draft", False)
        ]
        
        if not stable_releases:
            self.finished.emit({"has_update": False})
            return
        
        latest = stable_releases[0]
        remote_tag = latest.get("tag_name", "")
        remote_version = remote_tag.lstrip("v")
        
        try:
            local_ver = Version(self.current_version)
            remote_ver = Version(remote_version)
        except Exception as e:
            logger.error("版本解析失败: %s", e)
            self.finished.emit({"has_update": False, "error": "版本号格式错误"})
            return
        
        has_update = remote_ver > local_ver
        
        self.finished.emit({
            "has_update": has_update,
            "version": remote_version,
            "tag": remote_tag,
            "url": latest.get("html_url", GITHUB_RELEASES_URL),
            "notes": latest.get("body", ""),
            "published_at": latest.get("published_at", ""),
        })
    
    def _check_test(self, releases: list):
        """检查测试版更新"""
        test_releases = [
            r for r in releases
            if r.get("prerelease", False) and not r.get("draft", False)
        ]
        
        if not test_releases:
            self.finished.emit({"has_update": False})
            return
        
        latest = test_releases[0]
        published_at = latest.get("published_at", "")
        
        has_update = False
        if self.last_check_time:
            try:
                remote_time = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                last_check = datetime.fromisoformat(self.last_check_time.replace("Z", "+00:00"))
                has_update = remote_time > last_check
            except (ValueError, TypeError):
                has_update = True
        else:
            has_update = True
        
        self.finished.emit({
            "has_update": has_update,
            "version": latest.get("tag_name", ""),
            "tag": latest.get("tag_name", ""),
            "url": latest.get("html_url", GITHUB_RELEASES_URL),
            "notes": latest.get("body", ""),
            "published_at": published_at,
        })


class UpdateChecker(QObject):
    """更新检查器"""
    
    check_finished = Signal(dict)
    check_error = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: Optional[UpdateCheckWorker] = None
    
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
    
    @Slot(dict)
    def _on_check_finished(self, result: dict):
        """检查完成"""
        self.check_finished.emit(result)
    
    @Slot(str)
    def _on_check_error(self, error_msg: str):
        """检查失败"""
        self.check_error.emit(error_msg)
    
    def get_current_check_time(self) -> str:
        """获取当前时间的ISO格式字符串"""
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
