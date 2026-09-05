"""Tests for the Fill window (tasks 6.1 and 6.3 of add-character-sheet-a1;
addressing re-targeted onto the QML island in Q3b task 3.3, semantics unchanged).

No palette; rail without add/delete/reorder; drag does not move geometry;
click text → inline; click checkbox → toggle; click label — no inline;
single selection; Save writes values; dirty-close confirm; Edit menu is
Undo/Redo on StandardKey. The content lives in the SheetFillRoot island — the
field clicks are island input (the migrated canvas semantics pinned once in
test_sheet_canvas_island), the popups stay native facade dialogs.
"""
from __future__ import annotations

import asyncio
import base64
import json

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt, QUrl
from PySide6.QtGui import QMouseEvent
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
from tests.presentation.qml_helpers import (
    click_item,
    find_item,
    find_items,
    island_rows,
    walk_items,
)

# QML Image.status — Image.Ready
_IMAGE_READY = 1


def _pump(qtbot) -> None:
    for _ in range(4):
        qtbot.wait(5)


def _item(d, name: str):
    return find_item(d.quick, name)


def _canvas(d):
    return _item(d, "sheetFillCanvas")


def _field_item(d, fid: str):
    return find_item(d.quick, f"sheetField-{fid}")


def _send(widget, kind, pos, button, buttons,
          modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    QApplication.sendEvent(widget, QMouseEvent(
        kind, QPointF(pos), widget.mapToGlobal(QPointF(pos).toPoint()),
        button, buttons, modifiers,
    ))


def _center(d, fid: str) -> QPointF:
    item = _field_item(d, fid)
    return item.mapToScene(QPointF(item.width() / 2, item.height() / 2))


def _click_field(d, fid: str, qtbot) -> None:
    click_item(d.quick, _field_item(d, fid))
    _pump(qtbot)


def _drag_field(d, fid: str, dx: float, dy: float, qtbot) -> None:
    """Press the field centre and drag by a page-point offset (the migrated
    _drag_field; the canvas holds the zoom, so px = pt * zoom)."""
    z = float(_canvas(d).property("zoom"))
    start = _center(d, fid)
    end = QPointF(start.x() + dx * z, start.y() + dy * z)
    global _qtbot_ref
    _qtbot_ref = qtbot
    _press(d, start)
    _move(d, end)
    _release(d, end)
    _pump(qtbot)


def _press(d, pos) -> None:
    _send(d.quick, QEvent.Type.MouseButtonPress, pos,
          Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    _pump(_qtbot_ref)


def _release(d, pos) -> None:
    _send(d.quick, QEvent.Type.MouseButtonRelease, pos,
          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
    _pump(_qtbot_ref)


def _move(d, pos) -> None:
    _send(d.quick, QEvent.Type.MouseMove, pos,
          Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    _pump(_qtbot_ref)


_qtbot_ref = None


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
    _pump(qtbot)  # the island fits its width on the first frames (like fit_width)
    yield d, ids, inst_svc, instance_id
    d.force_close()
    d.deleteLater()
    qtbot.wait(1)


async def test_no_palette_and_rail_has_no_page_mutation(dlg):
    d, ids, *_ = dlg
    # the fill island: no palette tools at all, no page-mutation rail chrome
    assert [i for i in walk_items(d.quick.rootObject())
            if i.objectName().startswith("paletteTool")] == []
    for name in ("railAddButton", "railDeleteButton", "railUpButton",
                 "railDownButton"):
        assert find_items(d.quick, name) == []
    from PySide6.QtWidgets import QPushButton
    assert "Экспорт в PDF…" not in [b.text() for b in d.findChildren(QPushButton)]


async def test_drag_does_not_change_geometry(dlg, qtbot):
    d, ids, *_ = dlg
    field = d.view_model.template.get_field(ids["text"])
    before = (field.x, field.y, field.w, field.h)
    _drag_field(d, ids["text"], 80.0, 60.0, qtbot)
    field = d.view_model.template.get_field(ids["text"])
    assert (field.x, field.y, field.w, field.h) == before


async def test_click_text_opens_inline(dlg, qtbot):
    d, ids, *_ = dlg
    _click_field(d, ids["text"], qtbot)
    assert d.view_model.inline_field_id == ids["text"]
    assert find_items(d.quick, "sheetInlineEditor") != []


async def test_click_checkbox_toggles_without_inline(dlg, qtbot):
    d, ids, *_ = dlg
    assert d.view_model.display_value(ids["chk"]) is False
    _click_field(d, ids["chk"], qtbot)
    assert d.view_model.display_value(ids["chk"]) is True
    assert d.view_model.inline_field_id is None
    assert find_items(d.quick, "sheetInlineEditor") == []


async def test_click_label_does_not_open_inline(dlg, qtbot):
    d, ids, *_ = dlg
    _click_field(d, ids["lab"], qtbot)
    assert d.view_model.inline_field_id is None
    assert d.view_model.selection == ids["lab"]


async def test_single_selection(dlg, qtbot):
    d, ids, *_ = dlg
    _click_field(d, ids["text"], qtbot)
    _click_field(d, ids["lab"], qtbot)
    assert d.view_model.selection == ids["lab"]
    assert d.view_model.selected_ids == [ids["lab"]]


async def test_save_writes_values(dlg, qtbot):
    d, ids, inst_svc, instance_id = dlg
    d.view_model.set_text(ids["text"], "Пётр")
    click_item(d.quick, _item(d, "saveButton"))
    for _ in range(200):
        if not d.view_model.dirty:
            break
        await asyncio.sleep(0.01)
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
    _pump(qtbot)
    try:
        bind = _item(d, "bindButton")
        assert bind.property("visible") is True
        click_item(d.quick, bind)
        for _ in range(80):
            await asyncio.sleep(0)
            qtbot.wait(1)
            if d.view_model.character_id == char.id:
                break
        assert d.view_model.character_id == char.id
        _pump(qtbot)  # _sync_bind_buttons pushes characterBound onto the island
        unbind = _item(d, "unbindButton")
        assert unbind.property("enabled") is True
        click_item(d.quick, unbind)
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
    QTest.keyClick(d.quick, Qt.Key_Delete)
    qtbot.wait(10)
    assert d.view_model.template.get_field(ids["lab"]) is not None
    assert find_items(d.quick, f"sheetField-{ids['lab']}") != []


async def test_click_dropdown_opens_menu(dlg, qtbot):
    d, ids, *_ = dlg
    _click_field(d, ids["dd"], qtbot)
    # the QMenu-bridge: the island reports the field, the facade pops the
    # native menu (D9) and its choice lands on vm.set_dropdown
    menu = d.dropdown_menu
    assert menu is not None
    texts = [a.text() for a in menu.actions() if a.text()]
    assert "эльф" in texts
    assert "орк" in texts
    ork = next(a for a in menu.actions() if a.text() == "орк")
    ork.trigger()
    assert d.view_model.display_value(ids["dd"]) == "орк"


async def test_checkbox_double_click_toggles_once(dlg, qtbot):
    d, ids, *_ = dlg
    assert d.view_model.display_value(ids["chk"]) is False
    # one double-click toggles exactly once (the mouseDClick the canvas
    # handles as a double-click, not as two clicks)
    click_item(d.quick, _field_item(d, ids["chk"]), double=True)
    _pump(qtbot)
    assert d.view_model.display_value(ids["chk"]) is True


def _qtbot_global(d, qtbot) -> None:
    global _qtbot_ref
    _qtbot_ref = qtbot


async def test_panel_textarea_one_undo_step(dlg, qtbot):
    d, ids, *_ = dlg
    d.view_model.select(ids["ta"])
    _pump(qtbot)
    textarea = _item(d, "fillTextarea")
    assert textarea.property("visible") is True
    click_item(d.quick, textarea)           # focus: the island's typing session
    assert textarea.property("activeFocus") is True
    textarea.setProperty("text", "абв")
    _pump(qtbot)
    assert d.view_model.can_undo is False   # committed only on focus-out
    # focus-out (the old setFocus(canvas) → eventFilter commit): the canvas
    # takes the active focus, the TextArea commits on leaving it
    _canvas(d).forceActiveFocus()
    _pump(qtbot)
    assert d.view_model.display_value(ids["ta"]) == "абв"
    assert d.view_model.can_undo is True
    d.view_model.undo()
    assert d.view_model.display_value(ids["ta"]) == ""
    assert d.view_model.can_undo is False


async def test_orphan_dropdown_reselect_keeps_panel_in_sync(dlg, qtbot):
    d, ids, *_ = dlg
    d.view_model.set_dropdown(ids["dd"], "орк")
    field = d.view_model.template.get_field(ids["dd"])
    field.options = ["эльф"]
    d.view_model.select(ids["dd"])
    _pump(qtbot)
    combo = _item(d, "fillDropdown")
    # the orphan current stays visible in the panel combo
    assert "орк" in list(combo.property("model"))
    d.view_model.set_dropdown(ids["dd"], "эльф")
    _pump(qtbot)
    # once the current is a listed option the orphan drops out of the next
    # rebuild (the migrated QComboBox refresh rules)
    model = list(combo.property("model"))
    assert model == ["эльф"]
    # a pick of the orphaned option (what a stale open menu would send) is
    # refused by the VM; the combo re-reads the stored value (the migrated
    # _commit_dropdown + re-sync meaning)
    assert d.view_model.set_dropdown(ids["dd"], "орк") is False
    combo.setProperty("currentIndex", model.index("эльф"))
    combo.activated.emit(model.index("эльф"))
    _pump(qtbot)
    assert d.view_model.display_value(ids["dd"]) == "эльф"
    assert int(combo.property("currentIndex")) == model.index("эльф")


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
    _pump(qtbot)
    try:
        assert d.view_model.set_image(ids["img"], 99) is True
        # the delegate's async Image resolves through ``image://sheet`` with
        # the store bound by the facade — Ready replaces the old pixmap check
        images = []
        for _ in range(40):
            delegate = _field_item(d, ids["img"])
            images = [i for i in walk_items(delegate)
                      if i.objectName() == "fieldImage"]
            if images and float(images[0].property("paintedWidth")) > 0:
                break
            await asyncio.sleep(0)
            qtbot.wait(5)
        assert images, "the image delegate exists"
        # paintedWidth > 0 exactly once the provider has delivered the image
        # (QML Image status is an enum PySide6 does not hand back as int)
        assert float(images[0].property("paintedWidth")) > 0
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


async def test_read_only_fill_does_not_open_inline(qtbot, services):
    sheet_svc, inst_svc = services
    instance_id, ids = await _seed(sheet_svc, inst_svc)
    d = CharacterSheetFillDialog(inst_svc, sheet_svc, instance_id, read_only=True)
    await d.load()
    d.show()
    qtbot.addWidget(d)
    _pump(qtbot)
    assert d.view_model.read_only
    assert _item(d, "saveButton").property("visible") is False
    d._pick_image(ids["img"])
    _click_field(d, ids["text"], qtbot)
    assert d.view_model.inline_field_id is None
    other = await inst_svc.create("Другой", (await sheet_svc.list_sheets())[0].id)
    await d.load_instance(other.id)
    assert d.view_model.instance_id == other.id
    d.force_close()


async def test_set_read_only_restores_writable_ui(qtbot, services):
    sheet_svc, inst_svc = services
    instance_id, _ids = await _seed(sheet_svc, inst_svc)
    d = CharacterSheetFillDialog(inst_svc, sheet_svc, instance_id, read_only=True)
    await d.load()
    d.show()
    qtbot.addWidget(d)
    _pump(qtbot)
    assert _item(d, "saveButton").property("visible") is False
    d.set_read_only(False)
    assert d.view_model.read_only is False
    _pump(qtbot)
    assert _item(d, "saveButton").property("visible") is True
    assert _item(d, "bindButton").property("visible") is True
    d.set_read_only(True)
    assert d.view_model.read_only is True
    _pump(qtbot)
    assert _item(d, "saveButton").property("visible") is False
    d.force_close()


# ── Enter marker & the native dropdown menu (Q3b D1 / migrated canvas rules) ─


async def test_enter_on_the_wrapper_clicks_the_save_marker(dlg, qtbot):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    d, _ids, *_ = dlg
    marker = d.quick.rootObject().property("defaultButton")
    fired: list[int] = []
    marker.clicked.connect(lambda: fired.append(1))

    d.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                              Qt.KeyboardModifier.NoModifier))
    assert fired == [1]                      # «Сохранить» via the marker
    d.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Plus,
                              Qt.KeyboardModifier.NoModifier))
    assert fired == [1]                      # not Enter — wrapper stays out


async def test_enter_in_read_only_never_clicks_the_hidden_marker(dlg, qtbot):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    d, ids, *_ = dlg
    marker = d.quick.rootObject().property("defaultButton")
    fired: list[int] = []
    marker.clicked.connect(lambda: fired.append(1))
    d.view_model.set_read_only(True)
    _pump(qtbot)
    d.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                              Qt.KeyboardModifier.NoModifier))
    assert fired == []                       # «Сохранить» hidden — nothing to click


async def test_popup_dropdown_closes_previous_and_keeps_orphan_first(dlg, qtbot):
    d, ids, *_ = dlg
    # the old canvas rule: the current outside the options stays visible as a
    # disabled head entry; re-opening retires the stale menu instead of
    # stacking a second one; a foreign id keeps the last known state quietly.
    field = d.view_model.template.get_field(ids["dd"])
    field.options = ["эльф"]
    # the current the instance carries outside the shortened options —
    # applied through the VM's own remote-refresh entrance (validation-free
    # by contract, exactly what produced orphaned currents in the field)
    d.view_model.apply_remote_value(ids["dd"], "устаревшее")
    assert d.view_model.display_value(ids["dd"]) == "устаревшее"

    d._popup_dropdown(ids["dd"], 0.0, 0.0)
    first = d.dropdown_menu
    assert first is not None
    d._popup_dropdown(ids["dd"], 0.0, 0.0)
    menu = d.dropdown_menu
    assert menu is not first, "the previous popup retires, no stacking"

    texts = [a.text() for a in menu.actions() if a.text()]
    assert texts[0] == "устаревшее"          # orphan first…
    head = menu.actions()[0]
    assert head.isEnabled() is False          # …and disabled
    assert "эльф" in texts
    elf = next(a for a in menu.actions() if a.text() == "эльф")
    elf.trigger()
    assert d.view_model.display_value(ids["dd"]) == "эльф"
    d.dropdown_menu = None                    # teardown: closed by trigger

    # the migrated close-previous rule also covers the raced field: a foreign
    # id closes the stale popup and leaves nothing behind instead of keeping
    # a menu wired to a field the template no longer has
    d._popup_dropdown(ids["dd"], 0.0, 0.0)
    assert d.dropdown_menu is not None
    d._popup_dropdown("ghost-field", 0.0, 0.0)
    assert d.dropdown_menu is None
