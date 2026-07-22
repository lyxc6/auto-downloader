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

# Build executable (PyInstaller)
pyinstaller 自动下载器.spec
# Output: dist/自动下载器.exe
```

## Architecture Notes

- MVC architecture pattern
- Uses PySide6 + PySide6-Fluent-Widgets for Win11 Fluent Design
- GUI runs downloads in daemon threads with signal-slot communication
- Supports theme switching (light/dark/auto)
- Cache file location: same directory as exe (frozen) or script (dev)

## Conventions

- All UI strings in Chinese (Simplified)
- File paths use `os.path` for cross-platform compatibility
- HTTP requests use `requests.Session` with retry logic
- PySide6 signal-slot pattern for UI updates

## Gotchas

- `downloader.py` globals (`BASE_URL`, `DOWNLOAD_DIR`, etc.) are mutated by CLI args—avoid importing and relying on defaults
- GUI preview requires Pillow; gracefully degrades if missing
- Auto-save timer runs every 30s during active scan/download operations
- Signal handler (SIGINT) registered for emergency cache save on Ctrl+C
