"""配置管理模型"""

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AppConfig:
    """应用配置"""

    # 下载设置
    download_dir: str = "downloads"
    max_workers: int = 3
    retry_times: int = 3
    timeout: int = 120

    # 扫描设置
    max_depth: int = 10
    scan_delay: float = 0.15  # 扫描间隔（秒）
    scan_mode: str = "dfs"  # "dfs" 深度优先, "bfs" 广度优先
    scan_max_workers: int = 3  # 扫描并发数

    # 界面设置
    theme: str = "auto"  # "light", "dark", "auto"
    language: str = "zh_CN"
    window_width: int = 1400
    window_height: int = 900

    # 更新设置
    update_channel: str = "stable"  # "stable" 稳定版 / "test" 测试版
    auto_check_update: bool = True  # 启动时自动检查更新
    last_update_check_time: str = ""  # 上次检查更新的时间

    # 最近使用的URL
    last_url: str = "https://www.flyingfry.cc/index.php/224.html"

    @property
    def cache_dir(self) -> str:
        """缓存目录"""
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    @property
    def cache_file(self) -> str:
        """缓存文件路径"""
        return os.path.join(self.cache_dir, "cache.json")

    @property
    def config_file(self) -> str:
        """配置文件路径"""
        return os.path.join(self.cache_dir, "config.json")

    def save(self):
        """保存配置"""
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        except Exception:
            logger.error("保存配置失败", exc_info=True)

    @classmethod
    def load(cls) -> "AppConfig":
        """加载配置"""
        config = cls()
        try:
            if os.path.exists(config.config_file):
                with open(config.config_file, encoding="utf-8") as f:
                    data = json.load(f)
                    for key, value in data.items():
                        if hasattr(config, key):
                            setattr(config, key, value)
        except Exception:
            logger.error("加载配置失败", exc_info=True)
        return config

    def update(self, **kwargs: Any):
        """更新配置"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
