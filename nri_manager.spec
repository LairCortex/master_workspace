# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for НРИ Сценарий Менеджер.

Build:
    pyinstaller nri_manager.spec

The result is a directory-based bundle in dist/nri_manager/
(--onefile is not recommended for Qt 6 apps).
"""

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ["app/main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("docs", "docs"),
        # character-sheet PDF export embeds these TTFs at runtime (sheet_pdf)
        ("app/infrastructure/pdf/fonts", "app/infrastructure/pdf/fonts"),
    ],
    hiddenimports=[
        "aiosqlite",
        "sqlalchemy.dialects.sqlite.aiosqlite",
        "qasync",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        # reportlab: most submodules come in via the static app import chain,
        # these two are loaded dynamically / need explicit collection
        "reportlab",
        "reportlab.lib.fonts",
        "reportlab.lib.rl_accel",
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
            "CFBundleShortVersionString": "0.17.0",
            "NSHighResolutionCapable": True,
        },
    )
