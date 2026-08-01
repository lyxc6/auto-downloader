"""更新检查纯逻辑（无 Qt 依赖，可单测）"""

import logging
import sys
from datetime import datetime
from pathlib import Path

from packaging.version import Version

from ..utils.helpers import get_app_dir

logger = logging.getLogger(__name__)

GITHUB_API_URL = "https://api.github.com/repos/lyxc6/auto-downloader/releases"
GITHUB_RELEASES_URL = "https://github.com/lyxc6/auto-downloader/releases"
ASSET_FILENAME = "自动下载器.exe"
TEMP_EXE_NAME = "update_temp.exe"
OLD_EXE_NAME = "自动下载器_old.exe"


def get_exe_dir() -> Path:
    """获取可执行文件所在目录（打包后为 exe 目录，开发时为项目根）"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(get_app_dir())


def get_exe_path() -> Path:
    """获取可执行文件路径（打包后为 exe 本身，开发时为 main.py）"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return Path(get_app_dir()) / "main.py"


def cleanup_old_exe():
    """清理上次更新残留的旧版本文件"""
    exe_dir = get_exe_dir()
    old_path = exe_dir / OLD_EXE_NAME
    if old_path.exists():
        try:
            old_path.unlink()
            logger.info("已清理旧版本文件: %s", old_path)
        except OSError as e:
            logger.warning("清理旧版本文件失败: %s", e)

    temp_path = exe_dir / TEMP_EXE_NAME
    if temp_path.exists():
        try:
            temp_path.unlink()
            logger.info("已清理残留临时文件: %s", temp_path)
        except OSError as e:
            logger.warning("清理临时文件失败: %s", e)


def extract_download_url(release: dict) -> str:
    """从 release 的 assets 中提取下载 URL"""
    assets = release.get("assets", [])
    for asset in assets:
        if asset.get("name") == ASSET_FILENAME:
            return asset.get("browser_download_url", "")
    return ""


def parse_version(version_str: str) -> Version | None:
    """解析版本号，失败返回 None"""
    try:
        return Version(version_str.lstrip("v"))
    except Exception:
        return None


def compare_versions(current: str, remote: str) -> bool:
    """比较版本：remote 是否比 current 新（任一版本号无法解析时返回 False）"""
    local_ver = parse_version(current)
    remote_ver = parse_version(remote)
    if local_ver is None or remote_ver is None:
        logger.error("版本解析失败: current=%s remote=%s", current, remote)
        return False
    return remote_ver > local_ver


def is_newer_test_release(published_at: str, last_check_time: str) -> bool:
    """测试版判断：发布是否晚于上次检查时间（时间无法解析时视为有新版本）"""
    if not last_check_time:
        return True
    try:
        remote_time = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        last_check = datetime.fromisoformat(last_check_time.replace("Z", "+00:00"))
        return remote_time > last_check
    except (ValueError, TypeError):
        return True
