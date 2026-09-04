"""E2E gap-fillers for ApplicationWiring and Application handlers.

Branches no user scenario in the main E2E set exercises: unknown-type
guards, rollback-on-failure paths, the date window, search-result
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
from app.presentation.views.timeline_rows import ScaleUnit

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
    # A closed 1300 event: a window that does not cross it excludes it under
    # the day-ladder overlap visibility (an open end would reach into 1400).
    await helpers.create_event_via_ui(
        window, wait_for, "Лето-Битва", start_date=QDate(1300, 7, 1),
        end_date=QDate(1300, 7, 1),
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
    assert window.detail_panel.title_label.text() == "" or not window.detail_panel.title_label.text()

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
    # Closed event: the 1400 window excludes it (no overlap); an open end
    # would cross the window and keep it visible (day-ladder semantics).
    await helpers.create_event_via_ui(
        window, wait_for, "Война", start_date=QDate(1300, 7, 1),
        end_date=QDate(1300, 7, 1),
    )
    canvas = timeline_probe.tape(window)
    await wait_for(lambda: len(canvas.events) == 1)

    event_id = helpers.click_timeline_event(window, "Война")
    await wait_for(lambda: "Война" in window.detail_panel.title_label.text())
    assert canvas.selected_id == event_id

    window.timeline_widget.window_changed.emit(
        datetime.date(1400, 1, 1), datetime.date(1400, 12, 31)
    )
    await wait_for(lambda: len(canvas.events) == 0)
    await helpers.wait_until_settled()

    # canvas, view model and detail panel agree: nothing is selected
    assert canvas.selected_id is None
    assert window.detail_panel.title_label.text() == ""
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
    canvas = timeline_probe.tape(window)

    # "event" result: the event's bar is selected on the scale (id-contract)
    window.search_bar.result_selected.emit("event", event_id)
    await helpers.wait_until_settled()
    assert canvas.selected_id == event_id
    assert any(e.id == event_id for e in timeline_vm_events(canvas))

    # entity result: the entity card opens
    window.search_bar.result_selected.emit("character", char_id)
    await wait_for(lambda: any(
        d.isVisible() and d.name_input.text() == "ГеройПоиска"
        for d in window.findChildren(EntityCardDialog)
    ))


async def test_search_result_descends_ladder_past_an_excluding_window(
    app, wait_for
):
    """Spec «Внешний выбор с крупной ступени спускает лестницу» through the
    REAL search channel (regression: the wiring once gated on the windowed
    slice, silently dropping results the active «Выбор даты» window excluded).

    «Ранний» is cut out by a June-only window while the ladder stands on
    «месяц»; its search result must still descend to сутки, reset the window
    to «Все дни», repaint the tape and land the highlight on its card."""
    application, window = app
    widget = window.timeline_widget
    view = timeline_probe.tape(window)
    await helpers.create_event_via_ui(
        window, wait_for, "Ранний",
        start_date=QDate(1200, 3, 1), end_date=QDate(1200, 3, 1),
    )
    await helpers.create_event_via_ui(
        window, wait_for, "Поздний",
        start_date=QDate(1200, 6, 1), end_date=QDate(1200, 6, 1),
    )
    await helpers.wait_until_settled()
    early_id = helpers.find_event_id(window, "Ранний")

    # The user drills the window onto June and zooms out to «месяц»: «Ранний»
    # leaves both the window and the visible sample (but not the VM's sample).
    widget._on_window_range(datetime.date(1200, 6, 1), datetime.date(1200, 6, 30))
    await helpers.wait_until_settled()
    vm = application._wiring._timeline_vm
    vm.level = __import__(
        "app.presentation.views.timeline_rows", fromlist=["ScaleUnit"]
    ).ScaleUnit.MONTH
    widget.update_events(vm.events)
    await helpers.wait_until_settled()
    assert widget._vm.level.name == "MONTH"
    assert all(e.name != "Ранний" for e in view.events)  # excluded by the window

    # …and the search result for that very event must still reach it.
    window.search_bar.result_selected.emit("event", early_id)
    await helpers.wait_until_settled()

    assert vm.level.name == "DAY"                      # ladder descended
    assert vm.window is None                           # «Все дни» reset
    assert widget._vm.level.name == "DAY"                    # the tape followed
    assert view.window == (None, None)
    assert view.selected_id == early_id                # card highlighted
    assert view.index_for_event(early_id) is not None  # …and pictured, visible
    assert vm.selected_event is not None and vm.selected_event.name == "Ранний"


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
        modal_qdialog, sub._related_sections["locations"], "Цех"
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

    await helpers.create_related_via_popup(
        window, wait_for, modal_qdialog, dialog, "characters", "character", "Не сохранится"
    )
    # The (failing) save task already ran before the popup closed.
    await helpers.wait_until_settled()

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
        window, wait_for, modal_qdialog, dialog, "characters", "character", "Фантом"
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


# ── the tape's write branches: a commit that fails, a payload that is not one ──

async def test_date_move_failure_reports_once_even_when_the_rollback_fails(
    app, wait_for, monkeypatch, message_boxes
):
    """on_event_dates_moved: the write fails, the rollback itself fails (the
    inner guard swallows it), the tape reloads the stored dates and exactly one
    modal error is shown."""
    application, window = app
    await helpers.create_event_via_ui(
        window, wait_for, "Держись",
        start_date=QDate(1200, 3, 1), end_date=QDate(1200, 3, 2),
    )
    widget = window.timeline_widget
    view = timeline_probe.tape(window)
    await wait_for(lambda: len(view.events) == 1)
    event_id = view.events[0].id

    async def boom_update(*args, **kwargs):
        raise RuntimeError("db write failed")

    session = application._wiring._event_service._session
    real_rollback = session.rollback
    attempts: list[str] = []

    async def flaky_rollback():
        attempts.append("rollback")
        if len(attempts) == 1:
            raise RuntimeError("rollback itself failed")
        await real_rollback()

    monkeypatch.setattr(EventService, "update_event", boom_update)
    monkeypatch.setattr(type(session), "rollback", lambda _s: flaky_rollback())

    widget.event_dates_moved.emit(
        event_id, datetime.date(1200, 4, 1), datetime.date(1200, 4, 2),
    )
    await wait_for(lambda: any(kind == "critical" for kind, _, _ in message_boxes))
    await helpers.wait_until_settled()

    assert attempts == ["rollback"]  # the swallowed failure happened once
    assert [text for kind, _, text in message_boxes if kind == "critical"] == [
        "Не удалось сохранить даты события: db write failed"
    ]
    # The reload after the failed write shows what is actually stored
    await wait_for(lambda: view.events[0].start_date == datetime.date(1200, 3, 1))


async def test_inline_create_without_a_day_or_a_name_creates_nothing(
    app, wait_for, message_boxes
):
    """The widget normally filters these out; the wiring must agree with it and
    treat a missing day or a blank draft as no create at all."""
    application, window = app
    db_path = application._db_path

    window.timeline_widget.event_create_requested.emit(None, "Имя без дня")
    window.timeline_widget.event_create_requested.emit(
        datetime.date(1200, 3, 5), "   ",
    )
    await helpers.wait_until_settled()

    assert query_db(db_path, "SELECT COUNT(*) FROM events")[0][0] == 0
    assert message_boxes == []


async def test_inline_create_failure_repaints_the_tape_and_reports_once(
    app, wait_for, monkeypatch, message_boxes
):
    """create_event_at re-raises over its own rollback: the old tape stays
    truthful and exactly one modal error names the failure."""
    application, window = app
    await helpers.create_event_via_ui(
        window, wait_for, "Якорь",
        start_date=QDate(1200, 3, 1), end_date=QDate(1200, 3, 1),
    )
    view = timeline_probe.tape(window)
    await wait_for(lambda: len(view.events) == 1)

    async def boom_create(*args, **kwargs):
        raise RuntimeError("db write failed")

    monkeypatch.setattr(EventService, "create_event", boom_create)

    window.timeline_widget.event_create_requested.emit(
        datetime.date(1200, 3, 5), "Не создастся",
    )
    await wait_for(lambda: any(kind == "critical" for kind, _, _ in message_boxes))
    await helpers.wait_until_settled()

    assert [text for kind, _, text in message_boxes if kind == "critical"] == [
        "Не удалось создать событие: db write failed"
    ]
    await wait_for(lambda: len(view.events) == 1)
    assert [e.name for e in view.events] == ["Якорь"]


async def test_inline_create_without_a_record_stops_before_the_panel(
    app, wait_for, monkeypatch, message_boxes
):
    """No record came back (the ViewModel's own empty-name guard): no card is
    selected, the detail panel stays empty and no error is shown."""
    application, window = app
    view = timeline_probe.tape(window)
    seen: list[tuple] = []

    async def no_record(day, name):
        seen.append((day, name))
        return None

    monkeypatch.setattr(application._wiring._timeline_vm, "create_event_at", no_record)

    window.timeline_widget.event_create_requested.emit(
        datetime.date(1200, 3, 5), "Черновик",
    )
    await helpers.wait_until_settled()

    assert seen == [(datetime.date(1200, 3, 5), "Черновик")]
    assert message_boxes == []
    assert view.selected_id is None


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
