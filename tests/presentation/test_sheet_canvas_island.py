"""The character-sheet canvas QML island (change port-character-sheet-canvas-qml-q3b,
tasks 2.1–2.5).

The island-load convention of the launcher/sheet-list precedents: a real
offscreen ``QQuickWidget`` whose only context property the canvas header pins
(``vm`` — production ViewModels, the «VM не знает про QML» seam), addressed
through the shared ``qml_helpers`` walk; synthetic mouse/wheel input follows
the timeline-probe style (explicit ``QMouseEvent``/``QWheelEvent`` through the
application dispatcher — no stale-global button state, positions in canvas
pixels).

Checked here are the island's own acceptance points of group 2 (the migrated
dialog/e2e suites re-target them in group 4):

* 2.1 — the island loads on a test template, the page/field structure is
  addressable (``sheetCanvas`` / ``sheetPage-<i>`` / ``sheetField-<id>``), all
  nine field types render their migrated paint branches, z-order = row order,
  the unthemed paper colors moved 1:1;
* 2.2 — zoom constants (0.25–4.0, step 1.15), cursor-anchored Ctrl+wheel,
  plain-wheel scroll, fit-width on first presentation and on orientation
  switches, the visible-page report into ``vm.set_current_page``,
  ``scrollToPage``/``visibleCenter`` through the probe harness;
* 2.3 — design gestures: tool-placement clicks (Shift = one-shot no-snap),
  single/Shift selection, rubber band (additive with Shift), set drag with the
  cross-gutter relocation counted by the VM, corner-handle resize, dblclick
  branches, Del/Backspace/Esc;
* 2.4 — the inline editor: seeding, live writes into the single VM buffer,
  Enter/Ctrl+Enter/Esc, the number reject re-show, commit-on-switch, the
  panel-push direction;
* 2.5 — fill and read-only: checkbox click toggles, text/number open the
  inline, the image and dropdown bridges report to the facade (the facade
  answers through ``vm.set_dropdown``), read-only is select-only through both
  the mode property and the fill VM's per-row ``disabled`` role.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication

from app.application.services.character_sheet_instance_service import (
    CharacterSheetInstanceService,
)
from app.application.services.character_sheet_service import CharacterSheetService
from app.domain.entities.character_sheet import (
    PAGE_HEIGHT_PT,
    PAGE_WIDTH_PT,
    page_origin,
)
from app.domain.enums.field_type import FieldType
from app.infrastructure.repositories.character_sheet_instance_repository import (
    CharacterSheetInstanceRepository,
)
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)
from app.presentation import qml as qml_shell
from app.presentation.qml.sheet_font import register_sheet_font
from app.presentation.qml.sheet_image_provider import (
    SHEET_IMAGE_PROVIDER_ID,
    SheetImageProvider,
)
from app.presentation.viewmodels.character_sheet_fill_viewmodel import (
    CharacterSheetFillViewModel,
)
from app.presentation.viewmodels.character_sheet_viewmodel import (
    CharacterSheetViewModel,
)
from tests.presentation.qml_helpers import find_item, find_items, walk_items

SHEET_CANVAS_QML = Path(qml_shell.__file__).resolve().parent / "SheetCanvas.qml"

# The test-side harness for the canvas functions Python cannot call directly
# (QML-declared functions are not meta-object invokables): it hosts the real
# SheetCanvas.qml in a Loader and drives the very functions the group-3 window
# islands will call from their own QML.
PROBE_QML = """
import QtQuick

Item {
    id: probe
    objectName: "sheetCanvasProbe"
    property url canvasSource
    // Group 3 (window islands) seam: the canvas takes its VM as a declared
    // property, never as a context property (the one shared engine has one
    // global root context — Q3a pinned it in list_dialog.py). The probe
    // mirrors what the window roots do: receive the VM at load and hand it
    // to the canvas they instantiate.
    property var vm: null

    Loader {
        id: loader
        anchors.fill: parent
        source: probe.canvasSource
        onLoaded: {
            item.anchors.fill = loader
            item.vm = probe.vm
        }
    }

    property int scrollRequest: -1
    onScrollRequestChanged:
        if (scrollRequest >= 0 && loader.item)
            loader.item.scrollToPage(scrollRequest)

    property int centerFor: -1
    property point centerProbe: Qt.point(-12345, -12345)
    onCenterForChanged:
        if (centerFor >= 0 && loader.item)
            centerProbe = loader.item.visibleCenter(centerFor)
}
"""

# The zoom constants spelled out again deliberately (they are canvas.py's
# MIN/MAX/STEP ported 1:1): a silent move on the island must fail this pin.
MIN_ZOOM = 0.25
MAX_ZOOM = 4.0
ZOOM_STEP = 1.15


# ── fixtures (the migrated canvas suites' services) ───────────────────────────


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
async def vm2(services):
    """Two-page tape (the A-playable ribbon)."""
    sheet_svc, _ = services
    row = await sheet_svc.create("Лист")
    view_model = CharacterSheetViewModel(sheet_svc)
    await view_model.load(row.id)
    view_model.add_page(after_index=0)
    return view_model


@pytest.fixture
async def fill_case(services):
    """Saved template + instance for the fill/readonly modes.

    Text «Иван» and dropdown «эльф» with an EMPTY value map exercise the
    display role's default path (resolve_display), the checkbox keeps its
    template-default "true" — distinct from any value the map could set.
    """
    sheet_svc, inst_svc = services
    row = await sheet_svc.create("Шаблон")
    template = await sheet_svc.load(row.id)
    text_f = template.add_field(FieldType.TEXT, (40.0, 40.0))
    text_f.content = "Иван"
    num_f = template.add_field(FieldType.NUMBER, (40.0, 80.0))
    num_f.content = "4"
    chk = template.add_field(FieldType.CHECKBOX, (40.0, 120.0))
    chk.content = "true"
    lab = template.add_field(FieldType.LABEL, (40.0, 160.0))
    lab.content = "Имя"
    dd = template.add_field(FieldType.DROPDOWN, (40.0, 200.0))
    dd.options = ["эльф", "орк"]
    dd.content = "эльф"
    img = template.add_field(FieldType.IMAGE, (40.0, 280.0))
    img.image_id = 7
    await sheet_svc.update_pages(row.id, template)
    inst = await inst_svc.create("Лист героя", row.id)
    fvm = CharacterSheetFillViewModel(inst_svc, sheet_svc)
    await fvm.load(inst.id)
    ids = {"text": text_f.id, "num": num_f.id, "chk": chk.id,
           "lab": lab.id, "dd": dd.id, "img": img.id}
    return fvm, ids


# ── the island loader (the launcher/sheet-list convention) ───────────────────


def _pump(ticks: int = 2) -> None:
    for _ in range(ticks):
        QApplication.processEvents()


_PROBE_PATH: str | None = None


def _probe_file() -> str:
    global _PROBE_PATH
    if _PROBE_PATH is None:
        dir_ = tempfile.mkdtemp(prefix="sheet_canvas_probe_")
        _PROBE_PATH = str(Path(dir_) / "SheetCanvasProbe.qml")
        Path(_PROBE_PATH).write_text(PROBE_QML, encoding="utf-8")
    return _PROBE_PATH


def _base_widget(qtbot, vm, size) -> QQuickWidget:
    register_sheet_font()
    if QQuickStyle.name() != "Basic":
        QQuickStyle.setStyle("Basic")
    widget = QQuickWidget()
    qtbot.addWidget(widget)
    # the same sizing + image-provider conventions the window facades apply
    # in production (D7: image://sheet is registered per engine)
    widget.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
    widget.engine().addImageProvider(SHEET_IMAGE_PROVIDER_ID,
                                     SheetImageProvider())
    widget.resize(*size)
    vm.setParent(widget)  # the VM outlives the island, dies with it
    # Group 3 seam: the VM arrives as a DECLARED root-object property, applied
    # before the object completes (the production facade uses the very same
    # injection — the engine-wide root context must never carry a per-dialog
    # name, Q3a lesson pinned in list_dialog.py).
    widget.setInitialProperties({"vm": vm})
    return widget


def load_canvas(qtbot, vm, size=(700, 700), mode: str | None = None) -> QQuickWidget:
    """The canvas as the island ROOT (the group-3 facades embed it as a child;
    every address used here is relative, so both framings address the same)."""
    widget = _base_widget(qtbot, vm, size)
    widget.setSource(QUrl.fromLocalFile(str(SHEET_CANVAS_QML)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    if mode is not None:
        root(widget).setProperty("mode", mode)
    widget.show()
    _pump(6)
    return widget


def load_probe(qtbot, vm, size=(700, 700)) -> QQuickWidget:
    widget = _base_widget(qtbot, vm, size)
    widget.setSource(QUrl.fromLocalFile(_probe_file()))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    # The probe owns its canvasSource property; handing it the url after the
    # load starts feeds the Loader's binding the same way the group-3 facades
    # will (the VM itself rode in through _base_widget's initial properties).
    root(widget).setProperty("canvasSource",
                             QUrl.fromLocalFile(str(SHEET_CANVAS_QML)))
    widget.show()
    _pump(6)
    return widget


# ── addressing & input helpers ────────────────────────────────────────────────


def root(widget):
    return widget.rootObject()


def canvas(widget):
    if root(widget).objectName() == "sheetCanvas":
        return root(widget)
    return find_item(widget, "sheetCanvas")


def zoom(widget) -> float:
    return float(canvas(widget).property("zoom"))


def flick(widget):
    return find_item(widget, "sheetFlick")


def content_xy(widget) -> tuple[float, float]:
    f = flick(widget)
    return float(f.property("contentX")), float(f.property("contentY"))


def tape_point(widget, px: float, py: float) -> QPointF:
    """A tape (page-unit) point → the canvas-pixel position of the click.

    Fractional on purpose: a quantised QPoint position would leak a sub-pixel
    round-trip error (≈1/zoom page points) back into the page coordinates the
    VM computes from the click, so synthetic events carry the exact position.
    """
    z = zoom(widget)
    cx, cy = content_xy(widget)
    return QPointF(px * z - cx, py * z - cy)


def scene_center(item) -> QPoint:
    p = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
    return QPoint(round(p.x()), round(p.y()))


def _send(widget, kind, pos, button, buttons,
          modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    QApplication.sendEvent(widget, QMouseEvent(
        kind, QPointF(pos), widget.mapToGlobal(QPointF(pos).toPoint()),
        button, buttons, modifiers,
    ))
    _pump(1)


def mouse_press(widget, pos, modifiers=Qt.KeyboardModifier.NoModifier):
    _send(widget, QEvent.Type.MouseButtonPress, pos,
          Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, modifiers)


def mouse_release(widget, pos):
    _send(widget, QEvent.Type.MouseButtonRelease, pos,
          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)


def mouse_move(widget, pos, modifiers=Qt.KeyboardModifier.NoModifier):
    _send(widget, QEvent.Type.MouseMove, pos,
          Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, modifiers)


def click_at(widget, pos: QPoint, modifiers=Qt.KeyboardModifier.NoModifier):
    """press(modifiers) + release — the migrated ``_click`` semantics (only
    the press carries modifiers, exactly like qtbot.mouseClick)."""
    mouse_press(widget, pos, modifiers)
    mouse_release(widget, pos)


def click_field(widget, fid: str, *, double: bool = False,
                modifiers=Qt.KeyboardModifier.NoModifier):
    item = find_item(widget, f"sheetField-{fid}")
    pos = scene_center(item)
    if double:
        mouse_press(widget, pos)
        mouse_release(widget, pos)
        _send(widget, QEvent.Type.MouseButtonDblClick, pos,
              Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
        # Qt's own mouseDClick ends the double-click press with a physical
        # release; without it the canvas would hold the press's drag state
        # until the next click and turn it into a stray move.
        mouse_release(widget, pos)
    else:
        click_at(widget, pos, modifiers)


def click_point_pt(widget, px: float, py: float,
                   modifiers=Qt.KeyboardModifier.NoModifier):
    click_at(widget, tape_point(widget, px, py), modifiers)


def drag_pt(widget, start_pt: tuple, end_pt: tuple,
            modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    """Press, dragged moves, release (the timeline-probe sequence)."""
    start = tape_point(widget, *start_pt)
    end = tape_point(widget, *end_pt)
    mouse_press(widget, start, modifiers)
    mouse_move(widget, QPointF((start.x() + end.x()) / 2.0,
                               (start.y() + end.y()) / 2.0), modifiers)
    mouse_move(widget, end, modifiers)
    mouse_release(widget, end)


def wheel(widget, pos, dy: int,
          modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    QApplication.sendEvent(widget, QWheelEvent(
        QPointF(pos), widget.mapToGlobal(QPointF(pos).toPoint()),
        QPoint(0, 0), QPoint(0, dy),
        Qt.MouseButton.NoButton, modifiers,
        Qt.ScrollPhase.NoScrollPhase, False,
    ))
    _pump(2)


def key_press(widget, code, modifiers=Qt.KeyboardModifier.NoModifier,
              text: str = "") -> None:
    for etype in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        QApplication.sendEvent(widget, QKeyEvent(etype, code, modifiers, text))
    _pump(1)


def _key_for(ch: str) -> int:
    if ch.isalpha():
        return int(getattr(Qt.Key, f"Key_{ch.upper()}"))
    if ch.isdigit():
        # Qt names the top-row digits Key_1 .. Key_0 (no Key_DigitN exists)
        return int(getattr(Qt.Key, f"Key_{ch}"))
    specials = {",": Qt.Key.Key_Comma, ".": Qt.Key.Key_Period,
                "-": Qt.Key.Key_Minus, " ": Qt.Key.Key_Space}
    return int(specials.get(ch, Qt.Key.Key_unknown))


def type_text(widget, text: str) -> None:
    """Key events with real text payloads (deterministic, no keyboard layout —
    the mention_text_edit precedent)."""
    for ch in text:
        for etype in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QApplication.sendEvent(widget, QKeyEvent(
                etype, _key_for(ch), Qt.KeyboardModifier.NoModifier, ch))
    _pump(2)


def editor(widget):
    return find_item(widget, "sheetInlineEditor")


def field_pos(vm, fid: str):
    page = vm.page_of(fid)
    field = vm.template.get_field(fid)
    return page, field.x, field.y, field.w, field.h


def text_of(widget, fid: str) -> str | None:
    item = find_item(widget, f"sheetField-{fid}")
    for i in walk_items(item):
        if i.objectName() == "fieldText":
            return i.property("text")
    return None


def sub_named(widget, fid: str, name: str):
    item = find_item(widget, f"sheetField-{fid}")
    for i in walk_items(item):
        if i.objectName() == name:
            return i
    return None


def visible_named(widget, fid: str, name: str):
    item = sub_named(widget, fid, name)
    return None if item is None else bool(item.property("visible"))


def place(vm, type_: FieldType, x: float, y: float, page: int = 0) -> str:
    return vm.place(type_.value, x, y, page)


# ── 2.1 — loading, addressable structure, the nine type renders ───────────────


class TestStructure:
    def test_island_loads_pages_and_objectname_contract(self, qtbot, vm2):
        w = load_canvas(qtbot, vm2)
        names = {root(w).objectName()} | {i.objectName() for i in walk_items(root(w))}
        # The island's address contract, spelled out literally.
        for name in ("sheetCanvas", "sheetFlick", "sheetTape", "sheetGestures",
                     "sheetInlineLoader"):
            assert name in names
        assert find_item(w, "sheetPage-0") is not None
        p1 = find_item(w, "sheetPage-1")
        z = zoom(w)
        tl = p1.mapToScene(QPointF(0, 0))
        _, oy = page_origin(1, PAGE_HEIGHT_PT)
        assert tl.x() == pytest.approx(0.0, abs=1.0)
        assert tl.y() == pytest.approx(oy * z - content_xy(w)[1], abs=1.0)
        assert p1.width() == pytest.approx(PAGE_WIDTH_PT)
        assert p1.height() == pytest.approx(PAGE_HEIGHT_PT)

    def test_empty_template_loads_as_blank_clickable_viewport(self, qtbot, vm):
        # No field exists before the first placement; the canvas is still
        # there and fits (the migrated pre-load tolerance).
        w = load_canvas(qtbot, vm)
        assert find_items(w, "sheetPage-0")
        assert zoom(w) == pytest.approx(700 / PAGE_WIDTH_PT, rel=1e-3)

    def test_field_rows_become_addressable_delegates(self, qtbot, vm):
        w = load_canvas(qtbot, vm)
        fid = place(vm, FieldType.LABEL, 100.0, 150.0)
        _pump(3)
        item = find_item(w, f"sheetField-{fid}")
        # The delegate lays out in tape units straight from the model roles.
        assert item.x() == pytest.approx(100.0, abs=0.01)
        assert item.y() == pytest.approx(150.0, abs=0.01)
        assert item.width() == pytest.approx(vm.template.get_field(fid).w, abs=0.01)

    def test_all_nine_types_render_after_the_migrated_paint_branches(
        self, qtbot, vm
    ):
        w = load_canvas(qtbot, vm)
        ids = {
            "label": place(vm, FieldType.LABEL, 40, 40),
            "text": place(vm, FieldType.TEXT, 40, 90),
            "textarea": place(vm, FieldType.TEXTAREA, 40, 140),
            "number": place(vm, FieldType.NUMBER, 40, 190),
            "checkbox": place(vm, FieldType.CHECKBOX, 40, 240),
            "dropdown": place(vm, FieldType.DROPDOWN, 40, 290),
            "image": place(vm, FieldType.IMAGE, 40, 340),
            "rect": place(vm, FieldType.RECT, 40, 390),
            "line": place(vm, FieldType.LINE, 40, 440),
        }
        _pump(2)
        vm.set_content(ids["label"], "Метка")
        vm.set_content(ids["text"], "текст")
        vm.set_content(ids["number"], "12")
        vm.set_options(ids["dropdown"], ["эльф", "орк"])
        vm.set_content(ids["dropdown"], "орк")
        vm.toggle_checkbox(ids["checkbox"])          # default → "true"
        vm.set_image_id(ids["image"], 7)
        _pump(3)
        assert text_of(w, ids["label"]) == "Метка"
        assert text_of(w, ids["text"]) == "текст"
        assert text_of(w, ids["number"]) == "12"
        assert text_of(w, ids["dropdown"]) == "орк"
        assert text_of(w, ids["rect"]) is None       # outline only, no text
        assert visible_named(w, ids["rect"], "fieldFrame") is True
        assert visible_named(w, ids["checkbox"], "fieldCheck") is True
        vm.toggle_checkbox(ids["checkbox"])          # back to "false"
        _pump(2)
        assert visible_named(w, ids["checkbox"], "fieldCheck") is False
        # image: the dashed placeholder frame always, the Image itself only
        # with an imageKey (async bytes over image://sheet — D7).
        assert visible_named(w, ids["image"], "fieldImageFrame") is True
        image_item = sub_named(w, ids["image"], "fieldImage")
        assert image_item is not None
        assert bool(image_item.property("visible")) is True
        # The Image's source is a QUrl — the scheme/id contract is what pins.
        assert str(image_item.property("source").toString()) == "image://sheet/7"
        assert visible_named(w, ids["line"], "fieldLine") is True

    def test_zorder_row_order_hit_test_topmost_wins(self, qtbot, vm):
        w = load_canvas(qtbot, vm)
        first = place(vm, FieldType.LABEL, 200, 300)
        second = place(vm, FieldType.LABEL, 240, 308)   # overlaps the first
        _pump(3)
        # A click inside the overlap: the later-placed row wins (the migrated
        # z ladder page*10000 + index + 1 == the flat Repeater order). The
        # overlap point is arithmetic (label default 72x18): both rects hold
        # (255, 312), the second row is the top one.
        assert first != second
        click_point_pt(w, 255.0, 312.0)
        assert list(vm.selected_ids) == [second]

    def test_paper_constants_moved_1_to_1(self, qtbot, vm):
        w = load_canvas(qtbot, vm)
        c = canvas(w)
        expected = {
            "gutterColor": "#e2e2e2",       # GUTTER_BACKGROUND
            "pageFrameColor": "#5a5a5a",    # _PAGE_FRAME
            "frameColor": "#788cb4",        # _FRAME_COLOR
            "selectedColor": "#2f7de1",     # _SELECTED_COLOR
            "textColor": "#141414",         # _TEXT_COLOR
            "lineColor": "#3c3c3c",         # _LINE_COLOR
            "checkColor": "#1e6ebe",        # _CHECK_COLOR
            "imagePlaceholderColor": "#969696",   # _IMAGE_PLACEHOLDER
            "gridColor": "#d2dae4",         # _GRID_COLOR
        }
        for name, hex_ in expected.items():
            got = c.property(name)
            assert got.name().lower() == hex_, (name, got.name())
        # The root paints the gutter wash; the view-constant knobs.
        assert c.property("color").name().lower() == "#e2e2e2"
        assert float(c.property("minZoom")) == MIN_ZOOM
        assert float(c.property("maxZoom")) == MAX_ZOOM
        assert float(c.property("zoomStep")) == ZOOM_STEP


    def test_cyrillic_renders_through_the_sheet_font_pixels(self, qtbot, vm):
        # The migrated `test_cyrillic_renders_and_font_is_dejavu`: the render
        # pass is the island's Text delegate on the one bundled DejaVu Sans
        # (the family must be a registered application font — the widgets test
        # pinned the item font, the island pins the delegate's), and the
        # Cyrillic glyphs must really paint: dark text pixels
        # (_TEXT_COLOR #141414) strictly inside the field rect on white paper.
        # Nothing else in that interior is dark: the label frame is #788cb4
        # (green 140 > 127) and the page border lives a page margin away.
        from PySide6.QtGui import QFontDatabase, QImage

        from app.presentation.qml.sheet_font import SHEET_FONT_FAMILY

        w = load_canvas(qtbot, vm)
        assert SHEET_FONT_FAMILY in QFontDatabase.families()  # registered once

        fid = place(vm, FieldType.LABEL, 50, 50)
        vm.set_content(fid, "Кириллица")
        _pump(3)
        txt = sub_named(w, fid, "fieldText")
        assert txt is not None and txt.property("text") == "Кириллица"
        assert txt.property("font").family() == SHEET_FONT_FAMILY
        assert bool(txt.property("visible")) is True

        item = find_item(w, f"sheetField-{fid}")
        corner = item.mapToScene(QPointF(0, 0))
        other = item.mapToScene(QPointF(item.width(), item.height()))
        # Inset 2 px: keep the scan strictly off the field's own frame pass.
        x0 = int(corner.x()) + 2
        y0 = int(corner.y()) + 2
        x1 = int(other.x()) - 1
        y1 = int(other.y()) - 1

        def dark_in_rect() -> bool:
            img = w.grab().toImage().convertToFormat(
                QImage.Format.Format_RGBA8888)
            if img.isNull():
                return False
            return any(
                (c := img.pixelColor(x, y)).red() < 128
                and c.green() < 128
                and c.blue() < 128
                for y in range(y0, y1)
                for x in range(x0, x1)
            )

        # The grab lags one scene-graph frame behind the QML property change
        # (the same fact the smoke test's fresh-widget render proves); pumping
        # until the frame catches up is timing only — the pixel assertion
        # itself stays the hard migrated criterion.
        qtbot.waitUntil(dark_in_rect, timeout=5000)

    def test_paper_pixels_are_the_migrated_constants(self, qtbot, vm2):
        # The pixel half of the 1:1 paper port (task 4.3 / design D10): the
        # page interior paints pure white and the GUTTER_PT band between two
        # pages paints GUTTER_BACKGROUND — measured through grab() at the
        # fit-width zoom, not only pinned as QML properties above.
        from PySide6.QtGui import QImage

        from app.domain.entities.character_sheet import GUTTER_PT

        assert GUTTER_PT == 24.0
        w = load_canvas(qtbot, vm2)
        # Park the page-1 gutter band at mid-viewport (at contentY=0 it sits
        # below the fold of the 700-px canvas).
        _, oy1 = page_origin(1, PAGE_HEIGHT_PT)
        z = zoom(w)
        flick(w).setProperty("contentY", max(0.0, oy1 * z - 350.0))
        _pump(3)

        def rgb(tape_x: float, tape_y: float) -> tuple[int, int, int]:
            pos = tape_point(w, tape_x, tape_y)
            img = w.grab().toImage().convertToFormat(
                QImage.Format.Format_RGBA8888)
            assert not img.isNull()
            sx = img.width() / w.width()
            sy = img.height() / w.height()
            c = img.pixelColor(min(int(pos.x() * sx), img.width() - 1),
                               min(int(pos.y() * sy), img.height() - 1))
            return (c.red(), c.green(), c.blue())

        white = (255, 255, 255)          # the page Rectangle's "white"
        gutter = (0xE2, 0xE2, 0xE2)      # GUTTER_BACKGROUND #e2e2e2

        def painted() -> bool:
            return (rgb(PAGE_WIDTH_PT / 2.0, 600.0) == white
                    and rgb(PAGE_WIDTH_PT / 2.0,
                            PAGE_HEIGHT_PT + GUTTER_PT / 2.0) == gutter)

        # Frame freshness only (grab lags one scene-graph sync); the color
        # equalities below stay the hard assertion either way.
        qtbot.waitUntil(painted, timeout=5000)
        assert rgb(PAGE_WIDTH_PT / 2.0, 600.0) == white
        assert rgb(PAGE_WIDTH_PT / 2.0,
                   PAGE_HEIGHT_PT + GUTTER_PT / 2.0) == gutter


# ── 2.2 — zoom / scroll / fit-width / visible page ────────────────────────────


class TestZoomAndTape:
    def test_fit_width_on_first_presentation(self, qtbot, vm):
        w = load_canvas(qtbot, vm, size=(700, 700))
        assert zoom(w) == pytest.approx(700 / PAGE_WIDTH_PT, rel=1e-3)
        cx, cy = content_xy(w)
        assert cx == pytest.approx(0.0, abs=1e-6)
        assert cy == pytest.approx(0.0, abs=1e-6)

    def test_fit_capped_by_max_zoom(self, qtbot, vm):
        w = load_canvas(qtbot, vm, size=(4760, 700))
        assert zoom(w) == pytest.approx(MAX_ZOOM, rel=1e-6)

    def test_ctrl_wheel_zoom_steps_1_15_from_the_cursor(self, qtbot, vm):
        w = load_canvas(qtbot, vm)
        z0 = zoom(w)
        cx0, cy0 = content_xy(w)
        anchor = QPoint(300, 400)
        bx = (300 + cx0) / z0
        by = (400 + cy0) / z0
        wheel(w, anchor, 120, Qt.KeyboardModifier.ControlModifier)
        z1 = zoom(w)
        assert z1 == pytest.approx(z0 * ZOOM_STEP, rel=1e-3)
        # The tape point under the cursor stayed under the cursor.
        cx1, cy1 = content_xy(w)
        assert bx * z1 - cx1 == pytest.approx(300.0, abs=1.0)
        assert by * z1 - cy1 == pytest.approx(400.0, abs=1.0)
        wheel(w, anchor, -120, Qt.KeyboardModifier.ControlModifier)
        assert zoom(w) == pytest.approx(z0, rel=1e-3)

    def test_zoom_clamps_at_the_migrated_min_max(self, qtbot, vm):
        w = load_canvas(qtbot, vm)
        for _ in range(30):
            wheel(w, QPoint(350, 350), 120, Qt.KeyboardModifier.ControlModifier)
        assert zoom(w) == pytest.approx(MAX_ZOOM)
        for _ in range(80):
            wheel(w, QPoint(350, 350), -120, Qt.KeyboardModifier.ControlModifier)
        assert zoom(w) == pytest.approx(MIN_ZOOM)

    def test_plain_wheel_scrolls_the_tape(self, qtbot, vm2):
        w = load_canvas(qtbot, vm2)
        wheel(w, QPoint(350, 350), -120)
        assert content_xy(w)[1] == pytest.approx(120.0, abs=1.0)
        for _ in range(20):   # clamped at the content bottom
            wheel(w, QPoint(350, 350), -120)
        assert content_xy(w)[1] == pytest.approx(
            max(0.0, float(flick(w).property("contentHeight")) - 700.0), abs=2.0)
        for _ in range(40):   # and at the top
            wheel(w, QPoint(350, 350), 120)
        assert content_xy(w)[1] == pytest.approx(0.0, abs=1e-6)

    def test_orientation_switch_refits_width(self, qtbot, vm):
        w = load_canvas(qtbot, vm)
        assert vm.set_orientation("landscape") is True
        _pump(4)
        # The landscape page fills the canvas width again (task 2.2).
        assert zoom(w) == pytest.approx(700 / PAGE_HEIGHT_PT, rel=1e-3)

    def test_visible_page_reports_through_the_vm_channel(self, qtbot, vm2):
        w = load_canvas(qtbot, vm2)
        assert vm2.current_page_index == 0
        z = zoom(w)
        _, oy = page_origin(1, PAGE_HEIGHT_PT)
        flick(w).setProperty("contentY", oy * z + 40)
        _pump(3)
        assert vm2.current_page_index == 1
        flick(w).setProperty("contentY", 0)
        _pump(3)
        assert vm2.current_page_index == 0

    def test_scroll_to_page_and_visible_center_invokables(self, qtbot, vm2):
        w = load_probe(qtbot, vm2)
        z = zoom(w)
        _, oy = page_origin(1, PAGE_HEIGHT_PT)
        root(w).setProperty("scrollRequest", 1)
        _pump(3)
        assert content_xy(w)[1] == pytest.approx(oy * z, abs=1.0)
        root(w).setProperty("centerFor", 1)
        _pump(2)
        point = root(w).property("centerProbe")
        # viewport ∩ page-2 centre in page-local points (the paste seam).
        view_h_pts = 700.0 / z
        expect_y = min(view_h_pts, PAGE_HEIGHT_PT) / 2.0
        assert point.x() == pytest.approx(PAGE_WIDTH_PT / 2.0, abs=1.0)
        assert point.y() == pytest.approx(expect_y, abs=1.0)


# ── 2.3 — design gestures ─────────────────────────────────────────────────────


class TestDesignGestures:
    def test_tool_click_places_at_the_page_point(self, qtbot, vm):
        w = load_canvas(qtbot, vm)
        vm.set_tool("place_text")
        click_point_pt(w, 120.0, 250.0)
        _pump(3)
        assert len(vm.template.pages[0].fields) == 1
        field = vm.template.pages[0].fields[0]
        assert field.type is FieldType.TEXT
        assert (field.x, field.y) == (pytest.approx(120.0), pytest.approx(250.0))
        # place selects the new field and resets the tool (the VM contract).
        assert list(vm.selected_ids) == [field.id]
        assert vm.tool == "pointer"

    def test_gutter_click_with_a_placement_tool_places_nothing(self, qtbot, vm2):
        w = load_canvas(qtbot, vm2)
        vm2.set_tool("place_label")
        click_point_pt(w, 300.0, PAGE_HEIGHT_PT + 8.0)   # inside the gutter
        page_fields = [len(p.fields) for p in vm2.template.pages]
        assert page_fields == [0, 0]

    def test_shift_click_places_unsnapped_while_the_grid_is_on(self, qtbot, vm):
        w = load_canvas(qtbot, vm)
        vm.set_snap_enabled(True)
        _pump(2)
        grids = [i for i in walk_items(root(w)) if i.objectName() == "pageGrid"]
        assert grids and all(bool(i.property("visible")) for i in grids)
        vm.set_tool("place_label")
        click_point_pt(w, 122.3, 251.4)
        assert len(vm.template.pages[0].fields) == 1
        snapped = vm.template.pages[0].fields[0]
        assert (snapped.x, snapped.y) == (124.0, 252.0)      # SNAP_PT = 4
        vm.set_tool("place_label")
        click_point_pt(w, 301.7, 402.2,
                       modifiers=Qt.KeyboardModifier.ShiftModifier)
        unsnapped = vm.template.pages[0].fields[-1]
        assert (unsnapped.x, unsnapped.y) == pytest.approx((301.7, 402.2))
        # And the normal click after that snaps again (one-shot override).
        vm.set_tool("place_label")
        click_point_pt(w, 300.6, 500.6)
        assert (vm.template.pages[0].fields[-1].x,
                vm.template.pages[0].fields[-1].y) == (300.0, 500.0)

    def test_click_selects_shift_click_toggles(self, qtbot, vm):
        w = load_canvas(qtbot, vm)
        a = place(vm, FieldType.LABEL, 60, 60)
        b = place(vm, FieldType.LABEL, 60, 200)
        _pump(3)
        click_field(w, a)
        assert list(vm.selected_ids) == [a]
        click_field(w, b, modifiers=Qt.KeyboardModifier.ShiftModifier)
        assert list(vm.selected_ids) == [a, b]
        click_field(w, a, modifiers=Qt.KeyboardModifier.ShiftModifier)
        assert list(vm.selected_ids) == [b]

    def test_click_empty_and_escape_clear_the_selection(self, qtbot, vm):
        w = load_canvas(qtbot, vm)
        a = place(vm, FieldType.LABEL, 60, 60)
        _pump(3)
        click_field(w, a)
        # an empty page point that fits inside the 700-px viewport
        click_point_pt(w, 450.0, 550.0)
        assert list(vm.selected_ids) == []
        click_field(w, a)
        key_press(w, Qt.Key.Key_Escape)                  # Esc without inline
        assert list(vm.selected_ids) == []

    def test_rubber_band_selects_intersecting_shift_additive(self, qtbot, vm):
        w = load_canvas(qtbot, vm)
        a = place(vm, FieldType.LABEL, 80, 80)
        b = place(vm, FieldType.LABEL, 80, 380)
        _pump(3)
        drag_pt(w, (20.0, 30.0), (300.0, 430.0))
        _pump(2)
        assert set(vm.selected_ids) == {a, b}
        # Shift-click out of a standing selection drops ONE field (2.3), then
        # an additive rubber band brings it back (the migrated select_ids).
        click_field(w, a, modifiers=Qt.KeyboardModifier.ShiftModifier)
        assert set(vm.selected_ids) == {b}
        drag_pt(w, (20.0, 30.0), (300.0, 140.0),
                modifiers=Qt.KeyboardModifier.ShiftModifier)
        assert set(vm.selected_ids) == {a, b}

    def test_drag_moves_live_within_the_page_and_commits(self, qtbot, vm):
        w = load_canvas(qtbot, vm)
        a = place(vm, FieldType.LABEL, 100, 100)
        _pump(3)
        drag_pt(w, (110.0, 110.0), (180.0, 160.0))
        _pump(2)
        page, x, y, _w, _h = field_pos(vm, a)
        assert page == 0
        assert (x, y) == (pytest.approx(170.0, abs=1.0),
                          pytest.approx(150.0, abs=1.0))

    def test_drag_through_the_gutter_relocates_by_vm_count(self, qtbot, vm2):
        w = load_canvas(qtbot, vm2)
        a = place(vm2, FieldType.LABEL, 100, 700)    # near the page-0 bottom
        _pump(3)
        # Scroll so both the grab point and the page-1 landing fit the
        # viewport (the old widget relied on the auto-scroll margin; the tape
        # here is exactly 700 px tall, so the drag happens inside it).
        flick(w).setProperty("contentY", 700.0 * zoom(w))
        _pump(2)
        # Drop far into page 1 — the page change is the VM's computation
        # (design D5: drag_move/apply_drag know the gutter).
        drag_pt(w, (110.0, 710.0), (140.0, PAGE_HEIGHT_PT + 140.0))
        _pump(3)
        assert vm2.page_of(a) == 1
        _page, x, y, _w, _h = field_pos(vm2, a)
        assert 0 <= x <= PAGE_WIDTH_PT and 0 <= y <= PAGE_HEIGHT_PT

    def test_multi_selection_drag_moves_the_set(self, qtbot, vm):
        w = load_canvas(qtbot, vm)
        a = place(vm, FieldType.LABEL, 60, 60)
        b = place(vm, FieldType.LABEL, 60, 180)
        _pump(3)
        click_field(w, a)
        click_field(w, b, modifiers=Qt.KeyboardModifier.ShiftModifier)
        assert set(vm.selected_ids) == {a, b}
        drag_pt(w, (70.0, 70.0), (110.0, 95.0))
        _pump(2)
        assert field_pos(vm, a)[1] == pytest.approx(100.0, abs=1.0)
        assert field_pos(vm, b)[1] == pytest.approx(100.0, abs=1.0)

    def test_corner_handle_resize(self, qtbot, vm):
        w = load_canvas(qtbot, vm)
        a = place(vm, FieldType.LABEL, 100, 300)
        _page, x0, y0, w0, h0 = field_pos(vm, a)
        _pump(3)
        click_field(w, a)                          # single selection → handles
        _pump(2)
        handles = [i for i in walk_items(root(w))
                   if i.objectName().startswith("fieldHandle-")]
        assert len(handles) == 4                   # the migrated handle_count
        se = (x0 + w0, y0 + h0)                    # the page-local SE corner
        drag_pt(w, (se[0] + 0.5, se[1] + 0.5), (se[0] + 30.0, se[1] + 20.0))
        _pump(2)
        _page, _x, _y, w1, h1 = field_pos(vm, a)
        assert w1 == pytest.approx(w0 + 30.0, abs=1.0)
        assert h1 == pytest.approx(h0 + 20.0, abs=1.0)

    def test_doubleclick_branches_inline_toggle_bridge_and_plain_selects(
        self, qtbot, vm
    ):
        w = load_canvas(qtbot, vm)
        text_fid = place(vm, FieldType.TEXT, 60, 60)
        chk = place(vm, FieldType.CHECKBOX, 60, 200)
        img = place(vm, FieldType.IMAGE, 60, 280)
        # The image default box (120x120) reaches y=400 — dd/rect live below
        # it so every click point is unambiguous (fieldAt prefers the
        # selection, so overlaps would steal the hit like in the widgets).
        dd = place(vm, FieldType.DROPDOWN, 60, 430)
        rect = place(vm, FieldType.RECT, 60, 540)
        _pump(3)
        click_field(w, text_fid, double=True)
        _pump(2)
        assert vm.inline_field_id == text_fid
        key_press(w, Qt.Key.Key_Escape)
        _pump(1)
        assert vm.inline_field_id is None
        click_field(w, chk, double=True)
        assert vm.template.get_field(chk).content == "true"    # default flips
        click_field(w, img, double=True)
        assert canvas(w).property("lastImageFieldId") == img   # the bridge
        click_field(w, dd, double=True)
        assert list(vm.selected_ids) == [dd]
        assert vm.inline_field_id is None
        click_field(w, rect, double=True)
        assert list(vm.selected_ids) == [rect]
        assert vm.inline_field_id is None

    def test_del_and_backspace_remove_the_selection(self, qtbot, vm):
        w = load_canvas(qtbot, vm)
        a = place(vm, FieldType.LABEL, 60, 60)
        b = place(vm, FieldType.LABEL, 60, 200)
        _pump(3)
        click_field(w, a)
        key_press(w, Qt.Key.Key_Delete)
        _pump(2)
        assert vm.template.get_field(a) is None
        assert vm.template.get_field(b) is not None
        click_field(w, b)
        key_press(w, Qt.Key.Key_Backspace)
        _pump(2)
        assert vm.template.get_field(b) is None


# ── 2.4 — inline editing (native QML editors, no proxy) ───────────────────────


class TestInlineEditing:
    def test_open_seed_live_write_and_enter_commit(self, qtbot, vm):
        w = load_canvas(qtbot, vm)
        fid = place(vm, FieldType.TEXT, 60, 60)
        vm.set_content(fid, "x")
        _pump(3)
        click_field(w, fid, double=True)
        _pump(2)
        ed = editor(w)
        assert ed.property("text") == "x"
        type_text(w, "123")
        assert vm.template.get_field(fid).content == "x123"  # single live buffer
        assert text_of(w, fid) == "x123"                      # repainted
        key_press(w, Qt.Key.Key_Return, text="\r")
        _pump(2)
        assert vm.inline_field_id is None
        assert vm.template.get_field(fid).content == "x123"

    def test_number_reject_reshows_valid_enter_applies_normalized(self, qtbot, vm):
        w = load_canvas(qtbot, vm)
        fid = place(vm, FieldType.NUMBER, 60, 60)
        vm.set_content(fid, "4")
        _pump(3)
        click_field(w, fid, double=True)
        _pump(2)
        ed = editor(w)
        assert ed.property("text") == "4"
        type_text(w, "abc")
        assert vm.template.get_field(fid).content == "4"      # no leaks
        key_press(w, Qt.Key.Key_Return, text="\r")
        _pump(2)
        # The reject: the editor stays open re-showing the stored value.
        assert vm.inline_field_id == fid
        assert editor(w).property("text") == "4"
        type_text(w, "5,5")
        assert vm.template.get_field(fid).content == "4"      # still no draft
        key_press(w, Qt.Key.Key_Return, text="\r")
        _pump(2)
        assert vm.template.get_field(fid).content == "5.5"    # ',' → '.'
        assert vm.inline_field_id is None

    def test_escape_cancels_restoring_the_snapshot(self, qtbot, vm):
        w = load_canvas(qtbot, vm)
        fid = place(vm, FieldType.TEXT, 60, 60)
        vm.set_content(fid, "keep")
        _pump(3)
        click_field(w, fid, double=True)
        _pump(2)
        type_text(w, "zz")
        assert vm.template.get_field(fid).content == "keepzz"
        key_press(w, Qt.Key.Key_Escape)
        _pump(2)
        assert vm.inline_field_id is None
        assert vm.template.get_field(fid).content == "keep"

    def test_opening_another_field_commits_the_previous_session(self, qtbot, vm):
        w = load_canvas(qtbot, vm)
        a = place(vm, FieldType.TEXT, 60, 60)
        b = place(vm, FieldType.TEXT, 60, 300)
        vm.set_content(b, "two")
        _pump(3)
        click_field(w, a, double=True)
        _pump(2)
        type_text(w, "AAA")
        assert vm.template.get_field(a).content == "AAA"
        click_field(w, b, double=True)
        _pump(2)
        # The click on the other field commit-closed A (the migrated
        # _commit_inline_close) and opened B seeded with ITS display text.
        assert vm.template.get_field(a).content == "AAA"
        assert vm.inline_field_id == b
        assert editor(w).property("text") == "two"

    def test_panel_changes_push_into_the_open_editor(self, qtbot, vm):
        w = load_canvas(qtbot, vm)
        fid = place(vm, FieldType.TEXT, 60, 60)
        vm.set_content(fid, "orig")
        _pump(3)
        click_field(w, fid, double=True)
        _pump(2)
        assert vm.set_content(fid, "panel") is True
        _pump(2)
        assert editor(w).property("text") == "panel"
        # A panel-driven resize re-flows the reused editor (the proxy used to
        # resize with the field — the same follow lives on the geomTick seam).
        w_before = float(find_item(w, "sheetInlineLoader").property("width"))
        assert vm.resize(fid, 60, 60, 300, 30) is True
        _pump(2)
        w_after = float(find_item(w, "sheetInlineLoader").property("width"))
        assert w_after > w_before

    def test_textarea_enter_inserts_newline_ctrl_enter_commits(self, qtbot, vm):
        w = load_canvas(qtbot, vm)
        fid = place(vm, FieldType.TEXTAREA, 60, 60)
        vm.set_content(fid, "")
        _pump(3)
        click_field(w, fid, double=True)
        _pump(2)
        ed = editor(w)
        assert "TextArea" in ed.metaObject().className()
        type_text(w, "ab")
        key_press(w, Qt.Key.Key_Return, text="\r")            # plain Enter
        _pump(1)
        assert len(editor(w).property("text")) == 3           # a newline went in
        assert vm.template.get_field(fid).content == editor(w).property("text")
        key_press(w, Qt.Key.Key_Return,
                  modifiers=Qt.KeyboardModifier.ControlModifier)
        _pump(2)
        assert vm.inline_field_id is None                     # Ctrl+Enter closed


# ── 2.5 — fill & read-only modes ──────────────────────────────────────────────


class TestFillAndReadOnly:
    def test_checkbox_click_toggles_value_shown_display(self, qtbot, fill_case):
        fvm, ids = fill_case
        w = load_canvas(qtbot, fvm, mode="fill")
        _pump(3)
        # The default «true» template value renders checked through the fill
        # display resolution (empty value map — resolve_display defaults).
        assert visible_named(w, ids["chk"], "fieldCheck") is True
        click_field(w, ids["chk"])
        _pump(2)
        assert fvm.values.get(ids["chk"]) is False
        assert visible_named(w, ids["chk"], "fieldCheck") is False
        click_field(w, ids["chk"])
        _pump(2)
        assert fvm.values.get(ids["chk"]) is True

    def test_text_click_opens_inline_commit_lands_in_values(self, qtbot, fill_case):
        fvm, ids = fill_case
        w = load_canvas(qtbot, fvm, mode="fill")
        _pump(3)
        assert text_of(w, ids["text"]) == "Иван"      # template default shown
        click_field(w, ids["text"])
        _pump(2)
        assert fvm.inline_field_id == ids["text"]
        type_text(w, "1")
        assert fvm.values.get(ids["text"]) == "Иван1"  # live into the value map
        key_press(w, Qt.Key.Key_Return, text="\r")
        _pump(2)
        assert fvm.inline_field_id is None
        assert text_of(w, ids["text"]) == "Иван1"
        assert fvm.dirty is True

    def test_number_click_opens_inline_gated_by_apply_number(self, qtbot, fill_case):
        fvm, ids = fill_case
        w = load_canvas(qtbot, fvm, mode="fill")
        _pump(3)
        assert text_of(w, ids["num"]) == "4"
        click_field(w, ids["num"])
        _pump(2)
        assert fvm.inline_field_id == ids["num"]
        type_text(w, "7")
        key_press(w, Qt.Key.Key_Return, text="\r")
        _pump(2)
        assert fvm.values.get(ids["num"]) == "47"     # seeded "4" + typed 7
        assert fvm.inline_field_id is None

    def test_label_click_selects_only(self, qtbot, fill_case):
        fvm, ids = fill_case
        w = load_canvas(qtbot, fvm, mode="fill")
        _pump(3)
        click_field(w, ids["lab"])
        assert fvm.selection == ids["lab"]
        assert fvm.inline_field_id is None

    def test_image_click_requests_the_file_bridge(self, qtbot, fill_case):
        fvm, ids = fill_case
        w = load_canvas(qtbot, fvm, mode="fill")
        _pump(3)
        c = canvas(w)
        assert c.property("lastImageFieldId") == ""
        values_before = dict(fvm.values)
        click_field(w, ids["img"])
        _pump(2)
        # The picture-field file choice belongs to the facade (QFileDialog);
        # the island only reports, the VM stays untouched.
        assert c.property("lastImageFieldId") == ids["img"]
        assert dict(fvm.values) == values_before

    def test_dropdown_reports_to_the_facade_and_a_pick_shows(self, qtbot, fill_case):
        fvm, ids = fill_case
        w = load_canvas(qtbot, fvm, mode="fill")
        _pump(3)
        c = canvas(w)
        item = find_item(w, f"sheetField-{ids['dd']}")
        pos = scene_center(item)
        click_at(w, pos)
        _pump(2)
        # The island never owns a menu (the system-menu rule): the request
        # lands on the bridge with the canvas-space click point — the facade
        # shows its native QMenu at the point (group 3) and answers the pick
        # through vm.set_dropdown; here the pick plays the mocked facade.
        assert c.property("lastDropdownFieldId") == ids["dd"]
        assert float(c.property("lastDropdownX")) == pytest.approx(pos.x(), abs=1.0)
        assert float(c.property("lastDropdownY")) == pytest.approx(pos.y(), abs=1.0)
        assert fvm.set_dropdown(ids["dd"], "орк") is True
        _pump(2)
        assert text_of(w, ids["dd"]) == "орк"

    def test_readonly_mode_is_select_only(self, qtbot, fill_case):
        fvm, ids = fill_case
        w = load_canvas(qtbot, fvm, mode="readonly")
        _pump(3)
        values_before = dict(fvm.values)
        click_field(w, ids["text"])
        assert fvm.inline_field_id is None
        assert fvm.selection == ids["text"]                  # selection lives
        click_field(w, ids["chk"])
        assert dict(fvm.values) == values_before             # no value written
        assert fvm.dirty is False                            # nothing happened
        assert fvm.selection == ids["chk"]

    def test_vm_read_only_gate_flips_through_the_disabled_role(self, qtbot, fill_case):
        fvm, ids = fill_case
        w = load_canvas(qtbot, fvm, mode="fill")
        _pump(3)
        fvm.set_read_only(True)
        _pump(2)
        click_field(w, ids["text"])
        assert fvm.inline_field_id is None                   # per-row disabled
        assert fvm.selection == ids["text"]
        fvm.set_read_only(False)
        _pump(2)
        click_field(w, ids["text"])
        assert fvm.inline_field_id == ids["text"]            # input restored
