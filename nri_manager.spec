# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for НРИ Сценарий Менеджер.

Build:
    pyinstaller nri_manager.spec

The result is a directory-based bundle in dist/nri_manager/
(--onefile is not recommended for Qt 6 apps).
"""

import sys

block_cipher = None

a = Analysis(
    ["app/main.py"],
    pathex=[],
    binaries=[],
    # The preset layouts ship as an explicit file list (not a directory copy)
    # so that no stray files (e.g. __pycache__) end up in the bundle; the
    # catalog's .py modules are already part of the PYZ archive. Keep in sync
    # with PresetCatalog.list() (checked by tests/test_spec_presets_bundle.py).
    datas=[
        ("docs", "docs"),
        ("app/presentation/views/character_sheet/fonts",
         "app/presentation/views/character_sheet/fonts"),
        ("app/presentation/views/character_sheet/presets/fate_core.json",
         "app/presentation/views/character_sheet/presets"),
        ("app/presentation/views/character_sheet/presets/mork_borg.json",
         "app/presentation/views/character_sheet/presets"),
        ("app/presentation/views/table_host/web",
         "app/presentation/views/table_host/web"),
        ("app/presentation/theme/tokens.json",
         "app/presentation/theme"),
    ],
    hiddenimports=[
        "aiosqlite",
        "sqlalchemy.dialects.sqlite.aiosqlite",
        "qasync",
        "aiohttp",
        "segno",
        "reportlab",
        "reportlab.pdfgen",
        "reportlab.pdfbase",
        "reportlab.pdfbase.ttfonts",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "pytest",
        "pytest_qt",
        "pytest_mock",
        "pytest_asyncio",
        "pytest_cov",
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="nri_manager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # GUI app, no console window
    target_arch=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="nri_manager",
)

# macOS .app bundle (ignored on other platforms)
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="НРИ Сценарий Менеджер.app",
        icon=None,
        bundle_identifier="com.nri.scenario-manager",
        info_plist={
            "CFBundleShortVersionString": "0.16.0",
            "NSHighResolutionCapable": True,
        },
    )
