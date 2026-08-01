# AGENTS.md

## Project Overview

Python PySide6 desktop app for downloading files from a remote file server. Chinese language UI. Uses PySide6-Fluent-Widgets for Win11 Fluent Design style interface.

## Key Files

- `src/app.py` - Application bootstrap + composition root + shutdown management
- `src/presenters/` - Flow presenters (scan_presenter, download_presenter, auto_save) - view state transitions, no direct UI in app.py
- `src/update_flow.py` - Update check/download/restart flow
- `src/models/` - Data models (download_item, config, cache_manager)
- `src/views/` - UI views (main_window, download_panel, settings_panel, queue_panel)
- `src/controllers/` - Controllers (scan_controller, download_controller, scan_runner, size_prefetcher)
- `src/services/` - Business logic (scanner, downloader, http_client, html_parser)
- `main.py` - Main startup script
- `自动下载器.spec` - PyInstaller build spec
- `requirements.txt` - Runtime dependencies
- `requirements-dev.txt` - Dev/test/analysis dependencies

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Run GUI
python main.py

# Tests
pytest                              # all tests
pytest -x                           # stop on first failure
pytest -m "not slow"                # skip slow tests
pytest --cov=src --cov-report=html  # coverage report (HTML in htmlcov/)
pytest tests/test_foo.py            # single test file
pytest -k "test_name"               # single test by name
pytest -n auto                      # parallel (requires pytest-xdist)

# Lint & format
ruff check src/ tests/              # lint check
ruff check src/ tests/ --fix        # auto-fix fixable issues
ruff format src/ tests/             # format all files
ruff format --check src/ tests/     # check without modifying

# Type checking
pyright src/

# Memory analysis
memory_profiler your_script.py      # line-by-line memory (decorate functions with @profile)
python -c "import objgraph; objgraph.show_growth()"  # track object growth
python -c "from pympler import asizeof; print(asizeof.asizeof(obj))"  # object size

# Performance
py-spy top -- python main.py        # CPU sampling (best for GUI apps, low overhead)
kernprof -l -v your_script.py       # line-by-line timing (decorate with @profile)

# Build
pyinstaller 自动下载器.spec          # output: dist/自动下载器.exe
```

## Testing & Analysis Tools

Quick reference for all available tools (installed via `requirements-dev.txt`):

| Tool | Purpose | Command / Usage |
|------|---------|-----------------|
| `pytest` | Unit tests | `pytest` |
| `pytest-cov` | Coverage | `pytest --cov=src --cov-report=html` |
| `pytest-qt` | GUI testing | Use `qtbot` fixture |
| `pytest-mock` | Mocking | Use `mocker` fixture |
| `pytest-xdist` | Parallel tests | `pytest -n auto` |
| `pytest-timeout` | Prevent hangs | Default 30s (configured in pyproject.toml) |
| `ruff` | Lint + format | `ruff check` / `ruff format` |
| `pyright` | Type checking | `pyright src/` |
| `memory-profiler` | Line-by-line memory | `@profile` decorator + `memory_profiler` CLI |
| `objgraph` | Object reference graph | `objgraph.show_growth()` / `objgraph.show_backrefs()` |
| `pympler` | Object size analysis | `asizeof.asizeof()` / `muppy.show_usage()` |
| `line-profiler` | Line-by-line timing | `@profile` decorator + `kernprof` CLI |
| `py-spy` | CPU sampling profiler | `py-spy top -- python main.py` |

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

- MVC + Presenter architecture pattern
- app.py = composition root: assembles controllers/window/presenters, owns shutdown sequence
- presenters = view state transitions (ScanPresenter/DownloadPresenter), auto-save policy in auto_save.py
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
- Line endings: CRLF (configured in ruff format)

## Gotchas

- `downloader.py` globals (`BASE_URL`, `DOWNLOAD_DIR`, etc.) are mutated by CLI args—avoid importing and relying on defaults
- GUI preview requires Pillow; gracefully degrades if missing
- Auto-save timer saves cache every 30s during active scan/download; stops when both are idle. Refresh keeps checked items and prunes entries no longer present on the server (incremental, preserves expand/scroll state).
- Signal handler (SIGINT) registered for emergency cache save on Ctrl+C
- PyInstaller build requires `collect_data_files('qfluentwidgets')` for FluentUI assets
- `qfluentwidgets` lacks type stubs—pyright will report ~150 `reportUnknownMemberType` errors; this is expected and harmless
