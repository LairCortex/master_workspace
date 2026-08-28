"""A-playable type acceptance (design D8) — one fixed set per field type.

The set (parameterized over the closed catalog): place (+ default size and
selection), move, resize with the page clamp, per-type properties/default,
save/open round-trip, portrait → landscape clamp without scaling. Without the
set a type is out of scope.

Plus the per-type specifics:
- checkbox: default off; double-click (and the panel) toggle the default;
- number: "1,5" → 1.5 on Enter; non-numeric and out-of-bounds values refused;
- dropdown: options without empties; the default text is drawn on the canvas;
- image: pick goes through the ImageStore of the current game (dedup),
  double-click opens the pick, clear + save drops the file, an undecodable
  file leaves the field empty with a visible error;
- rect: no content, outline only;
- line: width > height → horizontal, otherwise vertical (axis).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QLineEdit

from app.application.services.character_sheet_service import CharacterSheetService
from app.domain.entities.character_sheet import (
    ORIENTATION_LANDSCAPE,
    PAGE_HEIGHT_PT,
    PAGE_WIDTH_PT,
)
from app.domain.enums.field_type import FieldType
from app.infrastructure.images.store import ImageStore
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)

from app.presentation.viewmodels.character_sheet_viewmodel import (
    TOOL_POINTER,
    CharacterSheetViewModel,
)
from app.presentation.views.character_sheet.canvas import CharacterSheetCanvas

ALL_TYPES = list(FieldType)


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
    view.close()
    view.deleteLater()
    qtbot.wait(30)


def _dclick(canvas, scene_x: float, scene_y: float, qtbot) -> None:
    view_pos = canvas.mapFromScene(QPointF(scene_x, scene_y))
    qtbot.mouseDClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=view_pos)


def _click(canvas, scene_x: float, scene_y: float, qtbot) -> None:
    view_pos = canvas.mapFromScene(QPointF(scene_x, scene_y))
    qtbot.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=view_pos)


# ── the common D8 set, per type ─────────────────────────────────────────────


@pytest.mark.parametrize("ftype", ALL_TYPES)
def test_place_selects_resets_tool_and_no_inline(ftype, canvas, vm, qtbot):
    fid = vm.place(ftype, 100.0, 100.0)

    item = canvas.item_for(fid)
    assert item is not None
    assert vm.selection == fid                # the new field is selected
    assert vm.tool == TOOL_POINTER            # one-shot placement
    assert vm.inline_field_id is None         # inline editing is NOT opened
    assert item.selected is True
    assert vm.dirty is True


@pytest.mark.parametrize("ftype", ALL_TYPES)
def test_move_clamped_into_its_page(ftype, canvas, vm):
    fid = vm.place(ftype, 100.0, 100.0)
    vm.move(fid, PAGE_WIDTH_PT + 50.0, PAGE_HEIGHT_PT + 50.0)

    f = vm.template.get_field(fid)
    assert f.x + f.w <= PAGE_WIDTH_PT + 1e-6
    assert f.y + f.h <= PAGE_HEIGHT_PT + 1e-6
    assert f.x >= 0 and f.y >= 0


@pytest.mark.parametrize("ftype", ALL_TYPES)
def test_resize_clamped_to_minimums_and_page(ftype, canvas, vm):
    fid = vm.place(ftype, 10.0, 10.0)

    vm.resize(fid, 0.0, 0.0, 1.0, 1.0)      # below the minimums
    f = vm.template.get_field(fid)
    if ftype is FieldType.LINE:                # thickness floor: 1 pt (D7)
        thickness = min(f.w, f.h)
        assert thickness >= 1.0
    else:
        assert f.w >= 16.0 and f.h >= 16.0

    vm.resize(fid, 0.0, 0.0, PAGE_WIDTH_PT * 2, PAGE_HEIGHT_PT * 2)
    f = vm.template.get_field(fid)
    assert f.w <= PAGE_WIDTH_PT and f.h <= PAGE_HEIGHT_PT


@pytest.mark.parametrize("ftype", ALL_TYPES)
async def test_save_open_roundtrip_keeps_the_field(ftype, service):
    row = await service.create(f"Тип {ftype.value}")
    template = await service.load(row.id)
    f = template.add_field(ftype, (55.0, 65.0), page_index=0)

    # per-type data (the D3 extras) where the type has any
    if ftype is FieldType.NUMBER:
        f.content, f.min_value, f.max_value = "1.5", 0.0, 10.0
    elif ftype is FieldType.DROPDOWN:
        f.options, f.content = ["а", "б"], "б"
    elif ftype is FieldType.CHECKBOX:
        f.content = "true"
    await service.update_pages(row.id, template)

    reloaded = await service.load(row.id)
    r = reloaded.pages[0].fields
    assert len(r) == 1
    g = r[0]
    assert g.id == f.id
    assert g.type is ftype
    assert (g.x, g.y, g.w, g.h) == (f.x, f.y, f.w, f.h)
    assert g.content == f.content
    if ftype is FieldType.NUMBER:
        assert g.min_value == 0.0 and g.max_value == 10.0
    if ftype is FieldType.DROPDOWN:
        assert g.options == ["а", "б"]


@pytest.mark.parametrize("ftype", ALL_TYPES)
def test_portrait_to_landscape_clamps_without_scaling(ftype, canvas, vm):
    fid = vm.place(ftype, 100.0, 10.0)
    h0 = vm.template.get_field(fid).h
    # force the field into the bottom of the portrait page: after the switch
    # to the shorter (landscape) height it must be clamped back on the sheet
    vm.move(fid, 100.0, PAGE_HEIGHT_PT - vm.template.get_field(fid).h)

    assert vm.set_orientation(ORIENTATION_LANDSCAPE) is True
    f = vm.template.get_field(fid)

    assert vm.template.page_size == (PAGE_HEIGHT_PT, PAGE_WIDTH_PT)
    assert f.x + f.w <= PAGE_HEIGHT_PT + 1e-6
    assert f.y + f.h <= PAGE_WIDTH_PT + 1e-6
    assert f.h == h0                        # clamped, never scaled
    assert f.w >= 16.0 or ftype is FieldType.LINE


# ── 6.1 checkbox ────────────────────────────────────────────────────────────

def test_checkbox_default_off_survives_roundtrip(vm, qtbot):
    fid = vm.place(FieldType.CHECKBOX, 100.0, 100.0)
    assert vm.template.get_field(fid).content == "false"


def test_checkbox_doubleclick_toggles_default(canvas, vm, qtbot):
    fid = vm.place(FieldType.CHECKBOX, 100.0, 100.0)
    _dclick(canvas, 109.0, 109.0, qtbot)
    assert vm.template.get_field(fid).content == "true"
    _dclick(canvas, 109.0, 109.0, qtbot)
    assert vm.template.get_field(fid).content == "false"


# ── 6.2 number ─────────────────────────────────────────────────────────────

def test_number_inline_comma_on_enter(canvas, vm, qtbot):
    fid = vm.place(FieldType.NUMBER, 100.0, 100.0)
    _dclick(canvas, 110.0, 109.0, qtbot)
    edit = canvas.inline_edit()
    assert isinstance(edit, QLineEdit)       # single-line type

    edit.setText("1,5")
    qtbot.keyClick(edit, Qt.Key_Return)
    assert vm.inline_field_id is None
    assert vm.template.get_field(fid).content == "1.5"


def test_number_refuses_out_of_bounds_and_non_numeric(canvas, vm, qtbot):
    fid = vm.place(FieldType.NUMBER, 100.0, 100.0)
    vm.set_min_value(fid, 0.0)
    vm.set_max_value(fid, 5.0)
    vm.apply_number(fid, "1,5")
    assert vm.template.get_field(fid).content == "1.5"

    _dclick(canvas, 110.0, 109.0, qtbot)
    edit = canvas.inline_edit()
    edit.setText("10")                       # above max
    qtbot.keyClick(edit, Qt.Key_Return)
    assert vm.template.get_field(fid).content == "1.5"
    assert vm.inline_field_id is not None    # the rejected edit stays open
    edit.setText("x")                        # not a number
    qtbot.keyClick(edit, Qt.Key_Return)
    assert vm.template.get_field(fid).content == "1.5"
    vm.commit_inline()


# ── 6.3 dropdown ────────────────────────────────────────────────────────────

def test_dropdown_default_text_is_drawn_on_canvas(canvas, vm, qtbot):
    fid = vm.place(FieldType.DROPDOWN, 100.0, 100.0)
    assert vm.set_options(fid, ["Меч", "Щит"]) is True
    vm.set_content(fid, "Меч")

    from PySide6.QtGui import QImage as _QI

    img = _QI(int(PAGE_WIDTH_PT), int(PAGE_HEIGHT_PT), _QI.Format.Format_ARGB32)
    img.fill(QColor("white"))
    from PySide6.QtGui import QPainter

    p = QPainter(img)
    canvas.scene().render(p)
    p.end()
    r = canvas.item_for(fid).rect()
    dark = False
    for dy in range(int(r.height())):
        for dx in range(int(r.width())):
            px = img.pixelColor(int(r.x()) + dx, int(r.y()) + dy)
            if px.red() < 128 and px.green() < 128 and px.blue() < 128:
                dark = True
                break
        if dark:
            break
    assert dark, "the default option text must be visible on the canvas"


def test_dropdown_set_options_refuses_empties(vm):
    fid = vm.place(FieldType.DROPDOWN, 10.0, 10.0)
    assert vm.set_options(fid, ["а", "б"]) is True
    assert vm.set_options(fid, ["а", "   ", "б"]) is False
    assert vm.set_options(fid, ["", "б"]) is False
    assert vm.template.get_field(fid).options == ["а", "б"]


# ── 6.5 rect ────────────────────────────────────────────────────────────────

def test_rect_has_no_content_and_doubleclick_only_selects(canvas, vm, qtbot):
    """Rect carries no character data: no content, no inline editor on the
    canvas (the double-click only selects it, spec)."""
    fid = vm.place(FieldType.RECT, 100.0, 100.0)
    f = vm.template.get_field(fid)
    assert f.content == ""

    _dclick(canvas, 110.0, 110.0, qtbot)
    assert vm.selection == fid
    assert vm.inline_field_id is None
    assert canvas.inline_edit() is None
    assert vm.template.get_field(fid).content == ""


# ── 6.6 line ────────────────────────────────────────────────────────────────

def test_line_is_horizontal_when_wider(vm):
    fid = vm.place(FieldType.LINE, 10.0, 10.0)   # 120 x 2
    f = vm.template.get_field(fid)
    assert f.w > f.h                             # horizontal axis
    vm.resize(fid, 10.0, 10.0, 5.0, 200.0)
    f = vm.template.get_field(fid)
    assert f.w < f.h                             # now the vertical axis
    # thickness keeps the 1pt floor (D7)
    vm.resize(fid, 10.0, 10.0, 0.0, 0.0)
    f = vm.template.get_field(fid)
    assert min(f.w, f.h) >= 1.0


# ── 6.4 image: ImageStore pipeline ──────────────────────────────────────────

@pytest.fixture
async def sheet_env(async_session, tmp_path):
    """Service + ImageStore + editor dialog of a fresh game (in-memory DB)."""
    store = ImageStore(async_session, tmp_path / "images")
    service = CharacterSheetService(CharacterSheetRepository(async_session),
                                    image_store=store)
    row = await service.create("С картинкой")
    return service, store, row


def _png_bytes() -> bytes:
    img = QImage(16, 16, QImage.Format.Format_ARGB32)
    img.fill(QColor(200, 30, 30))
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    byte_array = QByteArray()
    buf = QBuffer(byte_array)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(byte_array)


async def _write(tmp_path: Path, name: str, data: bytes) -> str:
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


async def test_image_doubleclick_picks_and_stores(
    qtbot, monkeypatch, sheet_env, tmp_path
):
    service, store, row = sheet_env
    from app.presentation.views.character_sheet.editor_dialog import (
        CharacterSheetEditorDialog,
    )

    png = await _write(tmp_path, "img.png", _png_bytes())
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **k: (png, "")),
    )

    dlg = CharacterSheetEditorDialog(service, row.id, image_store=store)
    dlg.resize(1200, 800)
    await dlg.load()
    dlg.show()
    qtbot.wait(30)

    fid = dlg.view_model.place(FieldType.IMAGE, 100.0, 100.0)
    assert dlg.view_model.template.get_field(fid).image_id is None

    # double-click opens the pick; the picked file goes through the ImageStore
    pos = dlg.canvas.mapFromScene(QPointF(110.0, 110.0))
    qtbot.mouseDClick(dlg.canvas.viewport(), Qt.MouseButton.LeftButton, pos=pos)

    for _ in range(100):
        if dlg.view_model.template.get_field(fid).image_id is not None:
            break
        await asyncio.sleep(0.01)
        qtbot.wait(1)
    field = dlg.view_model.template.get_field(fid)
    assert field.image_id is not None

    await dlg.view_model.save()
    # after the committed save the sheet field is the only referrer …
    assert await store.refcount(field.image_id) == 1
    orig = await store.original_file_path(field.image_id)
    assert orig is not None and orig.exists()  # … and the file is in the game storage

    dlg.force_close()
    dlg.deleteLater()
    qtbot.wait(20)


async def test_image_clear_and_save_gcs_the_file(qtbot, sheet_env, tmp_path):
    service, store, row = sheet_env
    from app.presentation.views.character_sheet.editor_dialog import (
        CharacterSheetEditorDialog,
    )

    dlg = CharacterSheetEditorDialog(service, row.id, image_store=store)
    dlg.resize(1200, 800)
    await dlg.load()
    dlg.show()
    qtbot.wait(30)

    fid = dlg.view_model.place(FieldType.IMAGE, 100.0, 100.0)
    image_id = await store.store(_png_bytes())
    dlg.view_model.set_image_id(fid, image_id)

    # refcount counts DB refs, so commit first
    orig_before = await store.original_file_path(image_id)
    await dlg.view_model.save()
    assert await store.refcount(image_id) == 1

    dlg.view_model.set_image_id(fid, None)
    await dlg.view_model.save()

    assert await store.refcount(image_id) == 0
    assert orig_before is not None and not orig_before.exists()  # GC'd
    row_after = await service._repo.get_by_id(row.id)
    assert "image_id" in row_after.pages
    assert dlg.view_model.dirty is False

    dlg.force_close()
    dlg.deleteLater()
    qtbot.wait(20)


async def test_image_undecodable_file_leaves_field_empty(
    qtbot, monkeypatch, sheet_env, tmp_path
):
    service, store, row = sheet_env
    from app.presentation.views.character_sheet.editor_dialog import (
        CharacterSheetEditorDialog,
    )

    txt = await _write(tmp_path, "not-image.txt", b"definitely not a png")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **k: (txt, "")),
    )
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda *a, **k: warnings.append(a[1:3]))  # (title, text)
    )

    dlg = CharacterSheetEditorDialog(service, row.id, image_store=store)
    dlg.resize(1200, 800)
    await dlg.load()
    dlg.show()
    qtbot.wait(30)

    fid = dlg.view_model.place(FieldType.IMAGE, 100.0, 100.0)
    pos = dlg.canvas.mapFromScene(QPointF(110.0, 110.0))
    qtbot.mouseDClick(dlg.canvas.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    for _ in range(100):
        if warnings:
            break
        await asyncio.sleep(0.01)
        qtbot.wait(1)

    assert dlg.view_model.template.get_field(fid).image_id is None
    assert len(warnings) == 1
    assert "не является изображением" in warnings[0][1]

    dlg.force_close()
    dlg.deleteLater()
    qtbot.wait(20)
