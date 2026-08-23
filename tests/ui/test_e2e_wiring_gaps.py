"""E2E gap-fillers for ApplicationWiring and Application handlers.

Branches no user scenario in the main E2E set exercises: unknown-type
guards, rollback-on-failure paths, date filtering, search-result
selection, the create-related flow, snapshot dispatch, mention search
and the AI-button error paths.
"""
from __future__ import annotations

import datetime

from PySide6.QtCore import QDate

from app.infrastructure.llm.config import LlmConfig
from app.infrastructure.llm.errors import LlmHttpError
from app.application.services.event_service import EventService
from app.infrastructure.llm.remote_provider import RemoteLlmProvider
from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog

from tests.ui import helpers
from tests.ui.conftest import query_db

ENDPOINT = "http://mock-llm/v1"
MODEL = "test-model"


async def _open_entity_card(window, wait_for, entity_type: str, entity_id: int) -> EntityCardDialog:
    window.detail_panel.entity_clicked.emit(entity_type, entity_id)

    def _visible() -> bool:
        return any(
            d.isVisible() and d._entity_type == entity_type
            for d in window.findChildren(EntityCardDialog)
        )

    await wait_for(_visible)
    return next(
        d for d in window.findChildren(EntityCardDialog)
        if d.isVisible() and d._entity_type == entity_type
    )


async def test_filter_and_unknown_type_guards(app, wait_for):
    application, window = app
    await helpers.create_event_via_ui(
        window, wait_for, "Лето-Битва", start_date=QDate(1300, 7, 1)
    )
    timeline = window.timeline_widget.list_widget
    await wait_for(lambda: timeline.count() == 1)

    # A narrow date range hides the event; clearing brings it back
    window.timeline_widget.filter_changed.emit(
        datetime.date(1400, 1, 1), datetime.date(1400, 12, 31)
    )
    await wait_for(lambda: timeline.count() == 0)
    window.timeline_widget.filter_changed.emit(None, None)
    await wait_for(lambda: timeline.count() == 1)

    # Unknown entity type from the "+" menu: guard, no dialog
    window.timeline_widget.add_entity_requested.emit("no-such-type")
    await helpers.wait_until_settled()
    assert not [d for d in window.findChildren(EntityCardDialog) if d.isVisible()]

    # Unknown event id on double-click: guard, no dialog
    window.timeline_widget.event_double_clicked.emit(999999)
    await helpers.wait_until_settled()
    assert not [d for d in window.findChildren(EventDialog) if d.isVisible()]

    # Entity click with an unknown type or id: guards, no card
    window.detail_panel.entity_clicked.emit("no-such-type", 1)
    window.detail_panel.entity_clicked.emit("character", 999999)
    await helpers.wait_until_settled()
    assert not [d for d in window.findChildren(EntityCardDialog) if d.isVisible()]


async def test_entity_create_failure_rolls_back(app, wait_for, menu_qmenu, monkeypatch):
    application, window = app
    db_path = application._db_path

    # A healthy creation first (proves the flow, then the next one bombs)
    await helpers.create_entity_via_context_menu(
        window, wait_for, menu_qmenu, "character", "Исходный", characteristics="о"
    )
    await helpers.wait_until_settled()

    async def boom(**kwargs):
        raise RuntimeError("db write failed")

    monkeypatch.setattr(application._entity_services["character"], "create_entity", boom)

    # The card's own save click (inside the helper) fires the failing path:
    # create_entity raises → the rollback branch of on_entity_saved
    await helpers.create_entity_via_context_menu(
        window, wait_for, menu_qmenu, "character", "Не сохранится"
    )
    await helpers.wait_until_settled()

    names = [name for name, in query_db(db_path, "SELECT name FROM characters")]
    assert "Не сохранится" not in names
    # The shared session survived the rollback
    assert len(await application._entity_services["character"].get_all()) == 1


async def test_entity_dialog_construction_failure_rolls_back(app, wait_for, menu_qmenu, monkeypatch):
    application, window = app
    db_path = application._db_path

    await helpers.create_entity_via_context_menu(
        window, wait_for, menu_qmenu, "character", "Целевой"
    )
    await helpers.wait_until_settled()
    char_id = query_db(db_path, "SELECT id FROM characters WHERE name = 'Целевой'")[0][0]

    import app.application.wiring as wiring_mod

    class _BoomDialog:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("constructor exploded")

    monkeypatch.setattr(wiring_mod, "EntityCardDialog", _BoomDialog)

    # "+" menu: outer guard of on_add_entity
    window.timeline_widget.add_entity_requested.emit("character")
    await helpers.wait_until_settled()
    assert not [d for d in window.findChildren(EntityCardDialog) if d.isVisible()]

    # Detail-panel click with a valid id: outer guard of on_entity_click
    window.detail_panel.entity_clicked.emit("character", char_id)
    await helpers.wait_until_settled()
    assert not [d for d in window.findChildren(EntityCardDialog) if d.isVisible()]


async def test_event_edit_failure_rolls_back(app, wait_for, monkeypatch):
    application, window = app

    async def boom(self, event_id):
        raise RuntimeError("repo down")

    monkeypatch.setattr(EventService, "get_event", boom)
    window.timeline_widget.event_double_clicked.emit(1)
    await helpers.wait_until_settled()
    assert not [d for d in window.findChildren(EventDialog) if d.isVisible()]


async def test_search_result_selection(app, wait_for, menu_qmenu):
    application, window = app
    db_path = application._db_path
    await helpers.create_event_via_ui(window, wait_for, "СобытиеПоиска")
    await helpers.create_entity_via_context_menu(
        window, wait_for, menu_qmenu, "character", "ГеройПоиска"
    )
    await helpers.wait_until_settled()
    event_id = query_db(db_path, "SELECT id FROM events WHERE name = 'СобытиеПоиска'")[0][0]
    char_id = query_db(db_path, "SELECT id FROM characters WHERE name = 'ГеройПоиска'")[0][0]
    timeline = window.timeline_widget.list_widget

    # "event" result: the event is selected on the timeline
    window.search_bar.result_selected.emit("event", event_id)
    await helpers.wait_until_settled()
    current = timeline.item(timeline.currentRow())
    assert current is not None and "СобытиеПоиска" in current.text()

    # entity result: the entity card opens
    window.search_bar.result_selected.emit("character", char_id)
    await wait_for(lambda: any(
        d.isVisible() and d.name_input.text() == "ГеройПоиска"
        for d in window.findChildren(EntityCardDialog)
    ))


async def test_create_related_entity_from_card(app, wait_for, menu_qmenu):
    application, window = app
    db_path = application._db_path
    await helpers.create_entity_via_context_menu(
        window, wait_for, menu_qmenu, "character", "Мастер"
    )
    await helpers.wait_until_settled()
    char_id = query_db(db_path, "SELECT id FROM characters WHERE name = 'Мастер'")[0][0]

    card = await _open_entity_card(window, wait_for, "character", char_id)

    # Request a new related entity → sub-card opens (non-modal)
    card.create_related_requested.emit("items", "item")

    def _sub_visible() -> bool:
        return any(
            d.isVisible() and d._entity_type == "item"
            for d in window.findChildren(EntityCardDialog)
        )

    await wait_for(_sub_visible)
    sub = next(
        d for d in window.findChildren(EntityCardDialog)
        if d.isVisible() and d._entity_type == "item"
    )

    sub.saved.emit({
        "name": "Клинок",
        "start_date": datetime.date(1300, 1, 1),
        "end_date": datetime.date(1300, 2, 1),
    })
    await helpers.wait_until_settled()

    # on_sub_saved flushes only; the row is visible through the app session
    # (the parent card's save would commit it in the real flow)
    items = list(await application._entity_services["item"].get_all())
    assert any(it.name == "Клинок" for it in items)
    # The new entity was attached to the parent card's related section
    section = card._related_sections["items"].list_widget
    assert any(
        "Клинок" in section.item(i).text() for i in range(section.count())
    )


async def test_snapshot_requested_both_modes(app, wait_for, monkeypatch):
    application, window = app
    await helpers.create_event_via_ui(
        window, wait_for, "МоментВремени", start_date=QDate(1300, 5, 15)
    )
    calls: list = []
    monkeypatch.setattr(
        window.world_snapshot, "populate",
        lambda events, target_date: calls.append((len(events), target_date)),
    )

    # "Показать всё" (None) and a concrete date
    window.world_snapshot.snapshot_requested.emit(None)
    await helpers.wait_until_settled()
    window.world_snapshot.snapshot_requested.emit(datetime.date(1300, 5, 15))
    await helpers.wait_until_settled()

    assert calls == [(1, None), (1, datetime.date(1300, 5, 15))]


async def test_mention_search_success(app, wait_for, menu_qmenu):
    application, window = app
    db_path = application._db_path
    await helpers.create_entity_via_context_menu(
        window, wait_for, menu_qmenu, "character", "ЛовецМечты"
    )
    await helpers.wait_until_settled()
    char_id = query_db(db_path, "SELECT id FROM characters WHERE name = 'ЛовецМечты'")[0][0]

    card = await _open_entity_card(window, wait_for, "character", char_id)
    edits = card.get_mention_edits()
    assert edits
    # Successful mention search feeds the candidate list (no exception path)
    edits[0].mention_search_requested.emit("Ловец")
    await helpers.wait_until_settled()


async def test_ai_button_generation_request_failure(app, wait_for, menu_qmenu, monkeypatch):
    application, window = app
    db_path = application._db_path
    await helpers.create_entity_via_context_menu(
        window, wait_for, menu_qmenu, "character", "Астра"
    )
    await helpers.wait_until_settled()
    char_id = query_db(db_path, "SELECT id FROM characters WHERE name = 'Астра'")[0][0]

    application._llm_vm.apply_config(LlmConfig(base_url=ENDPOINT, model=MODEL))
    card = await _open_entity_card(window, wait_for, "character", char_id)
    btn = next(b for b in card.get_ai_buttons() if b.field_name == "name")

    async def explode(*args, **kwargs):
        raise RuntimeError("generation exploded")

    # request_generation itself fails → the wiring's except + stop progress
    monkeypatch.setattr(application._llm_vm, "request_generation", explode)
    btn.generate_requested.emit(btn.entity_type, btn.field_name, "Название", "")
    assert btn._generating
    await wait_for(lambda: not btn._generating)


async def test_ai_button_generation_provider_error(app, wait_for, menu_qmenu, monkeypatch):
    application, window = app
    db_path = application._db_path
    await helpers.create_entity_via_context_menu(
        window, wait_for, menu_qmenu, "character", "Веста"
    )
    await helpers.wait_until_settled()
    char_id = query_db(db_path, "SELECT id FROM characters WHERE name = 'Веста'")[0][0]

    application._llm_vm.apply_config(LlmConfig(base_url=ENDPOINT, model=MODEL))
    card = await _open_entity_card(window, wait_for, "character", char_id)
    btn = next(b for b in card.get_ai_buttons() if b.field_name == "name")

    async def reject(*args, **kwargs):
        raise LlmHttpError(401, "unauthorized")

    # The provider rejects → vm emits generation_error → the wiring's
    # _on_error handler matches the field id and stops the progress
    monkeypatch.setattr(RemoteLlmProvider, "generate", reject)
    btn.generate_requested.emit(btn.entity_type, btn.field_name, "Название", "")
    assert btn._generating
    await wait_for(lambda: not btn._generating)


async def test_create_related_without_service_is_noop(app, wait_for, menu_qmenu):
    """on_sub_saved: no service registered for the related type → early return.

    The UI only offers «items», but the wiring must survive any type without a
    registered service (defensive guard, no crash, nothing attached).
    """
    application, window = app
    db_path = application._db_path
    await helpers.create_entity_via_context_menu(
        window, wait_for, menu_qmenu, "character", "Смотритель"
    )
    await helpers.wait_until_settled()
    char_id = query_db(db_path, "SELECT id FROM characters WHERE name = 'Смотритель'")[0][0]
    card = await _open_entity_card(window, wait_for, "character", char_id)

    card.create_related_requested.emit("items", "rating")

    def _sub_visible() -> bool:
        return any(
            d.isVisible() and d._entity_type == "rating"
            for d in window.findChildren(EntityCardDialog)
        )

    await wait_for(_sub_visible)
    sub = next(
        d for d in window.findChildren(EntityCardDialog)
        if d.isVisible() and d._entity_type == "rating"
    )
    sub.saved.emit({"name": "МнимыйРейтинг"})
    await helpers.wait_until_settled()

    # Guard: no service → nothing created, nothing attached to the card
    assert query_db(db_path, "SELECT COUNT(*) FROM characters")[0][0] == 1
    section = card._related_sections["items"].list_widget
    assert section.count() == 0
