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

import ast
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

# Island roots loaded via QQuickWidget.setSource from the Python facades
# (change port-event-timeline-qml-island-q2-5a, design D10; extended by
# port-sheet-list-preset-dialogs-qml-q3a task 4.3 and
# port-character-sheet-canvas-qml-q3b task 4.3): listed explicitly
# next to the directory glob — QQuickWidget resolves TimelineRoot.qml by
# absolute path and TimelineRowDelegate.qml as a same-directory import, so a
# missing datas entry breaks the scale only in the frozen build; the same
# reasoning pins the two char-sheet dialog roots (list/preset facades call
# setSource on SheetListRoot.qml / SheetPresetRoot.qml) and the Q3b canvas +
# window roots (editor/fill facades call setSource on SheetEditorRoot.qml /
# SheetFillRoot.qml, which instantiate SheetCanvas.qml from the same
# directory). The tooltip shim ships Python-side
# (app/presentation/qml/tooltip_shim.py, PYZ), hence no qml entry for it here.
EXPECTED_QML_ROOT_FILES = (
    "LauncherRoot.qml",
    "TimelineRoot.qml",
    "TimelineRowDelegate.qml",
    "SheetListRoot.qml",
    "SheetPresetRoot.qml",
    "SheetCanvas.qml",
    "SheetEditorRoot.qml",
    "SheetFillRoot.qml",
    "XlsxImportRoot.qml",
    "ImageViewerRoot.qml",
    "DocViewerRoot.qml",
    "LlmSetupRoot.qml",
    "EventTypesRoot.qml",
    "SearchBarRoot.qml",
    "DetailPanelRoot.qml",
    # nri-0022-entity-preview: the entity-preview column's island root.
    "EntityPreviewRoot.qml",
    "WorldSnapshotRoot.qml",
    "EventDialogRoot.qml",
    "EntityCardRoot.qml",
)

# The qmldir type contract (design D4) plus the shared helpers — listed
# explicitly so the test stays a real guard even if the source directory is
# ever emptied/moved (an empty glob would silently pass a scan-only check).
EXPECTED_COMPONENT_FILES = (
    "qmldir",
    "tokens.js",
    # Shared panel-header band of the three main-window columns (live fix
    # 2026-09-26, docs/qa/2026-09-26-header-alignment.md) — a library script
    # imported by the three roots, same shipping rule as tokens.js.
    "panelHeader.js",
    # Lucide glyph pair (user request 2026-09-30): the generated icons.js map
    # and its ThemeIcon brush. The SVGs they derive from live in the icons/
    # subdirectory, which ships too (PR-027 fix 2026-10-04): the widget bridge
    # app/presentation/views/lucide_icons.py reads those files at RUNTIME as
    # QIcons, so it is runtime data, not only the build-time source
    # scripts/vendor_lucide.py expands from. The scan below counts module files
    # only; the subdirectory has its own guard further down this file.
    "icons.js",
    "ThemeIcon.qml",
    "ThemeButton.qml",
    "ThemeField.qml",
    "ThemeTextArea.qml",
    "MentionField.qml",
    "ThemeAiButton.qml",
    "RelatedSection.qml",
    "ThemeSwatch.qml",
    "ThemeDateField.qml",
    "ThemeRatingCard.qml",
    "ThemeCheckBox.qml",
    "ThemeComboBox.qml",
    "ThemeTabBar.qml",
    "ThemeTabButton.qml",
    "TitleText.qml",
    "HintText.qml",
    "CardPanel.qml",
    "RowItem.qml",
    # nri-0014 task 4.1: the island-sheet title row (qml-components delta).
    "ThemeSheetHeader.qml",
    # NRI-0018 task 1.2: the square small-action glyph button (qml-components
    # delta «Квадратная мелкая кнопка действия библиотеки»).
    "ThemeIconButton.qml",
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
    on_disk = {qml_file.name for qml_file in qml_files}
    missing_contract = set(EXPECTED_QML_ROOT_FILES) - on_disk
    assert not missing_contract, (
        f"qml root directory lost contract files: {sorted(missing_contract)}"
    )
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


# Documentation viewers (app/presentation/wiring.py resolve their files as
# bundle_resource_path("docs") / <file_name>) read exactly these two files;
# the whole docs/ directory — QA reports/screenshots under docs/qa plus the
# development roadmaps — must stay out of the release bundle.
DOCS_DEST = "docs"
EXPECTED_DOC_FILES = ("README.md", "CHANGELOG.md")


def test_spec_datas_ship_docs_without_qa():
    datas = _spec_section("datas")
    # The directory copy is the defect this guards: it dragged the whole
    # docs/qa (QA artifacts and screenshots) into the release.
    assert f'("{DOCS_DEST}", "{DOCS_DEST}")' not in datas, (
        "nri_manager.spec datas must not bundle the whole docs/ directory — "
        "QA artifacts and screenshots under docs/qa do not ship in a release"
    )
    assert "docs/qa" not in datas, (
        "nri_manager.spec datas must not reference docs/qa — QA artifacts "
        "and screenshots never belong in the release bundle"
    )
    # The viewers must keep working: every file they open ships, under the
    # destination the frozen bundle_resource_path("docs") layout scan derives.
    for file_name in EXPECTED_DOC_FILES:
        source = f"{DOCS_DEST}/{file_name}"
        assert f'"{source}"' in datas, (
            f"nri_manager.spec datas must ship {source} — the documentation "
            "viewer opens bundle_resource_path('docs') / "
            f"{file_name} from the filesystem"
        )
        assert (REPO_ROOT / DOCS_DEST / file_name).is_file()
    assert f'"{DOCS_DEST}"' in datas, (
        f"the docs files must land in the '{DOCS_DEST}' destination — the "
        "frozen resolver scans for <resource root>/docs"
    )


def test_spec_hiddenimports_include_qtquick_modules():
    hidden = _spec_section("hiddenimports")
    for module in QUICK_HIDDEN_IMPORTS:
        assert module in hidden, (
            f"nri_manager.spec hiddenimports must list {module} — without "
            "the Quick modules (and the hook anchored on PySide6.QtQml) the "
            "frozen app loses the QML islands"
        )


# The widget-side glyph bridge (app/presentation/views/lucide_icons.py) reads
# the vendored SVG files out of ICONS_DIR at RUNTIME to build its QIcons — the
# same ``__file__``-relative mechanism as preset_catalog/sheet_font, so under
# the bundle it reads <sys._MEIPASS>/app/presentation/qml/nri/components/icons.
# Those files are runtime data, not only the build-time source that
# scripts/vendor_lucide.py expands into icons.js: PR-027 was precisely this
# premise being wrong (the spec comment said "build-time source", the scan
# above counted module files only), so the release bundle opened the launcher
# and died with KeyError "lucide icon 'chevron-left' is not vendored" the
# moment a game was chosen. The two guards below read their expectations out
# of the code and the spec instead of a hand-kept list: the set "glyphs the
# code loads at runtime" must stay a subset of "files the spec ships".
ICONS_SRC_DIR = COMPONENTS_SRC_DIR / "icons"


def _entry_text(node: ast.expr) -> str:
    """One datas tuple element as text: the literal value, or the expression
    source for a computed path (the Qt translations directory)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ast.unparse(node)


def _spec_datas_pairs() -> list[tuple[str, str]]:
    """Every (source, destination) pair of the spec's datas list, read with
    ast — a path named inside an explanatory comment can neither satisfy nor
    violate an entry (the rule _spec_section enforces for substring checks)."""
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"), filename=str(SPEC_PATH))
    pairs: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Analysis"
        ):
            continue
        for keyword in node.keywords:
            if keyword.arg != "datas" or not isinstance(keyword.value, ast.List):
                continue
            pairs.extend(
                (_entry_text(element.elts[0]), _entry_text(element.elts[1]))
                for element in keyword.value.elts
                if isinstance(element, ast.Tuple) and len(element.elts) == 2
            )
    return pairs


def _bundled_paths() -> set[str]:
    """Bundle-relative file paths the datas list produces: a file entry lands
    as ``<dest>/<name>``, a directory entry copies its whole tree into
    ``<dest>`` (PyInstaller's own rule for hook-style datas tuples). Sources
    the spec computes from an expression are no repo paths and are skipped —
    no icon guard reads the Qt translations folder."""
    bundled: set[str] = set()
    for source, dest in _spec_datas_pairs():
        path = REPO_ROOT / source
        if path.is_file():
            bundled.add(f"{dest}/{path.name}")
        elif path.is_dir():
            bundled.update(
                f"{dest}/{file.relative_to(path).as_posix()}"
                for file in sorted(path.rglob("*"))
                if file.is_file()
            )
    return bundled


def _runtime_lucide_icon_names() -> set[str]:
    """Every literal glyph name app/ asks the widget bridge for: the first
    argument of each ``lucide_icon()`` call, taken from the syntax tree so a
    prose mention of the loader never counts as a call site."""
    names: set[str] = set()
    for module in sorted((REPO_ROOT / "app").rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else getattr(node.func, "attr", "")
            )
            if callee != "lucide_icon" or not node.args:
                continue
            first_argument = node.args[0]
            if isinstance(first_argument, ast.Constant) and isinstance(
                first_argument.value, str
            ):
                names.add(first_argument.value)
    return names


def _bridge_icons_dest() -> str:
    """Where the widget bridge reads its glyphs, repo-relative: the bridge
    derives ICONS_DIR from its own ``__file__``, which a frozen build resolves
    under ``sys._MEIPASS`` — so the repo-relative location IS the datas
    destination the files must land in."""
    from app.presentation.views import lucide_icons

    return Path(lucide_icons.ICONS_DIR).resolve().relative_to(REPO_ROOT).as_posix()


def test_spec_datas_ship_every_icon_the_widget_bridge_reads():
    names = _runtime_lucide_icon_names()
    assert names, "no lucide_icon() call site found under app/ — test setup broken"
    vendored = {svg.stem for svg in ICONS_SRC_DIR.glob("*.svg")}
    assert vendored, "the vendored icons directory is empty — test setup broken"
    not_vendored = names - vendored
    assert not not_vendored, (
        "lucide_icon() is called for glyphs that are not vendored: "
        f"{sorted(not_vendored)} — add them to ICON_NAMES in "
        "scripts/vendor_lucide.py and re-run --fetch"
    )
    icons_dest = _bridge_icons_dest()
    bundled = _bundled_paths()
    missing = {
        f"{icons_dest}/{name}.svg"
        for name in sorted(names)
        if f"{icons_dest}/{name}.svg" not in bundled
    }
    assert not missing, (
        f"nri_manager.spec datas must ship {sorted(missing)} under "
        f"{icons_dest} — app/presentation/views/lucide_icons.py reads the "
        "vendored SVGs from the filesystem at runtime, and PR-027 is the "
        "frozen build dying with KeyError on the first opened game"
    )


def test_spec_datas_ship_the_vendored_icons_at_the_bridges_own_path():
    # Presence is half of the contract, the destination the other half: the
    # bridge derives its directory from __file__, so the bundle mirrors the
    # development layout verbatim (the same posture the nri.components module
    # takes) and the whole directory ships — every glyph plus the ISC license
    # the upstream files travel with.
    icons_dest = _bridge_icons_dest()
    assert icons_dest == f"{COMPONENTS_DEST}/icons", (
        "the bridge's icon directory moved away from the bundled QML module "
        "layout — the datas destination has to follow it"
    )
    on_disk = {icon.name for icon in ICONS_SRC_DIR.iterdir() if icon.is_file()}
    assert "LICENSE.txt" in on_disk, (
        "the ISC license of the vendored glyphs must stay next to them — the "
        "directory ships verbatim"
    )
    missing = {f"{icons_dest}/{name}" for name in sorted(on_disk)} - _bundled_paths()
    assert not missing, (
        f"the whole vendored icons directory must ship under {icons_dest}: "
        f"{sorted(missing)} — a glyph the widgets load is read from disk in "
        "the frozen build (PR-027)"
    )
