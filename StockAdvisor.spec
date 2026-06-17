# -*- mode: python ; coding: utf-8 -*-
"""One-folder build of the Stock Advisor local app.

Entry point is src/app.py (the same launcher as `python -m src.app`). defaults/ and
ui/ are bundled at the _MEIPASS root so resources.base_path() finds them when frozen.
Lazy/dynamic imports (keyring's OS backend, uvicorn's loop/protocol autodetect, the
lazily-imported anthropic SDK) are declared explicitly because PyInstaller's static
analysis cannot see them.
"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hiddenimports = []
hiddenimports += collect_submodules("keyring")          # OS credential store backends
hiddenimports += collect_submodules("uvicorn")          # loop/protocol autodetect
hiddenimports += ["anthropic"]                           # imported lazily when AI is on

datas = [("defaults", "defaults"), ("ui", "ui")]
datas += collect_data_files("pandas_market_calendars")   # bundled NYSE calendar data

a = Analysis(
    ["src/app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "_pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StockAdvisor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                       # UPX off: it raises antivirus false positives
    console=True,                    # visible launcher window (clear stop = close it)
    icon="installer/StockAdvisor.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="StockAdvisor",
)
