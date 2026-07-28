# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.building.build_main import Analysis, PYZ, EXE
from PyInstaller.building.api import APP  # the fuck

a = Analysis(
    ['hwgdreqs/main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
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
    icon=['assets/logo.icns'],  # Use .icns for macOS!
)

app = APP(
    exe,
    a.binaries,
    a.datas,
    name='HwGDReqs',
    icon='assets/logo.icns',
    bundle_identifier='com.malikhw47.hwgdreqs',
    info_plist={
        'CFBundleShortVersionString': '0.13.0',
        'CFBundleVersion': '0.13.0',
        'LSMinimumSystemVersion': '10.13',
        'NSHighResolutionCapable': True,
    },
)