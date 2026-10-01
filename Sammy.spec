# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['packaging/entry.py'],
    pathex=['src'],
    binaries=[],
    datas=[('assets', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['dotenv', 'tkinter', 'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.Qt3DCore', 'PySide6.QtWebEngineCore', 'PySide6.QtCharts', 'PySide6.QtMultimedia', 'PySide6.QtTest', 'PySide6.QtDesigner'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Sammy',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Sammy',
)
app = BUNDLE(
    coll,
    name='Sammy.app',
    icon=None,
    bundle_identifier='com.rowan.sammy',
)
