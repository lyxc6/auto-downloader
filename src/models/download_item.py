"""下载项数据模型"""

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class DownloadStatus(Enum):
    """下载状态枚举"""

    PENDING = "pending"  # 等待下载
    DOWNLOADING = "downloading"  # 下载中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败
    SKIPPED = "skipped"  # 已跳过（文件已存在）
    CANCELLED = "cancelled"  # 已取消


class ItemType(Enum):
    """项目类型枚举"""

    FILE = "file"  # 文件
    DIR = "dir"  # 目录


@dataclass
class DownloadItem:
    """下载项数据类

    字段语义：
    - item_id: 唯一标识，文件为 "目录路径/文件名"，目录为完整路径（与 full_path 相同）
    - full_path: 逻辑路径（"/" 分隔），文件与 item_id 相同；目录为不含前导斜杠的路径
    - parent_id: 父目录的 item_id（根级项目为空字符串）
    """

    item_id: str  # 唯一标识（文件/目录的完整逻辑路径）
    name: str  # 文件/目录名
    url: str  # 下载URL
    item_type: ItemType  # 项目类型
    parent_id: str = ""  # 父目录ID（根级为空）
    full_path: str = ""  # 完整路径（与 item_id 一致或为其规范化形式）
    size: int = 0  # 文件大小（字节）
    downloaded_size: int = 0  # 已下载大小
    status: DownloadStatus = DownloadStatus.PENDING
    error_message: str = ""  # 错误信息
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

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        data = asdict(self)
        data["status"] = self.status.value
        data["item_type"] = self.item_type.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DownloadItem":
        """从字典创建（不修改传入字典）

        宽容反序列化：缺失或未知的 status/item_type 回退默认值，不抛异常。
        """
        data = dict(data)
        try:
            status = DownloadStatus(data["status"])
        except (KeyError, ValueError):
            status = DownloadStatus.PENDING
        try:
            item_type = ItemType(data["item_type"])
        except (KeyError, ValueError):
            item_type = ItemType.FILE
        data["status"] = status
        data["item_type"] = item_type
        return cls(**data)


@dataclass
class DownloadStats:
    """下载统计"""

    total_files: int = 0
    total_dirs: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    cancelled: int = 0
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CacheStats:
    """缓存统计信息"""

    total_files: int = 0
    total_dirs: int = 0
    checked_count: int = 0
    unscanned_count: int = 0
