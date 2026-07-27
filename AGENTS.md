# AGENTS.md

## Project Overview

Python PySide6 desktop app for downloading files from a remote file server. Chinese language UI. Uses PySide6-Fluent-Widgets for Win11 Fluent Design style interface.

## Key Files

- `src/app.py` - Application entry point (PySide6 GUI)
- `src/models/` - Data models (download_item, config, cache_manager)
- `src/views/` - UI views (main_window, download_panel, settings_panel, queue_panel)
- `src/controllers/` - Controllers (download_controller, scan_controller)
- `src/services/` - Business logic (downloader, scanner)
- `main.py` - Main startup script
- `自动下载器.spec` - PyInstaller build spec
- `requirements.txt` - Dependencies: PySide6, PySide6-Fluent-Widgets, requests, beautifulsoup4, Pillow

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run GUI
python main.py

# Run tests
python -m pytest

# Run single test
python -m pytest tests/test_<name>.py

# Type checking
python -m pyright src

# Build executable (PyInstaller)
pyinstaller 自动下载器.spec
# Output: dist/自动下载器.exe
```

## FluentUI Constraint

**ALL UI components MUST use `qfluentwidgets` (PySide6-Fluent-Widgets).**

```python
# Correct - use qfluentwidgets components
from qfluentwidgets import (
    FluentWindow, CardWidget, TreeWidget,
    PrimaryPushButton, PushButton, LineEdit,
    ProgressBar, InfoBar, InfoBarPosition,
    SettingCardGroup, SwitchSettingCard,
    FluentIcon as FIF, Theme, setTheme
)

# Wrong - avoid raw PySide6 widgets for UI
from PySide6.QtWidgets import QPushButton, QLineEdit
```

- Use `FluentWindow` as main window base class
- Use `CardWidget` for grouped content
- Use `PrimaryPushButton` for main actions, `PushButton` for secondary
- Use `InfoBar` for notifications (not QMessageBox)
- Use `SettingCardGroup` for settings panels
- Use `FluentIcon` for icons (not custom QIcon)

## Architecture Notes

- MVC architecture pattern
- GUI runs downloads in daemon threads with signal-slot communication
- Supports theme switching (light/dark/auto) via `setTheme()`
- Cache file location: same directory as exe (frozen) or script (dev)
- Tree widget uses virtual loading for large datasets (lazy expansion)

## Conventions

- All UI strings in Chinese (Simplified)
- File paths use `os.path` for cross-platform compatibility
- HTTP requests use `requests.Session` with retry logic
- PySide6 signal-slot pattern for UI updates
- Use `qconfig` for theme persistence

## Gotchas

- `downloader.py` globals (`BASE_URL`, `DOWNLOAD_DIR`, etc.) are mutated by CLI args—avoid importing and relying on defaults
- GUI preview requires Pillow; gracefully degrades if missing
- Auto-save timer saves cache every 30s during active scan/download; stops when both are idle. Refresh keeps checked items and prunes entries no longer present on the server (incremental, preserves expand/scroll state).
- Signal handler (SIGINT) registered for emergency cache save on Ctrl+C
- PyInstaller build requires `collect_data_files('qfluentwidgets')` for FluentUI assets
