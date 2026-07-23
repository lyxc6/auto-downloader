"""日志配置模块"""
import logging
import sys
import os


_log_setup_done = False


def setup_logging(log_dir: str = "", level: int = logging.DEBUG) -> logging.Logger:
    """配置日志系统

    Args:
        log_dir: 日志文件存放目录，为空则默认脚本/exe所在目录
        level: 控制台日志级别，文件始终为INFO

    Returns:
        根logger
    """
    global _log_setup_done
    if _log_setup_done:
        return logging.getLogger()

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not log_dir:
        if getattr(sys, "frozen", False):
            log_dir = os.path.dirname(sys.executable)
        else:
            log_dir = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )

    log_path = os.path.join(log_dir, "app.log")
    try:
        os.makedirs(log_dir, exist_ok=True)
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(fmt)
        root_logger.addHandler(fh)
    except OSError:
        pass

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(fmt)
    root_logger.addHandler(ch)

    _log_setup_done = True
    return root_logger
