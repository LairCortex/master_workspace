"""Char-sheet list & preset QML islands (change port-sheet-list-preset-dialogs-qml-q3a, tasks 2.1–2.2).

Island-load tests following the launcher convention (``test_launcher_qml.py``):
each root lands in a real offscreen ``QQuickWidget`` with the two context
properties its header pins — ``vm`` (the production ``SheetListViewModel`` /
``SheetPresetViewModel``, untouched — the «VM не знает про QML» seam) and
``islandPalette`` — and is addressed through the shared ``qml_helpers``
``walk_items`` machinery (no new helper: delegate rows are not QObject
children, only the visual tree sees them).

Coverage per task:

* 2.1: ``SheetListRoot.qml`` loads Ready with the objectName contract
  (tabTemplates/tabInstances, templateList/instanceList, the six buttons),
  the ``defaultButton`` Enter-marker sits on ``openButton``, delegates are
  addressable rows whose taps land in the VM, the VM flags drive
  enabled/visible (``presetButton`` — templates tab only), and every button
  emits its root ``*Requested`` signal.
* 2.2: ``SheetPresetRoot.qml`` loads Ready (presetList/licenseView/nameField/
  okButton/cancelButton), delegates address the catalog rows by name, a row
  tap goes through the sync slot ``selectPreset`` (license + name re-drive
  from the VM, the user-typed name survives per D5), and the OK/Cancel
  buttons emit the root signals.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPointF, QUrl
from PySide6.QtGui import QColor, QImage
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtTest import QTest

from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation import qml as qml_shell
from app.presentation.theme.compiler import tokens_file_path
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.theme.runtime import ThemeRuntime
from app.presentation.viewmodels.sheet_list_view_model import SheetListViewModel
from app.presentation.viewmodels.sheet_preset_view_model import SheetPresetViewModel
from app.domain.character_sheets.preset_catalog import PresetCatalog
from tests.presentation.qml_helpers import (
    click_item,
    find_item,
    find_items,
    track,
    walk_items,
)

SHEET_LIST_QML = Path(qml_shell.__file__).resolve().parent / "SheetListRoot.qml"
SHEET_PRESET_QML = Path(qml_shell.__file__).resolve().parent / "SheetPresetRoot.qml"

# The objectName contract of the list island (task 2.1), spelled out literally
# to fail on renames — the facade of group 3 addresses the very same names.
LIST_OBJECT_NAMES = (
    "tabTemplates",
    "tabInstances",
    "templateList",
    "instanceList",
    "createButton",
    "presetButton",
    "openButton",
    "renameButton",
    "deleteButton",
    "closeButton",
)

# The objectName contract of the preset island (task 2.2).
PRESET_OBJECT_NAMES = (
    "presetList",
    "licenseView",
    "nameField",
    "okButton",
    "cancelButton",
)

# The migrated rows: two templates, one sheet on the first («лист — шаблон»
# label is the VM's Python-side composition).
TEMPLATES = (
    SimpleNamespace(id=1, name="Альфа"),
    SimpleNamespace(id=2, name="Бета"),
)
INSTANCES = (SimpleNamespace(id=10, name="Лист1", template_id=1),)


# ── fixtures & loader (the launcher's seam, replicated) ──────────────────────


@pytest.fixture
def tokens_file(tmp_path):
    dst = tmp_path / "tokens.json"
    dst.write_text(tokens_file_path().read_text(encoding="utf-8"), encoding="utf-8")
    return dst


@pytest.fixture
def palette(tmp_path, tokens_file):
    runtime = ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=tokens_file
    )
    return QmlPalette(runtime)


@pytest.fixture
def list_vm():
    return SheetListViewModel()


@pytest.fixture
def preset_vm():
    return SheetPresetViewModel()


def load_island(qtbot, source: Path, vm, palette, size) -> QQuickWidget:
    """QQuickWidget with the island's two context properties (design D1/D2).

    Same engine-agnostic seam as ``test_launcher_qml.load_island``: the test
    engine only adds the production import path (so ``import nri.components``
    resolves); the context contract is the island header's — ``vm`` +
    ``islandPalette`` and nothing else. Both objects are parented to the
    widget: context properties keep raw pointers (task 8.2 hazard).
    """
    if QQuickStyle.name() != "Basic":  # design D4 — set once, never re-set
        QQuickStyle.setStyle("Basic")

    widget = QQuickWidget()
    qtbot.addWidget(widget)
    widget.resize(*size)
    widget.engine().addImportPath(qml_shell.QML_IMPORT_PATH)
    vm.setParent(widget)
    palette.setParent(widget)
    # Island-scoped context names (apply-stage correction): production dialogs
    # share the process engine and QQuickWidget.rootContext() writes propagate
    # to every island on it, so the two sheet islands bind through their own
    # names — the loader mirrors the facades' contract exactly.
    prefix = "sheetList" if source is SHEET_LIST_QML else "sheetPreset"
    widget.rootContext().setContextProperty(f"{prefix}Vm", vm)
    widget.rootContext().setContextProperty("islandPalette", palette)
    widget.setSource(QUrl.fromLocalFile(str(source)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    return widget


def rows(widget: QQuickWidget, row_name: str):
    """Delegate rows top-to-bottom (the launcher's convention: `grab` first —
    materialization rides the render pass; sort by scene y, not child order)."""
    widget.grab()
    QTest.qWait(0)
    found = find_items(widget, row_name)
    found.sort(key=lambda r: r.mapToScene(QPointF(0, 0)).y())
    return found


def row_texts(widget: QQuickWidget, row_name: str, text_name: str) -> list[str]:
    """Delegate row labels top-to-bottom (row order from the sorted rows)."""
    items = []
    for row in rows(widget, row_name):
        texts = [i for i in walk_items(row) if i.objectName() == text_name]
        assert len(texts) == 1
        items.append(texts[0].property("text"))
    return items


# ── pixel acceptance helpers (launcher 5.3 convention, no golden images) ────


def grab_rgb(widget: QQuickWidget) -> QImage:
    img = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    assert not img.isNull()
    return img


def token_rgb(hex_value: str) -> tuple[int, int, int]:
    color = QColor(hex_value)
    assert color.isValid()
    return (color.red(), color.green(), color.blue())


def pixel_rgb(img: QImage, scene_x: float, scene_y: float, widget: QQuickWidget):
    """Pixel under a *scene* point; grab may be scaled by device pixel ratio."""
    sx = img.width() / widget.width()
    sy = img.height() / widget.height()
    x = min(int(scene_x * sx), img.width() - 1)
    y = min(int(scene_y * sy), img.height() - 1)
    color = img.pixelColor(x, y)
    return (color.red(), color.green(), color.blue())


def surface_pixel(widget: QQuickWidget, img: QImage | None = None):
    """Far top-left corner — the root rectangle's background, no content."""
    return pixel_rgb(img or grab_rgb(widget), 3, 3, widget)


def button_pixel(widget: QQuickWidget, button, img: QImage | None = None):
    """A point inside the button's left padding band (background, no glyphs)."""
    point = button.mapToScene(QPointF(4, button.height() / 2))
    return pixel_rgb(img or grab_rgb(widget), point.x(), point.y(), widget)


# ── 2.1: SheetListRoot.qml ───────────────────────────────────────────────────


def test_list_island_loads_with_object_name_contract(qtbot, list_vm, palette):
    widget = load_island(qtbot, SHEET_LIST_QML, list_vm, palette, (420, 520))
    assert widget.errors() == []
    for name in LIST_OBJECT_NAMES:
        assert find_item(widget, name) is not None, name
    # «Открыть» carries the Enter marker (design D5 — the wrapper clicks it).
    assert widget.rootObject().property("defaultButton") is find_item(widget, "openButton")


def test_list_rows_are_addressable_and_taps_land_in_vm(qtbot, list_vm, palette):
    list_vm.set_rows(templates=TEMPLATES, instances=INSTANCES)
    widget = load_island(qtbot, SHEET_LIST_QML, list_vm, palette, (420, 520))

    assert row_texts(widget, "templateRow", "templateRowText") == ["Альфа", "Бета"]
    click_item(widget, rows(widget, "templateRow")[1])
    assert list_vm.selected_template_id == 2
    # The VM flag re-drives the buttons through the enabled bindings.
    assert find_item(widget, "openButton").property("enabled") is True
    assert find_item(widget, "renameButton").property("enabled") is True


def test_list_flags_drive_enabled_and_preset_button_visibility(qtbot, list_vm, palette):
    list_vm.set_rows(templates=TEMPLATES, instances=INSTANCES)
    widget = load_island(qtbot, SHEET_LIST_QML, list_vm, palette, (420, 520))

    # No selection: open/rename/delete are disabled, presetButton shows on
    # the templates tab (the migrated setVisible rule).
    assert find_item(widget, "openButton").property("enabled") is False
    assert find_item(widget, "deleteButton").property("enabled") is False
    assert find_item(widget, "presetButton").property("visible") is True

    # A template that already has sheets cannot be deleted (delete-only rule;
    # open/rename stay available — the migrated _sync_actions_enabled split).
    list_vm.selectTemplate(0)
    assert find_item(widget, "openButton").property("enabled") is True
    assert find_item(widget, "deleteButton").property("enabled") is False

    # The sheets tab hides «Создать из пресета…» and re-bases the flags on the
    # instance selection; the seated blocker rides set_seated_ids.
    click_item(widget, find_item(widget, "tabInstances"))
    assert list_vm.current_tab == 1
    assert find_item(widget, "presetButton").property("visible") is False
    assert find_item(widget, "deleteButton").property("enabled") is False
    assert row_texts(widget, "instanceRow", "instanceRowText") == ["Лист1 — Альфа"]
    click_item(widget, rows(widget, "instanceRow")[0])
    assert list_vm.selected_instance_id == 10
    assert find_item(widget, "deleteButton").property("enabled") is True
    list_vm.set_seated_ids({10})
    assert find_item(widget, "deleteButton").property("enabled") is False


def test_list_root_emits_request_signals_from_the_buttons(qtbot, list_vm, palette):
    list_vm.set_rows(templates=TEMPLATES, instances=INSTANCES)
    widget = load_island(qtbot, SHEET_LIST_QML, list_vm, palette, (420, 520))
    list_vm.selectTemplate(1)  # unlock open/rename (delete stays blocked: sheets)
    root = widget.rootObject()
    emits = {
        name: track(getattr(root, name))
        for name in (
            "createRequested", "presetRequested", "openRequested",
            "renameRequested", "deleteRequested", "closeRequested",
        )
    }

    click_item(widget, find_item(widget, "createButton"))
    click_item(widget, find_item(widget, "presetButton"))
    click_item(widget, find_item(widget, "openButton"))
    click_item(widget, find_item(widget, "renameButton"))
    click_item(widget, find_item(widget, "closeButton"))
    assert emits["createRequested"] == [()]
    assert emits["presetRequested"] == [()]
    assert emits["openRequested"] == [()]
    assert emits["renameRequested"] == [()]
    assert emits["closeRequested"] == [()]
    # Disabled delete (the template has sheets): Basic buttons swallow the
    # click — the migrated setEnabled(False) semantics, no signal.
    assert emits["deleteRequested"] == []


# ── 2.2: SheetPresetRoot.qml ─────────────────────────────────────────────────


def test_preset_island_loads_with_object_name_contract(qtbot, preset_vm, palette):
    widget = load_island(qtbot, SHEET_PRESET_QML, preset_vm, palette, (540, 500))
    assert widget.errors() == []
    for name in PRESET_OBJECT_NAMES:
        assert find_item(widget, name) is not None, name
    # «Создать» carries the Enter marker (design D5).
    assert widget.rootObject().property("defaultButton") is find_item(widget, "okButton")

    # Construction pre-selects the first preset (the migrated
    # setCurrentRow(0)); the island mirrors the VM surface verbatim.
    first = PresetCatalog().list()[0]
    assert find_item(widget, "licenseView").property("text") == first.license_text
    assert find_item(widget, "nameField").property("text") == first.title
    # Read-only selectable (selectByMouse) — the spec's read-only license.
    assert find_item(widget, "licenseView").property("readOnly") is True
    assert find_item(widget, "licenseView").property("selectByMouse") is True


def test_preset_delegates_are_addressable_and_select_drives_vm(qtbot, preset_vm, palette):
    widget = load_island(qtbot, SHEET_PRESET_QML, preset_vm, palette, (540, 500))
    catalog = PresetCatalog().list()
    titles = [preset.title for preset in catalog]
    labels = row_texts(widget, "presetRow", "presetRowText")
    assert len(labels) == len(catalog)
    assert list(labels) == titles
    assert len(labels) >= 2  # addressability means >1 addressable delegate

    # A row tap is the migrated currentRowChanged: ONE sync selectPreset.
    click_item(widget, rows(widget, "presetRow")[1])
    assert preset_vm.selected_index == 1
    assert find_item(widget, "presetList") is not None
    assert find_item(widget, "licenseView").property("text") == catalog[1].license_text
    # The name was still a substituted title → D5 substitutes the new one.
    assert find_item(widget, "nameField").property("text") == titles[1]


def test_preset_user_name_survives_selection_through_the_island(qtbot, preset_vm, palette):
    widget = load_island(qtbot, SHEET_PRESET_QML, preset_vm, palette, (540, 500))
    name_field = find_item(widget, "nameField")
    name_field.setProperty("text", "Моё имя")
    QTest.qWait(0)
    assert preset_vm.name_text == "Моё имя"  # setNameText round trip

    # Foreign-substitution rule (D5) is VM-side; the island only mirrors it:
    # a user-typed name survives switching presets.
    click_item(widget, rows(widget, "presetRow")[1])
    assert preset_vm.name_text == "Моё имя"
    assert name_field.property("text") == "Моё имя"


def test_preset_ok_cancel_emit_root_signals(qtbot, preset_vm, palette):
    widget = load_island(qtbot, SHEET_PRESET_QML, preset_vm, palette, (540, 500))
    root = widget.rootObject()
    creates = track(root.createRequested)
    cancels = track(root.cancelRequested)

    click_item(widget, find_item(widget, "okButton"))
    click_item(widget, find_item(widget, "cancelButton"))
    assert creates == [()]
    assert cancels == [()]


# ── task 4.3: pixel acceptance — the token palette reaches both new islands ──
# (launcher 5.3 convention: exact token pixels through grab(), no golden).


def test_list_island_paints_surface_and_accent_tokens(qtbot, list_vm, palette):
    list_vm.set_rows(templates=TEMPLATES, instances=INSTANCES)
    list_vm.selectTemplate(0)  # unlock «Открыть» — accent fill needs enabled
    widget = load_island(qtbot, SHEET_LIST_QML, list_vm, palette, (420, 520))
    image = grab_rgb(widget)
    tokens = palette.tokens
    assert surface_pixel(widget, image) == token_rgb(tokens["color.bg.surface"])
    assert button_pixel(widget, find_item(widget, "openButton"), image) == token_rgb(
        tokens["color.accent"]
    )


def test_preset_island_paints_surface_and_accent_tokens(qtbot, preset_vm, palette):
    widget = load_island(qtbot, SHEET_PRESET_QML, preset_vm, palette, (540, 500))
    image = grab_rgb(widget)
    tokens = palette.tokens
    assert surface_pixel(widget, image) == token_rgb(tokens["color.bg.surface"])
    assert button_pixel(widget, find_item(widget, "okButton"), image) == token_rgb(
        tokens["color.accent"]
    )
