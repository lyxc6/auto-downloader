"""扫描控制器"""

import logging
import threading
from time import monotonic

from PySide6.QtCore import QObject, Signal

from ..models import AppConfig, CacheManager, DownloadItem
from ..services import ScanService

logger = logging.getLogger(__name__)


class ScanController(QObject):
    """扫描控制器"""

    # 信号定义
    items_found = Signal(list)  # List[DownloadItem]（批量）
    scan_progress = Signal(int, int)  # current, total
    scan_completed = Signal(int, int)  # files, dirs
    scan_error = Signal(str)  # error_message
    log_message = Signal(str, str)  # message, level
    dir_scanned = Signal(str)  # dir_path（目录扫描完成）

    # 缓存相关信号
    cache_load_completed = Signal(dict, set)  # tree_data, checked_items（缓存加载完成）

    def __init__(self, config: AppConfig, cache_manager: CacheManager, parent: QObject | None = None):
        super().__init__(parent)
        self.config = config
        self.cache_manager = cache_manager
        self._service: ScanService | None = None
        self._thread: threading.Thread | None = None
        self._is_scanning = False
        self._lock = threading.Lock()

        # 刷新状态（scanned_dirs 备份，用于错误恢复）
        self._refresh_scanned_backup: set[str] | None = None

    @property
    def is_scanning(self) -> bool:
        """是否正在扫描"""
        with self._lock:
            return self._is_scanning

    def _create_service(self) -> ScanService:
        """创建扫描服务"""
        service = ScanService()

        # 设置回调（on_item_found 在 start_scan 中按批次覆盖）
        service.on_error = lambda msg: self.scan_error.emit(msg)
        service.on_log = lambda msg, level: self.log_message.emit(msg, level)

        return service

    def start_scan(
        self,
        url: str,
        max_depth: int | None = None,
        scanned_dirs: set[str] | None = None,
        scan_mode: str = "dfs",
        parallel: bool = False,
    ):
        """开始扫描

        Args:
            url: 扫描目标 URL
            max_depth: 最大递归深度
            scanned_dirs: 已扫描目录集合（续扫时跳过这些目录）
            scan_mode: 扫描模式 "dfs" 深度优先 / "bfs" 广度优先
            parallel: 是否启用并行扫描
        """
        with self._lock:
            if self._is_scanning:
                self.log_message.emit("扫描已在进行中", "warning")
                return
            self._is_scanning = True

        if max_depth is None:
            max_depth = self.config.max_depth

        mode_str = "并行" if parallel else "串行"
        self.log_message.emit("=" * 50, "header")
        self.log_message.emit(f"开始扫描目录结构（{mode_str} {scan_mode.upper()}）", "header")
        self.log_message.emit("=" * 50, "header")

        logger.info("开始扫描: %s (深度=%d, 模式=%s_%s)", url, max_depth, mode_str, scan_mode)

        def _scan_worker():
            try:
                self._service = self._create_service()
                self._service.parallel_mode = parallel

                # 续扫：传入已扫描目录集合
                if scanned_dirs:
                    self._service.set_scanned_dirs(scanned_dirs)

                file_count = 0
                dir_count = 0
                dirs_found = 0
                dirs_completed = 0
                buffer: list[DownloadItem] = []
                last_flush = monotonic()
                last_progress_log = monotonic()
                BATCH_SIZE = 50
                FLUSH_INTERVAL = 0.1
                PROGRESS_LOG_INTERVAL = 0.3
                PROGRESS_DIR_INTERVAL = 5
                _cb_lock = threading.Lock()

                def on_item_found(item: DownloadItem):
                    nonlocal file_count, dir_count, dirs_found, last_flush, buffer

                    # 续扫去重：原子检查+添加，已存在的 item 不覆盖（避免并行竞态损坏 parent_id）
                    if not self.cache_manager.try_add_item(item):
                        return

                    # 发现目录时标记为未完成（扫描完成后会由 on_dir_scanned 标记为已完成）
                    if item.is_dir:
                        self.cache_manager.mark_dir_unscanned(item.full_path)

                    with _cb_lock:
                        if item.is_file:
                            file_count += 1
                        else:
                            dir_count += 1
                            dirs_found += 1

                        buffer.append(item)

                        if len(buffer) >= BATCH_SIZE or (monotonic() - last_flush) >= FLUSH_INTERVAL:
                            self.items_found.emit(list(buffer))
                            self.scan_progress.emit(file_count, dir_count)
                            buffer = []
                            last_flush = monotonic()

                def on_dir_scanned(dir_path: str):
                    nonlocal dirs_completed, last_progress_log
                    self.cache_manager.mark_dir_scanned(dir_path)
                    self.dir_scanned.emit(dir_path)
                    with _cb_lock:
                        dirs_completed += 1
                        now = monotonic()
                        if (
                            dirs_completed % PROGRESS_DIR_INTERVAL == 0
                            or (now - last_progress_log) >= PROGRESS_LOG_INTERVAL
                        ):
                            self.log_message.emit(
                                f"扫描进度: 已完成 {dirs_completed}/{dirs_found} 个目录 | 发现 {file_count} 个文件",
                                "info",
                            )
                            last_progress_log = now

                # 设置回调
                self._service.on_item_found = on_item_found
                self._service.on_dir_scanned = on_dir_scanned

                # 执行扫描
                if parallel:
                    # 并行模式
                    if scan_mode == "bfs":
                        _ = self._service.scan_directory_bfs_parallel(
                            url, max_depth=max_depth, max_workers=self.config.scan_max_workers
                        )
                    else:
                        _ = self._service.scan_directory_parallel(
                            url, max_depth=max_depth, max_workers=self.config.scan_max_workers
                        )
                else:
                    # 串行模式
                    if scan_mode == "bfs":
                        _ = self._service.scan_directory_bfs(url, max_depth=max_depth)
                    else:
                        _ = self._service.scan_directory(url, max_depth=max_depth)

                # flush 剩余 buffer
                with _cb_lock:
                    if buffer:
                        self.items_found.emit(list(buffer))
                        self.scan_progress.emit(file_count, dir_count)
                        buffer = []

                # 扫描进度汇总
                if parallel:
                    self.log_message.emit(
                        f"扫描进度: 全部完成 {dirs_completed} 个目录 | 发现 {file_count} 个文件", "success"
                    )

                # 标记扫描完成状态（仅在未取消时）
                if not self._service.is_cancelled():
                    self.cache_manager.set_scan_complete(True)

                # 扫描完成
                self.scan_completed.emit(file_count, dir_count)

                logger.info("扫描完成: 文件=%d 目录=%d", file_count, dir_count)

                self.log_message.emit("", "info")
                self.log_message.emit("=" * 50, "header")
                self.log_message.emit("扫描完成！", "success")
                self.log_message.emit(f"文件: {file_count}, 目录: {dir_count}", "info")
                self.log_message.emit("=" * 50, "header")

                # 内部处理（刷新分支清理等）
                self._on_scan_completed_internal(file_count, dir_count)

            except Exception as e:
                logger.error("扫描失败", exc_info=True)
                self.scan_error.emit(str(e))
                self.log_message.emit(f"扫描失败: {e}", "error")
                # 内部错误处理（恢复备份等）
                self._on_scan_error_internal(str(e))
            finally:
                with self._lock:
                    self._is_scanning = False
                    if self._service is not None:
                        self._service.close()
                        self._service = None

        self._thread = threading.Thread(target=_scan_worker, daemon=True)
        self._thread.start()

    def start_directory_scan(self, base_url: str, dir_path: str, parent_id: str):
        """扫描单个目录（不递归到根，只扫描指定目录及其子目录）

        Args:
            base_url: 根 URL（如 https://example.com/index.php/224.html）
            dir_path: 要扫描的目录路径（如 写真）
            parent_id: 该目录的父 item_id
        """
        with self._lock:
            if self._is_scanning:
                self.log_message.emit("扫描已在进行中", "warning")
                return
            self._is_scanning = True

        self.log_message.emit(f"刷新目录: {dir_path or '/'}", "header")
        logger.info("开始单目录扫描: %s (dir=%s)", base_url, dir_path)

        def _dir_scan_worker():
            try:
                self._service = self._create_service()

                file_count = 0
                dir_count = 0
                buffer: list[DownloadItem] = []
                last_flush = monotonic()
                BATCH_SIZE = 50
                FLUSH_INTERVAL = 0.1
                _cb_lock = threading.Lock()

                def on_item_found(item: DownloadItem):
                    nonlocal file_count, dir_count, last_flush, buffer
                    if not self.cache_manager.try_add_item(item):
                        return
                    # 发现目录时标记为未完成
                    if item.is_dir:
                        self.cache_manager.mark_dir_unscanned(item.full_path)
                    with _cb_lock:
                        if item.is_file:
                            file_count += 1
                        else:
                            dir_count += 1
                        buffer.append(item)
                        if len(buffer) >= BATCH_SIZE or (monotonic() - last_flush) >= FLUSH_INTERVAL:
                            self.items_found.emit(list(buffer))
                            self.scan_progress.emit(file_count, dir_count)
                            buffer = []
                            last_flush = monotonic()

                self._service.on_item_found = on_item_found
                self._service.on_dir_scanned = lambda dp: (
                    self.cache_manager.mark_dir_scanned(dp),
                    self.dir_scanned.emit(dp),
                )

                self._service.scan_directory(
                    base_url, dir_path=dir_path, parent_id=parent_id, depth=0, max_depth=self.config.max_depth
                )

                with _cb_lock:
                    if buffer:
                        self.items_found.emit(list(buffer))
                        self.scan_progress.emit(file_count, dir_count)
                        buffer = []

                self.scan_completed.emit(file_count, dir_count)
                logger.info("单目录扫描完成: 文件=%d 目录=%d", file_count, dir_count)

                self.log_message.emit(f"目录刷新完成: 文件 {file_count}, 目录 {dir_count}", "success")
                self.cache_manager.save()

            except Exception as e:
                logger.error("目录扫描失败", exc_info=True)
                self.scan_error.emit(str(e))
                self.log_message.emit(f"目录扫描失败: {e}", "error")
            finally:
                with self._lock:
                    self._is_scanning = False
                    if self._service is not None:
                        self._service.close()
                        self._service = None

        self._thread = threading.Thread(target=_dir_scan_worker, daemon=True)
        self._thread.start()

    def cancel_scan(self):
        """取消扫描"""
        if self._service:
            self._service.cancel()
            logger.warning("用户取消扫描")
            self.log_message.emit("正在取消扫描...", "warning")

    def close_service(self):
        """关闭扫描服务（线程安全，可在应用关闭时调用）"""
        with self._lock:
            if self._service is not None:
                self._service.close()
                self._service = None

    def start_scan_with_cache(self, url: str, scan_mode: str = "dfs", parallel: bool = False):
        """智能扫描：自动处理缓存逻辑

        - 有缓存且扫描完成 → 发射 cache_load_completed 信号
        - 有缓存但扫描未完成 → 断点续扫
        - 无缓存 → 新扫描
        """
        # 相同URL且有缓存数据
        if self.cache_manager.has_data_for(url):
            logger.info("使用缓存数据恢复目录树: %s", url)

            # 发射缓存加载完成信号，由视图层处理UI更新
            self.cache_load_completed.emit(
                self.cache_manager.get_tree_data_snapshot(), self.cache_manager.checked_items
            )

            # 扫描完整 → 直接返回
            if self.cache_manager.is_scan_complete():
                self.log_message.emit("=" * 50, "header")
                self.log_message.emit("从缓存加载目录结构", "info")
                stats = self.cache_manager.get_stats()
                self.log_message.emit(f"文件: {stats['total_files']}, 目录: {stats['total_dirs']}", "info")
                self.log_message.emit("=" * 50, "header")
                self.scan_completed.emit(stats["total_files"], stats["total_dirs"])
                return

            # 扫描未完成 → 断点续扫
            scanned_dirs = self.cache_manager.get_scanned_dirs()
            logger.info("检测到未完成扫描，继续从断点扫描: %s (已扫描 %d 个目录)", url, len(scanned_dirs))
            stats = self.cache_manager.get_stats()
            self.log_message.emit("=" * 50, "header")
            self.log_message.emit("▶▶▶ 检测到未完成扫描，继续从断点续扫", "success")
            self.log_message.emit(
                f"已扫描目录: {len(scanned_dirs)} 个 | 已缓存: 文件 {stats['total_files']}, 目录 {stats['total_dirs']}",
                "info",
            )
            self.log_message.emit("=" * 50, "header")

            self.cache_manager.set_scan_complete(False)
            self.cache_manager.save()
            self.start_scan(
                url, scanned_dirs=self.cache_manager.get_scanned_dirs(), scan_mode=scan_mode, parallel=parallel
            )
            return

        # 无缓存，全新扫描
        self.cache_manager.clear()
        self.cache_manager.set_url(url)
        self.cache_manager.save()
        self.start_scan(url, scan_mode=scan_mode, parallel=parallel)

    def start_refresh(self, url: str, scan_mode: str = "dfs", parallel: bool = False):
        """强制刷新扫描（忽略缓存，保留已选状态）"""
        logger.info("强制刷新扫描: %s", url)

        # 备份 scanned_dirs，手动清空以强制重新扫描所有目录
        self._refresh_scanned_backup = self.cache_manager.save_scanned_dirs_backup()
        with self.cache_manager._lock:
            self.cache_manager.scanned_dirs.clear()
        self.cache_manager.clear_tree_data_only()
        self.cache_manager.set_url(url)

        self.start_scan(url, scan_mode=scan_mode, parallel=parallel)

    def start_directory_refresh(self, base_url: str, item_id: str, item_full_path: str, item_parent_id: str):
        """刷新单个目录（清除其子项，重新扫描该目录）"""
        if not base_url:
            self.log_message.emit("无有效URL，请先执行一次扫描", "error")
            return

        logger.info("刷新单个目录: %s (path=%s)", item_id, item_full_path)

        # 通知视图层移除子节点
        _removed_ids = set()  # 视图层负责实际移除

        # 清理缓存中的子节点
        self.cache_manager.remove_directory_descendants(item_id)
        self.cache_manager.mark_dir_unscanned(item_full_path)

        # 开始单目录扫描
        self.start_directory_scan(base_url, item_full_path, item_parent_id)

    def _on_scan_completed_internal(self, file_count: int, dir_count: int):
        """扫描完成处理"""
        self._refresh_scanned_backup = None
        self.cache_manager.save()

    def _on_scan_error_internal(self, error_msg: str):
        """扫描错误处理（恢复备份的 scanned_dirs）"""
        if self._refresh_scanned_backup is not None:
            self.cache_manager.restore_scanned_dirs(self._refresh_scanned_backup)
            self._refresh_scanned_backup = None
            logger.info("刷新失败，已恢复 scanned_dirs 备份")
