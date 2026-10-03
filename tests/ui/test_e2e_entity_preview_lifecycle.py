"""E2E lifecycle of the entity preview (NRI-0022, tasks 5.1/5.2).

The wiring owns the preview lifecycle (design D2/D4): the one selection bus
runs middle→right (single-click selection loads through the entity service
into the preview) and right→middle (relation/mention activation shows and
tries the tab+row highlight, a no-op outside the current lists, the scale
never touched); event selection on the scale leaves the shown entity in
place; the popup-cleanup delete and the shown entity's own card save are the
two lifecycle signals; a game restart rebuilds the connector, so the fresh
preview starts empty.

Island-level behaviour (the composition, the picture, the Press contracts) is
pinned offscreen in tests/presentation/test_entity_preview_island.py; here the
bus itself is driven the way the user's gestures leave it — through the panel
VM's ``select`` slot and the preview's ``entity_requested`` relay signal (the
address seams the wiring layer established for its other widgets).
"""
from __future__ import annotations

from datetime import date

from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog

from tests.ui import helpers, timeline_probe
from tests.ui.conftest import query_db

#: Event-dialog tab widget per relation attr (the dialog's own attr names).
_EVENT_TAB = {
    "characters": "char_tab",
    "items": "item_tab",
    "locations": "loc_tab",
    "organizations": "org_tab",
}

#: event-dialog relation attr -> entity type key.
_ATTR_TYPE = {
    "characters": "character",
    "items": "item",
    "locations": "location",
    "organizations": "organization",
}

#: entity type -> (relation table, id column) for the event-link assertions.
_REL = {
    "character": ("event_character", "character_id"),
    "organization": ("event_organization", "organization_id"),
    "item": ("event_item", "item_id"),
    "location": ("event_location", "location_id"),
}


def _entity_id(db_path, entity_type: str, name: str) -> int:
    table = helpers.ENTITY_TABLES[entity_type]
    return query_db(db_path, f"SELECT id FROM {table} WHERE name = ?", (name,))[0][0]


async def _create_entity(
    window, wait_for, menu_qmenu, db_path, entity_type: str, name: str
) -> int:
    """Create one standalone entity through the timeline '+' menu and wait
    for its row to reach the database (the helper itself only saves the card)."""
    await helpers.create_entity_via_context_menu(
        window, wait_for, menu_qmenu, entity_type, name
    )
    table = helpers.ENTITY_TABLES[entity_type]
    await wait_for(
        lambda: len(
            query_db(db_path, f"SELECT id FROM {table} WHERE name = ?", (name,))
        ) == 1
    )
    await helpers.wait_until_settled()
    return _entity_id(db_path, entity_type, name)


def _washed_ids(model) -> list[int]:
    """entityIds of the rows the panel currently washes as selected."""
    return [
        int(row["entityId"])
        for row in helpers.detail_panel_rows(model)
        if row["selected"]
    ]


def _current_tab(window) -> int:
    return int(window.detail_panel.quick.rootObject().property("currentTab"))


def _tab_of(window, entity_type: str) -> int:
    return window.detail_panel.vm.ENTITY_TYPES.index(entity_type)


def _live_pane(window):
    """The live pane's dict or ``None`` while the live area is empty. The VM
    is the list face since NRI-0025 task 2.1 and the connector frames are its
    slot frames since task 5.1; frames are built live-last, so the trailing
    unpinned pane IS the live area."""
    panes = window.entity_preview.vm.panes
    if panes and not panes[-1]["pinned"]:
        return panes[-1]
    return None


def _shown_name(window) -> str:
    pane = _live_pane(window)
    return pane["nameText"] if pane is not None else ""


async def _open_card(window, wait_for, entity_type: str, entity_id: int) -> EntityCardDialog:
    """Open the editable card through the panel's activation seam (the
    double-click path) and return the visible dialog."""
    window.detail_panel.entity_clicked.emit(entity_type, entity_id)
    await wait_for(
        lambda: any(
            d.isVisible() and d._entity_type == entity_type
            for d in window.findChildren(EntityCardDialog)
        )
    )
    return next(
        d for d in window.findChildren(EntityCardDialog)
        if d.isVisible() and d._entity_type == entity_type
    )


async def _create_linked_event(
    app_fixtures, event_name: str, links: list[tuple[str, str]]
) -> int:
    """Create ``event_name`` through the UI and link ``links`` (attr, entity
    name) pairs into it via the edit dialog; returns the event id."""
    window, wait_for, modal_qdialog, db_path = app_fixtures
    await helpers.create_event_via_ui(window, wait_for, event_name)
    event_id = helpers.find_event_id(window, event_name)
    helpers.double_click_timeline_event(window, event_name)
    await wait_for(lambda: any(d.isVisible() for d in window.findChildren(EventDialog)))
    dialog = next(d for d in window.findChildren(EventDialog) if d.isVisible())
    for attr, name in links:
        tab = getattr(dialog, _EVENT_TAB[attr])
        await helpers.link_existing_entity_in_tab(window, wait_for, tab, name)
        await wait_for(
            lambda t=tab, n=name: any(
                n in t.list_widget.item(i).text()
                for i in range(t.list_widget.count())
            )
        )
    dialog.save_button.click()
    for attr, name in links:
        entity_type = _ATTR_TYPE[attr]
        rel_table, rel_col = _REL[entity_type]
        entity_id = _entity_id(db_path, entity_type, name)
        await wait_for(
            lambda rt=rel_table, rc=rel_col, e=event_id, i=entity_id: len(
                query_db(db_path, f"SELECT 1 FROM {rt} WHERE event_id = ? AND {rc} = ?", (e, i),)
            ) == 1
        )
    await helpers.wait_until_settled()
    return event_id


# ── task 5.1: the selection bus round-trips through the wiring ──────────────

async def test_selection_bus_round_trips_middle_to_preview_and_back(
    app, wait_for, menu_qmenu, modal_qdialog
):
    application, window = app
    db_path = application._db_path
    ban_id = await _create_entity(
        window, wait_for, menu_qmenu, db_path, "character", "Банн"
    )
    grot_id = await _create_entity(
        window, wait_for, menu_qmenu, db_path, "location", "Грот"
    )
    ten_id = await _create_entity(
        window, wait_for, menu_qmenu, db_path, "character", "Тень"
    )
    event_id = await _create_linked_event(
        (window, wait_for, modal_qdialog, db_path),
        "Собрание",
        [("characters", "Банн"), ("locations", "Грот")],
    )
    helpers.click_timeline_event(window, "Собрание")
    await wait_for(
        lambda: "Банн" in helpers.detail_panel_names(window.detail_panel.vm.characters)
    )
    # The event-save handler already showed the details unconditionally, so
    # the rows can predate this click; settle the click's own load task before
    # selecting, or its show_event re-render would paint out the selection.
    await helpers.wait_until_settled()
    canvas = timeline_probe.tape(window)

    # Middle → right: the production single-click slot feeds the wiring, the
    # wiring loads through the entity service and shows the read-only card.
    window.detail_panel.vm.select("character", ban_id)
    await wait_for(lambda: _shown_name(window) == "Банн")
    assert _live_pane(window)["title"] == "Карточка: Персонаж · Банн"
    assert _washed_ids(window.detail_panel.vm.characters) == [ban_id]
    assert canvas.selected_id == event_id  # the scale was not touched
    # The selection opened no card: selection and activation stay separate.
    assert not [d for d in window.findChildren(EntityCardDialog) if d.isVisible()]

    # Right → middle (row inside the current lists): show + switch the type's
    # tab + wash the row; the previous wash leaves the other tab (spec «Переход
    # по связи»), the scale stays where it was.
    window.entity_preview.entity_requested.emit("location", grot_id)
    await wait_for(lambda: _shown_name(window) == "Грот")
    await wait_for(lambda: _current_tab(window) == _tab_of(window, "location"))
    assert _washed_ids(window.detail_panel.vm.locations) == [grot_id]
    assert _washed_ids(window.detail_panel.vm.characters) == []
    assert window.detail_panel.vm.last_selected == ("location", grot_id)
    assert canvas.selected_id == event_id

    # Right → middle (row OUTSIDE the current lists): the preview shows it,
    # the middle column does not switch and keeps its previous wash (spec
    # «Связь вне текущего списка»), the scale is still untouched.
    window.entity_preview.entity_requested.emit("character", ten_id)
    await wait_for(lambda: _shown_name(window) == "Тень")
    await helpers.wait_until_settled()
    assert _current_tab(window) == _tab_of(window, "location")
    assert _washed_ids(window.detail_panel.vm.locations) == [grot_id]
    assert window.detail_panel.vm.last_selected == ("location", grot_id)
    assert canvas.selected_id == event_id


# ── task 5.2: the lifecycle rule — what moves the preview and what does not ─

async def test_event_selection_and_deselect_leave_the_preview_untouched(
    app, wait_for, menu_qmenu, modal_qdialog
):
    application, window = app
    db_path = application._db_path
    ban_id = await _create_entity(
        window, wait_for, menu_qmenu, db_path, "character", "Банн"
    )
    await helpers.create_event_via_ui(
        window, wait_for, "Осень", start_date=date(1300, 10, 1), end_date=date(1300, 10, 20)
    )
    # Link Банн into Осень through the event edit dialog, then select it.
    helpers.double_click_timeline_event(window, "Осень")
    await wait_for(lambda: any(d.isVisible() for d in window.findChildren(EventDialog)))
    dialog = next(d for d in window.findChildren(EventDialog) if d.isVisible())
    await helpers.link_existing_entity_in_tab(
        window, wait_for, dialog.char_tab, "Банн"
    )
    dialog.save_button.click()
    await wait_for(
        lambda: len(query_db(db_path, "SELECT 1 FROM event_character")) == 1
    )
    await helpers.wait_until_settled()

    helpers.click_timeline_event(window, "Осень")
    await wait_for(
        lambda: "Банн" in helpers.detail_panel_names(window.detail_panel.vm.characters)
    )
    await helpers.wait_until_settled()  # the click's detail load task is done
    window.detail_panel.vm.select("character", ban_id)
    await wait_for(lambda: _shown_name(window) == "Банн")

    # Another event on the scale: the detail panel re-models over it, the
    # preview keeps the shown character (spec «Смена события предпросмотр не
    # трогает») even though Банн is no longer in any shown list.
    await helpers.create_event_via_ui(
        window, wait_for, "Весна", start_date=date(1301, 3, 1), end_date=date(1301, 3, 10)
    )
    helpers.click_timeline_event(window, "Весна")
    await wait_for(lambda: window.detail_panel.vm.title == "Весна")
    await helpers.wait_until_settled()
    assert _shown_name(window) == "Банн"
    assert window.detail_panel.vm.last_selected == ("character", ban_id)

    # Deselecting the event (a date window that excludes it prunes the
    # selection, detail panel cleared): still no preview movement.
    window.timeline_widget.window_changed.emit(date(1400, 1, 1), date(1400, 12, 31))
    await wait_for(lambda: window.detail_panel.vm.title == "")
    await helpers.wait_until_settled()
    assert _shown_name(window) == "Банн"


async def test_deleting_the_shown_entity_and_a_restart_clear_the_preview(
    app, wait_for, menu_qmenu, modal_qdialog
):
    application, window = app
    db_path = application._db_path
    ban_id = await _create_entity(
        window, wait_for, menu_qmenu, db_path, "character", "Банн"
    )

    # The connector's entity-delete channel: an entity created in the card's
    # popup is deleted when the card is REJECTED (the popup cleanup). Preview
    # the popup child first, then reject — the right column must fall back to
    # its self-explaining empty state (spec «Удаление показанной сущности»).
    card = await _open_card(window, wait_for, "character", ban_id)
    await helpers.create_related_via_popup(
        window, wait_for, card, "locations", "location", "Пещера"
    )
    peshchera_id = _entity_id(db_path, "location", "Пещера")
    window.entity_preview.entity_requested.emit("location", peshchera_id)
    await wait_for(lambda: _shown_name(window) == "Пещера")

    card.reject()
    await wait_for(lambda: _live_pane(window) is None)
    # The zero-pane column is the empty state; its «Карточка» caption is the
    # painting-side literal pinned offscreen in test_entity_preview_island.py.
    assert window.entity_preview.vm.panes == []
    # The delete really happened (the cleanup ran, this is not a stale view).
    assert query_db(db_path, "SELECT 1 FROM locations WHERE name = ?", ("Пещера",)) == []

    # Restart = the game shutdown → start flow the game switch also runs
    # (_on_game_selected does exactly these two calls): the rebuilt connector
    # restores the saved pins — nothing was ever pinned here, so the fresh
    # preview starts empty.
    window.close()
    await helpers.wait_until_settled()
    await application.shutdown()
    window2 = await application.start(str(db_path))
    try:
        await helpers.wait_until_settled()
        assert window2.entity_preview.vm.panes == []
    finally:
        window2.close()
        await helpers.wait_until_settled()


async def test_card_save_refreshes_only_the_shown_entity(
    app, wait_for, menu_qmenu, modal_qdialog
):
    application, window = app
    db_path = application._db_path
    ban_id = await _create_entity(
        window, wait_for, menu_qmenu, db_path, "character", "Банн"
    )
    arrow_id = await _create_entity(
        window, wait_for, menu_qmenu, db_path, "item", "Стрела"
    )
    await _create_linked_event(
        (window, wait_for, modal_qdialog, db_path),
        "Собрание",
        [("characters", "Банн"), ("items", "Стрела")],
    )
    helpers.click_timeline_event(window, "Собрание")
    await wait_for(
        lambda: "Банн" in helpers.detail_panel_names(window.detail_panel.vm.characters)
    )
    await helpers.wait_until_settled()  # see the round-trip test's note
    window.detail_panel.vm.select("character", ban_id)
    await wait_for(lambda: _shown_name(window) == "Банн")

    # A foreign save: the item's card saves successfully, the detail panel
    # re-models with the new name, the preview keeps the character untouched.
    arrow_card = await _open_card(window, wait_for, "item", arrow_id)
    arrow_card.name_input.setText("Стрела-2")
    arrow_card.save_button.click()
    await wait_for(
        lambda: "Стрела-2" in helpers.detail_panel_names(window.detail_panel.vm.items)
    )
    await helpers.wait_until_settled()
    assert _shown_name(window) == "Банн"
    assert _live_pane(window)["entityId"] == ban_id

    # The shown entity's own save repaints the preview with the stored values
    # (spec «Сохранение карточки обновляет предпросмотр»).
    ban_card = await _open_card(window, wait_for, "character", ban_id)
    ban_card.name_input.setText("Банн-2")
    ban_card.save_button.click()
    # The wait rides the RENDERED text, not the shown name: the service
    # updates the session-identity-mapped row in place mid-transaction, so
    # the live row's name flips before the save task repaints the island.
    await wait_for(lambda: _shown_name(window) == "Банн-2")
    assert _live_pane(window)["title"] == "Карточка: Персонаж · Банн-2"
    assert _live_pane(window)["nameText"] == "Банн-2"


# ── guards: dead bus entries leave the shown state alone, never raise ───────

async def test_preview_bus_guards_unknown_types_and_vanished_rows(app, wait_for):
    application, window = app
    # A dead type key and a vanished id on both faces of the bus: silent
    # no-ops — the preview keeps its empty state, no card opens.
    window.detail_panel.entity_selected.emit("no-such-type", 1)
    window.detail_panel.entity_selected.emit("character", 999999)
    window.entity_preview.entity_requested.emit("event", 1)
    window.entity_preview.entity_requested.emit("character", 999999)
    await helpers.wait_until_settled()
    assert _live_pane(window) is None
    assert not [d for d in window.findChildren(EntityCardDialog) if d.isVisible()]

    # The facade's programmatic selection is defensive the same way: a type
    # with no tab and a pair outside the shown lists change nothing.
    window.detail_panel.select_entity("no-such-type", 1)
    window.detail_panel.select_entity("character", 999999)
    assert _current_tab(window) == 0
    assert _live_pane(window) is None

