"""E2E scenario 5: case-insensitive search across entities and events."""
from __future__ import annotations

import json
from datetime import date

from app.presentation.views.event_dialog import EventDialog

from tests.presentation.qml_helpers import click_item, find_item, island_rows
from tests.ui import helpers, timeline_probe
from tests.ui.conftest import query_db


def _result_texts(bar) -> list[str]:
    return [row["text"] for row in bar._vm.rows]


async def test_search_is_case_insensitive(app, wait_for):
    application, window = app

    # Seed: a character and an event with distinctive names.
    await application._entity_services["character"].create_entity(
        name="Архимаг Вельзариан",
        characteristics="Повелитель тайн",
        backstory="",
        start_date=date(1199, 1, 1),
        end_date=date(1199, 12, 31),
    )
    await application._session.commit()
    await application._entity_services["item"].create_entity(
        name="Меч Судьбы",
        characteristics="Клинок",
        backstory="",
        start_date=date(1199, 2, 1),
        end_date=date(1199, 12, 31),
    )
    await application._session.commit()

    bar = window.search_bar

    # Uppercase query finds the lowercase-stored character name.
    find_item(bar.quick, "searchInput").setProperty("text", "ВЕЛЬЗАРИАН")
    click_item(bar.quick, find_item(bar.quick, "searchButton"))
    await wait_for(lambda: any("Архимаг Вельзариан" in t for t in _result_texts(bar)))
    assert any("Персонажи" in t for t in _result_texts(bar))  # section header present

    # Mixed-case query finds an item.
    find_item(bar.quick, "searchInput").setProperty("text", "меч суд")
    click_item(bar.quick, find_item(bar.quick, "searchButton"))
    await wait_for(lambda: any("Меч Судьбы" in t for t in _result_texts(bar)))


# ── NRI-0022 task 6.2: the result gestures ─────────────────────────────────


def _washed_ids(model) -> list[int]:
    """entityIds of the rows the panel currently washes as selected (the
    NRI-0025 task 6.1 pin reads it EMPTY: an entity click must wash nothing)."""
    return [
        int(row["entityId"])
        for row in helpers.detail_panel_rows(model)
        if row["selected"]
    ]


def _current_tab(window) -> int:
    return int(window.detail_panel.quick.rootObject().property("currentTab"))


def _shown_name(window) -> str:
    # The list VM since NRI-0025 task 2.1. Since task 6.1 the search's single
    # click addresses the LIVE area, so the trailing unpinned pane is exactly
    # what the click had to show (zero pins — the click cannot pin anything).
    panes = window.entity_preview.vm.panes
    if panes and not panes[-1]["pinned"]:
        return panes[-1]["nameText"]
    return ""


async def _seed_entity_and_two_events(application, window, wait_for):
    """One character linked into two events through the real event service,
    then the scale re-reads the sample. Since task 6.1 the events exist only
    as the PROVOCATION the retired full path would have chased: the click on
    the character must leave the scale and the panel untouched whatever
    events the entity participates in. Returns (char_id, late_id)."""
    wiring = application._wiring
    char = await application._entity_services["character"].create_entity(
        name="Банн", characteristics="", backstory="",
        start_date=date(1199, 1, 1), end_date=None,
    )
    await application._session.commit()
    await wiring.event_service.create_event_with_relations(
        name="Раннее", start_date=date(1200, 3, 1), end_date=date(1200, 3, 2),
        characteristics="", backstory="",
        relations={"characters": [{"_existing_id": char.id}]},
    )
    late = await wiring.event_service.create_event_with_relations(
        name="Позднее", start_date=date(1200, 10, 1), end_date=date(1200, 10, 2),
        characteristics="", backstory="",
        relations={"characters": [{"_existing_id": char.id}]},
    )
    await wiring.timeline_vm.load_events()
    window.timeline_widget.update_events(wiring.timeline_vm.events)
    await helpers.wait_until_settled()
    return char.id, late.id


# ── NRI-0025 task 6.1: an entity click addresses the live area only ───────


def _press_pin(window, entity_type: str, entity_id: int, pinned: bool) -> None:
    """A pin press as the island emits it: pair + the card's current state
    (the same seam tests/ui/test_e2e_preview_pins.py drives)."""
    window.entity_preview.pin_toggle_requested.emit(entity_type, entity_id, pinned)


def _panes(window) -> list[dict]:
    return window.entity_preview.vm.panes


def _signature(window) -> list[tuple[bool, int]]:
    """What the column shows: (pinned, entityId) per pane, top to bottom
    (the same reading tests/ui/test_e2e_preview_pins.py pins with)."""
    return [(bool(p["pinned"]), int(p["entityId"])) for p in _panes(window)]


async def test_left_click_on_entity_result_shows_only_the_live_preview(
    app, wait_for
):
    """Spec «Сущность показывается только в предпросмотре» (full path abolished,
    design Д7): the character swims in two events and the June window cuts
    «Позднее» out of the visible slice — exactly the configuration the retired
    requirement used to chase. The single click must now show the character
    in the live area AND NOTHING ELSE: no event selection, no window reset
    («Все дни» must NOT be entered), no tab switch, no row wash; the results
    list collapses with the gesture."""
    application, window = app
    bar = window.search_bar
    char_id, late_id = await _seed_entity_and_two_events(
        application, window, wait_for
    )
    canvas = timeline_probe.tape(window)

    # The user narrows the window to June: «Позднее» leaves the visible slice.
    # Under the retired full path the click would have reset it to «Все дни».
    window.timeline_widget._on_window_range(date(1200, 6, 1), date(1200, 6, 30))
    await helpers.wait_until_settled()
    assert all(e.name != "Позднее" for e in canvas.events)
    tab_before = _current_tab(window)

    find_item(bar.quick, "searchInput").setProperty("text", "Банн")
    click_item(bar.quick, find_item(bar.quick, "searchButton"))
    await wait_for(lambda: any("Банн" in t for t in _result_texts(bar)))
    # The delegate materialization rides the render pass; the grab-driven
    # probe re-runs until the scene has grown its single row (events do not
    # match the query, so the character row is alone).
    await wait_for(lambda: len(island_rows(bar.quick, "searchResultRow")) == 1)
    qt_rows = island_rows(bar.quick, "searchResultRow")

    click_item(bar.quick, qt_rows[0])  # single left click — live area only
    await wait_for(lambda: _shown_name(window) == "Банн")
    await helpers.wait_until_settled()

    wiring_vm = application._wiring._timeline_vm
    assert wiring_vm.window is not None                # no «Все дни» reset
    assert canvas.window == (date(1200, 6, 1), date(1200, 6, 30))
    assert canvas.selected_id is None                  # no event got chosen
    assert canvas.selected_id != late_id               # …not even the late one
    assert _current_tab(window) == tab_before          # the tab never moved
    assert _washed_ids(window.detail_panel.vm.characters) == []  # no row wash
    assert _shown_name(window) == "Банн"
    assert bar._vm.listVisible is False                # the list collapsed
    assert window.entity_preview.vm.panes[-1]["title"] == "Карточка: Персонаж · Банн"


async def test_left_click_on_entity_result_leaves_pinned_cards_as_they_were(
    app, wait_for, menu_qmenu
):
    """Spec «Закреплённые карточки поиск не трогает»: with a pinned card in
    the column the entity click fills ONLY the live area — the pinned card
    keeps its row untouched, and neither the pin list nor its storage moves.
    The click rides the connector's ``result_selected`` seam (the real QML
    gesture half is pinned by the test above; here the subject is the
    connector's addressing)."""
    application, window = app
    db_path = application._db_path
    await helpers.create_entity_via_context_menu(
        window, wait_for, menu_qmenu, "item", "Компас"
    )
    await helpers.wait_until_settled()
    comp_id = query_db(
        db_path, "SELECT id FROM items WHERE name = 'Компас'"
    )[0][0]
    window.detail_panel.entity_selected.emit("item", comp_id)
    await wait_for(lambda: _signature(window) == [(False, comp_id)])
    _press_pin(window, "item", comp_id, False)
    await wait_for(lambda: _signature(window) == [(True, comp_id)])

    char = await application._entity_services["character"].create_entity(
        name="Наёмница", characteristics="", backstory="",
        start_date=date(1200, 1, 1), end_date=None,
    )
    await application._session.commit()

    window.search_bar.result_selected.emit("character", char.id)
    # Only the live area fills; the pinned Компас and the storage stay put.
    await wait_for(lambda: _signature(window) == [(True, comp_id), (False, char.id)])
    await helpers.wait_until_settled()
    assert _panes(window)[0]["nameText"] == "Компас"
    assert _panes(window)[0]["pinned"] is True
    assert application._wiring._preview_pins == [("item", comp_id)]
    assert application._wiring._preview_live == ("character", char.id)
    raw = dict(query_db(db_path, "SELECT key, value FROM game_settings")).get(
        "preview_pins"
    )
    assert json.loads(raw) == [{"t": "item", "i": comp_id}]
    # The scale stays untouched by the entity click too (spec scenarios).
    assert timeline_probe.tape(window).selected_id is None


async def test_double_click_on_event_result_opens_the_editor(app, wait_for):
    """Spec «Событие открывается редактором двойным кликом»: the edit gesture
    on an event result opens the event editor (no scale selection happens)."""
    application, window = app
    await helpers.create_event_via_ui(window, wait_for, "Редактируемое")
    event_id = helpers.find_event_id(window, "Редактируемое")
    canvas = timeline_probe.tape(window)

    window.search_bar.result_activated.emit("event", event_id)
    await wait_for(
        lambda: any(d.isVisible() for d in window.findChildren(EventDialog))
    )
    assert canvas.selected_id is None  # the edit gesture does not select
