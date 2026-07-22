# 任务5：应用入口和集成

## 任务描述
创建应用入口文件，集成所有模块。

## 文件清单
- `src/app.py` - 应用主类
- `src/utils/__init__.py`
- `src/utils/helpers.py` - 工具函数
- `main.py` - 启动脚本
- `src/__init__.py`

## 技术要求
- 正确初始化所有模块
- 连接控制器和视图
- 错误处理

## 依赖
- 需要前面所有任务的模块

---

## 文件1：src/utils/helpers.py

```python
"""工具函数"""
import os
import sys


def get_resource_path(relative_path: str) -> str:
    """获取资源文件路径"""
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def get_app_dir() -> str:
    """获取应用目录"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def format_size(size: int) -> str:
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def format_duration(seconds: float) -> str:
    """格式化时长"""
    if seconds < 60:
        return f"{seconds:.1f}秒"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}分钟"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}小时"
```

---

## 文件2：src/utils/__init__.py

```python
"""工具函数"""
from .helpers import get_resource_path, get_app_dir, format_size, format_duration

__all__ = ['get_resource_path', 'get_app_dir', 'format_size', 'format_duration']
```

---

## 文件3：src/app.py

```python
"""应用主类"""
import sys
import signal
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from .models import AppConfig, CacheManager
from .controllers import DownloadController, ScanController
from .views import MainWindow


class Application:
    """应用主类"""
    
    def __init__(self):
        # 创建QApplication
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("网站文件自动下载器")
        self.app.setApplicationVersion("2.0.0")
        
        # 设置高DPI支持
        self.app.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        
        # 加载配置
        self.config = AppConfig.load()
        
        # 创建缓存管理器
        self.cache_manager = CacheManager(self.config.cache_file)
        self.cache_manager.load()
        
        # 创建控制器
        self.download_controller = DownloadController(self.config)
        self.scan_controller = ScanController(self.config, self.cache_manager)
        
        # 创建主窗口
        self.window = MainWindow(self.config)
        
        # 连接信号
        self._connect_signals()
        
        # 设置信号处理（Ctrl+C）
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _connect_signals(self):
        """连接信号"""
        # 下载面板信号
        download_panel = self.window.downloadPanel
        
        # 扫描信号
        download_panel.scan_requested.connect(self._start_scan)
        download_panel.stop_scan_btn.clicked.connect(self.scan_controller.cancel_scan)
        
        # 下载信号
        download_panel.download_requested.connect(self._start_download)
        download_panel.stop_download_btn.clicked.connect(self.download_controller.cancel_download)
        
        # 控制器信号
        self.scan_controller.log_message.connect(download_panel.add_log)
        self.scan_controller.scan_progress.connect(
            lambda f, d: download_panel.update_stats(f, d, len(self.cache_manager.checked_items))
        )
        self.scan_controller.scan_completed.connect(self._on_scan_completed)
        
        self.download_controller.log_message.connect(download_panel.add_log)
        self.download_controller.progress_updated.connect(
            lambda id, dl, total: self.window.queuePanel.update_progress(id, dl, total)
        )
        self.download_controller.status_changed.connect(
            lambda id, status: self.window.queuePanel.update_status(id, status)
        )
        self.download_controller.batch_completed.connect(self._on_download_completed)
        
        # 设置面板信号
        self.window.settingsPanel.theme_changed.connect(self.window._apply_theme)
    
    def _start_scan(self, url: str):
        """开始扫描"""
        self.config.last_url = url
        self.config.save()
        
        self.window.downloadPanel.set_scanning(True)
        self.window.downloadPanel.log_widget.clear()
        
        self.scan_controller.start_scan(url)
    
    def _on_scan_completed(self, file_count: int, dir_count: int):
        """扫描完成"""
        self.window.downloadPanel.set_scanning(False)
        self.window.downloadPanel.download_btn.setEnabled(file_count > 0)
        
        # 更新统计
        stats = self.cache_manager.get_stats()
        self.window.downloadPanel.update_stats(
            stats['total_files'],
            stats['total_dirs'],
            stats['checked_count']
        )
    
    def _start_download(self):
        """开始下载"""
        # 获取选中的文件
        checked_files = self.cache_manager.get_checked_files()
        
        if not checked_files:
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.warning(
                title="警告",
                content="请先选择要下载的文件",
                parent=self.window,
                position=InfoBarPosition.TOP
            )
            return
        
        # 添加到队列
        for item in checked_files:
            self.window.queuePanel.add_item(item.item_id, item.name)
        
        # 开始下载
        self.window.downloadPanel.set_downloading(True)
        self.download_controller.start_download(checked_files)
    
    def _on_download_completed(self, stats_dict: dict):
        """下载完成"""
        self.window.downloadPanel.set_downloading(False)
    
    def _signal_handler(self, sig, frame):
        """信号处理器"""
        self.cache_manager.save()
        sys.exit(0)
    
    def run(self) -> int:
        """运行应用"""
        self.window.show()
        return self.app.exec()
```

---

## 文件4：src/__init__.py

```python
"""自动下载器"""
__version__ = "2.0.0"
```

---

## 文件5：main.py

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""网站文件自动下载器 - 启动脚本"""

import sys
import os

# 添加src目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.app import Application


def main():
    """主函数"""
    app = Application()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
```

---

## 验证标准

1. 所有文件无语法错误
2. 应用可以正常启动
3. 所有模块正确连接
4. 功能正常工作

## 测试命令

```bash
# 测试导入
python -c "from src.app import Application; print('App OK')"

# 运行应用
python main.py
```

---

## 完整目录结构

```
自动下载器/
├── src/
│   ├── __init__.py
│   ├── app.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── download_item.py
│   │   ├── config.py
│   │   └── cache_manager.py
│   ├── views/
│   │   ├── __init__.py
│   │   ├── main_window.py
│   │   ├── download_panel.py
│   │   ├── settings_panel.py
│   │   ├── queue_panel.py
│   │   └── widgets/
│   │       ├── __init__.py
│   │       ├── log_widget.py
│   │       └── tree_widget.py
│   ├── controllers/
│   │   ├── __init__.py
│   │   ├── download_controller.py
│   │   └── scan_controller.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── downloader.py
│   │   └── scanner.py
│   └── utils/
│       ├── __init__.py
│       └── helpers.py
├── resources/
│   ├── icons/
│   └── themes/
├── tasks/
│   ├── task1_models.md
│   ├── task2_services.md
│   ├── task3_controllers.md
│   ├── task4_views.md
│   └── task5_integration.md
├── main.py
├── requirements.txt
└── README.md
```
