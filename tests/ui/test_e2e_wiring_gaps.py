"""E2E gap-fillers for ApplicationWiring and Application handlers.

Branches no user scenario in the main E2E set exercises: unknown-type
guards, rollback-on-failure paths, the date window, search-result
selection, the create-related flow, snapshot dispatch, mention search
and the AI-button error paths.
"""
from __future__ import annotations

from datetime import date

import datetime


from PySide6.QtCore import Qt

from app.infrastructure.llm.config import LlmConfig
from app.domain.game_calendar import as_game_coord
from app.infrastructure.llm.errors import LlmHttpError
from app.application.services.event_service import EventService
from app.infrastructure.llm.remote_provider import RemoteLlmProvider
from app.presentation.dialog_results import EntityCreateResult
from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog

from tests.ui import helpers, timeline_probe
from tests.ui.conftest import query_db

ENDPOINT = "http://mock-llm/v1"
MODEL = "test-model"


def timeline_vm_events(canvas):
    return canvas.events


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


async def test_window_and_unknown_type_guards(app, wait_for):
    application, window = app
    # A closed 1300 event: a window whose interval does not cross it excludes
    # it (the flat window rule; an open end would reach into 1400).
    await helpers.create_event_via_ui(
        window, wait_for, "Лето-Битва", start_date=date(1300, 7, 1),
        end_date=date(1300, 7, 1),
    )
    canvas = timeline_probe.tape(window)
    await wait_for(lambda: len(canvas.events) == 1)

    # A narrow date range hides the event; clearing brings it back
    window.timeline_widget.window_changed.emit(
        datetime.date(1400, 1, 1), datetime.date(1400, 12, 31)
    )
    await wait_for(lambda: len(canvas.events) == 0)
    window.timeline_widget.window_changed.emit(None, None)
    await wait_for(lambda: len(canvas.events) == 1)

    # Unknown entity type from the "+" menu: guard, no dialog
    window.timeline_widget.add_entity_requested.emit("no-such-type")
    await helpers.wait_until_settled()
    assert not [d for d in window.findChildren(EntityCardDialog) if d.isVisible()]

    # Unknown event id on double-click: guard, no dialog
    window.timeline_widget.event_double_clicked.emit(999999)
    await helpers.wait_until_settled()
    assert not [d for d in window.findChildren(EventDialog) if d.isVisible()]

    # Unknown id on selection: the detail panel is cleared, not left stale
    window.timeline_widget.event_selected.emit(999999)
    await helpers.wait_until_settled()
    assert not window.detail_panel.vm.title

    # Entity click with an unknown type or id: guards, no card
    window.detail_panel.entity_clicked.emit("no-such-type", 1)
    window.detail_panel.entity_clicked.emit("character", 999999)
    await helpers.wait_until_settled()
    assert not [d for d in window.findChildren(EntityCardDialog) if d.isVisible()]


async def test_window_out_of_the_selected_event_clears_every_layer(app, wait_for):
    """The selection is id-centered in all three layers (task 3.3).

    A window that drops the selected event used to leave the ViewModel and the
    detail panel holding an object the canvas had already forgotten.
    """
    application, window = app
    # Closed event: the 1400 window excludes it (no interval crossing); an
    # open end would cross the window and keep it visible (flat window rule).
    await helpers.create_event_via_ui(
        window, wait_for, "Война", start_date=date(1300, 7, 1),
        end_date=date(1300, 7, 1),
    )
    canvas = timeline_probe.tape(window)
    await wait_for(lambda: len(canvas.events) == 1)

    event_id = helpers.click_timeline_event(window, "Война")
    await wait_for(lambda: "Война" in window.detail_panel.vm.title)
    assert canvas.selected_id == event_id

    window.timeline_widget.window_changed.emit(
        datetime.date(1400, 1, 1), datetime.date(1400, 12, 31)
    )
    await wait_for(lambda: len(canvas.events) == 0)
    await helpers.wait_until_settled()

    # canvas, view model and detail panel agree: nothing is selected
    assert canvas.selected_id is None
    assert window.detail_panel.vm.title == ""
    assert application._wiring._timeline_vm.selected_event is None


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

    import app.presentation.wiring as wiring_mod

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
    canvas = timeline_probe.tape(window)

    # "event" result: the event's bar is selected on the scale (id-contract)
    window.search_bar.result_selected.emit("event", event_id)
    await helpers.wait_until_settled()
    assert canvas.selected_id == event_id
    assert any(e.id == event_id for e in timeline_vm_events(canvas))

    # entity result, single click (NRI-0022 task 6.2 re-pin): the full-path
    # gesture — the character has no events, so the scale and the panel stay
    # as they are and only the preview shows the entity; no card opens.
    window.search_bar.result_selected.emit("character", char_id)
    await wait_for(
        lambda: window.entity_preview.vm.shown_entity is not None
        and window.entity_preview.vm.shown_entity.id == char_id
    )
    await helpers.wait_until_settled()
    assert canvas.selected_id == event_id  # the scale kept the previous choice
    assert window.detail_panel.vm.title == "СобытиеПоиска"  # the panel too
    assert not [
        d for d in window.findChildren(EntityCardDialog) if d.isVisible()
    ]

    # entity result, double click: the edit gesture opens the card
    window.search_bar.result_activated.emit("character", char_id)
    await wait_for(lambda: any(
        d.isVisible() and d.name_input.text() == "ГеройПоиска"
        for d in window.findChildren(EntityCardDialog)
    ))


async def test_search_result_resets_an_excluding_window(app, wait_for):
    """Spec «Внешний выбор вне окна сбрасывает окно» through the REAL search
    channel (regression: the wiring once gated on the windowed slice, silently
    dropping results the active «Выбор даты» window excluded).

    «Ранний» is cut out by a June-only window; its search result must reset
    the window to «Все дни», repaint the list and land the highlight on its
    single row (there is no ladder left to descend — flat list, design D3)."""
    application, window = app
    widget = window.timeline_widget
    view = timeline_probe.tape(window)
    await helpers.create_event_via_ui(
        window, wait_for, "Ранний",
        start_date=date(1200, 3, 1), end_date=date(1200, 3, 1),
    )
    await helpers.create_event_via_ui(
        window, wait_for, "Поздний",
        start_date=date(1200, 6, 1), end_date=date(1200, 6, 1),
    )
    await helpers.wait_until_settled()
    early_id = helpers.find_event_id(window, "Ранний")

    # The user narrows the window onto June: «Ранний» leaves the visible
    # sample (but not the VM's whole loaded sample).
    widget._on_window_range(datetime.date(1200, 6, 1), datetime.date(1200, 6, 30))
    await helpers.wait_until_settled()
    vm = application._wiring._timeline_vm
    assert all(e.name != "Ранний" for e in view.events)  # excluded by the window

    # …and the search result for that very event must still reach it.
    window.search_bar.result_selected.emit("event", early_id)
    await helpers.wait_until_settled()

    assert vm.window is None                           # «Все дни» reset
    assert view.window == (None, None)                 # the list followed
    assert view.selected_id == early_id                # row highlighted
    assert view.index_for_event(early_id) is not None  # …and pictured, visible
    assert vm.selected_event is not None and vm.selected_event.name == "Ранний"


async def test_search_click_on_a_collapsed_subevent_expands_then_highlights(
    app, wait_for
):
    """NRI-0023 task 8.2 (spec event-subevents «Переход к свёрнутому
    подсобытию раскрывает цепочку»): the search result route reveals the
    parent BEFORE the highlight lands — the clicked child's row appears under
    its parent and carries the selection, all through the real
    result_selected channel."""
    application, window = app
    db_path = application._db_path
    await helpers.create_event_via_ui(
        window, wait_for, "Поход",
        start_date=date(1200, 7, 1), end_date=date(1200, 7, 2),
    )
    await helpers.create_event_via_ui(
        window, wait_for, "Разведка",
        start_date=date(1200, 7, 1), end_date=date(1200, 7, 1),
    )
    await helpers.wait_until_settled()
    parent_id = query_db(db_path, "SELECT id FROM events WHERE name = 'Поход'")[0][0]
    child_id = query_db(db_path, "SELECT id FROM events WHERE name = 'Разведка'")[0][0]
    canvas = timeline_probe.tape(window)
    vm = timeline_probe.vm(window)

    # Link «Разведка» under «Поход» through the card (task 7.1's own channel).
    window.timeline_widget.event_double_clicked.emit(child_id)
    await wait_for(lambda: any(
        d.isVisible() and d.event_id == child_id
        for d in window.findChildren(EventDialog)
    ))
    dialog = next(
        d for d in window.findChildren(EventDialog)
        if d.isVisible() and d.event_id == child_id
    )
    dialog.vm.selectParent(1)
    dialog.save_button.click()
    await wait_for(lambda: query_db(
        db_path, "SELECT parent_id FROM events WHERE id = ?", (child_id,)
    ) == [(parent_id,)])
    await helpers.wait_until_settled()

    # The precondition: the tree is collapsed by default, so the child has
    # no row at all while its parent does.
    assert vm.expanded_parent_ids == frozenset()
    assert canvas.index_for_event(child_id) is None
    assert canvas.index_for_event(parent_id) is not None

    # The real query channel (task 8.2): the connector hands the VM the
    # id → имя card, so the child's row names the parent the query never
    # matched («Подсобытие названо через родителя»).
    window.search_bar.search_requested.emit("Разведка")
    search_vm = application._wiring._search_vm
    await wait_for(lambda: any(
        row["kind"] == "result" for row in search_vm.rows
    ))
    result_rows = [row for row in search_vm.rows if row["kind"] == "result"]
    assert result_rows[0]["text"] == "Разведка · Поход  [01 Июль 1200]"

    # The search click on the collapsed child: chain first, highlight second.
    window.search_bar.result_selected.emit("event", child_id)
    await helpers.wait_until_settled()

    assert vm.expanded_parent_ids == frozenset({parent_id})
    assert vm.selected_event is not None and vm.selected_event.id == child_id
    assert canvas.selected_id == child_id
    child_index = canvas.index_for_event(child_id)
    assert child_index is not None
    assert canvas.rows[child_index].depth == 1
    assert canvas.rows[child_index - 1].event_id == parent_id


async def test_create_related_entity_from_card(app, wait_for, menu_qmenu, modal_qdialog):
    """4.6 Card sub-flow: the popup is populated, its links are applied.

    Creating a related entity from the card while linking a pre-existing
    entity inside the popup: after saving the popup and the parent card,
    the new entity's relations are persisted.
    """
    application, window = app
    db_path = application._db_path
    await helpers.create_entity_via_context_menu(
        window, wait_for, menu_qmenu, "character", "Мастер"
    )
    await helpers.wait_until_settled()
    char_id = query_db(db_path, "SELECT id FROM characters WHERE name = 'Мастер'")[0][0]

    # A pre-existing location to link inside the creation popup.
    await application._entity_services["location"].create_entity(
        name="Цех", characteristics="", backstory="",
        start_date=datetime.date(1200, 1, 1), end_date=datetime.date(1200, 12, 31),
    )
    await application._session.commit()
    loc_id = query_db(db_path, "SELECT id FROM locations WHERE name = 'Цех'")[0][0]

    card = await _open_entity_card(window, wait_for, "character", char_id)

    # Request a new related entity → sub-card opens (non-modal).
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

    # The popup's related sections are populated: link the existing location.
    await helpers.link_existing_entity_in_tab(
        window, wait_for, sub._related_sections["locations"], "Цех"
    )
    await wait_for(lambda: any(
        "Цех" in sub._related_sections["locations"].list_widget.item(i).text()
        for i in range(sub._related_sections["locations"].list_widget.count())
    ))

    sub.name_input.setText("Клинок")
    sub.save_button.click()
    await helpers.wait_until_settled()

    # The new entity was attached to the parent card's related section.
    section = card._related_sections["items"].list_widget
    assert any(
        "Клинок" in section.item(i).text() for i in range(section.count())
    )

    # Save the parent card — the popped-up entity and its links are committed.
    card.save_button.click()
    await helpers.wait_until_settled()

    item_id = query_db(db_path, "SELECT id FROM items WHERE name = 'Клинок'")[0][0]
    linked = query_db(
        db_path,
        "SELECT 1 FROM item_location WHERE item_id = ? AND location_id = ?",
        (item_id, loc_id),
    )
    assert len(linked) == 1


async def test_snapshot_requested_both_modes(app, wait_for, monkeypatch):
    application, window = app
    await helpers.create_event_via_ui(
        window, wait_for, "МоментВремени", start_date=date(1300, 5, 15)
    )
    calls: list = []
    # NRI-0022 (group 2): the panel lives in the «Обзор мира…» window; the
    # real menu action opens it, the wiring answers the panel's signals.
    # NRI-0023 task 8.3: every dispatch also hands the id → имя card (the
    # orphan stubs' naming source) — one event in this game, one entry.
    snapshot = helpers.open_world_snapshot(application, window)
    monkeypatch.setattr(
        snapshot, "populate",
        lambda events, target_date, event_names=None: calls.append(
            (len(events), target_date, sorted((event_names or {}).values()))
        ),
    )

    # "Показать всё" (None) and a concrete date
    snapshot.snapshot_requested.emit(None)
    await helpers.wait_until_settled()
    snapshot.snapshot_requested.emit(datetime.date(1300, 5, 15))
    await helpers.wait_until_settled()

    assert calls == [
        (1, None, ["МоментВремени"]),
        (1, datetime.date(1300, 5, 15), ["МоментВремени"]),
    ]


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


async def test_popup_create_failure_rolls_back_and_notifies(
    app, wait_for, modal_qdialog, monkeypatch, message_boxes
):
    """on_sub_saved: create_entity failure -> rollback + user notification.

    The popup save must not leak the exception out of the wiring task, must
    leave the shared session usable, must attach nothing to the parent
    section, and must notify the user via a critical message box.
    """
    application, window = app
    db_path = application._db_path

    # A committed character proves the session survived the rollback.
    await application._entity_services["character"].create_entity(
        name="Целевой", characteristics="Описание", backstory="",
        start_date=datetime.date(1200, 1, 1), end_date=datetime.date(1200, 12, 31),
    )
    await application._session.commit()

    async def boom(**kwargs):
        raise RuntimeError("db write failed")

    monkeypatch.setattr(application._entity_services["character"], "create_entity", boom)

    timeline_probe.click_object(window, "addButton")
    await wait_for(lambda: any(d.isVisible() for d in window.findChildren(EventDialog)))
    dialog = next(d for d in window.findChildren(EventDialog) if d.isVisible())
    loaded = helpers.watch_available_entity_load(dialog)
    await wait_for(lambda: len(loaded) == 4)
    dialog.name_input.setText("Сбой")
    dialog.characteristics_input.setContent("Текст")

    sub = await helpers.create_related_via_popup(
        window, wait_for, dialog, "characters", "character",
        "Не сохранится", expect_success=False,
    )
    # Save failure preserves the popup data and unlocks retry.
    await helpers.wait_until_settled()
    assert sub.isVisible()
    assert sub.name_input.text() == "Не сохранится"
    assert sub.save_button.isEnabled()

    # Nothing attached to the parent section, nothing persisted.
    assert dialog.char_tab.list_widget.count() == 0
    assert query_db(db_path, "SELECT COUNT(*) FROM characters")[0][0] == 1
    # Only the committed character's description survives.
    assert query_db(db_path, "SELECT COUNT(*) FROM descriptions")[0][0] == 1
    # The wiring notified the user via a critical message box.
    assert ("critical", "Ошибка создания сущности", "db write failed") in message_boxes
    # The shared session survived the rollback.
    assert len(await application._entity_services["character"].get_all()) == 1


async def test_popup_cleanup_after_external_rollback(app, wait_for, modal_qdialog):
    """_cleanup_popup_entities: pending rows already discarded by an
    unrelated rollback are not found - both None guards make the cleanup a
    safe no-op that leaves the session usable."""
    application, window = app
    db_path = application._db_path

    timeline_probe.click_object(window, "addButton")
    await wait_for(lambda: any(d.isVisible() for d in window.findChildren(EventDialog)))
    dialog = next(d for d in window.findChildren(EventDialog) if d.isVisible())
    loaded = helpers.watch_available_entity_load(dialog)
    await wait_for(lambda: len(loaded) == 4)
    dialog.name_input.setText("Отменное")
    dialog.characteristics_input.setContent("Текст")

    # Popup-created entity: flushed (pending) and tracked for cleanup.
    await helpers.create_related_via_popup(
        window, wait_for, dialog, "characters", "character", "Фантом"
    )
    await helpers.wait_until_settled()
    assert len(application._wiring._popup_created[dialog]) == 1

    # An unrelated rollback discards the pending rows (entity + description).
    await application._session.rollback()

    # Rejecting the parent runs the cleanup with both pending rows gone.
    dialog.reject()
    await helpers.wait_until_settled()

    assert query_db(db_path, "SELECT COUNT(*) FROM characters")[0][0] == 0
    assert query_db(db_path, "SELECT COUNT(*) FROM descriptions")[0][0] == 0
    # The session is usable afterwards.
    assert await application._entity_services["character"].get_all() == []


async def test_popup_entity_committed_by_foreign_task_does_not_survive_cancel(
    app, wait_for, modal_qdialog
):
    """Task 5.6 characterization (audit Q14 scenario 1).

    A popup-created entity is only flushed; if another task's unrelated
    commit drags it into the database before the parent dialog's fate is
    decided, cancelling the parent must STILL remove the entity, and a later
    commit must not bring it back. Task 5.4 (cleanup commits its deletes) and
    the popup path's unit of work (task 5.8) are what keep this invariant.
    """
    application, window = app
    db_path = application._db_path

    timeline_probe.click_object(window, "addButton")
    await wait_for(lambda: any(d.isVisible() for d in window.findChildren(EventDialog)))
    dialog = next(d for d in window.findChildren(EventDialog) if d.isVisible())
    loaded = helpers.watch_available_entity_load(dialog)
    await wait_for(lambda: len(loaded) == 4)
    dialog.name_input.setText("Отменное")
    dialog.characteristics_input.setContent("Текст")

    await helpers.create_related_via_popup(
        window, wait_for, dialog, "characters", "character", "Фантом"
    )
    await helpers.wait_until_settled()

    # A random commit (task 5.8 already committed it at popup save; before
    # 5.8 this commit is what dragged the pending rows into the DB) — either
    # way the entity is committed and cancel must remove it in both modes.
    await application._session.commit()
    assert query_db(db_path, "SELECT COUNT(*) FROM characters")[0][0] == 1

    # Cancelling the parent must still erase the entity, though it was committed.
    dialog.reject()
    await helpers.wait_until_settled()
    assert query_db(db_path, "SELECT COUNT(*) FROM characters")[0][0] == 0
    assert query_db(db_path, "SELECT COUNT(*) FROM descriptions")[0][0] == 0

    # A later unrelated commit must not resurrect anything.
    await application._session.commit()
    assert query_db(db_path, "SELECT COUNT(*) FROM characters")[0][0] == 0


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
    sub.saved.emit(
        EntityCreateResult(
            fields={"name": "МнимыйРейтинг"}, characteristics="",
            backstory="", related_changes={},
        )
    )
    await helpers.wait_until_settled()

    # Guard: no service → nothing created, nothing attached to the card
    assert query_db(db_path, "SELECT COUNT(*) FROM characters")[0][0] == 1
    section = card._related_sections["items"].list_widget
    assert section.count() == 0


async def test_sheet_list_refresh_skips_a_missing_or_dead_dialog(app, wait_for):
    """The refresh task runs while the app may already be closing: no dialog is
    a no-op, and a dialog that fails mid-refresh ends the task quietly."""
    application, window = app

    await application._sheet_list_refresh()  # nothing open

    class _DeadDialog:
        def __init__(self):
            self.refreshed = 0

        async def refresh(self):
            self.refreshed += 1
            raise RuntimeError("app already shut down under this task")

        def set_open_sheet_id(self, sheet_id):  # pragma: no cover - must not run
            raise AssertionError("a failed refresh must not repaint")

    dead = _DeadDialog()
    application._sheet_list_dialog = dead
    try:
        await application._sheet_list_refresh()
    finally:
        application._sheet_list_dialog = None

    assert dead.refreshed == 1


async def test_subevent_create_menu_prefills_dialog_and_links_parent(
    app, wait_for, menu_qmenu
):
    """NRI-0023 task 6.1 (spec «Создание подсобытия правым кликом»), full E2E
    round: a right click on a main event row runs through the island's context
    menu (item «Создать подсобытие»), and the pick opens the create card
    prefilled with the parent and the parent's start date («время пустое» is
    the штатный default — the time lists arrive in task 7.2); saving writes
    the sub-event link through the service guard."""
    application, window = app
    db_path = application._db_path
    await helpers.create_event_via_ui(
        window, wait_for, "Поход",
        start_date=date(1200, 7, 1), end_date=date(1200, 7, 2),
    )
    parent_id = query_db(db_path, "SELECT id FROM events WHERE name = 'Поход'")[0][0]
    canvas = timeline_probe.tape(window)
    row_index = canvas.index_for_event(parent_id)

    helpers.pick_menu_action(menu_qmenu, "Создать подсобытие")
    timeline_probe.click(
        window,
        timeline_probe.row_center(window, row_index),
        button=Qt.MouseButton.RightButton,
    )
    await wait_for(lambda: any(d.isVisible() for d in window.findChildren(EventDialog)))
    dialog = next(d for d in window.findChildren(EventDialog) if d.isVisible())
    load_done = helpers.watch_available_entity_load(dialog)
    await wait_for(lambda: len(load_done) == 4)

    # The spec's «Родитель и дата подставлены»: parent + parent's start date,
    # and this is still the CREATE flow (no event id loaded).
    assert dialog.vm.parent_id == parent_id
    assert dialog.vm._start_date == as_game_coord(date(1200, 7, 1))
    assert dialog.event_id is None

    dialog.name_input.setText("Разведка")
    dialog.characteristics_input.setContent("Вышли на рассвете")
    assert dialog.save_button.isEnabled()
    dialog.save_button.click()
    await wait_for(lambda: helpers.has_event_named(window, "Разведка"))
    assert query_db(
        db_path, "SELECT parent_id FROM events WHERE name = 'Разведка'"
    ) == [(parent_id,)]


async def test_subevent_request_for_a_gone_parent_stays_quiet(app, wait_for):
    """A row may quote an id that is no longer there (a reload raced the
    open): the connector's parent read answers nothing and no card opens."""
    application, window = app
    timeline_probe.vm(window).subevent_create_requested.emit(404)
    await helpers.wait_until_settled()
    assert not [d for d in window.findChildren(EventDialog) if d.isVisible()]


async def test_subevent_open_failure_logs_instead_of_a_dialog(
    app, wait_for, message_boxes, monkeypatch
):
    """The open-failure posture (as everywhere in this suite): a failed parent
    read is a quiet warning — never a modal, never a half-open card."""
    application, window = app

    async def boom(self, event_id):
        raise RuntimeError("repo down")

    monkeypatch.setattr(EventService, "get_event", boom)
    timeline_probe.vm(window).subevent_create_requested.emit(1)
    await helpers.wait_until_settled()
    assert not [d for d in window.findChildren(EventDialog) if d.isVisible()]
    assert message_boxes == []


async def test_card_parent_and_time_fields_round_trip(app, wait_for):
    """NRI-0023 task 7.1/7.2, full user round: the edit dialog's parent pool
    offers «—» + the mains (self and sub-events excluded), the combo перецепляет
    and writes the wall clock through the connector, a reopen shows the saved
    pair, and «—»/«—» promotes to main and clears the time (specs
    «Поле „Родительское событие“…», event-time «Списки часов и минут…»)."""
    application, window = app
    db_path = application._db_path
    await helpers.create_event_via_ui(
        window, wait_for, "Поход",
        start_date=date(1200, 7, 1), end_date=date(1200, 7, 2),
    )
    await helpers.create_event_via_ui(
        window, wait_for, "Пир",
        start_date=date(1200, 9, 1), end_date=date(1200, 9, 1),
    )
    parent_id = query_db(db_path, "SELECT id FROM events WHERE name = 'Поход'")[0][0]
    feast_id = query_db(db_path, "SELECT id FROM events WHERE name = 'Пир'")[0][0]

    def open_dialog(event_id: int) -> EventDialog:
        return next(
            d for d in window.findChildren(EventDialog)
            if d.isVisible() and d.event_id == event_id
        )

    # Перецепка + время: «Пир» едет под «Поход» с началом в 14:30.
    window.timeline_widget.event_double_clicked.emit(feast_id)
    await wait_for(lambda: any(
        d.isVisible() and d.event_id == feast_id
        for d in window.findChildren(EventDialog)
    ))
    dialog = open_dialog(feast_id)
    # The pool loaded after populate: «—» + mains, the edited event absent.
    assert dialog.vm.parentNames == ["—", "Поход"]
    assert dialog.vm.selectedParentIndex == 0
    dialog.vm.selectParent(1)
    dialog.vm.selectHour(15)  # «14»
    dialog.vm.selectMinute(7)  # «30» на ровной лестнице
    dialog.save_button.click()
    await wait_for(lambda: query_db(
        db_path, "SELECT parent_id, start_time FROM events WHERE id = ?", (feast_id,),
    ) == [(parent_id, 14 * 60 + 30)])
    await helpers.wait_until_settled()

    # Spec «Чужих детей в списке нет»: «Пир» стал подсобытием и из пула исчез.
    await helpers.create_event_via_ui(
        window, wait_for, "Разведка",
        start_date=date(1200, 7, 1), end_date=date(1200, 7, 1),
    )
    scout_id = query_db(db_path, "SELECT id FROM events WHERE name = 'Разведка'")[0][0]
    window.timeline_widget.event_double_clicked.emit(scout_id)
    await wait_for(lambda: any(
        d.isVisible() and d.event_id == scout_id
        for d in window.findChildren(EventDialog)
    ))
    scout_dialog = open_dialog(scout_id)
    assert scout_dialog.vm.parentNames == ["—", "Поход"]
    scout_dialog.vm.requestCancel()
    await wait_for(lambda: not scout_dialog.isVisible())

    # Scenario «Время задано» at the reopen: saved hour/minute/parent stand
    # selected; then «—» + «—» — подъём в основные и время стёрто.
    window.timeline_widget.event_double_clicked.emit(feast_id)
    await wait_for(lambda: any(
        d.isVisible() and d.event_id == feast_id
        for d in window.findChildren(EventDialog)
    ))
    reopen = open_dialog(feast_id)
    assert reopen.vm.selectedParentIndex == 1  # «Поход» prefilled
    assert reopen.vm.selectedHourIndex == 15  # «14»
    assert reopen.vm.selectedMinuteIndex == 7  # «30»
    reopen.vm.selectParent(0)
    reopen.vm.selectHour(0)  # минута гасится вместе с часом
    assert reopen.vm.minuteEnabled is False
    reopen.save_button.click()
    await wait_for(lambda: query_db(
        db_path, "SELECT parent_id, start_time FROM events WHERE id = ?", (feast_id,),
    ) == [(None, None)])
    await helpers.wait_until_settled()
