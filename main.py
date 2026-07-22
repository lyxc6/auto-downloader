#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""网站文件自动下载器 - 启动脚本"""

import sys
import os

# 添加src目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.app import Application


def main():
    """主函数"""
    app = Application()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
