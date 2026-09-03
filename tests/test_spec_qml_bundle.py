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

# nri.components library module (change add-qml-component-library-q2a1,
# design D5): `import nri.components` resolves through the engine's one
# import path as <QML_IMPORT_PATH>/nri/components/qmldir, so the bundle must
# ship the whole module directory under the same destination root — qmldir,
# every component .qml, and tokens.js (spec qml-shell «Бандл содержит QML»).
COMPONENTS_SRC_DIR = QML_SRC_DIR / "nri" / "components"
COMPONENTS_DEST = "app/presentation/qml/nri/components"

# The qmldir type contract (design D4) plus the shared helpers — listed
# explicitly so the test stays a real guard even if the source directory is
# ever emptied/moved (an empty glob would silently pass a scan-only check).
EXPECTED_COMPONENT_FILES = (
    "qmldir",
    "tokens.js",
    "ThemeButton.qml",
    "ThemeField.qml",
    "ThemeCheckBox.qml",
    "ThemeComboBox.qml",
    "TitleText.qml",
    "HintText.qml",
    "CardPanel.qml",
    "RowItem.qml",
    # Module probe from task 1.1, not a qmldir type: shipped so the bundle
    # mirrors the development import-path layout verbatim; inert at runtime
    # (no qmldir entry, no app code references it) — decision recorded in
    # nri_manager.spec next to its datas entry.
    "smoke.qml",
)

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
    section = text.split(f"{keyword}=[", 1)[1].rsplit("]", 1)[0]
    # Keep only code lines: a path mentioned in an explanatory comment must
    # never satisfy (or violate) an entry check — only real list entries count.
    return "\n".join(
        line
        for line in section.splitlines()
        if not line.strip().startswith("#")
    )


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


def test_spec_datas_ships_the_nri_components_module():
    # The frozen launcher island does `import nri.components`; if any module
    # file is missing from datas the island dies at startup with
    # `module "nri.components" is not installed` (spec qml-shell «Бандл
    # содержит QML»). Guard both directions: every expected contract file
    # ships, and every module file that exists on disk ships — so a future
    # component or js helper cannot be added to the module without its datas
    # entry.
    datas = _spec_section("datas")
    expected = set(EXPECTED_COMPONENT_FILES)
    assert expected, "component contract list is empty — test setup broken"

    on_disk = {
        p.name
        for p in COMPONENTS_SRC_DIR.iterdir()
        if p.is_file() and (p.suffix in {".qml", ".js"} or p.name == "qmldir")
    }
    assert "qmldir" in on_disk, (
        "app/presentation/qml/nri/components/qmldir is missing — the module "
        "cannot resolve from the import path at all"
    )
    assert expected <= on_disk, (
        f"module directory lost contract files: {sorted(expected - on_disk)}"
    )

    for file_name in sorted(on_disk):
        source = f"{COMPONENTS_DEST}/{file_name}"
        assert source in datas, (
            f"nri_manager.spec datas must ship {source} — the library module "
            "resolves through the engine import path and the whole directory "
            "is data, absent from the PYZ archive"
        )
        assert (COMPONENTS_SRC_DIR / file_name).is_file()

    # Destination matters as much as presence: Qt derives the module dir from
    # QML_IMPORT_PATH (sys._MEIPASS/app/presentation/qml), so the files must
    # land in the components subdirectory of that exact root.
    assert f'"{COMPONENTS_DEST}"' in datas


def test_spec_datas_keeps_test_only_qml_out_of_the_bundle():
    # The Q2 gallery (tests/presentation/qml_components_gallery.qml) is test
    # data: shipping it would drift the bundle away from the app's own qml
    # layout without any runtime consumer. (_spec_section strips the spec's
    # explanatory datas comment that names the file, so only entries count.)
    datas = _spec_section("datas")
    assert "qml_components_gallery" not in datas


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
