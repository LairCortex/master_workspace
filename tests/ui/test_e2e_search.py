"""E2E scenario 5: case-insensitive search across entities and events."""
from __future__ import annotations

from datetime import date

from app.presentation.views.event_dialog import EventDialog

from tests.presentation.qml_helpers import click_item, find_item, island_rows
from tests.ui import helpers, timeline_probe


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


def _shown_name(window) -> str:
    return getattr(window.entity_preview.vm.shown_entity, "name", "")


async def _seed_entity_and_two_events(application, window, wait_for):
    """One character linked into two events through the real event service
    (the latest by start is «Позднее»), then the scale re-reads the sample.
    Returns (char_id, late_id)."""
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


async def test_left_click_on_entity_result_walks_the_full_path(app, wait_for):
    """Spec «Сущность ведёт полный путь» (+ «Событие вне окна фильтрации»):
    the single click on the character result selects the character's
    latest-by-start event — the June window resets to «Все дни» — switches
    the panel to the character tab, washes its row and shows the preview;
    the results list collapses with the gesture."""
    application, window = app
    bar = window.search_bar
    char_id, late_id = await _seed_entity_and_two_events(
        application, window, wait_for
    )
    canvas = timeline_probe.tape(window)

    # The user narrows the window to June: «Позднее» leaves the visible slice
    # exactly like in the «Внешний выбор вне окна» scenario.
    window.timeline_widget._on_window_range(date(1200, 6, 1), date(1200, 6, 30))
    await helpers.wait_until_settled()
    assert all(e.name != "Позднее" for e in canvas.events)

    find_item(bar.quick, "searchInput").setProperty("text", "Банн")
    click_item(bar.quick, find_item(bar.quick, "searchButton"))
    await wait_for(lambda: any("Банн" in t for t in _result_texts(bar)))
    # The delegate materialization rides the render pass; the grab-driven
    # probe re-runs until the scene has grown its single row (events do not
    # match the query, so the character row is alone).
    await wait_for(lambda: len(island_rows(bar.quick, "searchResultRow")) == 1)
    qt_rows = island_rows(bar.quick, "searchResultRow")

    click_item(bar.quick, qt_rows[0])  # single left click — the full path
    await wait_for(lambda: _shown_name(window) == "Банн")
    await helpers.wait_until_settled()

    wiring_vm = application._wiring._timeline_vm
    assert wiring_vm.window is None                    # window reset «в Все дни»
    assert canvas.window == (None, None)               # the list followed
    assert canvas.selected_id == late_id               # the LATER event is lit
    assert _current_tab(window) == _tab_of(window, "character")
    assert _washed_ids(window.detail_panel.vm.characters) == [char_id]
    assert _shown_name(window) == "Банн"
    assert bar._vm.listVisible is False                # the list collapsed
    assert window.entity_preview.vm.title == "Карточка: Персонаж"


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
