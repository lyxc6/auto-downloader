"""下载项数据模型"""
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any
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
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        data = asdict(self)
        data['status'] = self.status.value
        data['item_type'] = self.item_type.value
        return data
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'DownloadItem':
        """从字典创建（不修改传入字典）"""
        data = dict(data)
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
    
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
