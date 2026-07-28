"""构建元数据 - 由 CI/CD 自动生成，本地开发使用默认值"""
from datetime import datetime, timezone


def _get_build_time() -> str:
    """获取构建时间"""
    try:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


def _get_git_sha() -> str:
    """获取 Git commit SHA"""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _get_build_channel() -> str:
    """获取构建渠道"""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            if branch == "main":
                return "test"
    except Exception:
        pass
    return "stable"


# 构建元数据
BUILD_TIME: str = _get_build_time()
GIT_SHA: str = _get_git_sha()
BUILD_CHANNEL: str = _get_build_channel()
