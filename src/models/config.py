"""配置管理模型"""

import json
import logging
import os
from dataclasses import asdict, dataclass
from typing import Any

from ..utils.helpers import get_app_dir

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
    scan_timeout: float = 0.0  # 无进展超时（秒），0 表示不限时
    dir_scan_timeout: float = 30.0  # 单个目录扫描超时（秒），0 表示不限时

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
        """缓存目录（exe 所在目录或项目根目录）"""
        return get_app_dir()

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
            # 写入临时文件，然后原子替换，防止崩溃时损坏配置文件
            temp_file = self.config_file + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, ensure_ascii=False, indent=2)
            os.replace(temp_file, self.config_file)
        except Exception:
            logger.error("保存配置失败", exc_info=True)

    @classmethod
    def load(cls) -> "AppConfig":
        """加载配置

        文件不存在（首次运行）时静默返回默认值；文件损坏时记录告警并回退默认值。
        """
        config = cls()
        if not os.path.exists(config.config_file):
            logger.debug("配置文件不存在，使用默认配置: %s", config.config_file)
            return config

        try:
            with open(config.config_file, encoding="utf-8") as f:
                data = json.load(f)
                for key, value in data.items():
                    if hasattr(config, key):
                        current_value = getattr(config, key)
                        field_type = type(current_value)
                        # 尝试类型转换
                        try:
                            if field_type is bool and isinstance(value, str):
                                value = value.lower() in ("true", "1", "yes")
                            elif field_type is int and isinstance(value, (int, float)):
                                value = int(value)
                            elif field_type is float and isinstance(value, (int, float)):
                                value = float(value)
                            setattr(config, key, value)
                        except (ValueError, TypeError):
                            logger.warning(
                                "配置项 %s 类型错误: 期望 %s, 得到 %s",
                                key,
                                field_type.__name__,
                                type(value).__name__,
                            )
        except Exception:
            logger.warning("配置文件损坏，已回退默认配置: %s", config.config_file)
        return config

    def update(self, **kwargs: Any) -> set[str]:
        """更新配置（未知键忽略并告警）

        Returns:
            实际被接受的键集合
        """
        accepted: set[str] = set()
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
                accepted.add(key)
            else:
                logger.warning("忽略未知配置项: %s", key)
        return accepted
