"""缓存管理器"""

import json
import logging
import os
import time
from typing import Any, cast

from .download_item import DownloadItem

logger = logging.getLogger(__name__)


class CacheManager:
    """缓存管理器"""

    def __init__(self, cache_file: str):
        self.cache_file = cache_file
        self.tree_data: dict[str, DownloadItem] = {}
        self.checked_items: set[str] = set()
        self.scanned_dirs: set[str] = set()
        self.scan_complete: bool = False
        self.url: str = ""
        self._lock = __import__("threading").Lock()
        # 增量计数器（避免 get_stats 遍历 tree_data）
        self._file_count = 0
        self._dir_count = 0

    def load(self) -> bool:
        """加载缓存"""
        try:
            if not os.path.exists(self.cache_file):
                return False

            with open(self.cache_file, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)

            # 加载tree_data
            tree_data: dict[str, Any] = cast("dict[str, Any]", data.get("tree_data", {}))

            with self._lock:
                self.tree_data.clear()
                self._file_count = 0
                self._dir_count = 0
                for item_id, item_dict in tree_data.items():
                    try:
                        item = DownloadItem.from_dict(cast("dict[str, Any]", item_dict))
                        self.tree_data[str(item_id)] = item
                        if item.is_file:
                            self._file_count += 1
                        elif item.is_dir:
                            self._dir_count += 1
                    except Exception as e:
                        logger.warning("解析缓存项 %s 失败: %s", str(item_id), e)

            # 加载URL
            with self._lock:
                self.url = str(cast("str", data.get("url", "")))

            # 加载checked_items
            checked_items: list[Any] = cast("list[Any]", data.get("checked_items", []))
            with self._lock:
                self.checked_items = set(cast("list[str]", checked_items))

            # 加载 scanned_dirs 和 scan_complete
            scanned_dirs: list[Any] = cast("list[Any]", data.get("scanned_dirs", []))
            with self._lock:
                self.scanned_dirs = set(cast("list[str]", scanned_dirs))

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
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                }

            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            with open(self.cache_file, "w", encoding="utf-8") as f:
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
            self._file_count = 0
            self._dir_count = 0

    def clear_tree_data_only(self):
        """仅清空 tree_data 和 scan_complete，保留 checked_items、scanned_dirs、url（用于刷新场景）"""
        with self._lock:
            self.tree_data.clear()
            self.scan_complete = False
            self._file_count = 0
            self._dir_count = 0

    def save_scanned_dirs_backup(self) -> set[str]:
        """返回 scanned_dirs 快照（刷新前备份用）"""
        with self._lock:
            return set(self.scanned_dirs)

    def restore_scanned_dirs(self, backup: set[str]) -> None:
        """恢复 scanned_dirs（刷新失败时用）"""
        with self._lock:
            self.scanned_dirs = set(backup)

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

    def mark_dir_unscanned(self, dir_path: str) -> None:
        """移除目录的已扫描标记，允许重新扫描（线程安全）"""
        with self._lock:
            self.scanned_dirs.discard(dir_path)

    def is_dir_scanned(self, dir_path: str) -> bool:
        """目录是否已完全扫描"""
        with self._lock:
            return dir_path in self.scanned_dirs

    def get_scanned_dirs(self) -> set[str]:
        """获取已扫描目录集合快照（用于续扫时传给 ScanService）"""
        with self._lock:
            return set(self.scanned_dirs)

    def has_item(self, item_id: str) -> bool:
        """是否已存在该 item（用于续扫时去重计数）"""
        with self._lock:
            return item_id in self.tree_data

    def set_checked_items(self, items: set[str]) -> None:
        """整体替换勾选集合（线程安全）"""
        with self._lock:
            self.checked_items = set(items)

    def set_url(self, url: str) -> None:
        """设置当前 URL（线程安全）"""
        with self._lock:
            self.url = url

    def get_all_items(self) -> list[DownloadItem]:
        """获取所有项目（用于恢复到目录树）"""
        with self._lock:
            return sorted(self.tree_data.values(), key=lambda item: (item.full_path or "").count("/"))

    def get_tree_data_snapshot(self) -> dict[str, DownloadItem]:
        """返回 tree_data 的浅拷贝 dict（item_id -> DownloadItem）"""
        with self._lock:
            return dict(self.tree_data)

    def add_item(self, item: DownloadItem):
        """添加项目"""
        with self._lock:
            is_new = item.item_id not in self.tree_data
            self.tree_data[item.item_id] = item
            if is_new:
                if item.is_file:
                    self._file_count += 1
                elif item.is_dir:
                    self._dir_count += 1

    def try_add_item(self, item: DownloadItem) -> bool:
        """原子检查+添加（返回 True 表示真正新增，False 表示已存在跳过）"""
        with self._lock:
            if item.item_id in self.tree_data:
                return False
            self.tree_data[item.item_id] = item
            if item.is_file:
                self._file_count += 1
            elif item.is_dir:
                self._dir_count += 1
            return True

    def remove_item(self, item_id: str):
        """移除项目"""
        with self._lock:
            removed = self.tree_data.pop(item_id, None)
            if removed is not None:
                if removed.is_file:
                    self._file_count -= 1
                elif removed.is_dir:
                    self._dir_count -= 1
            self.checked_items.discard(item_id)

    def remove_directory_descendants(self, dir_item_id: str) -> set[str]:
        """移除目录的所有后代（含子目录和文件），返回被移除的 item_id 集合。线程安全。"""
        with self._lock:
            from collections import deque as _dq

            to_remove: set[str] = set()
            queue = _dq()
            for cid, item in self.tree_data.items():
                if item.parent_id == dir_item_id:
                    queue.append(cid)
            while queue:
                cid = queue.popleft()
                to_remove.add(cid)
                for child_id, child_item in self.tree_data.items():
                    if child_item.parent_id == cid:
                        queue.append(child_id)
            for rid in to_remove:
                removed = self.tree_data.pop(rid, None)
                if removed is not None:
                    if removed.is_file:
                        self._file_count -= 1
                    elif removed.is_dir:
                        self._dir_count -= 1
                self.checked_items.discard(rid)
            self.scanned_dirs.discard(dir_item_id)
            return to_remove

    def get_item(self, item_id: str) -> DownloadItem | None:
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

    def get_checked_files(self) -> list[DownloadItem]:
        """获取所有选中的文件"""
        with self._lock:
            return [item for item_id, item in self.tree_data.items() if item_id in self.checked_items and item.is_file]

    def get_stats(self) -> dict[str, int]:
        """获取统计信息（O(1)，使用增量计数器）"""
        with self._lock:
            return {
                "total_files": self._file_count,
                "total_dirs": self._dir_count,
                "checked_count": len(self.checked_items),
            }
