"""Pytest 全局配置"""

import os
import sys

# 将项目根目录加入 sys.path，使 `import src...` 在测试中可用
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def pytest_collection_modifyitems(config, items):
    """自动为所有测试添加 timeout，避免卡死"""
    import pytest

    timeout = config.getoption("timeout", default=None)
    if timeout:
        for item in items:
            if "timeout" not in item.keywords:
                item.add_marker(pytest.mark.timeout(timeout))
