"""Tests for the Fill window (tasks 6.1 and 6.3).

No palette; rail without add/delete/reorder; drag does not move geometry;
click text → inline; click checkbox → toggle; click label — no inline;
single selection; Save writes values; dirty-close confirm; Edit menu is
Undo/Redo on StandardKey.
"""
from __future__ import annotations

import asyncio
import base64
import json

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

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
from app.presentation.views.character_sheet.fill_dialog import (
    CharacterSheetFillDialog,
    character_choice_labels,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def services(async_session):
    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    return sheet_svc, inst_svc


_PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


async def _seed(sheet_svc, inst_svc):
    row = await sheet_svc.create("Шаблон")
    template = await sheet_svc.load(row.id)
    text_f = template.add_field(FieldType.TEXT, (40.0, 40.0))
    text_f.content = "Иван"
    chk = template.add_field(FieldType.CHECKBOX, (40.0, 80.0))
    chk.content = "false"
    lab = template.add_field(FieldType.LABEL, (40.0, 120.0))
    lab.content = "Имя"
    dd = template.add_field(FieldType.DROPDOWN, (40.0, 160.0))
    dd.options = ["эльф", "орк"]
    dd.content = "эльф"
    ta = template.add_field(FieldType.TEXTAREA, (40.0, 200.0))
    ta.content = ""
    img = template.add_field(FieldType.IMAGE, (40.0, 280.0))
    img.image_id = 7
    await sheet_svc.update_pages(row.id, template)
    inst = await inst_svc.create("Лист героя", row.id)
    return inst.id, {
        "text": text_f.id, "chk": chk.id, "lab": lab.id,
        "dd": dd.id, "ta": ta.id, "img": img.id,
    }


@pytest.fixture
def confirm(monkeypatch) -> dict:
    state: dict = {"answer": QMessageBox.StandardButton.Yes, "calls": []}

    def fake_question(parent, title, text, *args, **kwargs):
        state["calls"].append((title, text))
        return state["answer"]

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_question))
    return state


@pytest.fixture
async def dlg(qtbot, services):
    sheet_svc, inst_svc = services
    instance_id, ids = await _seed(sheet_svc, inst_svc)
    d = CharacterSheetFillDialog(inst_svc, sheet_svc, instance_id)
    d.resize(1100, 800)
    await d.load()
    d.show()
    d.canvas.fit_width()
    qtbot.wait(20)
    yield d, ids, inst_svc, instance_id
    d.force_close()
    d.deleteLater()
    qtbot.wait(1)


def _click_field(dlg, field_id: str, qtbot) -> None:
    field = dlg.view_model.template.get_field(field_id)
    page = dlg.view_model.page_of(field_id) or 0
    from app.domain.entities.character_sheet import page_origin
    _, oy = page_origin(page, dlg.view_model.template.page_size[1])
    scene_x = field.x + field.w / 2
    scene_y = field.y + oy + field.h / 2
    view_pos = dlg.canvas.mapFromScene(QPointF(scene_x, scene_y))
    qtbot.mouseClick(dlg.canvas.viewport(), Qt.LeftButton, pos=view_pos)


def _drag_field(dlg, field_id: str, dx: float, dy: float) -> None:
    field = dlg.view_model.template.get_field(field_id)
    from app.domain.entities.character_sheet import page_origin
    _, oy = page_origin(0, dlg.view_model.template.page_size[1])
    p0 = dlg.canvas.mapFromScene(QPointF(field.x + 4, field.y + oy + 4))
    p1 = dlg.canvas.mapFromScene(QPointF(field.x + 4 + dx, field.y + oy + 4 + dy))
    QTest.mousePress(dlg.canvas.viewport(), Qt.MouseButton.LeftButton, pos=p0)
    QTest.mouseMove(dlg.canvas.viewport(), p1)
    QTest.mouseRelease(dlg.canvas.viewport(), Qt.MouseButton.LeftButton, pos=p1)


async def test_no_palette_and_rail_has_no_page_mutation(dlg):
    d, ids, *_ = dlg
    assert d.palette is None
    assert not d.rail.add_button.isVisible()
    assert not d.rail.delete_button.isVisible()
    assert not d.rail.up_button.isVisible()
    assert not d.rail.down_button.isVisible()


async def test_drag_does_not_change_geometry(dlg, qtbot):
    d, ids, *_ = dlg
    field = d.view_model.template.get_field(ids["text"])
    before = (field.x, field.y, field.w, field.h)
    _drag_field(d, ids["text"], 80.0, 60.0)
    qtbot.wait(10)
    field = d.view_model.template.get_field(ids["text"])
    assert (field.x, field.y, field.w, field.h) == before


async def test_click_text_opens_inline(dlg, qtbot):
    d, ids, *_ = dlg
    _click_field(d, ids["text"], qtbot)
    qtbot.wait(10)
    assert d.view_model.inline_field_id == ids["text"]
    assert d.canvas.inline_edit() is not None


async def test_click_checkbox_toggles_without_inline(dlg, qtbot):
    d, ids, *_ = dlg
    assert d.view_model.display_value(ids["chk"]) is False
    _click_field(d, ids["chk"], qtbot)
    qtbot.wait(10)
    assert d.view_model.display_value(ids["chk"]) is True
    assert d.view_model.inline_field_id is None
    assert d.canvas.inline_edit() is None


async def test_click_label_does_not_open_inline(dlg, qtbot):
    d, ids, *_ = dlg
    _click_field(d, ids["lab"], qtbot)
    qtbot.wait(10)
    assert d.view_model.inline_field_id is None
    assert d.view_model.selection == ids["lab"]


async def test_single_selection(dlg, qtbot):
    d, ids, *_ = dlg
    _click_field(d, ids["text"], qtbot)
    _click_field(d, ids["lab"], qtbot)
    qtbot.wait(10)
    assert d.view_model.selection == ids["lab"]
    assert d.view_model.selected_ids == [ids["lab"]]


async def test_save_writes_values(dlg, qtbot):
    d, ids, inst_svc, instance_id = dlg
    d.view_model.set_text(ids["text"], "Пётр")
    d.save_button.click()
    for _ in range(50):
        if not d.view_model.dirty:
            break
        await asyncio.sleep(0)
    assert d.view_model.dirty is False
    row = await inst_svc.get(instance_id)
    assert json.loads(row.values)[ids["text"]] == "Пётр"


async def test_close_dirty_no_keeps_window(dlg, confirm, qtbot):
    d, ids, inst_svc, instance_id = dlg
    d.view_model.set_text(ids["text"], "Пётр")
    confirm["answer"] = QMessageBox.StandardButton.No
    d.close()
    qtbot.wait(10)
    assert d.isVisible()
    assert d.view_model.dirty is True
    row = await inst_svc.get(instance_id)
    assert json.loads(row.values)[ids["text"]] == "Иван"


async def test_edit_menu_only_undo_redo_standard_keys(dlg):
    d, *_ = dlg
    titles = [a.text() for a in d.edit_menu.actions() if not a.isSeparator()]
    assert titles == ["Отменить", "Повторить"]
    assert d.undo_action.shortcut() == QKeySequence(QKeySequence.StandardKey.Undo)
    assert d.redo_action.shortcut() == QKeySequence(QKeySequence.StandardKey.Redo)
    assert not hasattr(d, "copy_action")
    assert not hasattr(d, "duplicate_action")


async def test_bind_unbind_buttons(qtbot, services, async_session, monkeypatch):
    from datetime import date

    from PySide6.QtWidgets import QInputDialog

    from app.infrastructure.repositories.character_repository import CharacterRepository

    sheet_svc, inst_svc = services
    instance_id, ids = await _seed(sheet_svc, inst_svc)
    char = await CharacterRepository(async_session).create(
        name="Герой", start_date=date(1300, 1, 1)
    )
    await async_session.commit()

    class _Chars:
        async def get_all(self):
            return [char]

    monkeypatch.setattr(
        QInputDialog, "getItem", staticmethod(lambda *a, **k: ("Герой", True))
    )
    d = CharacterSheetFillDialog(
        inst_svc, sheet_svc, instance_id, character_service=_Chars()
    )
    d.resize(1100, 800)
    await d.load()
    d.show()
    qtbot.wait(10)
    try:
        assert d.bind_button.isVisible()
        d.bind_button.click()
        for _ in range(80):
            await asyncio.sleep(0)
            qtbot.wait(1)
            if d.view_model.character_id == char.id:
                break
        assert d.view_model.character_id == char.id
        d.unbind_button.click()
        for _ in range(80):
            await asyncio.sleep(0)
            qtbot.wait(1)
            if d.view_model.character_id is None:
                break
        assert d.view_model.character_id is None
    finally:
        d.force_close()
        d.deleteLater()
        qtbot.wait(1)


async def test_delete_key_does_not_remove_field(dlg, qtbot):
    d, ids, *_ = dlg
    _click_field(d, ids["lab"], qtbot)
    qtbot.wait(10)
    qtbot.keyClick(d.canvas, Qt.Key_Delete)
    qtbot.wait(10)
    assert d.view_model.template.get_field(ids["lab"]) is not None
    assert d.canvas.item_for(ids["lab"]) is not None


async def test_click_dropdown_opens_menu(dlg, qtbot):
    d, ids, *_ = dlg
    _click_field(d, ids["dd"], qtbot)
    qtbot.wait(10)
    menu = d.canvas.dropdown_menu
    assert menu is not None
    texts = [a.text() for a in menu.actions() if a.text()]
    assert "эльф" in texts
    assert "орк" in texts
    ork = next(a for a in menu.actions() if a.text() == "орк")
    ork.trigger()
    assert d.view_model.display_value(ids["dd"]) == "орк"


async def test_checkbox_double_click_toggles_once(dlg, qtbot):
    d, ids, *_ = dlg
    field = d.view_model.template.get_field(ids["chk"])
    from app.domain.entities.character_sheet import page_origin
    _, oy = page_origin(0, d.view_model.template.page_size[1])
    view_pos = d.canvas.mapFromScene(
        QPointF(field.x + field.w / 2, field.y + oy + field.h / 2)
    )
    assert d.view_model.display_value(ids["chk"]) is False
    QTest.mouseClick(d.canvas.viewport(), Qt.MouseButton.LeftButton, pos=view_pos)
    QTest.mouseClick(d.canvas.viewport(), Qt.MouseButton.LeftButton, pos=view_pos)
    qtbot.wait(10)
    assert d.view_model.display_value(ids["chk"]) is True


async def test_panel_textarea_one_undo_step(dlg, qtbot):
    d, ids, *_ = dlg
    d.view_model.select(ids["ta"])
    qtbot.wait(10)
    panel = d.properties_panel
    assert panel.textarea.isVisible()
    panel.textarea.setFocus()
    panel.textarea.setPlainText("абв")
    qtbot.wait(10)
    assert d.view_model.can_undo is False
    panel.textarea.clearFocus()
    d.canvas.setFocus()
    qtbot.wait(10)
    assert d.view_model.display_value(ids["ta"]) == "абв"
    assert d.view_model.can_undo is True
    d.view_model.undo()
    assert d.view_model.display_value(ids["ta"]) == ""
    assert d.view_model.can_undo is False


async def test_orphan_dropdown_reselect_keeps_panel_in_sync(dlg):
    d, ids, *_ = dlg
    d.view_model.set_dropdown(ids["dd"], "орк")
    field = d.view_model.template.get_field(ids["dd"])
    field.options = ["эльф"]
    d.view_model.select(ids["dd"])
    panel = d.properties_panel
    panel._refresh()
    items = [panel.dropdown.itemText(i) for i in range(panel.dropdown.count())]
    assert "орк" in items
    d.view_model.set_dropdown(ids["dd"], "эльф")
    panel._commit_dropdown("орк")
    assert d.view_model.display_value(ids["dd"]) == "эльф"
    assert panel.dropdown.currentText() == "эльф"


async def test_fill_image_loads_when_different_from_template(qtbot, services, tmp_path):
    sheet_svc, inst_svc = services
    instance_id, ids = await _seed(sheet_svc, inst_svc)
    png = tmp_path / "x.png"
    png.write_bytes(_PNG_1PX)

    class _Store:
        async def original_file_path(self, image_id):
            return png

    d = CharacterSheetFillDialog(
        inst_svc, sheet_svc, instance_id, image_store=_Store()
    )
    d.resize(1100, 800)
    await d.load()
    d.show()
    d.canvas.fit_width()
    qtbot.wait(20)
    try:
        assert d.view_model.set_image(ids["img"], 99) is True
        for _ in range(30):
            item = d.canvas.item_for(ids["img"])
            if item is not None and item._pixmap is not None and not item._pixmap.isNull():
                break
            await asyncio.sleep(0)
            qtbot.wait(5)
        item = d.canvas.item_for(ids["img"])
        assert item is not None
        assert item._pixmap is not None and not item._pixmap.isNull()
    finally:
        d.force_close()
        d.deleteLater()
        qtbot.wait(1)


def test_character_choice_labels_disambiguate_duplicate_names():
    class _C:
        def __init__(self, id, name):
            self.id = id
            self.name = name

    chars = [_C(1, "Герой"), _C(2, "Герой"), _C(3, "Маг")]
    labels = character_choice_labels(chars)
    assert labels == [("Герой (#1)", 1), ("Герой (#2)", 2), ("Маг", 3)]

