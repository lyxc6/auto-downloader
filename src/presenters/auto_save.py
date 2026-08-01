"""自动保存定时器策略：扫描/下载任一活动进行中时持续保存缓存"""

from collections.abc import Callable

from PySide6.QtCore import QTimer


class AutoSavePolicy:
    """自动保存策略

    扫描/下载任一活动进行中即启动定时器，每 interval_ms 保存一次缓存；
    两者都空闲时停止定时器，避免空闲时反复写盘。
    """

    def __init__(
        self,
        save: Callable[..., object],
        is_busy: Callable[[], bool],
        interval_ms: int = 30000,
    ):
        self._save = save
        self._is_busy = is_busy
        self._timer = QTimer()
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._save)

    def start(self) -> None:
        """任一活动开始：启动自动保存定时器"""
        self._timer.start()

    def stop_if_idle(self) -> None:
        """活动结束：全部空闲时停止定时器"""
        if not self._is_busy():
            self._timer.stop()
