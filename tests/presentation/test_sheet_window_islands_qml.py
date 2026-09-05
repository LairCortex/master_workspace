"""Window-island roots for the character sheet (change port-character-sheet-canvas-qml-q3b,
tasks 3.1–3.2).

The island-load convention of the canvas/sheet-list precedents: a real
offscreen ``QQuickWidget`` on the Basic style; the ViewModel arrives as the
root's DECLARED ``vm`` property through ``setInitialProperties`` (the two
sheet windows share the one process engine whose root context is global — the
Q3a lesson), ``islandPalette`` rides in as the context property the island
headers pin (the test engine is per-widget, production pushes the same name on
the shared one). Addressing is the shared ``qml_helpers`` walk.

Checked here (group 3, island semantics only — the facades' own migrated/e2e
suites cover save flows/popups):

* 3.1 ``SheetEditorRoot.qml`` — loads Ready with the objectName contract
  (palette buttons, rail rows + add/remove/↑↓, orientation combo, panels),
  ``defaultButton`` sits on «Сохранить»; the palette mirrors ``vm.currentTool``
  and clicks ``set_tool``; the rail feeds ``page_names`` (click =
  ``set_current_page`` + scroll, dblclick inline rename → ``rename_page``,
  − asks the facade ``pageRemoveRequested``, + ``add_page``, ↑↓ ``move_page``);
  the orientation combo pushes ``set_orientation`` and mirrors the VM; the
  property panel projects the selected field (X/Y/W/H, Кегль, content live
  buffer, number bounds, options editor, checkbox default, image buttons) and
  edits only through VM entrances; save/export/image-pick emit root signals;
  ``pasteRequested`` answers through the canvas' ``visibleCenter``.
* 3.2 ``SheetFillRoot.qml`` — loads Ready (nav rail without edit chrome, canvas
  in fill mode, value panel); row click navigates; the value panel's type
  branches land in ``set_text``/``set_number``/``toggle_checkbox``, the dropdown
  click bridges ``dropdownRequested`` to the facade which answers through
  ``set_dropdown``; image pick/clear land in the VM (pick relays to the facade);
  bind/unbind/save/inline stay input in edit mode, read-only turns them off.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QImage
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.application.services.character_sheet_instance_service import (
    CharacterSheetInstanceService,
)
from app.application.services.character_sheet_service import CharacterSheetService
from app.domain.enums.field_type import FieldType
from app.infrastructure.repositories.character_sheet_instance_repository import (
    CharacterSheetInstanceRepository,
)
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)
from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation import qml as qml_shell
from app.presentation.qml.sheet_font import register_sheet_font
from app.presentation.qml.sheet_image_provider import (
    SHEET_IMAGE_PROVIDER_ID,
    SheetImageProvider,
)
from app.presentation.qml.tooltip_shim import register_tooltip_shim
from app.presentation.theme.compiler import tokens_file_path
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.theme.runtime import ThemeRuntime
from app.presentation.viewmodels.character_sheet_fill_viewmodel import (
    CharacterSheetFillViewModel,
)
from app.presentation.viewmodels.character_sheet_viewmodel import (
    CharacterSheetViewModel,
)
from tests.presentation.qml_helpers import (
    click_item,
    find_item,
    find_items,
    island_row_texts,
    island_rows,
    track,
)

EDITOR_QML = Path(qml_shell.__file__).resolve().parent / "SheetEditorRoot.qml"
FILL_QML = Path(qml_shell.__file__).resolve().parent / "SheetFillRoot.qml"

# The objectName contracts (the facades and the migrated dialog suites address
# these exact names — spelled out to fail on silent renames).
EDITOR_OBJECT_NAMES = (
    "sheetEditorCanvas", "paletteTool-pointer", "paletteTool-text",
    "paletteTool-image", "pageListView", "orientationCombo",
    "propertiesPanel", "snapCheck", "bringFrontButton", "sendBackButton",
    "xField", "contentField", "saveButton", "exportPdfButton",
    "railUpButton", "railDownButton", "railDeleteButton", "railAddButton",
)
FILL_OBJECT_NAMES = (
    "sheetFillCanvas", "pageListView", "fillPropertiesPanel",
    "saveButton", "bindButton", "unbindButton",
)


# ── fixtures (the canvas island suite's services, replicated) ─────────────────


@pytest.fixture
def services(async_session):
    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    return sheet_svc, inst_svc


@pytest.fixture
async def vm(services):
    sheet_svc, _ = services
    row = await sheet_svc.create("Лист")
    view_model = CharacterSheetViewModel(sheet_svc)
    await view_model.load(row.id)
    return view_model


@pytest.fixture
async def editor_case(services):
    """Design VM: a text field on page 1 + a second page (panel/rail probes)."""
    sheet_svc, _ = services
    row = await sheet_svc.create("Лист")
    template = await sheet_svc.load(row.id)
    field = template.add_field(FieldType.TEXT, (40.0, 40.0))
    field.content = "привет"
    await sheet_svc.update_pages(row.id, template)
    view_model = CharacterSheetViewModel(sheet_svc)
    await view_model.load(row.id)
    view_model.add_page(after_index=0)
    return view_model, field.id


@pytest.fixture
async def fill_case(services):
    """Instance VM: text/number/checkbox/dropdown/image rows (3.2 branches)."""
    sheet_svc, inst_svc = services
    row = await sheet_svc.create("Шаблон")
    template = await sheet_svc.load(row.id)
    text_f = template.add_field(FieldType.TEXT, (40.0, 40.0))
    num_f = template.add_field(FieldType.NUMBER, (40.0, 80.0))
    num_f.min_value = 0
    num_f.max_value = 10
    chk = template.add_field(FieldType.CHECKBOX, (40.0, 120.0))
    dd = template.add_field(FieldType.DROPDOWN, (40.0, 160.0))
    dd.options = ["эльф", "орк"]
    img = template.add_field(FieldType.IMAGE, (40.0, 240.0))
    await sheet_svc.update_pages(row.id, template)
    inst = await inst_svc.create("Лист героя", row.id)
    fvm = CharacterSheetFillViewModel(inst_svc, sheet_svc)
    await fvm.load(inst.id)
    ids = {"text": text_f.id, "num": num_f.id, "chk": chk.id,
           "dd": dd.id, "img": img.id}
    return fvm, ids


# ── loaders (the canvas-island convention; VM as declared property) ───────────


def _pump(ticks: int = 2) -> None:
    for _ in range(ticks):
        QApplication.processEvents()


@pytest.fixture
def palette(tmp_path):
    dst = tmp_path / "tokens.json"
    dst.write_text(tokens_file_path().read_text(encoding="utf-8"), encoding="utf-8")
    runtime = ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=dst
    )
    return QmlPalette(runtime)


def _load(qtbot, source: Path, vm, palette, size) -> QQuickWidget:
    register_tooltip_shim()  # the Nri scope — production does it in setup_qml_shell
    register_sheet_font()
    if QQuickStyle.name() != "Basic":  # design D4 — set once, never re-set
        QQuickStyle.setStyle("Basic")
    widget = QQuickWidget()
    qtbot.addWidget(widget)
    widget.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
    widget.engine().addImageProvider(SHEET_IMAGE_PROVIDER_ID, SheetImageProvider())
    widget.engine().addImportPath(qml_shell.QML_IMPORT_PATH)
    widget.resize(*size)
    # context/raw-pointer lifetime: palette + VM die with the widget
    palette.setParent(widget)
    vm.setParent(widget)
    widget.rootContext().setContextProperty("islandPalette", palette)
    widget.setInitialProperties({"vm": vm})
    widget.setSource(QUrl.fromLocalFile(str(source)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    widget.show()
    _pump(6)
    return widget


def load_editor(qtbot, vm, palette, size=(1200, 700)) -> QQuickWidget:
    return _load(qtbot, EDITOR_QML, vm, palette, size)


def load_fill(qtbot, vm, palette, size=(1100, 700)) -> QQuickWidget:
    return _load(qtbot, FILL_QML, vm, palette, size)


# ── 3.1: SheetEditorRoot.qml ─────────────────────────────────────────────────


def test_editor_island_loads_with_object_name_contract(qtbot, vm, palette):
    widget = load_editor(qtbot, vm, palette)
    assert widget.errors() == []
    for name in EDITOR_OBJECT_NAMES:
        assert find_item(widget, name) is not None, name
    # «Сохранить» carries the Enter marker (design D1 — the wrapper clicks it).
    assert widget.rootObject().property("defaultButton") is find_item(
        widget, "saveButton"
    )


def test_editor_palette_mirrors_tool_and_clicks_set_tool(qtbot, vm, palette):
    widget = load_editor(qtbot, vm, palette)
    pointer = find_item(widget, "paletteTool-pointer")
    text_tool = find_item(widget, "paletteTool-text")
    assert pointer.property("checked") is True  # the VM starts on the pointer

    click_item(widget, text_tool)
    assert vm.currentTool == "place_text"
    assert text_tool.property("checked") is True
    assert pointer.property("checked") is False

    # A one-shot placement resets the tool in the VM; the palette follows the
    # VM, it never owns the tool (the migrated set_active_tool wiring).
    vm.set_tool("pointer")
    QTest.qWait(0)
    assert pointer.property("checked") is True


def test_editor_rail_rows_navigate_and_edit(qtbot, editor_case, palette):
    vm, _ = editor_case
    widget = load_editor(qtbot, vm, palette)
    assert island_row_texts(widget, "railPageRow", "railPageText") == [
        "Страница 1", "Страница 2",
    ]
    # A row click: current page + scroll (the migrated page_selected wiring).
    click_item(widget, island_rows(widget, "railPageRow")[1])
    assert vm.currentPage == 1
    assert vm.current_page_index == 1

    # Double-click switches the row into the inline rename field (the migrated
    # DoubleClicked edit trigger); Enter commits through rename_page.
    click_item(widget, island_rows(widget, "railPageRow")[0], double=True)
    fields = [f for f in find_items(widget, "railPageRenameField")
              if f.property("visible")]
    assert len(fields) == 1
    fields[0].setProperty("text", "Имя героя")
    QTest.keyClick(widget, Qt.Key.Key_Return)
    _pump(2)
    assert vm.page_names() == ["Имя героя", "Страница 2"]

    # «−» never removes on its own: the confirm is the facade's QMessageBox.
    page_before_remove = vm.currentPage
    removes = track(widget.rootObject().pageRemoveRequested)
    click_item(widget, find_item(widget, "railDeleteButton"))
    assert removes == [(page_before_remove,)]  # asked for the current page
    assert vm.pagesLayout["count"] == 2  # nothing removed yet

    # ↑ moves the current page (row 1 → row 0); «+» adds after the current.
    click_item(widget, find_item(widget, "railUpButton"))
    _pump(1)
    assert vm.page_names()[0] == "Страница 2"
    click_item(widget, find_item(widget, "railAddButton"))
    _pump(1)
    assert vm.pagesLayout["count"] == 3


def test_editor_orientation_combo_mirrors_and_pushes(qtbot, vm, palette):
    widget = load_editor(qtbot, vm, palette)
    combo = find_item(widget, "orientationCombo")
    assert int(combo.property("currentIndex")) == 0  # portrait default
    combo.setProperty("currentIndex", 1)
    _pump(2)
    assert vm.pagesLayout["orientation"] == "landscape"
    # the VM owns it back: switch programmatically → the combo mirrors
    vm.set_orientation("portrait")
    _pump(2)
    assert int(combo.property("currentIndex")) == 0


def test_editor_panel_projects_selected_field_and_edits_via_vm(
    qtbot, editor_case, palette
):
    vm, fid = editor_case
    widget = load_editor(qtbot, vm, palette)
    panel = find_item(widget, "propertiesPanel")
    box = find_item(widget, "fieldPropertiesBox")
    assert box.property("visible") is False  # nothing selected

    vm.select(fid)
    _pump(2)
    assert box.property("visible") is True

    # geometry: the panel shows the row values, an edit lands on vm.move
    x_field = find_item(widget, "xField")
    assert float(x_field.property("text")) == pytest.approx(40.0)
    x_field.setProperty("text", "80")
    x_field.editingFinished.emit()
    _pump(1)
    assert vm.template.get_field(fid).x == pytest.approx(80.0)

    # content buffer shared with the canvas inline (single VM buffer)
    content = find_item(widget, "contentField")
    assert content.property("text") == "привет"


@pytest.fixture
async def typed_case(services):
    """VM with number (0..10), dropdown (эльф/орк) and checkbox fields."""
    sheet_svc, _ = services
    row = await sheet_svc.create("Лист")
    template = await sheet_svc.load(row.id)
    num = template.add_field(FieldType.NUMBER, (40.0, 40.0))
    num.min_value = 0
    num.max_value = 10
    dd = template.add_field(FieldType.DROPDOWN, (40.0, 120.0))
    dd.options = ["эльф", "орк"]
    chk = template.add_field(FieldType.CHECKBOX, (40.0, 160.0))
    await sheet_svc.update_pages(row.id, template)
    vm = CharacterSheetViewModel(sheet_svc)
    await vm.load(row.id)
    return vm, num.id, dd.id, chk.id


def test_editor_panel_type_branches_write_through_vm(qtbot, typed_case, palette):
    """number bounds / dropdown options / checkbox default — the panel's type
    branches from properties_panel.py, all landing on existing VM entrances."""
    vm, num_id, dd_id, chk_id = typed_case
    widget = load_editor(qtbot, vm, palette)

    # number branch: garbage keeps the stored value, a bound edit applies
    vm.select(num_id)
    _pump(2)
    min_check = find_item(widget, "minCheck")
    assert min_check.property("checked") is True
    num_field = find_item(widget, "numberField")
    num_field.setProperty("text", "5")
    num_field.editingFinished.emit()
    _pump(1)
    assert vm.template.get_field(num_id).content == "5"
    num_field.setProperty("text", "99")  # out of the stored max → rejected
    num_field.editingFinished.emit()
    _pump(1)
    assert vm.template.get_field(num_id).content == "5"

    # dropdown branch: add an option via the list editor, pick the default
    vm.select(dd_id)
    _pump(2)
    option_input = find_item(widget, "optionInput")
    option_input.setProperty("text", "гном")
    click_item(widget, find_item(widget, "optionAddButton"))
    _pump(1)
    assert vm.field_props(dd_id)["options"] == ["эльф", "орк", "гном"]

    # checkbox branch: the «по умолчанию» flag toggles through the VM
    vm.select(chk_id)
    _pump(2)
    default_toggle = find_item(widget, "checkboxDefaultCheck")
    assert default_toggle.property("checked") is False
    default_toggle.setProperty("checked", True)
    default_toggle.toggled.emit()
    _pump(1)
    assert vm.template.get_field(chk_id).content == "true"


def test_editor_save_export_image_signals(qtbot, editor_case, palette):
    vm, fid = editor_case
    widget = load_editor(qtbot, vm, palette)
    root = widget.rootObject()
    saves = track(root.saveRequested)
    exports = track(root.exportPdfRequested)
    picks = track(root.imagePickRequested)

    click_item(widget, find_item(widget, "saveButton"))
    click_item(widget, find_item(widget, "exportPdfButton"))
    assert saves == [()]
    assert exports == [()]

    vm.select(fid)
    _pump(2)
    # the text row's panel has no image branch; place an image field instead
    fid_img = vm.place("image", 100.0, 100.0)
    vm.select(fid_img)
    _pump(2)
    click_item(widget, find_item(widget, "imagePickButton"))
    assert picks == [(fid_img,)]
    # «Очистить» clears straight through the VM
    vm.set_image_id(fid_img, 3)
    _pump(1)
    click_item(widget, find_item(widget, "imageClearButton"))
    _pump(1)
    assert vm.template.get_field(fid_img).image_id is None


def test_editor_paste_bridge_answers_visible_center(qtbot, vm, palette):
    widget = load_editor(qtbot, vm, palette)
    root = widget.rootObject()
    before = root.property("pasteCenterOut")
    root.pasteRequested.emit(0)
    center = root.property("pasteCenterOut")
    assert center != before
    # the canvas' own answer for page 0 (visibleCenter) — x is near the page
    # centre horizontally, whatever the fit-width zoom produced
    assert center.x() > 0


# ── 3.2: SheetFillRoot.qml ───────────────────────────────────────────────────


def test_fill_island_loads_with_object_name_contract(qtbot, fill_case, palette):
    fvm, _ = fill_case
    widget = load_fill(qtbot, fvm, palette)
    assert widget.errors() == []
    for name in FILL_OBJECT_NAMES:
        assert find_item(widget, name) is not None, name
    assert widget.rootObject().property("defaultButton") is find_item(
        widget, "saveButton"
    )
    assert find_item(widget, "fillValueHint").property("visible") is True
    # navigation-only rail: no edit chrome ever (the widgets mode mirror)
    assert find_items(widget, "railAddButton") == []
    assert find_items(widget, "railDeleteButton") == []
    assert find_items(widget, "railUpButton") == []


@pytest.fixture
async def fill_case_two_pages(services):
    """Two-page template -> instance fill VM (the nav-rail probe)."""
    sheet_svc, inst_svc = services
    row = await sheet_svc.create("Шаблон")
    design = CharacterSheetViewModel(sheet_svc)
    await design.load(row.id)
    design.add_page(after_index=0)
    await design.save()
    inst = await inst_svc.create("Лист героя", row.id)
    fvm = CharacterSheetFillViewModel(inst_svc, sheet_svc)
    await fvm.load(inst.id)
    return fvm


def test_fill_rail_navigates_without_editing(qtbot, fill_case_two_pages, palette):
    fvm = fill_case_two_pages
    widget = load_fill(qtbot, fvm, palette, size=(900, 700))
    assert island_row_texts(widget, "railPageRow", "railPageText") == [
        "Страница 1", "Страница 2",
    ]
    click_item(widget, island_rows(widget, "railPageRow")[1])
    assert fvm.currentPage == 1
    # a row click never edits anything: no rename fields exist here
    assert find_items(widget, "railPageRenameField") == []


def test_fill_value_panel_branches_write_through_vm(qtbot, fill_case, palette):
    import asyncio

    fvm, ids = fill_case
    widget = load_fill(qtbot, fvm, palette)

    # text branch: value round trip, single VM entrance (set_text)
    fvm.select(ids["text"])
    _pump(2)
    hint = find_item(widget, "fillValueHint")
    assert hint.property("visible") is False
    text_input = find_item(widget, "fillTextInput")
    assert text_input.property("visible") is True
    assert text_input.property("text") == ""
    text_input.setProperty("text", "Иван")
    text_input.editingFinished.emit()
    _pump(1)
    assert fvm.values[ids["text"]] == "Иван"
    assert text_input.property("text") == "Иван"

    # number branch: a refused write re-reads the stored display
    fvm.select(ids["num"])
    _pump(2)
    num_input = find_item(widget, "fillTextInput")
    # a refused write changes nothing (the instance starts from the
    # template-default skeleton — the stored display stays empty)
    num_input.setProperty("text", "99")  # stored max is 10
    num_input.editingFinished.emit()
    _pump(1)
    assert fvm.values[ids["num"]] == ""
    assert num_input.property("text") == ""
    num_input.setProperty("text", "7")
    num_input.editingFinished.emit()
    _pump(1)
    assert fvm.values[ids["num"]] == "7"

    # checkbox branch: toggling the panel toggles the stored value once
    fvm.select(ids["chk"])
    _pump(2)
    check = find_item(widget, "fillCheckbox")
    assert check.property("visible") is True
    before = bool(fvm.values.get(ids["chk"]))
    check.setProperty("checked", not before)
    check.toggled.emit()     # programmatic checked writes stay silent
    _pump(1)
    assert bool(fvm.values.get(ids["chk"])) is not before

    # dropdown branch: selecting an option lands on set_dropdown
    fvm.select(ids["dd"])
    _pump(2)
    combo = find_item(widget, "fillDropdown")
    assert list(combo.property("model")) == ["эльф", "орк"]
    assert int(combo.property("currentIndex")) == 0  # mirrors the stored default
    combo.setProperty("currentIndex", 1)
    combo.activated.emit(1)
    _pump(1)
    assert fvm.values.get(ids["dd"]) == "орк"
    # the same option again is a no-op the VM refuses — nothing changes
    combo.activated.emit(1)
    _pump(1)
    assert fvm.values.get(ids["dd"]) == "орк"

    # image branch: pick goes to the facade, clear goes to the VM
    fvm.select(ids["img"])
    _pump(2)
    picks = track(widget.rootObject().imagePickRequested)
    click_item(widget, find_item(widget, "fillImagePickButton"))
    assert picks == [(ids["img"],)]
    fvm.set_image(ids["img"], 5)
    _pump(1)
    click_item(widget, find_item(widget, "fillImageClearButton"))
    _pump(1)
    assert fvm.values.get(ids["img"]) is None


def test_fill_dropdown_from_canvas_relays_to_facade(qtbot, fill_case, palette):
    fvm, ids = fill_case
    widget = load_fill(qtbot, fvm, palette)
    root = widget.rootObject()
    requests = track(root.dropdownRequested)
    canvas = find_item(widget, "sheetFillCanvas")
    # the bridge contract itself: the canvas' signal is relayed unchanged
    # (the migrated fill suites drive the real click; the QMenu is the
    # facade's native popup — see test_character_sheet_fill_dialog)
    canvas.dropdownRequested.emit(ids["dd"], 12.0, 34.0)
    _pump(1)
    assert requests == [(ids["dd"], 12.0, 34.0)]


def test_fill_action_buttons_emit_and_read_only_locks(qtbot, fill_case, palette):
    fvm, ids = fill_case
    widget = load_fill(qtbot, fvm, palette)
    root = widget.rootObject()
    saves = track(root.saveRequested)
    binds = track(root.bindRequested)
    unbinds = track(root.unbindRequested)

    click_item(widget, find_item(widget, "saveButton"))
    click_item(widget, find_item(widget, "bindButton"))
    assert saves == [()]
    assert binds == [()]
    # «Отвязать» is disabled while unbound (the migrated _sync_bind_buttons)
    unbind = find_item(widget, "unbindButton")
    assert unbind.property("enabled") is False
    root.setProperty("characterBound", True)
    _pump(1)
    assert unbind.property("enabled") is True
    click_item(widget, unbind)
    assert unbinds == [()]

    # read-only: panel off, action buttons gone, canvas input select-only
    fvm.set_read_only(True)
    _pump(2)
    assert find_item(widget, "saveButton").property("visible") is False
    assert find_item(widget, "bindButton").property("visible") is False
    panel = find_item(widget, "fillPropertiesPanel")
    assert panel.property("enabled") is False
    fvm.select(ids["text"])
    _pump(1)
    assert fvm.inline_field_id is None  # disabled rows never open the inline
    fvm.set_read_only(False)
    _pump(1)
    assert find_item(widget, "saveButton").property("visible") is True


# ── 4.3: pixel acceptance — the token palette reaches both window islands ────
# (the launcher 5.3 / sheet-list Q3a convention: exact token pixels through
# grab(), no golden images; the chrome rule says every island pixel is either
# a token or a documented paper constant — the canvas paper itself is probed
# in test_sheet_canvas_island.py.)


def grab_rgb(widget: QQuickWidget) -> QImage:
    img = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    assert not img.isNull()
    return img


def token_rgb(hex_value: str) -> tuple[int, int, int]:
    color = QColor(hex_value)
    assert color.isValid()
    return (color.red(), color.green(), color.blue())


def pixel_rgb(img: QImage, scene_x: float, scene_y: float,
              widget: QQuickWidget) -> tuple[int, int, int]:
    """Pixel under a *scene* point; grab may be scaled by device pixel ratio."""
    sx = img.width() / widget.width()
    sy = img.height() / widget.height()
    x = min(int(scene_x * sx), img.width() - 1)
    y = min(int(scene_y * sy), img.height() - 1)
    color = img.pixelColor(x, y)
    return (color.red(), color.green(), color.blue())


def surface_pixel(widget: QQuickWidget, img: QImage | None = None):
    """Far top-left corner — inside the root's margins, so the root's own
    surfaceColor rectangle, no chrome over it."""
    return pixel_rgb(img or grab_rgb(widget), 3, 3, widget)


def button_pixel(widget: QQuickWidget, button, img: QImage | None = None):
    """A point inside the button's left padding band (background, no glyphs)."""
    point = button.mapToScene(QPointF(4, button.height() / 2))
    return pixel_rgb(img or grab_rgb(widget), point.x(), point.y(), widget)


def _wait_for_pixels(qtbot, widget, probes, timeout: int = 5000) -> None:
    """Probes read the CURRENT frame; grab may lag the polish one sync frame
    (the fact the canvas-island cyrillic probe pinned on full-suite runs)."""
    def settled() -> bool:
        image = grab_rgb(widget)
        return all(
            probe(widget, image) == expected for probe, expected in probes
        )

    qtbot.waitUntil(settled, timeout=timeout)


def test_editor_island_paints_surface_and_accent_tokens(qtbot, vm, palette):
    widget = load_editor(qtbot, vm, palette)
    tokens = palette.tokens
    _wait_for_pixels(qtbot, widget, [
        (surface_pixel, token_rgb(tokens["color.bg.surface"])),
        (lambda w, img: button_pixel(w, find_item(w, "saveButton"), img),
         token_rgb(tokens["color.accent"])),
    ])
    # Explicit re-read after the frame settled: the token equals the pixel.
    image = grab_rgb(widget)
    assert surface_pixel(widget, image) == token_rgb(tokens["color.bg.surface"])
    assert button_pixel(widget, find_item(widget, "saveButton"), image) == (
        token_rgb(tokens["color.accent"])
    )


def test_fill_island_paints_surface_and_accent_tokens(qtbot, fill_case, palette):
    fvm, _ids = fill_case
    widget = load_fill(qtbot, fvm, palette)
    tokens = palette.tokens
    _wait_for_pixels(qtbot, widget, [
        (surface_pixel, token_rgb(tokens["color.bg.surface"])),
        (lambda w, img: button_pixel(w, find_item(w, "saveButton"), img),
         token_rgb(tokens["color.accent"])),
    ])
    image = grab_rgb(widget)
    assert surface_pixel(widget, image) == token_rgb(tokens["color.bg.surface"])
    assert button_pixel(widget, find_item(widget, "saveButton"), image) == (
        token_rgb(tokens["color.accent"])
    )
