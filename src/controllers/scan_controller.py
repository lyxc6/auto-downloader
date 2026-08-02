"""扫描控制器：状态管理 + 信号桥 + 缓存决策（工作线程体见 ScanRunner，大小预取见 SizePrefetcher）"""

import logging
import threading
from time import monotonic

from PySide6.QtCore import QObject, Signal

from ..models import AppConfig, CacheManager
from ..services import ScanService
from .scan_runner import ScanRunner
from .size_prefetcher import SizePrefetcher

logger = logging.getLogger(__name__)


class ScanController(QObject):
    """扫描控制器"""

    # 信号定义
    items_found = Signal(list)  # List[DownloadItem]（批量）
    scan_progress = Signal(int, int)  # current, total
    scan_completed = Signal(int, int, str)  # files, dirs, dir_path (空=全量扫描)
    scan_error = Signal(str)  # error_message
    log_message = Signal(str, str)  # message, level
    dir_scanned = Signal(str)  # dir_path（目录扫描完成）

    # 缓存相关信号
    cache_load_completed = Signal(dict, set)  # tree_data, checked_items（缓存加载完成）

    # 文件大小预取信号
    size_prefetch_progress = Signal(str, int)  # item_id, size（每完成一个文件）
    size_prefetch_completed = Signal()  # 全部完成

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

        # 本次扫描是否被中断（取消/超时），用于跳过完成后的副作用（如大小预取）
        self._scan_interrupted = threading.Event()

        # 文件大小预取
        self._prefetch = SizePrefetcher(self.cache_manager, self.log_message.emit)
        self._prefetch.progress.connect(self.size_prefetch_progress.emit)
        self._prefetch.completed.connect(self.size_prefetch_completed.emit)

    @property
    def is_scanning(self) -> bool:
        """是否正在扫描"""
        with self._lock:
            return self._is_scanning

    @property
    def last_scan_interrupted(self) -> bool:
        """本次扫描是否被中断（取消/超时）"""
        return self._scan_interrupted.is_set()

    def _create_service(self) -> ScanService:
        """创建扫描服务"""
        service = ScanService(
            scan_delay=self.config.scan_delay,
            scan_timeout=self.config.scan_timeout,
            dir_scan_timeout=self.config.dir_scan_timeout,
        )

        # 设置回调（on_item_found 在 start_scan 中按批次覆盖）
        service.on_error = lambda msg: self.scan_error.emit(msg)
        service.on_log = lambda msg, level: self.log_message.emit(msg, level)

        return service

    def _create_runner(self) -> ScanRunner:
        """创建扫描运行器（节流/计数/进度日志）"""
        runner = ScanRunner(self.cache_manager, clock=monotonic)
        runner.on_item_found_batch = self._on_items_found_batch
        runner.on_progress = lambda files, dirs: self.scan_progress.emit(files, dirs)
        runner.on_log = lambda msg, level: self.log_message.emit(msg, level)
        runner.on_dir_scanned = lambda dp: self.dir_scanned.emit(dp)
        return runner

    def _on_items_found_batch(self, items: list) -> None:
        """批量 item 回调：转发给视图 + 边扫边取（提交文件到大小预取队列）"""
        for item in items:
            if item.is_file:
                self._prefetch.submit(item)
        self.items_found.emit(items)

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

        self._scan_interrupted.clear()

        if max_depth is None:
            max_depth = self.config.max_depth

        mode_str = "并行" if parallel else "串行"
        self.log_message.emit("=" * 50, "header")
        self.log_message.emit(f"开始扫描目录结构（{mode_str} {scan_mode.upper()}）", "header")
        self.log_message.emit("=" * 50, "header")

        logger.info("开始扫描: %s (深度=%d, 模式=%s_%s)", url, max_depth, mode_str, scan_mode)

        def _scan_worker():
            runner: ScanRunner | None = None
            try:
                self._service = self._create_service()
                self._service.parallel_mode = parallel

                # 续扫：传入已扫描目录集合
                if scanned_dirs:
                    self._service.set_scanned_dirs(scanned_dirs)

                runner = self._create_runner()
                self._service.on_item_found = runner.handle_item
                self._service.on_dir_scanned = runner.handle_dir_scanned

                # 方案B：边扫边取——启动大小预取消费线程（兜底收集缓存中已有 size<=0 文件）
                self._prefetch.start(max_workers=self.config.scan_max_workers, dir_path="")

                # 执行扫描
                _ = self._service.scan(
                    url,
                    scan_mode=scan_mode,
                    parallel=parallel,
                    max_depth=max_depth,
                    max_workers=self.config.scan_max_workers,
                )

                # flush 剩余 buffer
                runner.flush()

                # 检查是否因超时停止
                if self._service.is_timeout():
                    self._scan_interrupted.set()
                    self._prefetch.cancel()
                    self.log_message.emit("扫描超时，已自动停止", "warning")
                    self.log_message.emit(
                        f"已扫描: 文件 {runner.file_count}, 目录 {runner.dir_count}（已保存）", "info"
                    )
                # 检查是否因取消停止
                elif self._service.is_cancelled():
                    self._scan_interrupted.set()
                    self._prefetch.cancel()
                    self.log_message.emit("扫描已取消", "warning")
                else:
                    # 扫描正常完成：通知预取队列结束（耗尽后自动发 completed）
                    self._prefetch.done()
                    # 扫描进度汇总
                    if parallel:
                        self.log_message.emit(
                            f"扫描进度: 全部完成 {runner.dirs_completed} 个目录 | 发现 {runner.file_count} 个文件",
                            "success",
                        )

                # 标记扫描完成状态（仅在正常完成时）
                if not self._service.is_cancelled() and not self._service.is_timeout():
                    self.cache_manager.set_scan_complete(True)

                # 扫描完成
                self.scan_completed.emit(runner.file_count, runner.dir_count, "")

                logger.info("扫描完成: 文件=%d 目录=%d", runner.file_count, runner.dir_count)

                self.log_message.emit("", "info")
                self.log_message.emit("=" * 50, "header")
                self.log_message.emit("扫描完成！", "success")
                self.log_message.emit(f"文件: {runner.file_count}, 目录: {runner.dir_count}", "info")
                # 显示失败统计
                failed_dirs = self._service.get_failed_dirs_count()
                if failed_dirs > 0:
                    self.log_message.emit(
                        f"注意: {failed_dirs} 个目录因服务器错误未获取到内容",
                        "warning",
                    )
                error_dirs = self._service.get_error_dirs_count()
                if error_dirs > 0:
                    self.log_message.emit(
                        f"注意: {error_dirs} 个目录因服务器错误返回空内容",
                        "warning",
                    )
                self.log_message.emit("=" * 50, "header")

                # 内部处理（刷新分支清理等）
                self._on_scan_completed_internal(runner.file_count, runner.dir_count)

            except Exception as e:
                logger.error("扫描失败", exc_info=True)
                self._prefetch.cancel()
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

    def start_directory_scan(
        self, base_url: str, dir_path: str, parent_id: str, scan_mode: str = "dfs", parallel: bool = False
    ):
        """扫描单个目录（不递归到根，只扫描指定目录及其子目录）

        Args:
            base_url: 根 URL（如 https://example.com/index.php/224.html）
            dir_path: 要扫描的目录路径（如 写真）
            parent_id: 该目录的父 item_id
            scan_mode: 扫描模式 "dfs" 深度优先 / "bfs" 广度优先
            parallel: 是否启用并行扫描
        """
        with self._lock:
            if self._is_scanning:
                self.log_message.emit("扫描已在进行中", "warning")
                return
            self._is_scanning = True

        self._scan_interrupted.clear()

        self.log_message.emit(f"刷新目录: {dir_path or '/'}", "header")
        logger.info("开始单目录扫描: %s (dir=%s)", base_url, dir_path)

        def _dir_scan_worker():
            runner: ScanRunner | None = None
            try:
                self._service = self._create_service()
                self._service.parallel_mode = parallel

                runner = self._create_runner()
                self._service.on_item_found = runner.handle_item
                self._service.on_dir_scanned = runner.handle_dir_scanned

                # 方案B：边扫边取——单目录刷新只预取该目录下文件
                self._prefetch.start(max_workers=self.config.scan_max_workers, dir_path=dir_path)

                self._service.scan(
                    base_url,
                    scan_mode=scan_mode,
                    parallel=parallel,
                    dir_path=dir_path,
                    parent_id=parent_id,
                    max_depth=self.config.max_depth,
                )

                runner.flush()

                if self._service.is_timeout() or self._service.is_cancelled():
                    self._scan_interrupted.set()
                    self._prefetch.cancel()
                    self.log_message.emit("目录刷新已取消", "warning")
                else:
                    self._prefetch.done()

                self.scan_completed.emit(runner.file_count, runner.dir_count, dir_path)
                logger.info("单目录扫描完成: 文件=%d 目录=%d", runner.file_count, runner.dir_count)

                self.log_message.emit(f"目录刷新完成: 文件 {runner.file_count}, 目录 {runner.dir_count}", "success")
                self.cache_manager.save()

            except Exception as e:
                logger.error("目录扫描失败", exc_info=True)
                self._prefetch.cancel()
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
        with self._lock:
            if self._service is not None:
                self._service.cancel()
        logger.warning("用户取消扫描")
        self.log_message.emit("正在取消扫描...", "warning")

    def close_service(self):
        """关闭扫描服务（线程安全，可在应用关闭时调用）"""
        with self._lock:
            if self._service is not None:
                self._service.close()
                self._service = None
        # 等待工作线程结束
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)
            self._thread = None

    def start_size_prefetch(self, max_workers: int = 5, dir_path: str = ""):
        """扫描完成后，并行发送 HEAD 请求预取文件大小

        Args:
            max_workers: 并行线程数
            dir_path: 指定目录路径（空=预取全部，非空=只预取该目录下的文件）
        """
        self._prefetch.start(max_workers=max_workers, dir_path=dir_path)

    def cancel_size_prefetch(self):
        """取消文件大小预取"""
        self._prefetch.cancel()

    def load_cache_into_ui(self, url: str) -> bool:
        """启动时从缓存恢复目录树到 UI（无缓存则跳过）

        Args:
            url: 上次扫描的 URL

        Returns:
            True 表示成功加载缓存
        """
        if not url or not self.cache_manager.has_data_for(url):
            return False
        logger.info("启动时自动加载缓存: %s", url)
        self.cache_load_completed.emit(
            self.cache_manager.get_tree_data_snapshot(), self.cache_manager.checked_items_snapshot()
        )
        return True

    def start_scan_with_cache(self, url: str, scan_mode: str = "dfs", parallel: bool = False):
        """智能扫描：自动处理缓存逻辑

        - 有缓存且扫描完成 → 发射 cache_load_completed 信号
        - 有缓存但扫描未完成 → 断点续扫
        - 无缓存 → 新扫描
        """
        self._scan_interrupted.clear()  # 相同URL且有缓存数据
        if self.cache_manager.has_data_for(url):
            logger.info("使用缓存数据恢复目录树: %s", url)

            # 发射缓存加载完成信号，由视图层处理UI更新
            self.cache_load_completed.emit(
                self.cache_manager.get_tree_data_snapshot(), self.cache_manager.checked_items_snapshot()
            )

            # 扫描完整 → 直接返回（补一轮兜底大小预取）
            if self.cache_manager.is_scan_complete():
                self.log_message.emit("=" * 50, "header")
                self.log_message.emit("从缓存加载目录结构", "info")
                stats = self.cache_manager.get_stats()
                self.log_message.emit(f"文件: {stats.total_files}, 目录: {stats.total_dirs}", "info")
                self.log_message.emit("=" * 50, "header")
                self._prefetch.start(max_workers=self.config.scan_max_workers)
                self._prefetch.done()
                self.scan_completed.emit(stats.total_files, stats.total_dirs, "")
                return

            # 扫描未完成 → 断点续扫
            scanned_dirs = self.cache_manager.get_scanned_dirs()
            logger.info("检测到未完成扫描，继续从断点扫描: %s (已扫描 %d 个目录)", url, len(scanned_dirs))
            stats = self.cache_manager.get_stats()
            self.log_message.emit("=" * 50, "header")
            self.log_message.emit("▶▶▶ 检测到未完成扫描，继续从断点续扫", "success")
            self.log_message.emit(
                f"已扫描目录: {len(scanned_dirs)} 个 | 已缓存: 文件 {stats.total_files}, 目录 {stats.total_dirs}",
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
        self.cache_manager.clear_scanned_dirs()
        self.cache_manager.clear_tree_data_only()
        self.cache_manager.set_url(url)

        self.start_scan(url, scan_mode=scan_mode, parallel=parallel)

    def start_directory_refresh(
        self,
        base_url: str,
        item_id: str,
        item_full_path: str,
        item_parent_id: str,
        scan_mode: str = "dfs",
        parallel: bool = False,
    ):
        """刷新单个目录（清除其子项，重新扫描该目录）"""
        if not base_url:
            self.log_message.emit("无有效URL，请先执行一次扫描", "error")
            return

        logger.info("刷新单个目录: %s (path=%s)", item_id, item_full_path)

        # 清理缓存中的子节点
        self.cache_manager.remove_directory_descendants(item_id)
        self.cache_manager.mark_dir_unscanned(item_full_path)

        # 开始单目录扫描
        self.start_directory_scan(base_url, item_full_path, item_parent_id, scan_mode=scan_mode, parallel=parallel)

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
