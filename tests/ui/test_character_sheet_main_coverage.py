"""Edge paths of the character-sheet application glue (Application + wiring).

Guard branches and failure paths that the scenario-level E2E set never
reaches: the list refresh against a replaced/loaded state, the clean-editor
swap, load failures of the editor and fill windows, and the card refresh
that keeps «Открыть чар-лист» in sync with the instance bindings.
"""
from __future__ import annotations

from datetime import date

from app.application.services.character_sheet_instance_service import (
    CharacterSheetInstanceError,
)
from app.presentation.views.character_sheet.editor_dialog import (
    CharacterSheetEditorDialog,
)
from app.presentation.views.character_sheet.fill_dialog import CharacterSheetFillDialog
from app.presentation.views.entity_card_dialog import EntityCardDialog

from tests.ui import helpers
from tests.ui.test_char_sheets_wiring import (
    create_instance_via_list,
    create_via_list,
    open_list,
    wait_editor,
    wait_fill,
)


async def _make_character(application, name: str = "Герой"):
    char = await application._entity_services["character"].create_entity(
        name=name,
        characteristics="",
        backstory="",
        start_date=date(1300, 1, 1),
        end_date=None,
    )
    await application._session.commit()
    return char


async def _open_character_card(window, wait_for, char_id: int) -> EntityCardDialog:
    window.detail_panel.entity_clicked.emit("character", char_id)
    await wait_for(
        lambda: any(w.isVisible() for w in window.findChildren(EntityCardDialog))
    )
    return next(w for w in window.findChildren(EntityCardDialog) if w.isVisible())


async def _make_bound_instance(app, dialog_input, dialog_item, wait_for, char_id: int) -> int:
    """Template + instance bound to ``char_id``; the Fill window is closed again."""
    application, _window = app
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Макет")
    await wait_editor(app, wait_for, "Макет")
    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Макет", "Лист")
    fill = await wait_fill(app, wait_for, "Лист")
    instance_id = fill.view_model.instance_id
    await application._instance_service.bind_character(instance_id, char_id)
    fill.force_close()
    await wait_for(lambda: application._sheet_fill is None)
    return instance_id


# ── list refresh ────────────────────────────────────────────────────────────

async def test_list_refresh_marks_open_editor_and_fill(
    app, dialog_input, dialog_item, wait_for,
):
    """Reopening the list while both windows are open marks both rows as busy."""
    _application, window = app
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Макет")
    editor = await wait_editor(app, wait_for, "Макет")
    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Макет", "Лист")
    fill = await wait_fill(app, wait_for, "Лист")

    list_dlg.set_open_sheet_id(None)
    list_dlg.set_open_instance_id(None)

    window.char_sheets_action.trigger()
    await helpers.wait_until_settled()

    assert list_dlg._open_sheet_id == editor.view_model.sheet_id
    assert list_dlg._open_instance_id == fill.view_model.instance_id


async def test_list_refresh_aborts_when_dialog_was_replaced(app, wait_for, monkeypatch):
    """A refresh whose dialog is no longer the current one must not mark it."""
    application, _window = app
    list_dlg = await open_list(app, wait_for)
    marks: list[int | None] = []

    async def refresh_and_drop():
        application._sheet_list_dialog = None

    monkeypatch.setattr(list_dlg, "refresh", refresh_and_drop)
    monkeypatch.setattr(list_dlg, "set_open_sheet_id", marks.append)

    await application._sheet_list_refresh()

    assert marks == []
    application._sheet_list_dialog = list_dlg


# ── editor: clean swap and load failure ─────────────────────────────────────

async def test_opening_second_sheet_over_clean_editor_closes_it(
    app, dialog_input, message_boxes, wait_for,
):
    """A clean editor is replaced silently — no dirty prompt (D6)."""
    application, _window = app
    list_dlg = await open_list(app, wait_for)

    create_via_list(list_dlg, dialog_input, "A")
    editor_a = await wait_editor(app, wait_for, "A")
    assert not editor_a.view_model.dirty

    create_via_list(list_dlg, dialog_input, "B")
    editor_b = await wait_editor(app, wait_for, "B")

    assert editor_b is not editor_a
    assert application._sheet_editor is editor_b
    assert not any(kind == "question" for kind, _t, _x in message_boxes)


async def test_editor_load_crash_drops_the_editor(
    app, dialog_input, message_boxes, wait_for, monkeypatch,
):
    """A non-domain failure of ``load`` (session gone) drops the window quietly."""
    application, window = app
    list_dlg = await open_list(app, wait_for)

    async def boom(self):
        raise RuntimeError("session gone")

    monkeypatch.setattr(CharacterSheetEditorDialog, "load", boom)

    create_via_list(list_dlg, dialog_input, "A")
    await helpers.wait_until_settled()

    assert application._sheet_editor is None
    assert not [
        w for w in window.findChildren(CharacterSheetEditorDialog) if w.isVisible()
    ]
    assert not any(kind == "critical" for kind, _t, _x in message_boxes)


# ── fill: load failures and the not-yet-loaded window ───────────────────────

async def test_fill_load_domain_error_reports_and_drops(
    app, dialog_input, dialog_item, message_boxes, wait_for, monkeypatch,
):
    application, _window = app
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Макет")
    await wait_editor(app, wait_for, "Макет")

    async def boom(self):
        raise CharacterSheetInstanceError("лист повреждён")

    monkeypatch.setattr(CharacterSheetFillDialog, "load", boom)

    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Макет", "Лист")
    await wait_for(lambda: any(k == "critical" for k, _t, _x in message_boxes))
    await helpers.wait_until_settled()

    assert application._sheet_fill is None
    assert list_dlg._open_instance_id is None
    assert any("поврежд" in text for k, _t, text in message_boxes if k == "critical")


async def test_fill_load_crash_drops_the_window_quietly(
    app, dialog_input, dialog_item, message_boxes, wait_for, monkeypatch,
):
    application, window = app
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Макет")
    await wait_editor(app, wait_for, "Макет")

    async def boom(self):
        raise RuntimeError("session gone")

    monkeypatch.setattr(CharacterSheetFillDialog, "load", boom)

    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Макет", "Лист")
    await helpers.wait_until_settled()

    assert application._sheet_fill is None
    assert not [
        w for w in window.findChildren(CharacterSheetFillDialog) if w.isVisible()
    ]
    assert not any(kind == "critical" for kind, _t, _x in message_boxes)


async def test_reopening_a_not_yet_loaded_fill_raises_the_same_window(
    app, dialog_input, dialog_item, wait_for, monkeypatch,
):
    """Before ``load`` lands the view model has no id, so the requested id is
    matched against the one the window was constructed with."""
    application, _window = app
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Макет")
    await wait_editor(app, wait_for, "Макет")

    async def no_load(self):
        return None

    monkeypatch.setattr(CharacterSheetFillDialog, "load", no_load)

    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Макет", "Лист")
    await wait_for(lambda: application._sheet_fill is not None)
    fill = application._sheet_fill
    assert fill.view_model.instance_id is None

    application._on_instance_open(fill._instance_id)
    await helpers.wait_until_settled()

    assert application._sheet_fill is fill
    assert fill.isVisible()


# ── design save without wiring (shutdown race) ──────────────────────────────

async def test_design_saved_after_wiring_is_gone_is_ignored(app, dialog_input, wait_for):
    application, _window = app
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Макет")
    editor = await wait_editor(app, wait_for, "Макет")

    wiring = application._wiring
    application._wiring = None
    try:
        application._on_design_saved(editor)
    finally:
        application._wiring = wiring

    assert application._sheet_editor is editor


# ── character cards follow the instance bindings ────────────────────────────

async def test_refresh_character_cards_syncs_only_populated_character_cards(
    app, dialog_input, dialog_item, wait_for,
):
    application, window = app
    char = await _make_character(application)
    char_id = char.id
    await _make_bound_instance(app, dialog_input, dialog_item, wait_for, char_id)

    bound_card = await _open_character_card(window, wait_for, char_id)
    item_card = EntityCardDialog(None, entity_type="item", parent=window)
    empty_card = EntityCardDialog(None, entity_type="character", parent=window)
    assert bound_card.entity_type == "character"
    assert bound_card.populated_entity_id == char_id
    assert empty_card.populated_entity_id is None
    bound_card.set_character_sheet_available(False)

    await application._refresh_character_cards()

    assert not bound_card.open_sheet_button.isHidden()
    assert empty_card.open_sheet_button.isHidden()
    assert item_card.open_sheet_button.isHidden()


async def test_character_card_has_no_sheet_button_without_instance_service(app, wait_for):
    application, window = app
    char = await _make_character(application)
    service = application._instance_service
    application._instance_service = None
    try:
        card = await _open_character_card(window, wait_for, char.id)
        assert not card.open_sheet_button.isVisible()
    finally:
        application._instance_service = service


async def test_open_bound_sheet_after_unbind_hides_the_button(
    app, dialog_input, dialog_item, wait_for,
):
    """The binding can disappear between opening the card and pressing the
    button: the flow then only re-syncs the button, no Fill window."""
    application, window = app
    char = await _make_character(application)
    instance_id = await _make_bound_instance(
        app, dialog_input, dialog_item, wait_for, char.id
    )

    card = await _open_character_card(window, wait_for, char.id)
    await wait_for(lambda: card.open_sheet_button.isVisible())

    await application._instance_service.unbind_character(instance_id)
    card.open_sheet_button.click()
    await helpers.wait_until_settled()

    assert not card.open_sheet_button.isVisible()
    assert application._sheet_fill is None
