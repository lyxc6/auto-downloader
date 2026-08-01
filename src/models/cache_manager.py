"""缓存管理器"""

import json
import logging
import os
import threading
import time
import uuid
from typing import Any, cast

from .download_item import CacheStats, DownloadItem

logger = logging.getLogger(__name__)

# 缓存文件格式版本（向后兼容用）
CACHE_VERSION = 1


class CacheManager:
    """缓存管理器

    锁纪律：所有公开方法内部加锁；对外返回的 DownloadItem 是活对象引用，
    修改其字段（如 size/status）由调用方保证不与扫描/下载线程并发冲突
    （当前约定：大小预取与下载线程只写自身关注的字段）。
    """

    def __init__(self, cache_file: str):
        self.cache_file = cache_file
        self.tree_data: dict[str, DownloadItem] = {}
        self.checked_items: set[str] = set()
        self.scanned_dirs: set[str] = set()
        self.unscanned_dirs: set[str] = set()
        self.scan_complete: bool = False
        self.url: str = ""
        self._lock = threading.Lock()
        # 增量计数器（避免 get_stats 遍历 tree_data）
        self._file_count = 0
        self._dir_count = 0

    def load(self) -> bool:
        """加载缓存（单次加锁形成一致快照）"""
        try:
            if not os.path.exists(self.cache_file):
                return False

            with open(self.cache_file, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)

            # 宽容反序列化：坏条目跳过，不破坏整体加载
            tree_data: dict[str, Any] = cast("dict[str, Any]", data.get("tree_data", {}))
            loaded_tree: dict[str, DownloadItem] = {}
            file_count = 0
            dir_count = 0
            for item_id, item_dict in tree_data.items():
                try:
                    item = DownloadItem.from_dict(cast("dict[str, Any]", item_dict))
                    loaded_tree[str(item_id)] = item
                    if item.is_file:
                        file_count += 1
                    elif item.is_dir:
                        dir_count += 1
                except Exception as e:
                    logger.warning("解析缓存项 %s 失败: %s", str(item_id), e)

            # 单次加锁：一次性写入全部状态，避免跨锁区间的混合快照
            with self._lock:
                self.tree_data = loaded_tree
                self._file_count = file_count
                self._dir_count = dir_count
                self.url = str(cast("str", data.get("url", "")))
                self.checked_items = set(cast("list[str]", data.get("checked_items", [])))
                self.scanned_dirs = set(cast("list[str]", data.get("scanned_dirs", [])))
                self.unscanned_dirs = set(cast("list[str]", data.get("unscanned_dirs", [])))
                self.scan_complete = bool(data.get("scan_complete", False))

            return True

        except Exception:
            logger.error("加载缓存失败", exc_info=True)
            return False

    def save(self, url: str = "") -> bool:
        """保存缓存（原子写入：唯一临时文件 + 替换，避免并发写同一临时文件）

        Returns:
            True 表示保存成功
        """
        try:
            with self._lock:
                if url:
                    self.url = url
                else:
                    url = self.url
                data: dict[str, Any] = {
                    "version": CACHE_VERSION,
                    "url": url,
                    "tree_data": {k: v.to_dict() for k, v in self.tree_data.items()},
                    "checked_items": list(self.checked_items),
                    "scanned_dirs": list(self.scanned_dirs),
                    "unscanned_dirs": list(self.unscanned_dirs),
                    "scan_complete": self.scan_complete,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                }

            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            # 唯一临时文件名：并发 save（自动保存定时器/扫描线程/SIGINT）互不干扰
            temp_file = f"{self.cache_file}.{uuid.uuid4().hex}.tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            # 原子替换：在 Windows 上 os.replace 会自动处理
            os.replace(temp_file, self.cache_file)

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
            self.unscanned_dirs.clear()
            self.scan_complete = False
            self.url = ""
            self._file_count = 0
            self._dir_count = 0

    def clear_tree_data_only(self):
        """仅清空 tree_data 和 scan_complete，保留 checked_items、scanned_dirs、url（用于刷新场景）"""
        with self._lock:
            self.tree_data.clear()
            self.scan_complete = False
            self.unscanned_dirs.clear()
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

    def clear_scanned_dirs(self):
        """清空已扫描目录（线程安全）"""
        with self._lock:
            self.scanned_dirs.clear()

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
            self.unscanned_dirs.discard(dir_path)

    def mark_dir_unscanned(self, dir_path: str) -> None:
        """标记目录为未完全扫描（线程安全）"""
        with self._lock:
            self.scanned_dirs.discard(dir_path)
            self.unscanned_dirs.add(dir_path)

    def is_dir_scanned(self, dir_path: str) -> bool:
        """目录是否已完全扫描"""
        with self._lock:
            return dir_path in self.scanned_dirs

    def get_scanned_dirs(self) -> set[str]:
        """获取已扫描目录集合快照（用于续扫时传给 ScanService）"""
        with self._lock:
            return set(self.scanned_dirs)

    def get_unscanned_dirs(self) -> set[str]:
        """获取未完全扫描目录集合快照"""
        with self._lock:
            return set(self.unscanned_dirs)

    def checked_items_snapshot(self) -> set[str]:
        """获取勾选集合快照（线程安全，供外部读取）"""
        with self._lock:
            return set(self.checked_items)

    def checked_count(self) -> int:
        """获取勾选数量（O(1)，线程安全）"""
        with self._lock:
            return len(self.checked_items)

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

    def remove_directory_descendants(self, dir_item_id: str) -> set[str]:
        """移除目录的所有后代（含子目录和文件），返回被移除的 item_id 集合。线程安全。

        使用一次构建的 parent_id → children 索引做 BFS，复杂度 O(N)（原来每次全表扫描 O(N²)）。
        """
        with self._lock:
            # 构建 parent_id → children 索引
            children_index: dict[str, list[str]] = {}
            for cid, item in self.tree_data.items():
                children_index.setdefault(item.parent_id, []).append(cid)

            # BFS 收集后代
            to_remove: set[str] = set()
            queue = list(children_index.get(dir_item_id, []))
            while queue:
                cid = queue.pop()
                if cid in to_remove:
                    continue
                to_remove.add(cid)
                queue.extend(children_index.get(cid, []))

            for rid in to_remove:
                removed = self.tree_data.pop(rid, None)
                if removed is not None:
                    if removed.is_file:
                        self._file_count -= 1
                    elif removed.is_dir:
                        self._dir_count -= 1
                self.checked_items.discard(rid)
                self.unscanned_dirs.discard(rid)
            self.scanned_dirs.discard(dir_item_id)
            return to_remove

    def get_item(self, item_id: str) -> DownloadItem | None:
        """获取项目"""
        with self._lock:
            return self.tree_data.get(item_id)

    def update_item_size(self, item_id: str, size: int) -> bool:
        """更新项目文件大小（线程安全）

        Returns:
            True 表示更新成功，False 表示项目不存在
        """
        with self._lock:
            item = self.tree_data.get(item_id)
            if item is not None:
                item.size = size
                return True
            return False

    def toggle_check(self, item_id: str) -> bool:
        """切换选中状态

        Returns:
            True 表示切换后处于勾选状态，False 表示切换后未勾选
        """
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

    def get_stats(self) -> CacheStats:
        """获取统计信息（O(1)，使用增量计数器）"""
        with self._lock:
            return CacheStats(
                total_files=self._file_count,
                total_dirs=self._dir_count,
                checked_count=len(self.checked_items),
                unscanned_count=len(self.unscanned_dirs),
            )
