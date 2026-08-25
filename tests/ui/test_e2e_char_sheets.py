"""E2E tasks 7.1/7.2: menu «Чар-листы» → list dialog (create/open/delete/
JSON import-export) → editor; closing the editor on a game switch."""
from __future__ import annotations

import asyncio
import json

from PySide6.QtWidgets import QMessageBox

from app.application.services.character_sheet_service import CharacterSheetService
from app.domain.entities.character_sheet import SheetField, SheetPage, SheetTemplate
from app.domain.enums.field_type import FieldType
from app.domain.enums.sheet_orientation import SheetOrientation
from app.presentation.views.game_launcher_dialog import GameLauncherDialog
from app.presentation.views.character_sheet.editor_dialog import CharacterSheetEditorDialog
from app.presentation.views.character_sheet.list_dialog import CharacterSheetListDialog


async def spin(times: int = 10) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


async def open_sheet_list(window, wait_for) -> CharacterSheetListDialog:
    """Menu «Чар-листы» → the list dialog becomes visible."""
    window.character_sheets_action.trigger()
    await wait_for(lambda: any(d.isVisible() for d in window.findChildren(CharacterSheetListDialog)))
    return next(d for d in window.findChildren(CharacterSheetListDialog) if d.isVisible())


async def create_sheet(sheet_list, wait_for, dialog_input, name: str) -> None:
    dialog_input["answer"] = (name, True)
    sheet_list._create_btn.click()
    await wait_for(lambda: sheet_list._list.count() >= 1)


def list_names(sheet_list) -> list[str]:
    return [sheet_list._list.item(i).text() for i in range(sheet_list._list.count())]


# ── 7.2: menu → list → create → open editor → save ─────────────────────────


async def test_menu_list_create_open_save(app, wait_for, dialog_input):
    """Menu action opens the list; create → row; open → editor; save → DB row."""
    application, window = app
    db_path = application._db_path

    sheet_list = await open_sheet_list(window, wait_for)
    await wait_for(lambda: sheet_list._list.count() == 0)
    assert list_names(sheet_list) == []

    await create_sheet(sheet_list, wait_for, dialog_input, "Лист 1")
    assert list_names(sheet_list) == ["Лист 1"]

    sheet_list._list.setCurrentRow(0)
    sheet_list._open_btn.click()
    await wait_for(lambda: any(d.isVisible() for d in window.findChildren(CharacterSheetEditorDialog)))
    editor = next(d for d in window.findChildren(CharacterSheetEditorDialog) if d.isVisible())
    assert application._sheet_editor is editor

    # wait for the async template load, then edit and save
    await wait_for(lambda: editor.vm.is_ready)
    editor.vm.add_field(FieldType.SHORT_TEXT, 0, 40.0, 40.0, label="Имя")
    assert editor.vm.dirty
    editor.save_btn.click()
    await wait_for(lambda: not editor.vm.dirty and editor.vm.sheet_id is not None)

    from tests.ui.conftest import query_db

    rows = query_db(db_path, "SELECT name, pages FROM character_sheets")
    assert len(rows) == 1
    name, pages = rows[0]
    assert name == "Лист 1"
    parsed = json.loads(pages)
    assert len(parsed) == 1
    assert parsed[0]["fields"][0]["label"] == "Имя"


# ── 7.1: list dialog actions ───────────────────────────────────────────────


async def test_create_conflict_shows_warning(app, wait_for, dialog_input, message_boxes):
    application, window = app
    sheet_list = await open_sheet_list(window, wait_for)
    await create_sheet(sheet_list, wait_for, dialog_input, "Единственный")

    dialog_input["answer"] = ("Единственный", True)
    sheet_list._create_btn.click()
    await wait_for(lambda: any(kind == "warning" for kind, _t, _m in message_boxes))
    assert list_names(sheet_list) == ["Единственный"]


async def test_json_export_selected_sheet(app, wait_for, file_dialogs, tmp_path):
    application, window = app
    await application._sheet_service.create(SheetTemplate(
        name="Экспортный",
        orientation=SheetOrientation.LANDSCAPE,
        pages=[SheetPage(
            name="Стр 1",
            fields=[SheetField(
                id="aabbcc",
                type=FieldType.NUMBER,
                x=10.0, y=10.0, w=50.0, h=20.0,
                label="Хиты",
                min_value=1, max_value=30,
            )],
        )],
    ))
    sheet_list = await open_sheet_list(window, wait_for)
    await wait_for(lambda: sheet_list._list.count() == 1)
    sheet_list._list.setCurrentRow(0)

    dest = tmp_path / "sheet.json"
    file_dialogs["save"] = str(dest)
    sheet_list._export_btn.click()
    await wait_for(lambda: dest.exists())
    payload = json.loads(dest.read_text(encoding="utf-8"))
    assert payload["format"] == "nri-charsheet"
    assert payload["version"] == 1
    sheet_payload = payload["sheets"][0]
    assert sheet_payload["name"] == "Экспортный"
    field_payload = sheet_payload["pages"][0]["fields"][0]
    assert field_payload["id"] == "aabbcc"
    assert field_payload["type"] == "number"


async def test_import_json_conflict_suffix_and_bad_file(app, wait_for, file_dialogs, tmp_path, message_boxes):
    application, window = app
    sheet_service = application._sheet_service

    # A template that the imported project will clash with.
    await sheet_service.create(SheetTemplate(
        name="Лист 1",
        orientation=SheetOrientation.LANDSCAPE,
        pages=[SheetPage(name="Стр 1", fields=[SheetField(
            id="stable123", type=FieldType.SHORT_TEXT, x=5.0, y=5.0, w=90.0, h=20.0,
        )])],
    ))

    project_file = tmp_path / "project.json"
    project_file.write_text(CharacterSheetService.export_project([SheetTemplate(
        name="Лист 1",
        orientation=SheetOrientation.LANDSCAPE,
        pages=[SheetPage(name="Стр 1", fields=[SheetField(
            id="stable123", type=FieldType.SHORT_TEXT, x=5.0, y=5.0, w=90.0, h=20.0,
        )])],
    )]), encoding="utf-8")

    sheet_list = await open_sheet_list(window, wait_for)
    await wait_for(lambda: sheet_list._list.count() == 1)

    file_dialogs["open"] = str(project_file)
    sheet_list._import_btn.click()
    await wait_for(lambda: sheet_list._list.count() == 2)
    assert "Лист 1 (копия)" in list_names(sheet_list)  # clash → suffixed, original untouched
    assert "Лист 1" in list_names(sheet_list)

    # imported sheet kept its stable field id
    from tests.ui.conftest import query_db

    rows = query_db(application._db_path, "SELECT name, pages FROM character_sheets")
    copy_rows = [pages for name, pages in rows if name == "Лист 1 (копия)"]
    assert json.loads(copy_rows[0])[0]["fields"][0]["id"] == "stable123"

    # a corrupt file is rejected with the reason, nothing created
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("definitely not json", encoding="utf-8")
    file_dialogs["open"] = str(bad_file)
    sheet_list._import_btn.click()
    await wait_for(
        lambda: any(
            kind == "warning" and "JSON" in text
            for kind, _t, text in message_boxes
        )
    )
    assert len(list_names(sheet_list)) == 2


async def test_delete_with_confirmation(app, wait_for, dialog_input, monkeypatch):
    application, window = app
    sheet_service = application._sheet_service
    await sheet_service.create(SheetTemplate(
        name="Удаляемый",
        orientation=SheetOrientation.LANDSCAPE,
        pages=[SheetPage(name="Стр 1")],
    ))
    sheet_list = await open_sheet_list(window, wait_for)
    await wait_for(lambda: sheet_list._list.count() == 1)
    sheet_list._list.setCurrentRow(0)

    # declined: the default button of the stubbed question is returned
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No),
    )
    sheet_list._delete_btn.click()
    await spin()
    assert list_names(sheet_list) == ["Удаляемый"]

    # confirmed: the row disappears
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    sheet_list._delete_btn.click()
    await wait_for(lambda: sheet_list._list.count() == 0)


# ── 7.2: closing the editor on a game switch ───────────────────────────────


def _make_second_game(tmp_games_dir, name: str) -> None:
    game_dir = tmp_games_dir / name
    game_dir.mkdir()
    (game_dir / "images").mkdir()
    (game_dir / "game.db").touch()


async def _open_dirty_editor(window, wait_for, dialog_input) -> CharacterSheetEditorDialog:
    sheet_list = await open_sheet_list(window, wait_for)
    await create_sheet(sheet_list, wait_for, dialog_input, "Лист")
    sheet_list._list.setCurrentRow(0)
    sheet_list._open_btn.click()
    await wait_for(lambda: any(d.isVisible() for d in window.findChildren(CharacterSheetEditorDialog)))
    editor = next(d for d in window.findChildren(CharacterSheetEditorDialog) if d.isVisible())
    await wait_for(lambda: editor.vm.is_ready)
    editor.vm.add_field(FieldType.SHORT_TEXT, 0, 40.0, 40.0, label="Не сохранено")
    assert editor.vm.dirty
    return editor


def _select_game(launcher: GameLauncherDialog, name: str) -> None:
    from tests.ui import helpers

    item = next(
        launcher.list_widget.item(i)
        for i in range(launcher.list_widget.count())
        if name in launcher.list_widget.item(i).text()
    )
    helpers.select_item(launcher.list_widget, item)
    launcher.open_button.click()
    assert launcher.selected_path


async def test_switch_game_saves_dirty_editor_then_switches(app, tmp_games_dir, wait_for, dialog_input, monkeypatch):
    application, window = app
    old_db_path = application._db_path

    editor = await _open_dirty_editor(window, wait_for, dialog_input)
    _make_second_game(tmp_games_dir, "beta")

    # «Сменить игру»: the dirty editor is asked first — the user saves.
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    window.switch_game_action.trigger()
    await wait_for(lambda: not editor.isVisible())
    await wait_for(lambda: bool(window.findChildren(GameLauncherDialog)))
    launcher = next(d for d in window.findChildren(GameLauncherDialog) if d.isVisible())

    _select_game(launcher, "beta")
    await wait_for(lambda: "beta" in application._window.windowTitle())
    assert application._window is not window

    from tests.ui.conftest import query_db

    rows = query_db(old_db_path, "SELECT name, pages FROM character_sheets")
    assert len(rows) == 1
    assert json.loads(rows[0][1])[0]["fields"][0]["label"] == "Не сохранено"


async def test_switch_game_aborts_when_save_fails(app, wait_for, dialog_input, monkeypatch):
    """Yes to save, but the save fails → the switch is aborted, nothing lost."""
    application, window = app
    editor = await _open_dirty_editor(window, wait_for, dialog_input)

    async def failed_save():
        return False

    editor.vm.save = failed_save
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    window.switch_game_action.trigger()
    await spin(30)
    assert not (window.findChildren(GameLauncherDialog))
    assert editor.isVisible()
    assert editor.vm.dirty


async def test_switch_game_aborts_when_user_cancels(app, wait_for, dialog_input, message_boxes):
    application, window = app
    editor = await _open_dirty_editor(window, wait_for, dialog_input)

    # the message_boxes stub returns the default button (Cancel) → the switch
    # must be aborted and the editor must stay open
    window.switch_game_action.trigger()
    await spin(30)
    assert any(
        kind == "question" and title == "Смена игры"
        for kind, title, _text in message_boxes
    )
    assert editor.isVisible()
    assert not (window.findChildren(GameLauncherDialog))
