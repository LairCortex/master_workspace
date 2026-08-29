"""Wiring of the character-sheet windows into the app (tasks 7.1/7.2).

Full Application on the temporary game DB: menu → list, list → editor,
single-editor rule with dirty-prompt, game switch with dirty-prompt,
rename propagation from the list to the open editor.
"""
from __future__ import annotations

import asyncio
import sqlite3

from PySide6.QtWidgets import QApplication, QMessageBox

from app.domain.entities.character_sheet import EMPTY_PAGES_JSON
from app.domain.enums.field_type import FieldType
from app.presentation.views.character_sheet.editor_dialog import (
    CharacterSheetEditorDialog,
)
from app.presentation.views.character_sheet.fill_dialog import CharacterSheetFillDialog
from app.presentation.views.character_sheet.list_dialog import CharacterSheetListDialog
from app.presentation.views.game_launcher_dialog import GameLauncherDialog

from tests.ui import helpers
from tests.ui.conftest import query_db


# ── helpers ─────────────────────────────────────────────────────────────────

def _editors(qtop) -> list[CharacterSheetEditorDialog]:
    """Visible editor dialogs (a closed QDialog stays in topLevelWidgets, hidden)."""
    return [w for w in qtop if isinstance(w, CharacterSheetEditorDialog) and w.isVisible()]


def _visible_list_dialogs(qtop) -> list[CharacterSheetListDialog]:
    return [w for w in qtop if isinstance(w, CharacterSheetListDialog) and w.isVisible()]


async def open_list(app, wait_for) -> CharacterSheetListDialog:
    application, window = app
    window.char_sheets_action.trigger()
    await wait_for(lambda: application._sheet_list_dialog is not None)
    return application._sheet_list_dialog


def create_via_list(list_dlg: CharacterSheetListDialog, dialog_input, name: str) -> None:
    dialog_input["answer"] = (name, True)
    list_dlg.create_button.click()


def _editor_name(application) -> str:
    editor = application._sheet_editor
    if editor is None or editor.view_model.template is None:
        return ""
    return editor.view_model.template.name


async def wait_editor(app, wait_for, name: str) -> CharacterSheetEditorDialog:
    application, _window = app
    await wait_for(lambda: _editor_name(application) == name)
    return application._sheet_editor


def make_dirty(editor: CharacterSheetEditorDialog) -> str:
    fid = editor.view_model.place(FieldType.LABEL, 30.0, 30.0)
    assert editor.view_model.dirty
    return fid


def question_yes(monkeypatch) -> list[list[str]]:
    """Replace the QMessageBox.question stub with an affirmative one."""
    calls: list[list[str]] = []

    def fake_yes(parent, title, text, *args, **kwargs):
        calls.append([title, text])
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_yes))
    return calls


def question_no(monkeypatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_no(parent, title, text, *args, **kwargs):
        calls.append([title, text])
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_no))
    return calls


async def make_second_game(tmp_games_dir) -> str:
    path_b = tmp_games_dir / "beta" / "game.db"
    path_b.parent.mkdir(parents=True, exist_ok=True)
    path_b.touch()
    return str(path_b)


# ── 7.1: menu ───────────────────────────────────────────────────────────────

async def test_menu_action_exists_and_opens_list(app, wait_for):
    """«Чар-листы» menu action exists, opens the list, retrigger raises the same dialog."""
    application, window = app
    assert window.char_sheets_action.text() == "Чар-листы…"

    window.char_sheets_action.trigger()
    await wait_for(lambda: application._sheet_list_dialog is not None)
    list_dlg = application._sheet_list_dialog
    assert list_dlg.isVisible()

    assert len(_visible_list_dialogs(QApplication.instance().topLevelWidgets())) == 1

    # Second trigger — the same dialog, not a second one.
    window.char_sheets_action.trigger()
    await wait_for(lambda: True, timeout_s=0.1)
    assert application._sheet_list_dialog is list_dlg
    assert len(_visible_list_dialogs(QApplication.instance().topLevelWidgets())) == 1


# ── create → clean editor ──────────────────────────────────────────────────

async def test_create_via_list_opens_clean_editor(app, dialog_input, wait_for):
    application, _window = app

    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Иван")
    editor = await wait_editor(app, wait_for, "Иван")

    template = editor.view_model.template
    assert template.name == "Иван"
    assert len(template.pages) == 1
    assert template.pages[0].fields == []
    assert not editor.view_model.dirty
    assert editor.windowTitle() == "Иван"

    rows = query_db(application._db_path, "SELECT name, pages FROM character_sheets")
    assert [r[0] for r in rows] == ["Иван"]
    assert rows[0][1] == EMPTY_PAGES_JSON


# ── one editor: dirty prompt on open/create of another ─────────────────────

async def test_opening_second_sheet_with_dirty_editor_is_rejected(app, dialog_input, message_boxes, wait_for, qtbot):
    application, _window = app
    list_dlg = await open_list(app, wait_for)

    create_via_list(list_dlg, dialog_input, "A")
    editor_a = await wait_editor(app, wait_for, "A")
    make_dirty(editor_a)

    # message_boxes stub answers question with the default button (No).
    create_via_list(list_dlg, dialog_input, "B")
    await wait_for(lambda: len(message_boxes) >= 1)
    qtbot.wait(50)  # give the flow time to (incorrectly) proceed

    assert application._sheet_editor is editor_a
    assert editor_a.view_model.dirty
    assert any(kind == "question" for kind, _t, _x in message_boxes)
    qtop = QApplication.instance().topLevelWidgets()
    assert len(_editors(qtop)) == 1


async def test_opening_second_sheet_with_dirty_editor_confirm_closes_without_saving(
    app, dialog_input, wait_for, monkeypatch
):
    application, _window = app
    calls = question_yes(monkeypatch)
    list_dlg = await open_list(app, wait_for)

    create_via_list(list_dlg, dialog_input, "A")
    editor_a = await wait_editor(app, wait_for, "A")
    fid = make_dirty(editor_a)
    editor_a.view_model.set_content(fid, "черновик")

    create_via_list(list_dlg, dialog_input, "B")
    editor_b = await wait_editor(app, wait_for, "B")

    assert editor_b is not editor_a
    assert not editor_b.view_model.dirty
    # A is closed without update_pages (its C++ object may already be deleted)
    assert application._sheet_editor is not editor_a
    assert len(_editors(QApplication.instance().topLevelWidgets())) == 1
    assert len(calls) == 1  # exactly one dirty prompt

    rows = query_db(application._db_path, "SELECT pages FROM character_sheets WHERE name = 'A'")
    assert rows == [(EMPTY_PAGES_JSON,)]  # draft lost, DB unchanged


# ── game switch with a dirty editor ─────────────────────────────────────────

async def test_switch_game_with_dirty_editor_reject_keeps_game(app, dialog_input, tmp_games_dir, wait_for, monkeypatch):
    application, window = app
    calls = question_no(monkeypatch)

    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "A")
    editor_a = await wait_editor(app, wait_for, "A")
    make_dirty(editor_a)

    path_b = await make_second_game(tmp_games_dir)

    window.switch_game_action.trigger()
    await wait_for(lambda: bool(window.findChildren(GameLauncherDialog)))
    launcher = window.findChildren(GameLauncherDialog)[0]
    beta = next(
        launcher.list_widget.item(i)
        for i in range(launcher.list_widget.count())
        if "beta" in launcher.list_widget.item(i).text()
    )
    helpers.select_item(launcher.list_widget, beta)
    launcher.open_button.click()
    assert launcher.selected_path == path_b

    await wait_for(lambda: len(calls) >= 1)  # dirty prompt shown and answered No

    assert application._window is window  # not switched
    assert application._sheet_editor is editor_a  # editor survived
    assert editor_a.view_model.dirty
    assert "Несохранённые" in calls[0][0]


async def test_switch_game_with_dirty_editor_confirm_closes_without_saving(
    app, dialog_input, tmp_games_dir, wait_for, monkeypatch
):
    application, window = app
    old_db = application._db_path
    calls = question_yes(monkeypatch)

    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "A")
    editor_a = await wait_editor(app, wait_for, "A")
    fid = make_dirty(editor_a)
    editor_a.view_model.set_content(fid, "черновик")

    await make_second_game(tmp_games_dir)

    window.switch_game_action.trigger()
    await wait_for(lambda: bool(window.findChildren(GameLauncherDialog)))
    launcher = window.findChildren(GameLauncherDialog)[0]
    beta = next(
        launcher.list_widget.item(i)
        for i in range(launcher.list_widget.count())
        if "beta" in launcher.list_widget.item(i).text()
    )
    helpers.select_item(launcher.list_widget, beta)
    launcher.open_button.click()

    await wait_for(lambda: application._window is not window and "beta" in application._window.windowTitle())

    assert not list_dlg.isVisible()  # list closed
    assert application._sheet_editor is None  # editor_a closed and forgotten
    assert len(_editors(QApplication.instance().topLevelWidgets())) == 0  # no editor visible
    assert application._sheet_list_dialog is None
    assert len(calls) == 1

    rows = query_db(old_db, "SELECT pages FROM character_sheets WHERE name = 'A'")
    assert rows == [(EMPTY_PAGES_JSON,)]  # draft lost, DB unchanged


# ── rename from the list reaches the open editor ────────────────────────────

async def test_rename_in_list_updates_open_editor_title(app, dialog_input, wait_for):
    application, _window = app
    list_dlg = await open_list(app, wait_for)

    create_via_list(list_dlg, dialog_input, "A")
    editor_a = await wait_editor(app, wait_for, "A")
    make_dirty(editor_a)

    dialog_input["answer"] = ("Александр", True)
    list_dlg.rename_button.click()
    await wait_for(lambda: editor_a.windowTitle() == "Александр")

    assert editor_a.view_model.dirty  # a rename is not a layout edit
    rows = query_db(application._db_path, "SELECT name FROM character_sheets")
    assert [r[0] for r in rows] == ["Александр"]


# ── corrupt template: rejected at open, no editor left around ───────────────

async def test_corrupt_template_not_opened(app, message_boxes, wait_for):
    application, window = app
    # a row with malformed pages JSON (written outside the app) must not open
    conn = sqlite3.connect(application._db_path)
    conn.execute(
        "INSERT INTO character_sheets (name, schema_version, orientation, pages, "
        "created_at, updated_at) VALUES ('Повреждённый', 1, 'portrait', 'not json', "
        "datetime('now'), datetime('now'))"
    )
    conn.commit()
    conn.close()

    list_dlg = await open_list(app, wait_for)
    await wait_for(lambda: list_dlg.list_widget.count() == 1)
    list_dlg.list_widget.setCurrentRow(0)
    list_dlg.open_button.click()

    await wait_for(lambda: any(k == "critical" for k, _t, _x in message_boxes))
    assert application._sheet_editor is None, "a corrupt sheet must not be opened"
    _k, _t, text = next((k, t, x) for k, t, x in message_boxes if k == "critical")
    assert "поврежд" in text  # RU user-facing message


# ── editor closed mid-load must not leave a stale "open" mark in the list ───

async def test_editor_closed_during_load_does_not_mark_sheet_open(
    app, dialog_input, wait_for, monkeypatch, qtbot
):
    application, _window = app
    real_load = CharacterSheetEditorDialog.load

    async def close_while_loading(self):
        await asyncio.sleep(0.2)
        self.close()
        await real_load(self)

    monkeypatch.setattr(CharacterSheetEditorDialog, "load", close_while_loading)

    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "A")
    await wait_for(lambda: list_dlg.list_widget.count() == 1)
    # let the whole (slow) open flow settle
    for _ in range(60):
        await asyncio.sleep(0.02)
        qtbot.wait(1)

    assert application._sheet_editor is None
    assert not any(
        isinstance(w, CharacterSheetEditorDialog) and w.isVisible()
        for w in QApplication.instance().topLevelWidgets()
    )
    # the list must NOT keep treating the closed sheet as open (delete allowed)
    list_dlg.list_widget.setCurrentRow(0)
    assert list_dlg.delete_button.isEnabled()
    assert list_dlg._open_sheet_id is None


# ── a closed editor window is actually destroyed, not just hidden ───────────

async def test_forgotten_editor_window_is_destroyed(app, dialog_input, wait_for, qtbot):
    application, _window = app
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "A")
    editor = await wait_editor(app, wait_for, "A")
    assert editor.view_model.template is not None  # fully loaded

    editor.close()  # clean close, no prompt
    await wait_for(lambda: application._sheet_editor is None)
    qtbot.wait(100)  # process the queued deleteLater

    qtop = QApplication.instance().topLevelWidgets()
    assert [w for w in qtop if isinstance(w, CharacterSheetEditorDialog)] == [], (
        "closed editors must not linger as hidden top-level widgets"
    )


# ── templates are scoped to a game: switching games changes the list ────────

async def test_games_have_their_own_sheet_lists(
    app, dialog_input, tmp_games_dir, wait_for, qtbot
):
    application, window = app
    old_db = application._db_path

    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "ТолькоА")
    editor = await wait_editor(app, wait_for, "ТолькоА")
    editor.close()
    await wait_for(lambda: application._sheet_editor is None)

    path_b = await make_second_game(tmp_games_dir)
    window.switch_game_action.trigger()
    await wait_for(lambda: bool(window.findChildren(GameLauncherDialog)))
    launcher = window.findChildren(GameLauncherDialog)[0]
    beta = next(
        launcher.list_widget.item(i)
        for i in range(launcher.list_widget.count())
        if "beta" in launcher.list_widget.item(i).text()
    )
    helpers.select_item(launcher.list_widget, beta)
    launcher.open_button.click()
    assert launcher.selected_path == path_b

    await wait_for(
        lambda: application._window is not window
        and "beta" in application._window.windowTitle()
    )
    new_window = application._window

    new_window.char_sheets_action.trigger()
    await wait_for(lambda: application._sheet_list_dialog is not None)
    list_b = application._sheet_list_dialog
    # let the list refresh land (an empty list before refresh would pass vacuously)
    for _ in range(30):
        await asyncio.sleep(0.02)
        qtbot.wait(1)
    assert list_b is not list_dlg
    assert list_b.list_widget.count() == 0, "game B has none of game A templates"
    assert query_db(old_db, "SELECT name FROM character_sheets") == [("ТолькоА",)]

# ── list refresh on open touches the session under the app lock ────────────


async def test_list_refresh_on_open_runs_under_the_session_lock(
    app, wait_for, monkeypatch
):
    """Regression (review #12): the refresh performed when the list is opened
    queries the shared AsyncSession, so it must run while the application's
    session lock is held.

    ``list_dialog.refresh()`` deliberately does NOT lock itself — its caller
    provides the lock. The application-level caller ``_on_char_sheets``
    satisfies that by spawning ``_sheet_list_refresh`` through
    ``_wiring._spawn``, which holds the lock for the whole task; the plain
    ``await dialog.refresh()`` inside it inherits the lock by design.
    Do not "fix" it by wrapping ``refresh()`` in ``run_locked`` there: the
    ``asyncio.Lock`` is not reentrant, so the inner task would wait on the
    outer one forever (a hang, not an error).
    """
    application, window = app

    orig_list_sheets = application._sheet_service.list_sheets
    lock_states: list[bool] = []

    # A function set on the instance attribute is NOT bound (no self passed);
    # ``orig_list_sheets`` is already bound, so it is called bare below.
    async def list_sheets_spy(*args, **kwargs):
        lock_states.append(application._wiring._session_lock.locked())
        return await orig_list_sheets(*args, **kwargs)

    monkeypatch.setattr(
        application._sheet_service, "list_sheets", list_sheets_spy
    )

    window.char_sheets_action.trigger()
    await wait_for(lambda: len(lock_states) >= 1)

    assert lock_states, "list_sheets was not called when the list opened"
    assert all(lock_states), (
        f"the list refresh touched the session without the lock: {lock_states}"
    )


# ── DI: the sheet service owns the game ImageStore (design D6) ──────────────


async def test_sheet_service_wired_with_game_image_store(app, wait_for):
    """The sheet service must hold the game's ImageStore: only then are the
    sheet-page image references (pages JSON) GC'd after a save/delete commits
    (design D6). Without it, cleared/replaced/deleted sheet images are never
    freed in the running app."""
    application, _window = app
    assert application._image_store is not None
    assert application._sheet_service is not None
    assert application._sheet_service._image_store is application._image_store
    assert application._instance_service is not None
    assert application._instance_service._image_store is application._image_store
    assert application._sheet_service._instance_repo is not None


# ── B: Design + Fill windows (task 7.3) ─────────────────────────────────────

def _fills(qtop) -> list[CharacterSheetFillDialog]:
    return [w for w in qtop if isinstance(w, CharacterSheetFillDialog) and w.isVisible()]


def _fill_name(application) -> str:
    fill = application._sheet_fill
    if fill is None or fill.view_model.template is None:
        return ""
    return fill.view_model.name


async def wait_fill(app, wait_for, name: str) -> CharacterSheetFillDialog:
    application, _window = app
    await wait_for(lambda: _fill_name(application) == name)
    return application._sheet_fill


def create_instance_via_list(
    list_dlg: CharacterSheetListDialog,
    dialog_item,
    dialog_input,
    template_name: str,
    instance_name: str,
) -> None:
    list_dlg.tabs.setCurrentIndex(1)
    dialog_item["answer"] = (template_name, True)
    dialog_input["answer"] = (instance_name, True)
    list_dlg.create_button.click()


async def test_design_and_fill_same_template_open_together(
    app, dialog_input, dialog_item, wait_for,
):
    application, _window = app
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Макет")
    editor = await wait_editor(app, wait_for, "Макет")
    editor.view_model.place(FieldType.TEXT, 30.0, 30.0)
    editor.save_button.click()
    await wait_for(lambda: not editor.view_model.dirty)

    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Макет", "Лист")
    fill = await wait_fill(app, wait_for, "Лист")

    assert editor.isVisible()
    assert fill.isVisible()
    assert application._sheet_editor is editor
    assert application._sheet_fill is fill
    qtop = QApplication.instance().topLevelWidgets()
    assert len(_editors(qtop)) == 1
    assert len(_fills(qtop)) == 1


async def test_reopening_same_instance_raises_existing_fill(
    app, dialog_input, dialog_item, wait_for,
):
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Макет")
    await wait_editor(app, wait_for, "Макет")
    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Макет", "Лист")
    fill = await wait_fill(app, wait_for, "Лист")

    list_dlg.tabs.setCurrentIndex(1)
    list_dlg.instance_list.setCurrentRow(0)
    list_dlg.open_button.click()
    await wait_for(lambda: True, timeout_s=0.2)

    application, _window = app
    assert application._sheet_fill is fill
    assert fill.isVisible()
    assert len(_fills(QApplication.instance().topLevelWidgets())) == 1


async def test_second_fill_dirty_prompt_rejected(
    app, dialog_input, dialog_item, message_boxes, wait_for, qtbot,
):
    application, _window = app
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Макет")
    editor = await wait_editor(app, wait_for, "Макет")
    fid = editor.view_model.place(FieldType.TEXT, 30.0, 30.0)
    editor.save_button.click()
    await wait_for(lambda: not editor.view_model.dirty)

    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Макет", "Лист1")
    fill1 = await wait_fill(app, wait_for, "Лист1")
    fill1.view_model.set_text(fid, "черновик")
    assert fill1.view_model.dirty

    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Макет", "Лист2")
    await wait_for(lambda: len(message_boxes) >= 1)
    qtbot.wait(50)

    assert application._sheet_fill is fill1
    assert fill1.view_model.dirty
    assert any(kind == "question" for kind, _t, _x in message_boxes)
    assert len(_fills(QApplication.instance().topLevelWidgets())) == 1


async def test_second_fill_dirty_prompt_confirm_opens_other(
    app, dialog_input, dialog_item, wait_for, monkeypatch,
):
    application, _window = app
    calls = question_yes(monkeypatch)
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Макет")
    editor = await wait_editor(app, wait_for, "Макет")
    fid = editor.view_model.place(FieldType.TEXT, 30.0, 30.0)
    editor.save_button.click()
    await wait_for(lambda: not editor.view_model.dirty)

    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Макет", "Лист1")
    fill1 = await wait_fill(app, wait_for, "Лист1")
    fill1.view_model.set_text(fid, "черновик")

    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Макет", "Лист2")
    fill2 = await wait_fill(app, wait_for, "Лист2")

    assert fill2 is not fill1
    assert application._sheet_fill is fill2
    assert not fill2.view_model.dirty
    assert len(_fills(QApplication.instance().topLevelWidgets())) == 1
    assert len(calls) == 1
    assert editor.isVisible()


async def test_save_design_reloads_fill_layout_dirty_does_not_stream(
    app, dialog_input, dialog_item, wait_for,
):
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Макет")
    editor = await wait_editor(app, wait_for, "Макет")
    editor.save_button.click()
    await wait_for(lambda: not editor.view_model.dirty)

    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Макет", "Лист")
    fill = await wait_fill(app, wait_for, "Лист")

    fid = editor.view_model.place(FieldType.LABEL, 40.0, 40.0)
    assert editor.view_model.dirty
    assert fill.view_model.template.get_field(fid) is None

    editor.save_button.click()
    await wait_for(lambda: fill.view_model.template.get_field(fid) is not None)
    assert not editor.view_model.dirty


async def test_character_card_opens_bound_fill(
    app, dialog_input, dialog_item, wait_for,
):
    from datetime import date

    from app.presentation.views.entity_card_dialog import EntityCardDialog

    application, window = app
    char = await application._entity_services["character"].create_entity(
        name="Герой",
        characteristics="",
        backstory="",
        start_date=date(1300, 1, 1),
        end_date=None,
    )
    await application._session.commit()

    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Макет")
    await wait_editor(app, wait_for, "Макет")
    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Макет", "Лист")
    fill = await wait_fill(app, wait_for, "Лист")
    await application._instance_service.bind_character(fill.view_model.instance_id, char.id)
    fill.force_close()
    await wait_for(lambda: application._sheet_fill is None)

    window.detail_panel.entity_clicked.emit("character", char.id)
    await wait_for(
        lambda: any(
            isinstance(w, EntityCardDialog) and w.isVisible()
            for w in window.findChildren(EntityCardDialog)
        )
    )
    card = next(
        w for w in window.findChildren(EntityCardDialog)
        if w.isVisible()
    )
    assert card.open_sheet_button.isVisible()
    card.open_sheet_button.click()
    fill2 = await wait_fill(app, wait_for, "Лист")
    assert fill2.view_model.character_id == char.id


async def test_switch_game_with_dirty_fill_reject_keeps_game(
    app, dialog_input, dialog_item, tmp_games_dir, wait_for, monkeypatch,
):
    application, window = app
    calls = question_no(monkeypatch)
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Макет")
    editor = await wait_editor(app, wait_for, "Макет")
    fid = editor.view_model.place(FieldType.TEXT, 30.0, 30.0)
    editor.save_button.click()
    await wait_for(lambda: not editor.view_model.dirty)

    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Макет", "Лист")
    fill = await wait_fill(app, wait_for, "Лист")
    fill.view_model.set_text(fid, "черновик")
    assert fill.view_model.dirty

    await make_second_game(tmp_games_dir)
    window.switch_game_action.trigger()
    await wait_for(lambda: bool(window.findChildren(GameLauncherDialog)))
    launcher = window.findChildren(GameLauncherDialog)[0]
    beta = next(
        launcher.list_widget.item(i)
        for i in range(launcher.list_widget.count())
        if "beta" in launcher.list_widget.item(i).text()
    )
    helpers.select_item(launcher.list_widget, beta)
    launcher.open_button.click()
    await wait_for(lambda: len(calls) >= 1)

    assert application._window is window
    assert application._sheet_fill is fill
    assert fill.view_model.dirty
    assert "Несохранённые" in calls[0][0]


# ── C: «Создать из пресета…» over a dirty Design of another template ────────


async def _open_preset_dialog(list_dlg: CharacterSheetListDialog, wait_for):
    list_dlg.preset_button.click()
    await wait_for(
        lambda: list_dlg.preset_dialog is not None
        and list_dlg.preset_dialog.isVisible()
    )
    return list_dlg.preset_dialog


async def test_preset_over_dirty_design_reject_keeps_editor(
    app, dialog_input, message_boxes, wait_for, qtbot,
):
    """Spec «сначала спросить»: the snapshot is created, but its Design is
    opened only after the dirty editor is closed (here: the user rejects)."""
    application, _window = app
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "А")
    editor_a = await wait_editor(app, wait_for, "А")
    make_dirty(editor_a)

    preset = await _open_preset_dialog(list_dlg, wait_for)
    preset.ok_button.click()  # «Fate Core» (the default row)

    # message_boxes stub answers the dirty prompt with the default button (No).
    await wait_for(lambda: any(k == "question" for k, _t, _x in message_boxes))
    qtbot.wait(50)  # give the flow time to (incorrectly) proceed

    assert application._sheet_editor is editor_a  # A is still the editor
    assert editor_a.view_model.dirty
    qtop = QApplication.instance().topLevelWidgets()
    assert len(_editors(qtop)) == 1
    # the snapshot itself is a regular template now; the list shows both
    # (name-sorted: Latin «F…» before Cyrillic «А…»)
    names = [
        list_dlg.list_widget.item(i).text()
        for i in range(list_dlg.list_widget.count())
    ]
    assert names == ["Fate Core", "А"]


async def test_preset_over_dirty_design_confirm_closes_without_saving(
    app, dialog_input, wait_for, monkeypatch,
):
    application, _window = app
    calls = question_yes(monkeypatch)
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "А")
    editor_a = await wait_editor(app, wait_for, "А")
    fid = make_dirty(editor_a)
    editor_a.view_model.set_content(fid, "черновик")

    preset = await _open_preset_dialog(list_dlg, wait_for)
    preset.ok_button.click()  # «Fate Core» (the default row)
    editor_fc = await wait_editor(app, wait_for, "Fate Core")

    assert editor_fc is not editor_a
    assert not editor_fc.view_model.dirty  # the snapshot opens clean
    assert application._sheet_editor is editor_fc
    assert len(_editors(QApplication.instance().topLevelWidgets())) == 1
    assert len(calls) == 1  # exactly one dirty prompt
    rows = query_db(application._db_path, "SELECT pages FROM character_sheets WHERE name = 'А'")
    assert rows == [(EMPTY_PAGES_JSON,)]  # draft lost, DB unchanged
