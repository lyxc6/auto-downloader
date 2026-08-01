"""scan_completed 信号契约回归测试 (P0-1)

验证:
- app 的 _on_scan_completed 槽函数签名可接收信号的全部 3 个参数 (files, dirs, dir_path)
- 真实控制器发射 scan_completed 不因参数不匹配抛 TypeError
"""

import inspect

from src.app import Application
from src.controllers.scan_controller import ScanController
from src.models import AppConfig, CacheManager


def test_app_handler_signature_accepts_three_args():
    """_on_scan_completed 参数数必须 >= 信号参数数 (files, dirs, dir_path)"""
    params = inspect.signature(Application._on_scan_completed).parameters
    assert len(params) >= 3, f"_on_scan_completed 参数不足: {list(params)}"


def test_scan_completed_signal_emits_without_typeerror():
    """真实 ScanController 连接 3 参槽函数并发射，不得抛异常"""
    controller = ScanController(AppConfig(), CacheManager(""))
    received = {}

    def slot(files: int, dirs: int, dir_path: str):
        received["files"] = files
        received["dirs"] = dirs
        received["dir_path"] = dir_path

    controller.scan_completed.connect(slot)
    controller.scan_completed.emit(12, 34, "写真")
    assert received == {"files": 12, "dirs": 34, "dir_path": "写真"}

    # 全量扫描路径 dir_path 为空字符串
    controller.scan_completed.emit(1, 2, "")
    assert received["dir_path"] == ""
