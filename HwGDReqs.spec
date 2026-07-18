# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

a = Analysis(
    ['hwgdreqs/main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets')],
    hiddenimports=[
        'PySide6',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtNetwork',
        'shiboken6',
        'yt_dlp',
        'yt_dlp.extractor',
        'yt_dlp.downloader',
        'yt_dlp.postprocessor',
        'yt_dlp.utils',
        'pytchat',
        'pytchat.core',
        'pytchat.processors',
        'pytchat.parser',
        'brotli',
        'websocket',
        'charset_normalizer',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'yt_dlp', # test
        'pytchat',
        'Cryptodome',
        'secretstorage',
        'curl_cffi',
        'brotli',
        'mutagen',
        'websocket',
        'tkinter',
        'test',
        'unittest',
    ],
    noarchive=False,
    optimize=0,
)

import site
for site_dir in site.getsitepackages():
    pyside_path = os.path.join(site_dir, 'PySide6')
    if os.path.exists(pyside_path):
        # Add all DLLs from PySide6
        for root, dirs, files in os.walk(pyside_path):
            for file in files:
                if file.endswith('.dll'):
                    full_path = os.path.join(root, file)
                    # Add as (source_path, dest_name, 'BINARY')
                    a.binaries.append((full_path, os.path.basename(full_path), 'BINARY'))
        break

a.datas += collect_data_files('PySide6')

a.datas += collect_data_files('PySide6')
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='HwGDReqs',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\logo.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='HwGDReqs',
)