"""Pytest 全局配置"""
import os
import sys

# 将项目根目录加入 sys.path，使 `import src...` 在测试中可用
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
