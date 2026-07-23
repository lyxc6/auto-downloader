"""缓存管理器"""
import json
import logging
import os
import time
from typing import Any, Dict, List, Set, Optional, cast
from .download_item import DownloadItem

logger = logging.getLogger(__name__)


class CacheManager:
    """缓存管理器"""
    
    def __init__(self, cache_file: str):
        self.cache_file = cache_file
        self.tree_data: Dict[str, DownloadItem] = {}
        self.checked_items: Set[str] = set()
        self.scanned_dirs: Set[str] = set()
        self.scan_complete: bool = False
        self.url: str = ""
        self._lock = __import__('threading').Lock()
    
    def load(self) -> bool:
        """加载缓存"""
        try:
            if not os.path.exists(self.cache_file):
                return False
            
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                data: dict[str, Any] = json.load(f)
            
            # 加载tree_data
            tree_data: dict[str, Any] = cast(dict[str, Any], data.get("tree_data", {}))
            
            with self._lock:
                self.tree_data.clear()
                for item_id, item_dict in tree_data.items():
                    try:
                        self.tree_data[str(item_id)] = DownloadItem.from_dict(cast(dict[str, Any], item_dict))
                    except Exception as e:
                        logger.warning("解析缓存项 %s 失败: %s", str(item_id), e)
            
            # 加载URL
            with self._lock:
                self.url = str(cast(str, data.get("url", "")))
            
            # 加载checked_items
            checked_items: list[Any] = cast(list[Any], data.get("checked_items", []))
            with self._lock:
                self.checked_items = set(cast(list[str], checked_items))
            
            # 加载 scanned_dirs 和 scan_complete
            scanned_dirs: list[Any] = cast(list[Any], data.get("scanned_dirs", []))
            with self._lock:
                self.scanned_dirs = set(cast(list[str], scanned_dirs))
            
            with self._lock:
                self.scan_complete = bool(data.get("scan_complete", False))
            
            return True
            
        except Exception:
            logger.error("加载缓存失败", exc_info=True)
            return False
    
    def save(self, url: str = ""):
        """保存缓存"""
        try:
            with self._lock:
                if url:
                    self.url = url
                else:
                    url = self.url
                data: dict[str, Any] = {
                    "url": url,
                    "tree_data": {k: v.to_dict() for k, v in self.tree_data.items()},
                    "checked_items": list(self.checked_items),
                    "scanned_dirs": list(self.scanned_dirs),
                    "scan_complete": self.scan_complete,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }
            
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return True
            
        except Exception:
            logger.error("保存缓存失败", exc_info=True)
            return False
    
    def clear(self):
        """清空缓存"""
        with self._lock:
            self.tree_data.clear()
            self.checked_items.clear()
            self.scanned_dirs.clear()
            self.scan_complete = False
            self.url = ""
    
    def clear_tree_data_only(self):
        """仅清空 tree_data，保留 checked_items 和 url（用于刷新场景）"""
        with self._lock:
            self.tree_data.clear()
            self.scanned_dirs.clear()
            self.scan_complete = False
    
    def cleanup_checked(self):
        """剔除 checked_items 中已不在 tree_data 里的失效 id"""
        with self._lock:
            self.checked_items &= set(self.tree_data.keys())
    
    def has_data_for(self, url: str) -> bool:
        """是否已有指定URL的缓存数据"""
        with self._lock:
            return self.url == url and len(self.tree_data) > 0

    def is_scan_complete(self) -> bool:
        """扫描是否完整结束"""
        with self._lock:
            return self.scan_complete

    def set_scan_complete(self, complete: bool) -> None:
        """设置扫描完成状态（线程安全）"""
        with self._lock:
            self.scan_complete = complete

    def mark_dir_scanned(self, dir_path: str) -> None:
        """标记目录为已完全扫描（线程安全）"""
        with self._lock:
            self.scanned_dirs.add(dir_path)

    def is_dir_scanned(self, dir_path: str) -> bool:
        """目录是否已完全扫描"""
        with self._lock:
            return dir_path in self.scanned_dirs

    def get_scanned_dirs(self) -> Set[str]:
        """获取已扫描目录集合快照（用于续扫时传给 ScanService）"""
        with self._lock:
            return set(self.scanned_dirs)

    def has_item(self, item_id: str) -> bool:
        """是否已存在该 item（用于续扫时去重计数）"""
        with self._lock:
            return item_id in self.tree_data

    def set_checked_items(self, items: Set[str]) -> None:
        """整体替换勾选集合（线程安全）"""
        with self._lock:
            self.checked_items = set(items)

    def set_url(self, url: str) -> None:
        """设置当前 URL（线程安全）"""
        with self._lock:
            self.url = url
    
    def get_all_items(self) -> List[DownloadItem]:
        """获取所有项目（用于恢复到目录树）"""
        with self._lock:
            return sorted(
                self.tree_data.values(),
                key=lambda item: (item.full_path or "").count("/")
            )

    def get_tree_data_snapshot(self) -> Dict[str, DownloadItem]:
        """返回 tree_data 的浅拷贝 dict（item_id -> DownloadItem）"""
        with self._lock:
            return dict(self.tree_data)
    
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
    
    def get_checked_files(self) -> List[DownloadItem]:
        """获取所有选中的文件"""
        with self._lock:
            return [
                item for item_id, item in self.tree_data.items()
                if item_id in self.checked_items and item.is_file
            ]
    
    def get_stats(self) -> Dict[str, int]:
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
