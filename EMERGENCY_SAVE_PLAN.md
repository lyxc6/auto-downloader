# 紧急保存功能实现计划

## 目标
实现意外中止保存功能，确保程序在异常退出时能够保存当前状态。

## 需要修改的文件
- `gui_downloader.py`

## 实现步骤

### 1. 添加导入
```python
import atexit
import signal
```

### 2. 在 `__init__` 中注册退出保存
```python
atexit.register(self._emergency_save)
signal.signal(signal.SIGINT, lambda s, f: (self._emergency_save(), sys.exit(0)))
```

### 3. 添加紧急保存方法
```python
def _emergency_save(self):
    try:
        if self.tree_data:
            cache_data = {
                "url": self.url_entry.get().strip(),
                "tree_data": self.tree_data,
                "checked_items": list(self.checked_items),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except:
        pass
```

### 4. 添加定时自动保存
```python
def _start_auto_save(self):
    self._auto_save_timer = self.root.after(30000, self._auto_save_tick)

def _auto_save_tick(self):
    if self.is_scanning or self.is_downloading:
        self._emergency_save()
        self._auto_save_timer = self.root.after(30000, self._auto_save_tick)

def _stop_auto_save(self):
    if hasattr(self, '_auto_save_timer'):
        self.root.after_cancel(self._auto_save_timer)
```

### 5. 在扫描/下载开始时启动自动保存
- 在 `scan_website()` 中调用 `self._start_auto_save()`
- 在 `start_download()` 中调用 `self._start_auto_save()`

### 6. 在扫描/下载完成时停止自动保存
- 在 `_scan_complete()` 中调用 `self._stop_auto_save()`
- 在 `_download_complete()` 中调用 `self._stop_auto_save()`

### 7. 在退出时保存
- 在 `on_exit()` 中调用 `self._emergency_save()`

## 注意事项
1. `atexit` 的 handler 不能直接用 `self`，需要用模块级变量或闭包
2. `signal` handler 在主线程中注册
3. 定时保存用 `root.after`，不能在子线程中调用
4. 紧急保存不应抛出异常，用 `try/except` 包裹
5. exe环境下的缓存路径已正确处理（跟exe在同一个目录）

## 状态
- [x] 已实现
- [x] 已测试
- [x] 已打包

## 编译结果
- 编译时间: 2026-07-21
- 输出文件: `dist\自动下载器.exe`
- 文件大小: 24.36 MB