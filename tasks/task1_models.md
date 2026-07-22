# 任务1：数据模型层 (Models)

## 任务描述
创建项目的数据模型层，定义所有数据结构和缓存管理。

## 文件清单
- `src/models/__init__.py`
- `src/models/download_item.py`
- `src/models/config.py`
- `src/models/cache_manager.py`

## 技术要求
- 使用 `dataclasses` 定义数据类
- 使用 `enum` 定义枚举类型
- JSON序列化/反序列化支持
- 线程安全的数据操作

---

## 文件1：src/models/download_item.py

```python
"""下载项数据模型"""
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional
import time


class DownloadStatus(Enum):
    """下载状态枚举"""
    PENDING = "pending"          # 等待下载
    DOWNLOADING = "downloading"  # 下载中
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"            # 失败
    SKIPPED = "skipped"          # 已跳过（文件已存在）


class ItemType(Enum):
    """项目类型枚举"""
    FILE = "file"   # 文件
    DIR = "dir"     # 目录


@dataclass
class DownloadItem:
    """下载项数据类"""
    item_id: str                    # 唯一标识（通常是完整路径）
    name: str                       # 文件/目录名
    url: str                        # 下载URL
    item_type: ItemType             # 项目类型
    parent_id: str = ""             # 父目录ID
    full_path: str = ""             # 完整路径
    size: int = 0                   # 文件大小（字节）
    downloaded_size: int = 0        # 已下载大小
    status: DownloadStatus = DownloadStatus.PENDING
    error_message: str = ""         # 错误信息
    created_at: float = field(default_factory=time.time)
    
    @property
    def progress(self) -> float:
        """下载进度百分比"""
        if self.size <= 0:
            return 0.0
        return min(100.0, (self.downloaded_size / self.size) * 100)
    
    @property
    def is_file(self) -> bool:
        """是否为文件"""
        return self.item_type == ItemType.FILE
    
    @property
    def is_dir(self) -> bool:
        """是否为目录"""
        return self.item_type == ItemType.DIR
    
    @property
    def status_text(self) -> str:
        """状态文本"""
        status_map = {
            DownloadStatus.PENDING: "等待中",
            DownloadStatus.DOWNLOADING: "下载中",
            DownloadStatus.COMPLETED: "已完成",
            DownloadStatus.FAILED: "失败",
            DownloadStatus.SKIPPED: "已跳过",
        }
        return status_map.get(self.status, "未知")
    
    def to_dict(self) -> dict:
        """转换为字典"""
        data = asdict(self)
        data['status'] = self.status.value
        data['item_type'] = self.item_type.value
        return data
    
    @classmethod
    def from_dict(cls, data: dict) -> 'DownloadItem':
        """从字典创建"""
        data['status'] = DownloadStatus(data['status'])
        data['item_type'] = ItemType(data['item_type'])
        return cls(**data)


@dataclass
class DownloadStats:
    """下载统计"""
    total_files: int = 0
    total_dirs: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    total_size: int = 0
    downloaded_size: int = 0
    
    @property
    def total_items(self) -> int:
        return self.total_files + self.total_dirs
    
    @property
    def progress(self) -> float:
        if self.total_files <= 0:
            return 0.0
        return (self.completed / self.total_files) * 100
    
    def to_dict(self) -> dict:
        return asdict(self)
```

---

## 文件2：src/models/config.py

```python
"""配置管理模型"""
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from typing import Optional


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
    
    # 界面设置
    theme: str = "auto"  # "light", "dark", "auto"
    language: str = "zh_CN"
    window_width: int = 1400
    window_height: int = 900
    
    # 最近使用的URL
    last_url: str = ""
    
    @property
    def cache_dir(self) -> str:
        """缓存目录"""
        if getattr(sys, 'frozen', False):
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
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存配置失败: {e}")
    
    @classmethod
    def load(cls) -> 'AppConfig':
        """加载配置"""
        config = cls()
        try:
            if os.path.exists(config.config_file):
                with open(config.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for key, value in data.items():
                        if hasattr(config, key):
                            setattr(config, key, value)
        except Exception as e:
            print(f"加载配置失败: {e}")
        return config
    
    def update(self, **kwargs):
        """更新配置"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
```

---

## 文件3：src/models/cache_manager.py

```python
"""缓存管理器"""
import json
import os
import time
from typing import Dict, Set, Optional
from .download_item import DownloadItem, ItemType


class CacheManager:
    """缓存管理器"""
    
    def __init__(self, cache_file: str):
        self.cache_file = cache_file
        self.tree_data: Dict[str, DownloadItem] = {}
        self.checked_items: Set[str] = set()
        self._lock = __import__('threading').Lock()
    
    def load(self) -> bool:
        """加载缓存"""
        try:
            if not os.path.exists(self.cache_file):
                return False
            
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 校验数据结构
            if not isinstance(data, dict):
                raise ValueError("缓存数据格式错误")
            
            # 加载tree_data
            tree_data = data.get("tree_data", {})
            if not isinstance(tree_data, dict):
                raise ValueError("tree_data格式错误")
            
            with self._lock:
                self.tree_data.clear()
                for item_id, item_dict in tree_data.items():
                    try:
                        self.tree_data[item_id] = DownloadItem.from_dict(item_dict)
                    except Exception:
                        continue
            
            # 加载checked_items
            checked_items = data.get("checked_items", [])
            if isinstance(checked_items, list):
                with self._lock:
                    self.checked_items = set(checked_items)
            
            return True
            
        except Exception as e:
            print(f"加载缓存失败: {e}")
            return False
    
    def save(self, url: str = ""):
        """保存缓存"""
        try:
            with self._lock:
                data = {
                    "url": url,
                    "tree_data": {k: v.to_dict() for k, v in self.tree_data.items()},
                    "checked_items": list(self.checked_items),
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }
            
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return True
            
        except Exception as e:
            print(f"保存缓存失败: {e}")
            return False
    
    def clear(self):
        """清空缓存"""
        with self._lock:
            self.tree_data.clear()
            self.checked_items.clear()
    
    def add_item(self, item: DownloadItem):
        """添加项目"""
        with self._lock:
            self.tree_data[item.item_id] = item
    
    def remove_item(self, item_id: str):
        """移除项目"""
        with self._lock:
            self.tree_data.pop(item_id, None)
            self.checked_items.discard(item_id)
    
    def get_item(self, item_id: str) -> Optional[DownloadItem]:
        """获取项目"""
        with self._lock:
            return self.tree_data.get(item_id)
    
    def toggle_check(self, item_id: str) -> bool:
        """切换选中状态"""
        with self._lock:
            if item_id in self.checked_items:
                self.checked_items.discard(item_id)
                return False
            else:
                self.checked_items.add(item_id)
                return True
    
    def is_checked(self, item_id: str) -> bool:
        """是否选中"""
        with self._lock:
            return item_id in self.checked_items
    
    def get_checked_files(self) -> list:
        """获取所有选中的文件"""
        with self._lock:
            return [
                item for item_id, item in self.tree_data.items()
                if item_id in self.checked_items and item.is_file
            ]
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        with self._lock:
            total_files = sum(1 for item in self.tree_data.values() if item.is_file)
            total_dirs = sum(1 for item in self.tree_data.values() if item.is_dir)
            checked_count = len(self.checked_items)
            return {
                "total_files": total_files,
                "total_dirs": total_dirs,
                "checked_count": checked_count
            }
```

---

## 文件4：src/models/__init__.py

```python
"""数据模型层"""
from .download_item import DownloadItem, DownloadStats, DownloadStatus, ItemType
from .config import AppConfig
from .cache_manager import CacheManager

__all__ = [
    'DownloadItem', 'DownloadStats', 'DownloadStatus', 'ItemType',
    'AppConfig', 'CacheManager'
]
```

---

## 验证标准

1. 所有文件无语法错误
2. 数据类可以正确序列化/反序列化
3. 缓存管理器线程安全
4. 配置可以正确加载和保存

## 测试命令

```bash
python -c "from src.models import *; print('Models OK')"
```
