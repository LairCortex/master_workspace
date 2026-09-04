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
        # QML islands load their sources from the filesystem via
        # QQuickWidget.setSource — .qml files are data, never PYZ modules, so
        # they must ship explicitly. Destination = the package dir because
        # engine.QML_IMPORT_PATH derives from the module __file__ PyInstaller
        # assigns under sys._MEIPASS (checked by
        # tests/test_spec_qml_bundle.py; list .py/__pycache__ stay out of the
        # bundle — the package modules already live in the PYZ).
        ("app/presentation/qml/LauncherRoot.qml",
         "app/presentation/qml"),
        # Event-timeline island roots (change
        # port-event-timeline-qml-island-q2-5a): TimelineRoot.qml is loaded
        # via QQuickWidget.setSource from views/timeline_island.py and its
        # delegate resolves through the same directory (no qmldir).
        ("app/presentation/qml/TimelineRoot.qml",
         "app/presentation/qml"),
        ("app/presentation/qml/TimelineRowDelegate.qml",
         "app/presentation/qml"),
        # nri.components library module (change
        # add-qml-component-library-q2a1, design D5): islands do
        # `import nri.components`, which Qt resolves as
        # <QML_IMPORT_PATH>/nri/components/qmldir — so the module directory
        # must ship verbatim under the same destination root as
        # LauncherRoot.qml, one explicit entry per file (checked by
        # tests/test_spec_qml_bundle.py). smoke.qml is the group-1 module
        # probe, not a qmldir-declared type: it is deliberately shipped too,
        # so the bundle layout is byte-for-byte the development import-path
        # layout; at runtime it is inert (no qmldir entry, no app code
        # references it) and its own imports (nri.components, tokens.js)
        # resolve from this same bundled directory. tests/presentation/ QML
        # (e.g. qml_components_gallery.qml) is test data, never bundled.
        ("app/presentation/qml/nri/components/qmldir",
         "app/presentation/qml/nri/components"),
        ("app/presentation/qml/nri/components/tokens.js",
         "app/presentation/qml/nri/components"),
        ("app/presentation/qml/nri/components/CardPanel.qml",
         "app/presentation/qml/nri/components"),
        ("app/presentation/qml/nri/components/HintText.qml",
         "app/presentation/qml/nri/components"),
        ("app/presentation/qml/nri/components/RowItem.qml",
         "app/presentation/qml/nri/components"),
        ("app/presentation/qml/nri/components/ThemeButton.qml",
         "app/presentation/qml/nri/components"),
        ("app/presentation/qml/nri/components/ThemeCheckBox.qml",
         "app/presentation/qml/nri/components"),
        ("app/presentation/qml/nri/components/ThemeComboBox.qml",
         "app/presentation/qml/nri/components"),
        ("app/presentation/qml/nri/components/ThemeField.qml",
         "app/presentation/qml/nri/components"),
        ("app/presentation/qml/nri/components/TitleText.qml",
         "app/presentation/qml/nri/components"),
        ("app/presentation/qml/nri/components/smoke.qml",
         "app/presentation/qml/nri/components"),
        # Qt Quick *QML plugins* (QtQuick, QtQuick.Controls.Basic,
        # QtQuick.Layouts, templates, …) are NOT listed here: PyInstaller's
        # bundled hook-PySide6.QtQml runs collect_qtqml_files(), which scans
        # Qt's QmlImportsPath for qmldir plugin dirs and re-homes them under
        # PySide6/qml; the PySide6 runtime hook registers that tree in
        # QML2_IMPORT_PATH (both split trees on macOS .app). The QtQml
        # hiddenimport below anchors that hook. Finding fixed in
        # tests/test_spec_qml_bundle.py.
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
        # Qt Quick shell (change add-qml-shell-launcher-pilot-q1): the QML
        # engine/island modules the launcher needs. QtQml additionally keeps
        # hook-PySide6.QtQml — and with it the automatic collection of every
        # qmldir QML plugin — guaranteed in the build even if the analysis
        # graph of a future refactor stops importing it directly.
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickControls2",
        "PySide6.QtQuickWidgets",
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
