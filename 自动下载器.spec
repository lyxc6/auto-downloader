# -*- mode: python ; coding: utf-8 -*-

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# 收集qfluentwidgets的数据文件
datas = []
datas += collect_data_files('qfluentwidgets')

a = Analysis(
    ['main.py'],
    pathex=['.', 'src'],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtNetwork',
        'shiboken6',
        'qfluentwidgets',
        'qfluentwidgets.common',
        'qfluentwidgets.components',
        'qfluentwidgets.components.widgets',
        'qfluentwidgets.components.settings',
        'qfluentwidgets.window',
        'src',
        'src.models',
        'src.models.download_item',
        'src.models.config',
        'src.models.cache_manager',
        'src.services',
        'src.services.downloader',
        'src.services.scanner',
        'src.controllers',
        'src.controllers.download_controller',
        'src.controllers.scan_controller',
        'src.views',
        'src.views.main_window',
        'src.views.download_panel',
        'src.views.settings_panel',
        'src.views.queue_panel',
        'src.views.widgets',
        'src.views.widgets.log_widget',
        'src.views.widgets.tree_widget',
        'src.utils',
        'src.utils.helpers',
        'src.app',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.sip',
        'PyQt5',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PyQt5.sip',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='自动下载器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
