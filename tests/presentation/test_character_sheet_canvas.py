"""Tests for the character-sheet canvas, rail and palette (add-character-sheet-a1
+ a-playable, tasks 5.1/5.2).

Offscreen Qt: QGraphicsView canvas as the vertical page tape (design D1),
palette, placement click, z-order hit-testing, Delete/Esc, wheel = scroll the
tape / Ctrl+wheel = zoom (design D2, replacing the A1 wheel), fit the page
**width** on open, the page rail (add/remove/reorder/rename, click-to-scroll),
and built-in DejaVu Sans with Cyrillic (no family picker).
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF, QPoint, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QPainter,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import QApplication, QButtonGroup, QFontComboBox, QLabel, QToolButton

from app.application.services.character_sheet_service import CharacterSheetService
from app.domain.entities.character_sheet import (
    GUTTER_PT,
    ORIENTATION_LANDSCAPE,
    ORIENTATION_PORTRAIT,
    PAGE_HEIGHT_PT,
    PAGE_WIDTH_PT,
    page_origin,
    tape_height,
)
from app.domain.enums.field_type import FieldType
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)
from app.presentation.viewmodels.character_sheet_viewmodel import (
    TOOL_POINTER,
    CharacterSheetViewModel,
)
from app.presentation.views.character_sheet.canvas import (
    MAX_ZOOM,
    MIN_ZOOM,
    SHEET_FONT_FAMILY,
    CharacterSheetCanvas,
    SheetFieldItem,
)
from app.presentation.views.character_sheet.palette import SheetPalette
from app.presentation.views.character_sheet.page_rail import PageRail


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def service(async_session):
    return CharacterSheetService(CharacterSheetRepository(async_session))


@pytest.fixture
async def vm(service):
    row = await service.create("Лист")
    vm = CharacterSheetViewModel(service)
    await vm.load(row.id)
    return vm


@pytest.fixture
def canvas(qtbot, vm):
    view = CharacterSheetCanvas(vm)
    view.resize(800, 1010)
    view.show()
    view.fit_width()
    yield view
    # Deterministic teardown: destroy the C++ view (and scene) while the VM is
    # still alive — otherwise the deferred deletion lands in the next Qt pump
    # with a dead VM and the Python GC can destroy a still-owned wrapper.
    view.close()
    view.deleteLater()
    qtbot.wait(50)


@pytest.fixture
async def vm2(service):
    """VM loaded on a fresh sheet with two pages (the tape)."""
    row = await service.create("Лист")
    vm = CharacterSheetViewModel(service)
    await vm.load(row.id)
    vm.add_page(after_index=0)
    return vm


@pytest.fixture
def canvas2(qtbot, vm2):
    """The canvas of the two-page tape (the A-playable A4 ribbon)."""
    view = CharacterSheetCanvas(vm2)
    view.resize(800, 700)
    view.show()
    view.fit_width()
    qtbot.wait(30)  # let the tape scrollbar lay out (the fit re-runs on it)
    yield view
    view.close()
    view.deleteLater()
    qtbot.wait(50)


def _click(canvas, scene_x: float, scene_y: float, qtbot) -> None:
    """Left-click the view at a scene (page) point."""
    view_pos = canvas.mapFromScene(QPointF(scene_x, scene_y))
    qtbot.mouseClick(canvas.viewport(), Qt.LeftButton, pos=view_pos)


def _wheel(canvas, qtbot, angle_y: int,
           modifier=Qt.KeyboardModifier.NoModifier) -> None:
    ev = QWheelEvent(
        QPointF(400, 500), QPointF(400, 500),
        QPoint(0, 0), QPoint(0, angle_y),
        Qt.NoButton, modifier, Qt.ScrollPhase.ScrollUpdate, False,
    )
    canvas.wheelEvent(ev)
    qtbot.wait(1)


# ── palette ────────────────────────────────────────────────────────────────

def test_palette_has_pointer_and_nine_types(qtbot):
    """The closed A-playable catalog (design D7): pointer + 9 field types.
    Placement stays one-shot: the one-shot reset is checked in the placement
    test below, not here."""
    palette = SheetPalette()
    qtbot.addWidget(palette)

    assert len(palette.group.buttons()) == 10
    for b in palette.group.buttons():
        assert isinstance(b, QToolButton)
        assert b.isCheckable()
    assert palette.pointer_button.isChecked()  # pointer active by default

    sent = []
    palette.tool_requested.connect(sent.append)
    palette.label_button.click()
    palette.text_button.click()
    palette.checkbox_button.click()
    palette.number_button.click()
    palette.dropdown_button.click()
    palette.image_button.click()
    palette.rect_button.click()
    palette.line_button.click()
    palette.pointer_button.click()
    assert sent == [
        "place_label", "place_text", "place_checkbox", "place_number",
        "place_dropdown", "place_image", "place_rect", "place_line", "pointer",
    ]
    # exclusive: after the last click only pointer is checked
    assert palette.pointer_button.isChecked()
    assert not palette.label_button.isChecked()
    assert not palette.line_button.isChecked()

    # there is no font-family picker anywhere on the palette
    assert palette.findChildren(QFontComboBox) == []


def test_palette_tool_click_page_click_places_new_types(canvas, vm, qtbot):
    """The palette maps to the new types; placement is one-shot: after the
    click the tool resets to the pointer and the field is selected (spec)."""
    palette = SheetPalette()
    qtbot.addWidget(palette)
    palette.tool_requested.connect(vm.set_tool)

    cases = [
        (palette.checkbox_button, FieldType.CHECKBOX, (18, 18)),
        (palette.number_button, FieldType.NUMBER, (72, 18)),
        (palette.dropdown_button, FieldType.DROPDOWN, (120, 18)),
        (palette.image_button, FieldType.IMAGE, (120, 120)),
        (palette.rect_button, FieldType.RECT, (120, 72)),
        (palette.line_button, FieldType.LINE, (120, 2)),
    ]
    ys = (50.0, 100.0, 150.0, 200.0, 350.0, 450.0)  # all inside one A4 page
    for (button, ftype, (w, h)), y in zip(cases, ys):
        button.click()
        assert vm.tool == f"place_{ftype.value}"
        _click(canvas, 100.0, y, qtbot)
        fid = vm.selection
        f = vm.template.get_field(fid)
        assert f is not None and f.type is ftype
        assert (f.w, f.h) == (w, h)            # the D7 default size
        assert vm.tool == TOOL_POINTER          # one-shot: pointer again
        assert vm.inline_field_id is None       # inline NOT opened


# ── placement: palette tool + page click ───────────────────────────────────

def test_palette_tool_click_page_click_places_one_field(canvas, vm, qtbot):
    palette = SheetPalette()
    qtbot.addWidget(palette)
    palette.tool_requested.connect(vm.set_tool)

    assert canvas.item_count() == 0
    palette.text_button.click()
    assert vm.tool == "place_text"

    _click(canvas, 100, 100, qtbot)

    fields = vm.template.page.fields
    assert len(fields) == 1
    f = fields[0]
    assert f.type is FieldType.TEXT
    # pixel-quantised click: allow +-1 px in scene space
    assert abs(f.x - 100) <= 1 and abs(f.y - 100) <= 1
    assert (f.w, f.h) == (120, 18)
    assert vm.tool == TOOL_POINTER          # pointer active again
    assert vm.selection == f.id             # the field is selected
    assert vm.inline_field_id is None       # inline NOT opened

    item = canvas.item_for(f.id)
    assert item is not None
    assert item.rect().topLeft() == QPointF(f.x, f.y)
    assert (item.rect().width(), item.rect().height()) == (120, 18)
    assert item.pen().style() != Qt.PenStyle.NoPen   # frame visible in design
    assert vm.dirty is True


def test_place_click_clamped_at_page_edge(canvas, vm, qtbot):
    vm.set_tool("place_label")
    _click(canvas, PAGE_WIDTH_PT - 5, PAGE_HEIGHT_PT - 5, qtbot)
    f = vm.template.page.fields[0]
    assert f.x + f.w <= PAGE_WIDTH_PT
    assert f.y + f.h <= PAGE_HEIGHT_PT
    assert canvas.item_for(f.id).rect().topLeft() == QPointF(f.x, f.y)


def test_click_outside_page_places_nothing(canvas, vm, qtbot):
    vm.set_tool("place_text")
    # left of the page in scene space, but still inside the viewport
    # (after fit the page is narrower than the 800px viewport)
    _click(canvas, -10, 400, qtbot)
    assert vm.template.page.fields == []
    assert vm.inline_field_id is None


# ── hit-testing: overlapping fields ────────────────────────────────────────

def test_overlap_click_selects_later_placed(canvas, vm, qtbot):
    a = vm.place(FieldType.LABEL, 100, 100)    # 72x18  (100..172, 100..118)
    b = vm.place(FieldType.TEXT, 110, 105)     # 120x18 (110..230, 105..123)
    a_item = canvas.item_for(a)
    b_item = canvas.item_for(b)
    assert a_item is not None and b_item is not None
    # z-order: the later-placed one is on top
    assert b_item.zValue() > a_item.zValue()

    vm.select(None)
    _click(canvas, 130, 110, qtbot)
    assert vm.selection == b

    # already-selected field under the overlap: move that field, not the top one
    _click(canvas, 104, 104, qtbot)
    assert vm.selection == a
    _click(canvas, 130, 110, qtbot)
    assert vm.selection == a


def test_click_empty_page_clears_selection(canvas, vm, qtbot):
    a = vm.place(FieldType.LABEL, 100, 100)
    assert vm.selection == a
    _click(canvas, 400, 400, qtbot)
    assert vm.selection is None
    assert canvas.item_for(a).selected is False


# ── keyboard ───────────────────────────────────────────────────────────────

def test_delete_key_removes_selected(canvas, vm, qtbot):
    a = vm.place(FieldType.LABEL, 100, 100)
    b = vm.place(FieldType.TEXT, 200, 200)
    _click(canvas, 104, 104, qtbot)   # select A
    assert vm.selection == a

    canvas.setFocus()
    canvas.activateWindow()
    qtbot.keyClick(canvas, Qt.Key_Delete)

    assert [f.id for f in vm.template.page.fields] == [b]
    assert vm.selection is None
    assert canvas.item_count() == 1


def test_backspace_removes_selected(canvas, vm, qtbot):
    a = vm.place(FieldType.LABEL, 100, 100)
    canvas.setFocus()
    canvas.activateWindow()
    qtbot.keyClick(canvas, Qt.Key_Backspace)
    assert vm.template.page.fields == []
    assert canvas.item_count() == 0


def test_delete_without_selection_does_nothing(canvas, vm, qtbot):
    vm.place(FieldType.LABEL, 100, 100)
    vm.select(None)
    canvas.setFocus()
    canvas.activateWindow()
    qtbot.keyClick(canvas, Qt.Key_Delete)
    assert len(vm.template.page.fields) == 1


def test_esc_clears_selection(canvas, vm, qtbot):
    a = vm.place(FieldType.LABEL, 100, 100)
    canvas.setFocus()
    canvas.activateWindow()
    qtbot.keyClick(canvas, Qt.Key_Escape)
    assert vm.selection is None
    assert vm.inline_field_id is None


# ── the vertical tape: two pages stacked (design D1) ───────────────────────

def test_tape_layout_and_scene_rect(canvas2):
    """Two A4 pages in one scene, stacked with the GUTTER_PT gap (D1)."""
    from app.domain.entities.character_sheet import GUTTER_PT, tape_height

    page_w, page_h = PAGE_WIDTH_PT, PAGE_HEIGHT_PT
    scene = canvas2.scene()
    assert scene.sceneRect().width() == pytest.approx(page_w)
    assert scene.sceneRect().height() == pytest.approx(tape_height(2, page_h))

    # both white page rects at page_origin(i, page_h)
    # the page frame pen (1 pt) overhangs the rect by half a point
    tol = 1.0
    rects = sorted(
        (item.sceneBoundingRect() for item in scene.items()
         if not isinstance(item, SheetFieldItem)),
        key=lambda r: r.y(),
    )
    assert rects[0].x() == pytest.approx(0.0, abs=tol)
    assert rects[0].y() == pytest.approx(0.0, abs=tol)
    assert rects[0].width() == pytest.approx(page_w, abs=tol)
    assert rects[0].height() == pytest.approx(page_h, abs=tol)
    assert rects[1].x() == pytest.approx(0.0, abs=tol)
    assert rects[1].y() == pytest.approx(page_h + GUTTER_PT, abs=tol)
    assert rects[1].width() == pytest.approx(page_w, abs=tol)


def test_place_on_second_page_lands_on_that_page(canvas2, vm2, qtbot):
    """A place-tool click hits the sheet under the cursor, not page 0."""
    _, oy1 = page_origin(1, PAGE_HEIGHT_PT)
    vm2.set_tool("place_text")
    _click(canvas2, 100.0, oy1 + 30.0, qtbot)

    assert vm2.page_of(vm2.selection) == 1
    f = vm2.template.get_field(vm2.selection)
    assert f.type is FieldType.TEXT
    assert abs(f.x - 100) <= 1
    assert abs(f.y - 30) <= 1            # page-1 LOCAL coordinates


def test_click_gutter_places_nothing(canvas2, vm2, qtbot):
    """Grey gap between the sheets is not a sheet: no field is placed (spec)."""
    vm2.set_tool("place_text")
    _click(canvas2, 100.0, PAGE_HEIGHT_PT + GUTTER_PT / 2, qtbot)
    assert all(len(p.fields) == 0 for p in vm2.template.pages)
    assert vm2.selection is None


# ── wheel: scroll the tape; Ctrl = zoom (design D2, A1 wheel replaced) ─────

def test_wheel_without_ctrl_scrolls_and_keeps_scale(canvas2, qtbot):
    s0 = canvas2.transform().m11()
    bar = canvas2.verticalScrollBar()

    # scroll down: the second page comes into the canvas area…
    _wheel(canvas2, qtbot, -120)
    assert abs(canvas2.transform().m11() - s0) < 1e-9, "scale must not change"
    assert bar.value() > 0

    # …and scrolling up brings the first page back to the top
    for _ in range(10):
        _wheel(canvas2, qtbot, 120)
        if bar.value() == 0:
            break
    assert bar.value() == 0


def test_ctrl_wheel_changes_scale(canvas2, qtbot):
    s0 = canvas2.transform().m11()
    _wheel(canvas2, qtbot, 120, Qt.KeyboardModifier.ControlModifier)
    assert canvas2.transform().m11() > s0
    _wheel(canvas2, qtbot, -120, Qt.KeyboardModifier.ControlModifier)
    assert abs(canvas2.transform().m11() - s0) < 1e-6


def test_ctrl_wheel_zoom_clamped(canvas2, qtbot):
    for _ in range(60):
        _wheel(canvas2, qtbot, -120, Qt.KeyboardModifier.ControlModifier)
    assert canvas2.transform().m11() == MIN_ZOOM
    for _ in range(120):
        _wheel(canvas2, qtbot, 120, Qt.KeyboardModifier.ControlModifier)
    assert canvas2.transform().m11() == MAX_ZOOM


# ── open: fit the page WIDTH, first page on top (design D2) ────────────────

def test_fit_width_on_open_first_page_top_second_by_scroll(canvas2):
    vp_w, vp_h = canvas2.viewport().width(), canvas2.viewport().height()
    # the sheet width equals the canvas area width (the tape, not the page)
    left = canvas2.mapFromScene(QPointF(0, 0)).x()
    right = canvas2.mapFromScene(QPointF(PAGE_WIDTH_PT, 0)).x()
    assert vp_w - (right - left) < 3.0
    # the first page is at the top…
    assert canvas2.mapFromScene(QPointF(0, 0)).y() >= -0.5
    # …and with two pages the tape must be scrollable
    assert canvas2.verticalScrollBar().maximum() > 0


def test_scroll_to_page_brings_the_page_to_the_top(canvas2, qtbot):
    canvas2.scroll_to_page(1)
    qtbot.wait(20)
    _, oy1 = page_origin(1, PAGE_HEIGHT_PT)
    top_y = canvas2.mapFromScene(QPointF(0, oy1)).y()
    assert abs(top_y) < 2.0
    assert canvas2.verticalScrollBar().value() > 0


def test_fit_width_allowed_below_min_zoom(canvas2, qtbot):
    """Fit is capped by MAX_ZOOM from above only: a tiny viewport still shows
    the whole sheet width (the wheel keeps its 25% floor on its own)."""
    canvas2.resize(120, 100)
    for _ in range(5):
        canvas2.fit_width()
        qtbot.wait(20)
    s = canvas2.transform().m11()
    assert s < MIN_ZOOM
    vp_w = canvas2.viewport().width()
    left = canvas2.mapFromScene(QPointF(0, 0)).x()
    right = canvas2.mapFromScene(QPointF(PAGE_WIDTH_PT, 0)).x()
    # the whole sheet width still spans the canvas area (centered)
    assert abs((right - left) - vp_w) < 3.0


# ── the page rail (A-playable: names, add, delete, reorder, click-to-scroll) ─

@pytest.fixture
def rail(qtbot, vm2, canvas2):
    r = PageRail(vm2)
    qtbot.addWidget(r)
    r.resize(220, 300)
    r.show()
    # the same wiring the editor dialog does: a rail click scrolls the canvas
    r.page_selected.connect(canvas2.scroll_to_page)
    return r


def _click_rail_item(rail, index: int, qtbot) -> None:
    item = rail.pages_list.item(index)
    rect = rail.pages_list.visualItemRect(item)
    qtbot.mouseClick(rail.pages_list.viewport(), Qt.LeftButton, pos=rect.center())


def test_rail_lists_pages_and_current_row_follows_vm(rail, vm2):
    assert rail.pages_list.count() == 2
    assert rail.pages_list.item(0).text() == "Страница 1"
    assert rail.pages_list.item(1).text() == "Страница 2"
    assert rail.pages_list.currentRow() == vm2.current_page_index == 1

    vm2.set_current_page(0)
    assert rail.pages_list.currentRow() == 0


def test_rail_click_scrolls_canvas_to_the_page(rail, vm2, canvas2, qtbot):
    canvas2.scroll_to_page(0)
    qtbot.wait(20)
    assert canvas2.verticalScrollBar().value() == 0

    _click_rail_item(rail, 1, qtbot)
    qtbot.wait(20)
    assert canvas2.verticalScrollBar().value() > 0          # scrolled down…
    _, oy1 = page_origin(1, PAGE_HEIGHT_PT)                 # …page 2 on top
    assert abs(canvas2.mapFromScene(QPointF(0, oy1)).y()) < 2.0
    assert vm2.current_page_index == 1


def test_rail_add_inserts_after_current_and_rebuilds(rail, vm2):
    vm2.set_current_page(0)
    rail.add_button.click()

    assert vm2.page_count == 3
    assert vm2.current_page_index == 1
    assert [p.name for p in vm2.template.pages] == [
        "Страница 1", "Страница 3", "Страница 2"
    ]
    assert rail.pages_list.count() == 3
    assert rail.pages_list.item(1).text() == "Страница 3"


def test_rail_delete_button_unavailable_for_the_last_page(qtbot, vm):
    from app.presentation.views.character_sheet.page_rail import PageRail as _PR

    r = _PR(vm)
    qtbot.addWidget(r)
    r.show()
    assert r.delete_button.isEnabled() is False   # only one page: not deletable
    r.close()
    r.deleteLater()
    qtbot.wait(10)


def test_rail_delete_confirms_for_nonempty_page(rail, vm2, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    state = {"answer": QMessageBox.StandardButton.No, "asked": []}

    def fake_question(parent, title, text, *args, **kwargs):
        state["asked"].append((title, text))
        return state["answer"]

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_question))

    vm2.set_current_page(1)
    fid = vm2.place(FieldType.LABEL, 10.0, 10.0, page_index=1)
    assert vm2.page_of(fid) == 1

    rail.pages_list.setCurrentRow(1)
    rail.delete_button.click()
    assert vm2.page_count == 2            # declined: the page (and its field) stays
    assert vm2.template.get_field(fid) is not None

    state["answer"] = QMessageBox.StandardButton.Yes
    rail.delete_button.click()            # accepted: page and field are gone
    assert vm2.page_count == 1
    assert vm2.template.get_field(fid) is None
    assert len(state["asked"]) == 2       # confirmation was actually asked


def test_rail_rename_by_item_text_commit(rail, vm2):
    item = rail.pages_list.item(1)
    item.setText("Навыки")          # commit (what Enter does after the inline edit)

    assert vm2.template.pages[1].name == "Навыки"
    assert rail.pages_list.item(1).text() == "Навыки"


def test_rail_rename_empty_is_refused_and_reverted(rail, vm2):
    item = rail.pages_list.item(0)
    old = item.text()
    item.setText("   ")

    assert vm2.template.pages[0].name == old
    # restored to the stored name (no empty page name exists)
    assert rail.pages_list.currentItem().text() != "   "


def test_rail_reorder_up_down_moves_the_current_page(rail, vm2):
    assert [p.name for p in vm2.template.pages] == ["Страница 1", "Страница 2"]

    rail.pages_list.setCurrentRow(1)
    rail.up_button.click()
    assert [p.name for p in vm2.template.pages] == ["Страница 2", "Страница 1"]
    assert vm2.current_page_index == 0      # the current page followed the move

    rail.down_button.click()
    assert [p.name for p in vm2.template.pages] == ["Страница 1", "Страница 2"]


# ── font: bundled DejaVu Sans, Cyrillic, no family picker ─────────────────

def _render_scene(canvas) -> QImage:
    img = QImage(int(PAGE_WIDTH_PT), int(PAGE_HEIGHT_PT),
                 QImage.Format.Format_ARGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    canvas.scene().render(p)
    p.end()
    return img


def test_cyrillic_renders_and_font_is_dejavu(canvas, vm, qtbot):
    fid = vm.place(FieldType.LABEL, 50, 50)
    vm.set_content(fid, "Кириллица")
    item = canvas.item_for(fid)
    assert item.font().family() == SHEET_FONT_FAMILY

    f = vm.template.get_field(fid)
    img = _render_scene(canvas)
    rect = item.rect()
    dark = False
    for dy in range(int(rect.height())):
        for dx in range(int(rect.width())):
            px = img.pixelColor(int(rect.x()) + dx, int(rect.y()) + dy)
            if px.red() < 128 and px.green() < 128 and px.blue() < 128:
                dark = True
                break
        if dark:
            break
    assert dark, "Cyrillic text must be drawn inside the field rect"


def test_no_family_picker_on_canvas_or_palette(canvas, qtbot):
    palette = SheetPalette()
    qtbot.addWidget(palette)
    assert canvas.findChildren(QFontComboBox) == []
    assert palette.findChildren(QFontComboBox) == []


# ── inline editing (5.4) ───────────────────────────────────────────────────

from PySide6.QtGui import QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QLineEdit,
    QPlainTextEdit,
)
from app.presentation.views.character_sheet.properties_panel import (  # noqa: E402
    SheetPropertiesPanel,
)


@pytest.fixture
def panel(qtbot, vm):
    w = SheetPropertiesPanel(vm)
    qtbot.addWidget(w)
    w.resize(320, 500)
    w.show()
    return w


def _dclick(canvas, scene_x: float, scene_y: float, qtbot) -> None:
    view_pos = canvas.mapFromScene(QPointF(scene_x, scene_y))
    qtbot.mouseDClick(canvas.viewport(), Qt.LeftButton, pos=view_pos)


def _press_drag_release(canvas, qtbot, from_scene, to_scene) -> None:
    p0 = canvas.mapFromScene(QPointF(*from_scene))
    p1 = canvas.mapFromScene(QPointF(*to_scene))
    QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=p0)
    qtbot.wait(1)
    QTest.mouseMove(canvas.viewport(), pos=p1)
    qtbot.wait(1)
    QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=p1)
    qtbot.wait(1)


def test_doubleclick_opens_inline_editing(canvas, vm, qtbot):
    fid = vm.place(FieldType.TEXT, 100, 100)
    assert vm.inline_field_id is None

    _dclick(canvas, 110, 109, qtbot)

    assert vm.inline_field_id == fid
    assert vm.selection == fid
    edit = canvas.inline_edit()
    assert isinstance(edit, QLineEdit)      # single-line type
    assert edit.text() == ""

    _dclick(canvas, 110, 109, qtbot)        # double-click again: stays open
    assert vm.inline_field_id == fid


def test_doubleclick_opens_multiline_editor_for_textarea(canvas, vm, qtbot):
    fid = vm.place(FieldType.TEXTAREA, 100, 100)
    _dclick(canvas, 110, 110, qtbot)
    edit = canvas.inline_edit()
    assert isinstance(edit, QPlainTextEdit)


def test_enter_commits_label_and_text(canvas, vm, qtbot):
    for field_type in (FieldType.LABEL, FieldType.TEXT):
        fid = vm.place(field_type, 100, 150)
        _dclick(canvas, 110, 159, qtbot)
        edit = canvas.inline_edit()
        edit.setText("новое значение")
        qtbot.keyClick(edit, Qt.Key_Return)
        assert vm.inline_field_id is None
        assert vm.selection == fid
        assert vm.template.get_field(fid).content == "новое значение"
        assert canvas.inline_edit() is None


def test_textarea_enter_newline_ctrl_enter_commits(canvas, vm, qtbot):
    fid = vm.place(FieldType.TEXTAREA, 100, 100)
    _dclick(canvas, 110, 110, qtbot)
    edit = canvas.inline_edit()
    edit.setPlainText("строка один")
    edit.moveCursor(QTextCursor.MoveOperation.End)
    qtbot.keyClick(edit, Qt.Key_Return)
    # plain Enter in a multi-line field inserts a newline, does NOT commit
    assert vm.inline_field_id == fid
    assert edit.toPlainText() == "строка один\n"
    edit.setPlainText("строка один\nстрока два")
    qtbot.keyClick(edit, Qt.Key_Return, modifier=Qt.KeyboardModifier.ControlModifier)
    assert vm.inline_field_id is None
    assert vm.template.get_field(fid).content == "строка один\nстрока два"


def test_esc_cancel_restores_text_and_keeps_selection(canvas, vm, qtbot):
    fid = vm.place(FieldType.LABEL, 100, 100)
    vm.set_content(fid, "первоначальное")
    _dclick(canvas, 110, 109, qtbot)
    edit = canvas.inline_edit()
    edit.setText("изменено")
    assert vm.template.get_field(fid).content == "изменено"
    qtbot.keyClick(edit, Qt.Key_Escape)
    assert vm.inline_field_id is None
    assert vm.selection == fid
    assert vm.template.get_field(fid).content == "первоначальное"
    assert canvas.inline_edit() is None


def test_click_away_commits(canvas, vm, qtbot):
    fid = vm.place(FieldType.TEXT, 100, 100)
    _dclick(canvas, 110, 109, qtbot)
    canvas.inline_edit().setText("сохранено кликом мимо")
    _click(canvas, 500, 500, qtbot)   # empty page
    assert vm.inline_field_id is None
    assert vm.selection is None
    assert vm.template.get_field(fid).content == "сохранено кликом мимо"


def test_click_other_field_commits_and_selects(canvas, vm, qtbot):
    a = vm.place(FieldType.TEXT, 100, 100)
    b = vm.place(FieldType.LABEL, 300, 300)
    _dclick(canvas, 110, 109, qtbot)
    assert vm.inline_field_id == a
    canvas.inline_edit().setText("текст поля A")
    _click(canvas, 310, 309, qtbot)   # press field B
    assert vm.inline_field_id is None
    assert vm.selection == b
    assert vm.template.get_field(a).content == "текст поля A"
    assert canvas.inline_edit() is None


def test_no_move_or_resize_while_inline(canvas, vm, qtbot):
    fid = vm.place(FieldType.TEXT, 150, 150)
    before = (vm.template.get_field(fid).x, vm.template.get_field(fid).y,
              vm.template.get_field(fid).w, vm.template.get_field(fid).h)
    _dclick(canvas, 160, 159, qtbot)
    assert vm.inline_field_id == fid
    _press_drag_release(canvas, qtbot, (165, 160), (250, 250))
    f = vm.template.get_field(fid)
    assert (f.x, f.y, f.w, f.h) == before


def test_drag_without_inline_moves_field(canvas, vm, qtbot):
    fid = vm.place(FieldType.TEXT, 150, 150)
    _press_drag_release(canvas, qtbot, (170, 159), (250, 230))
    f = vm.template.get_field(fid)
    # dragged ~80pt right/down (minus the grab offset), clamped, on the page
    assert f.x > 200 and f.y > 200
    assert f.x + f.w <= PAGE_WIDTH_PT and f.y + f.h <= PAGE_HEIGHT_PT


# ── property panel (5.4) ───────────────────────────────────────────────────

def test_panel_shows_selected_field_values(canvas, vm, panel):
    fid = vm.place(FieldType.TEXT, 33, 44)
    vm.set_content(fid, "значение")
    vm.set_font_size(fid, 12.0)
    vm.select(fid)

    assert panel.field_id() == fid
    assert abs(panel.x_spin.value() - 33) < 0.01
    assert abs(panel.y_spin.value() - 44) < 0.01
    assert abs(panel.w_spin.value() - 120) < 0.01
    assert abs(panel.h_spin.value() - 18) < 0.01
    assert abs(panel.font_spin.value() - 12.0) < 0.01
    assert panel.content_edit.toPlainText() == "значение"
    assert panel.isEnabled()


def test_panel_empty_when_nothing_selected(vm, panel):
    vm.place(FieldType.LABEL, 10, 10)
    vm.select(None)
    assert panel.field_id() is None
    assert not panel.isEnabled()


def test_panel_content_edit_updates_canvas(canvas, vm, panel):
    fid = vm.place(FieldType.TEXT, 100, 100)
    vm.select(fid)

    # panel → canvas: one shared buffer in the VM
    panel.content_edit.setPlainText("из панели")
    assert vm.template.get_field(fid).content == "из панели"
    # and the canvas item still shows the same string: rendered inside the rect
    img = _render_scene(canvas)
    r = canvas.item_for(fid).rect()
    assert _rect_has_dark_pixel(
        img, int(r.x()), int(r.y()), int(r.width()), int(r.height())
    )


def test_panel_geometry_edits_clamped(canvas, vm, panel):
    fid = vm.place(FieldType.TEXT, 100, 100)
    vm.select(fid)

    panel.x_spin.setValue(PAGE_WIDTH_PT)      # beyond page: VM clamps
    panel.y_spin.setValue(PAGE_HEIGHT_PT)
    f = vm.template.get_field(fid)
    assert f.x == PAGE_WIDTH_PT - f.w
    assert f.y == PAGE_HEIGHT_PT - f.h
    # the panel shows the clamped (effective) geometry
    assert abs(panel.x_spin.value() - f.x) < 0.01
    assert abs(panel.y_spin.value() - f.y) < 0.01

    panel.w_spin.setValue(PAGE_WIDTH_PT * 2)  # bigger than the page
    f = vm.template.get_field(fid)
    assert f.w == PAGE_WIDTH_PT
    assert abs(panel.w_spin.value() - PAGE_WIDTH_PT) < 0.01

    panel.h_spin.setValue(1)                  # below the minimum
    f = vm.template.get_field(fid)
    assert f.h == 16
    assert abs(panel.h_spin.value() - 16) < 0.01

    panel.font_spin.setValue(400)             # clamped to the spin's own max
    assert vm.template.get_field(fid).font_size == panel.font_spin.value()
    assert canvas.findChildren(QFontComboBox) == []


def test_panel_and_inline_share_one_line(canvas, vm, panel, qtbot):
    fid = vm.place(FieldType.TEXT, 100, 100)
    vm.select(fid)
    _dclick(canvas, 110, 109, qtbot)
    edit = canvas.inline_edit()

    # typing in the panel while inline is open updates the inline widget…
    panel.content_edit.setPlainText("синхронно")
    assert edit.text() == "синхронно"

    # …and typing in the inline updates the panel
    edit.setText("обратно")
    assert panel.content_edit.toPlainText() == "обратно"


# ── per-type property sections (A-playable) ────────────────────────────────

def test_panel_checkbox_default_off_and_toggle(canvas, vm, panel):
    fid = vm.place(FieldType.CHECKBOX, 100, 100)
    vm.select(fid)

    assert panel.field_id() == fid
    assert vm.template.get_field(fid).content == "false"  # default off (D3)
    assert not panel.checkbox_state.isChecked()

    panel.checkbox_state.setChecked(True)
    assert vm.template.get_field(fid).content == "true"

    panel.checkbox_state.setChecked(False)
    assert vm.template.get_field(fid).content == "false"


def test_panel_number_comma_minmax_validation(canvas, vm, panel):
    fid = vm.place(FieldType.NUMBER, 100, 100)
    vm.select(fid)

    # optional bounds
    panel.min_check.setChecked(True)
    panel.min_spin.setValue(0.0)
    panel.max_check.setChecked(True)
    panel.max_spin.setValue(10.0)
    assert vm.template.get_field(fid).min_value == 0.0
    assert vm.template.get_field(fid).max_value == 10.0

    # comma is accepted and stored with a dot…
    panel.number_edit.setText("1,5")
    panel._on_number_commit()
    assert vm.template.get_field(fid).content == "1.5"

    # …out of bounds is refused (the old value is kept, the edit shows it)…
    panel.number_edit.setText("12")
    panel._on_number_commit()
    assert vm.template.get_field(fid).content == "1.5"
    assert panel.number_edit.text() == "1.5"

    # …and so is a non-number
    panel.number_edit.setText("abc")
    panel._on_number_commit()
    assert vm.template.get_field(fid).content == "1.5"
    assert panel.number_edit.text() == "1.5"


def test_panel_number_min_above_max_is_refused(canvas, vm, panel):
    fid = vm.place(FieldType.NUMBER, 100, 100)
    vm.select(fid)

    panel.min_check.setChecked(True)
    panel.min_spin.setValue(0.0)
    panel.max_check.setChecked(True)
    panel.max_spin.setValue(10.0)
    assert vm.template.get_field(fid).min_value == 0.0

    panel.min_spin.setValue(20.0)        # min > max: refused
    field = vm.template.get_field(fid)
    assert field.min_value == 0.0
    assert field.max_value == 10.0


def test_panel_dropdown_options_without_empties(canvas, vm, panel, qtbot):
    fid = vm.place(FieldType.DROPDOWN, 100, 100)
    vm.select(fid)
    assert vm.template.get_field(fid).options == []

    panel.option_input.setText("Меч")
    panel.option_add_button.click()
    panel.option_input.setText("Щит")
    panel.option_add_button.click()
    options = vm.template.get_field(fid).options
    assert options == ["Меч", "Щит"]
    assert [panel.options_list.item(i).text() for i in range(panel.options_list.count())] == options

    # an option of only whitespace is not added
    panel.option_input.setText("   ")
    panel.option_add_button.click()
    assert vm.template.get_field(fid).options == ["Меч", "Щит"]

    # reordering
    panel.options_list.setCurrentRow(0)
    panel.option_down_button.click()
    assert vm.template.get_field(fid).options == ["Щит", "Меч"]

    # the default is one of the options (or empty): written through content
    panel.default_combo.setCurrentText("Щит")
    assert vm.template.get_field(fid).content == "Щит"
    # the canvas shows the default text inside the field (design D3)
    img = _render_scene(canvas)
    r = canvas.item_for(fid).rect()
    assert _rect_has_dark_pixel(
        img, int(r.x()), int(r.y()), int(r.width()), int(r.height())
    )


def test_panel_image_pick_signal_and_clear(canvas, vm, panel):
    fid = vm.place(FieldType.IMAGE, 100, 100)
    vm.set_image_id(fid, 42)
    vm.select(fid)
    assert vm.template.get_field(fid).image_id == 42
    assert "42" in panel.image_label.text()

    requested = []
    panel.image_pick_requested.connect(requested.append)
    panel.image_pick_button.click()
    assert requested == [fid]          # the dialog does the ingest (ImageStore)

    panel.image_clear_button.click()
    assert vm.template.get_field(fid).image_id is None
    assert "не выбрана" in panel.image_label.text()


def test_panel_rect_line_have_no_data_section(canvas, vm, panel):
    """Rect: outline only, no character data. Line: decorative axis."""
    fid = vm.place(FieldType.RECT, 100, 100)
    vm.select(fid)
    assert panel.field_id() == fid
    assert panel.current_section is panel._decor_section
    assert not panel.content_edit.isVisible()          # no data edit in play

    lid = vm.place(FieldType.LINE, 100, 200)
    vm.select(lid)
    assert panel.current_section is panel._decor_section
    assert not panel.content_edit.isVisible()


# ── text wrap / clip rendering (5.4) ───────────────────────────────────────

def _rect_has_dark_pixel(img, x: int, y: int, w: int, h: int) -> bool:
    for dy in range(h):
        for dx in range(w):
            px = img.pixelColor(x + dx, y + dy)
            if px.red() < 128 and px.green() < 128 and px.blue() < 128:
                return True
    return False


def test_label_text_wraps_and_clips_in_frame(canvas, vm, qtbot):
    fid = vm.place(FieldType.LABEL, 40, 40)
    vm.resize(fid, 40, 40, 96, 24)             # narrow + short frame
    vm.set_content(fid, "АБВГДЕЖЗИКЛМНОПРСТУФЦЧШЩЪЫЬЭЮЯ0123456789")

    img = _render_scene(canvas)
    r = canvas.item_for(fid).rect()
    x, y, w, h = int(r.x()), int(r.y()), int(r.width()), int(r.height())
    # text is drawn …
    assert _rect_has_dark_pixel(img, x, y, w, h)
    # … inside the frame only (clipped by width and height)
    assert not _rect_has_dark_pixel(img, x, y + h + 1, w, 8)          # below
    assert not _rect_has_dark_pixel(img, x + w + 1, y, 8, h)          # right
    assert not _rect_has_dark_pixel(img, x - 8, y, 8, h)              # left
    assert not _rect_has_dark_pixel(img, x, y - 8, w, 8)              # above
    # and it actually wrapped: dark pixels in the lower half of the frame
    assert _rect_has_dark_pixel(img, x, y + h // 2, w, h // 2)


def test_text_field_single_line_clipped_by_width(canvas, vm, qtbot):
    fid = vm.place(FieldType.TEXT, 40, 120)
    vm.set_content(fid, "ОЧЕНЬДЛИННОЕЗНАЧЕНИЕ" * 10)

    img = _render_scene(canvas)
    r = canvas.item_for(fid).rect()
    x, y, w, h = int(r.x()), int(r.y()), int(r.width()), int(r.height())
    assert _rect_has_dark_pixel(img, x, y, w, h)
    # single line: nothing below the frame, nothing to its right
    assert not _rect_has_dark_pixel(img, x, y + h + 1, w, 8)
    assert not _rect_has_dark_pixel(img, x + w + 1, y, 8, h)


# ── canvas edge guards & flows ─────────────────────────────────────────────

def test_fit_width_noop_on_empty_viewport(vm, qtbot):
    class _ZeroViewportCanvas(CharacterSheetCanvas):
        def _viewport_size(self):
            return (0, 0)  # e.g. the very first moments before the window size lands

    view = _ZeroViewportCanvas(vm)
    qtbot.addWidget(view)
    view.fit_width()                     # refuses a zero-size viewport
    assert view.transform().m11() == 1.0
    view.close()


def test_template_changed_rebuilds_scene_items(canvas, vm, qtbot):
    a = vm.place(FieldType.LABEL, 10, 10)
    b = vm.place(FieldType.TEXT, 30, 30)
    vm.select(b)
    assert canvas.item_count() == 2

    vm.template_changed.emit()           # full rebuild: remove + re-add
    assert canvas.item_count() == 2
    assert canvas.item_for(a) is not None
    assert canvas.item_for(b) is not None
    assert canvas.item_for(b).selected is True     # selection survived rebuild


async def test_reload_with_saved_fields(canvas, vm, qtbot):
    a = vm.place(FieldType.LABEL, 10, 10)
    vm.place(FieldType.TEXT, 30, 30)
    await vm.save()
    await vm.reload()
    assert canvas.item_count() == 2
    assert canvas.item_for(a) is not None


def test_item_signal_guards_tolerate_unknown_ids(canvas, vm, qtbot):
    canvas._on_field_removed("absent")
    canvas._on_geometry_changed("absent")
    canvas._on_field_data_changed("absent")
    canvas._on_inline_changed("absent")
    canvas._on_inline_text_changed("absent")
    canvas._sync_inline_widget()
    canvas._start_drag("absent", QPointF(1, 1))
    assert canvas.item_count() == 0
    assert canvas.inline_edit() is None


def test_sync_inline_widget_with_vanished_field(canvas, vm, qtbot):
    fid = vm.place(FieldType.TEXT, 100, 100)
    _dclick(canvas, 110, 109, qtbot)
    assert canvas.inline_edit() is not None
    vm.template.remove_field(fid)        # field disappears under the open widget
    canvas._sync_inline_widget()         # guard: no crash, nothing to sync
    vm.commit_inline()
    assert canvas.inline_edit() is None


def test_right_button_press_is_ignored(canvas, vm, qtbot):
    QTest.mousePress(canvas.viewport(), Qt.MouseButton.RightButton, pos=QPoint(40, 40))
    qtbot.wait(10)
    QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.RightButton, pos=QPoint(40, 40))
    qtbot.wait(10)
    assert vm.template.page.fields == []


def test_doubleclick_other_field_commits_and_opens_it(canvas, vm, qtbot):
    a = vm.place(FieldType.TEXT, 100, 100)
    b = vm.place(FieldType.LABEL, 300, 300)
    _dclick(canvas, 110, 109, qtbot)            # inline A
    canvas.inline_edit().setText("из A")
    _dclick(canvas, 310, 309, qtbot)            # double-click B
    assert vm.inline_field_id == b
    assert vm.template.get_field(a).content == "из A"
    assert isinstance(canvas.inline_edit(), QLineEdit)


# ── property panel edge guards ─────────────────────────────────────────────

def test_panel_signal_guards_tolerate_foreign_or_missing_fields(canvas, vm, panel, qtbot):
    fid = vm.place(FieldType.TEXT, 10, 10)
    vm.select(fid)

    panel._on_geometry("absent")              # another field: no-op
    panel._on_content_changed("absent")
    panel._on_font_changed("absent")

    panel._fid = "ghost"                      # selected id no longer exists
    panel._on_geometry("ghost")
    panel._on_content_changed("ghost")
    panel._on_font_changed("ghost")
    panel.x_spin.setValue(5)                  # handlers see no field: no crash
    panel.y_spin.setValue(5)
    panel.w_spin.setValue(50)
    panel.h_spin.setValue(50)
    panel.font_spin.setValue(11)
    panel.content_edit.setPlainText("призрак")

    assert len(vm.template.page.fields) == 1
    assert vm.template.get_field(fid).x == 10  # nothing moved
    assert vm.template.get_field(fid).content == ""

    # removing the shown field disables the panel
    panel._fid = fid
    vm.remove(fid)
    assert panel.field_id() is None
    assert not panel.isEnabled()


def test_panel_on_removed_direct_disables(canvas, vm, panel, qtbot):
    fid = vm.place(FieldType.TEXT, 20, 20)
    vm.select(fid)
    assert panel.isEnabled()
    # direct signal (defensive ordering: field removed while still the shown one)
    panel._fid = fid
    panel._on_removed(fid)
    assert panel.field_id() is None
    assert not panel.isEnabled()


def test_on_field_removed_direct_clears_stale_selection(canvas, vm, qtbot):
    fid = vm.place(FieldType.LABEL, 20, 20)
    vm.select(fid)
    assert canvas.item_for(fid) is not None
    # direct signal: the removed field was the canvas' selected item
    canvas._on_field_removed(fid)
    assert canvas.item_for(fid) is None
    # a second call for the same (now absent) id is a safe no-op
    canvas._on_field_removed(fid)
    assert canvas.item_count() == 0


def test_inline_widget_resizes_with_field_while_open(canvas, vm, qtbot):
    fid = vm.place(FieldType.TEXT, 100, 100)   # default 120x18
    vm.select(fid)
    _dclick(canvas, 110, 109, qtbot)
    edit = canvas.inline_edit()
    assert edit is not None

    vm.resize(fid, 100, 100, 200, 40)          # geometry change under an open editor
    f = vm.template.get_field(fid)
    assert (f.w, f.h) == (200, 40)
    assert edit.width() == int(f.w - 2)        # proxy follows the field frame
    assert edit.height() == int(f.h - 2)


# ── inline session vs. page-structure operations (A-playable review) ────────
#
# A rebuild (add/remove/reorder/rename page, orientation) destroys every field
# item; the inline editor widget is a child of its field item. The VM must end
# the inline session BEFORE the rebuild, otherwise the canvas tears down a
# widget whose C++ object is already gone (RuntimeError / segfault) and the
# canvas key handling stays stuck on the inline branch.

def _open_inline_on_page(canvas, vm, page_index: int, qtbot) -> str:
    """Place a text field on the page, bring it into view, open inline on it."""
    fid = vm.place(FieldType.TEXT, 50.0, 50.0, page_index=page_index)
    canvas.scroll_to_page(page_index)
    qtbot.wait(10)
    _, oy = page_origin(page_index, PAGE_HEIGHT_PT)
    _dclick(canvas, 55, 55 + oy, qtbot)
    qtbot.wait(10)
    assert vm.inline_field_id == fid
    assert canvas.inline_edit() is not None
    return fid


def test_add_page_closes_open_inline(canvas2, vm2, qtbot):
    _open_inline_on_page(canvas2, vm2, 0, qtbot)
    vm2.add_page()
    qtbot.wait(10)
    assert vm2.inline_field_id is None        # not stuck with an open inline
    assert canvas2.inline_edit() is None      # no dangling widget
    # closing again must be a safe no-op
    vm2.commit_inline()
    canvas2._on_inline_changed(None)


def test_remove_page_closes_open_inline_on_removed_page(canvas2, vm2, qtbot):
    _open_inline_on_page(canvas2, vm2, 1, qtbot)
    # the field being edited lives on the page that is removed (worst order)
    assert vm2.remove_page(1, confirmed=True) is True
    qtbot.wait(10)
    assert vm2.inline_field_id is None
    assert canvas2.inline_edit() is None


def test_move_page_closes_open_inline(canvas2, vm2, qtbot):
    _open_inline_on_page(canvas2, vm2, 0, qtbot)
    vm2.move_page(0, 1)
    qtbot.wait(10)
    assert vm2.inline_field_id is None
    assert canvas2.inline_edit() is None


def test_set_orientation_closes_open_inline(canvas2, vm2, qtbot):
    _open_inline_on_page(canvas2, vm2, 0, qtbot)
    assert vm2.set_orientation(ORIENTATION_LANDSCAPE) is True
    qtbot.wait(10)
    assert vm2.inline_field_id is None
    assert canvas2.inline_edit() is None


# ── palette mirrors the VM's one-shot tool reset (design D7) ────────────────

def test_palette_mirrors_tool_reset_after_placement(canvas2, vm2, qtbot):
    palette = SheetPalette()
    qtbot.addWidget(palette)
    palette.resize(120, 500)
    palette.show()
    # the same two-way wiring as CharacterSheetEditorDialog
    palette.tool_requested.connect(vm2.set_tool)
    vm2.tool_changed.connect(palette.set_active_tool)

    palette.text_button.click()
    assert vm2.tool == "place_text"

    vm2.place(FieldType.TEXT, 50.0, 50.0, page_index=0)
    assert vm2.tool == "pointer"                    # one-shot reset in the VM
    assert palette.pointer_button.isChecked()       # the palette follows it
    assert not palette.text_button.isChecked()

    palette.checkbox_button.click()
    assert vm2.tool == "place_checkbox"
    assert palette.checkbox_button.isChecked()
    vm2.set_tool(TOOL_POINTER)
    assert palette.pointer_button.isChecked()
    assert not palette.checkbox_button.isChecked()


# ── properties panel geometry bounds follow the (oriented) page (D4) ────────

def test_properties_panel_bounds_follow_orientation(canvas, vm, panel, qtbot):
    assert panel.x_spin.maximum() == PAGE_WIDTH_PT   # portrait until switched
    assert vm.set_orientation(ORIENTATION_LANDSCAPE) is True
    qtbot.wait(10)
    # landscape A4: the wider axis becomes the x/w bound
    assert panel.x_spin.maximum() == PAGE_HEIGHT_PT
    assert panel.w_spin.maximum() == PAGE_HEIGHT_PT
    assert panel.y_spin.maximum() == PAGE_WIDTH_PT
    assert panel.h_spin.maximum() == PAGE_WIDTH_PT
    assert vm.set_orientation(ORIENTATION_PORTRAIT) is True
    qtbot.wait(10)
    assert panel.x_spin.maximum() == PAGE_WIDTH_PT
    assert panel.y_spin.maximum() == PAGE_HEIGHT_PT


# ── A-editor: rubber band + snap grid ──────────────────────────────────────

def _press_drag_release_mod(canvas, qtbot, from_scene, to_scene, modifier=Qt.KeyboardModifier.NoModifier) -> None:
    p0 = canvas.mapFromScene(QPointF(*from_scene))
    p1 = canvas.mapFromScene(QPointF(*to_scene))
    QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, modifier, p0)
    qtbot.wait(1)
    QTest.mouseMove(canvas.viewport(), pos=p1)
    qtbot.wait(1)
    QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, modifier, p1)
    qtbot.wait(1)


def test_rubber_band_from_empty_selects_intersections(canvas, vm, qtbot):
    a = vm.place(FieldType.LABEL, 100.0, 100.0)
    b = vm.place(FieldType.TEXT, 200.0, 200.0)
    c = vm.place(FieldType.TEXT, 400.0, 400.0)
    vm.select(None)

    _press_drag_release_mod(canvas, qtbot, (90.0, 90.0), (280.0, 230.0))

    assert set(vm.selected_ids) == {a, b}
    assert c not in vm.selected_ids


def test_rubber_band_without_shift_replaces(canvas, vm, qtbot):
    a = vm.place(FieldType.LABEL, 100.0, 100.0)
    b = vm.place(FieldType.TEXT, 200.0, 200.0)
    c = vm.place(FieldType.TEXT, 400.0, 400.0)
    vm.select(a)

    _press_drag_release_mod(canvas, qtbot, (190.0, 190.0), (330.0, 230.0))

    assert set(vm.selected_ids) == {b}


def test_shift_rubber_band_adds(canvas, vm, qtbot):
    a = vm.place(FieldType.LABEL, 100.0, 100.0)
    b = vm.place(FieldType.TEXT, 200.0, 200.0)
    c = vm.place(FieldType.TEXT, 400.0, 400.0)
    vm.select(a)

    _press_drag_release_mod(
        canvas, qtbot, (190.0, 190.0), (330.0, 230.0),
        Qt.KeyboardModifier.ShiftModifier,
    )

    assert set(vm.selected_ids) == {a, b}


def test_press_on_selected_starts_move_not_rubber(canvas, vm, qtbot):
    a = vm.place(FieldType.LABEL, 100.0, 100.0)
    b = vm.place(FieldType.TEXT, 300.0, 300.0)
    vm.select(a)
    before = (vm.template.get_field(a).x, vm.template.get_field(a).y)

    _press_drag_release_mod(canvas, qtbot, (110.0, 109.0), (180.0, 160.0))

    f = vm.template.get_field(a)
    assert (f.x, f.y) != before
    assert vm.selected_ids == [a]
    assert b not in vm.selected_ids


def test_snap_grid_visible_only_when_enabled(canvas, vm):
    assert canvas.grid_visible is False
    vm.set_snap_enabled(True)
    assert canvas.grid_visible is True
    vm.set_snap_enabled(False)
    assert canvas.grid_visible is False


def test_resize_handles_only_when_exactly_one_selected(canvas, vm):
    a = vm.place(FieldType.LABEL, 100.0, 100.0)
    assert canvas.handle_count() == 4
    b = vm.place(FieldType.TEXT, 300.0, 300.0)
    vm.select_ids([a, b])
    assert canvas.handle_count() == 0
    vm.select(a)
    assert canvas.handle_count() == 4


def test_resize_handle_drag_changes_size(canvas, vm, qtbot):
    fid = vm.place(FieldType.TEXT, 150.0, 150.0)
    before = (vm.template.get_field(fid).w, vm.template.get_field(fid).h)
    _press_drag_release_mod(canvas, qtbot, (270.0, 168.0), (310.0, 200.0))
    f = vm.template.get_field(fid)
    assert f.w > before[0] and f.h > before[1]


def test_inline_refused_when_multiple_selected(canvas, vm, qtbot):
    a = vm.place(FieldType.TEXT, 100.0, 100.0)
    b = vm.place(FieldType.LABEL, 300.0, 300.0)
    vm.select_ids([a, b])
    vm.open_inline(a)
    assert vm.inline_field_id is None
    assert canvas.inline_edit() is None


def test_visible_page_center_is_in_page(canvas, vm):
    cx, cy = canvas.visible_page_center(0)
    assert 0 <= cx <= PAGE_WIDTH_PT
    assert 0 <= cy <= PAGE_HEIGHT_PT
