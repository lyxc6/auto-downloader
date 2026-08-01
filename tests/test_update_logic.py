"""更新检查纯逻辑测试（services.update_logic，无 Qt 依赖）"""

from unittest.mock import patch

from src.services import update_logic


def test_parse_version_normal():
    assert update_logic.parse_version("v1.2.3") is not None
    assert update_logic.parse_version("1.2.3") is not None


def test_parse_version_invalid_returns_none():
    assert update_logic.parse_version("abc") is None
    assert update_logic.parse_version("") is None


def test_compare_versions_newer():
    assert update_logic.compare_versions("1.0.0", "1.1.0") is True
    assert update_logic.compare_versions("1.1.0", "1.1.1") is True
    assert update_logic.compare_versions("2.0.0", "1.9.9") is False
    assert update_logic.compare_versions("1.1.0", "1.1.0") is False


def test_compare_versions_invalid_returns_false():
    assert update_logic.compare_versions("abc", "1.0.0") is False
    assert update_logic.compare_versions("1.0.0", "abc") is False
    assert update_logic.compare_versions("", "") is False


def test_extract_download_url_finds_asset():
    release = {
        "assets": [
            {"name": "其他.exe", "browser_download_url": "http://other"},
            {"name": "自动下载器.exe", "browser_download_url": "http://ok"},
        ]
    }
    assert update_logic.extract_download_url(release) == "http://ok"


def test_extract_download_url_missing_returns_empty():
    assert update_logic.extract_download_url({"assets": []}) == ""
    assert update_logic.extract_download_url({}) == ""


def test_is_newer_test_release():
    assert update_logic.is_newer_test_release("2026-01-01T00:00:00Z", "") is True
    assert update_logic.is_newer_test_release("2026-02-01T00:00:00Z", "2026-01-01T00:00:00Z") is True
    assert update_logic.is_newer_test_release("2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z") is False
    # 时间无法解析时视为有新版本
    assert update_logic.is_newer_test_release("garbage", "2026-01-01T00:00:00Z") is True


def test_get_exe_dir_dev_mode():
    with patch.object(update_logic.sys, "frozen", False, create=True):
        d = update_logic.get_exe_dir()
        assert d.is_dir()
        assert d.name == "auto-downloader"  # 项目根


def test_get_exe_path_dev_mode():
    with patch.object(update_logic.sys, "frozen", False, create=True):
        p = update_logic.get_exe_path()
        assert p.name == "main.py"
        assert p.is_file()


def test_get_exe_dir_frozen_mode():
    with (
        patch.object(update_logic.sys, "frozen", True, create=True),
        patch.object(update_logic.sys, "executable", r"C:\app\自动下载器.exe", create=True),
    ):
        assert str(update_logic.get_exe_dir()) == r"C:\app"


def test_cleanup_old_exe_removes_leftovers(tmp_path):
    old = tmp_path / update_logic.OLD_EXE_NAME
    temp = tmp_path / update_logic.TEMP_EXE_NAME
    old.write_bytes(b"x")
    temp.write_bytes(b"y")

    with patch.object(update_logic, "get_exe_dir", return_value=tmp_path):
        update_logic.cleanup_old_exe()

    assert not old.exists()
    assert not temp.exists()


def test_cleanup_old_exe_missing_files_no_error(tmp_path):
    with patch.object(update_logic, "get_exe_dir", return_value=tmp_path):
        update_logic.cleanup_old_exe()  # 不应抛异常
