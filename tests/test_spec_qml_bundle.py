"""PyInstaller spec guard for the QML shell (add-qml-shell-launcher-pilot-q1).

``app/presentation/qml/*.qml`` is loaded at runtime via
``QQuickWidget.setSource(QUrl.fromLocalFile(...))`` — QML sources are data,
not importable Python, so the PYZ archive never picks them up: the spec must
ship every ``.qml`` file explicitly (spec qml-shell «Размещение qml-файлов и
поставка», scenario «Бандл содержит QML»), otherwise the frozen launcher
island fails to load with no way to notice until runtime.

The Qt Quick QML plugins themselves (``QtQuick``, ``QtQuick.Controls.Basic``,
``QtQuick.Layouts``, templates, …) are collected automatically by PyInstaller's
bundled ``hook-PySide6.QtQml``: its ``collect_qtqml_files()`` scans the whole
Qt ``QmlImportsPath`` for ``qmldir`` plugin directories and re-homes them under
``PySide6/qml`` (with the runtime hook registering that tree in
``QML2_IMPORT_PATH``, incl. the split Resources/Frameworks trees of a macOS
.app bundle). The hook fires whenever ``PySide6.QtQml`` is part of the build,
so the hiddenimports below double as the anchor that keeps that collection —
and therefore the Quick plugins — in the bundle. This fact is fixed here so a
future PyInstaller bump that changes hook behavior fails this file-first guard
rather than the shipped app.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "nri_manager.spec"
QML_SRC_DIR = REPO_ROOT / "app" / "presentation" / "qml"
QML_DEST = "app/presentation/qml"

# Modules the frozen Quick surface needs reachable (spec «Размещение
# qml-файлов и поставка»); QtQml additionally anchors the QML-plugin hook.
QUICK_HIDDEN_IMPORTS = (
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
)


def _spec_section(keyword: str) -> str:
    text = SPEC_PATH.read_text(encoding="utf-8")
    if f"{keyword}=[" not in text:
        raise AssertionError(f"nri_manager.spec has no {keyword} list")
    return text.split(f"{keyword}=[", 1)[1].rsplit("]", 1)[0]


def test_spec_datas_ship_every_qml_source_file():
    datas = _spec_section("datas")
    qml_files = sorted(QML_SRC_DIR.glob("*.qml"))
    assert qml_files, "no .qml sources found to bundle — test setup broken"
    for qml_file in qml_files:
        relative = f"{QML_DEST}/{qml_file.name}"
        assert f"app/presentation/qml/{qml_file.name}" in datas, (
            f"nri_manager.spec datas must ship {relative} — QML is loaded "
            "from the filesystem and is absent from the PYZ archive"
        )
        assert qml_file.is_file()


def test_spec_datas_uses_runtime_import_path_as_destination():
    # engine.QML_IMPORT_PATH derives from the module's own __file__, which a
    # frozen build resolves under sys._MEIPASS — so the bundle layout must be
    # "app/presentation/qml", matching the repo-relative source location.
    datas = _spec_section("datas")
    assert f'"{QML_DEST}"' in datas


def test_spec_hiddenimports_include_qtquick_modules():
    hidden = _spec_section("hiddenimports")
    for module in QUICK_HIDDEN_IMPORTS:
        assert module in hidden, (
            f"nri_manager.spec hiddenimports must list {module} — without "
            "the Quick modules (and the hook anchored on PySide6.QtQml) the "
            "frozen app loses the QML islands"
        )
