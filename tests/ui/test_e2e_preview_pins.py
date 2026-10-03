"""E2E lifecycle of the preview slots and the pin (NRI-0025, tasks 5.1–5.3).

The connector owns the slot rules (design Д1/Д3/Д4); this file drives them
the way the user's gestures leave them: selections ride the middle→right bus
(``entity_selected``), transitions from ANY pane ride the right→middle bus
(``entity_requested`` — the payload never names the source pane), and every
pin press rides the island's relay (``pin_toggle_requested``) exactly as the
QML seat emits it. Pinned: the split with the live area cleared, the fourth
pin rejected on the screen AND in the model, conscious duplicates, unpin
never eating the live copy, the card save repainting every copy, deletes
lifting pins in the column and in storage, restarts restoring the order, a
stale saved pair dropping silently without a storage rewrite, and the event
scale leaving the whole column alone.

The private model guards (stale presses, pin-less unpins, the no-service
connectors) are unit-pinned in
tests/presentation/test_wiring_preview_slots.py.
"""
from __future__ import annotations

import json
import sqlite3
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

#: entity type -> (relation table, id column) for the event-link assertions.
_REL = {
    "character": ("event_character", "character_id"),
    "organization": ("event_organization", "organization_id"),
    "item": ("event_item", "item_id"),
    "location": ("event_location", "location_id"),
}

_ATTR_TYPE = {
    "characters": "character",
    "items": "item",
    "locations": "location",
    "organizations": "organization",
}


def _entity_id(db_path, entity_type: str, name: str) -> int:
    table = helpers.ENTITY_TABLES[entity_type]
    return query_db(db_path, f"SELECT id FROM {table} WHERE name = ?", (name,))[0][0]


async def _create_entity(
    window, wait_for, menu_qmenu, db_path, entity_type: str, name: str
) -> int:
    """Create one standalone entity through the timeline '+' menu and wait
    for its row to reach the database."""
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


def _pins_storage(db_path) -> list[dict]:
    """The raw stored pin list (design Д3 body ``[{"t", "i"}]``); absent key
    reads as the empty list, like the repository does."""
    raw = dict(query_db(db_path, "SELECT key, value FROM game_settings")).get(
        "preview_pins"
    )
    return [] if raw is None else json.loads(raw)


def _select(window, entity_type: str, entity_id: int) -> None:
    """The middle column's single-click selection seam (the bus the panel
    emits and the wiring consumes)."""
    window.detail_panel.entity_selected.emit(entity_type, entity_id)


def _press_pin(window, entity_type: str, entity_id: int, pinned: bool) -> None:
    """A pin press as the island emits it: pair + the card's current state."""
    window.entity_preview.pin_toggle_requested.emit(entity_type, entity_id, pinned)


def _panes(window) -> list[dict]:
    return window.entity_preview.vm.panes


def _signature(window) -> list[tuple[bool, int]]:
    """What the column shows: (pinned, entityId) per pane, top to bottom."""
    return [(bool(p["pinned"]), int(p["entityId"])) for p in _panes(window)]


def _live_pane(window):
    """The trailing unpinned pane — frames are built live-last."""
    panes = _panes(window)
    return panes[-1] if panes and not panes[-1]["pinned"] else None


def _current_tab(window) -> int:
    return int(window.detail_panel.quick.rootObject().property("currentTab"))


def _tab_of(window, entity_type: str) -> int:
    return window.detail_panel.vm.ENTITY_TYPES.index(entity_type)


def _washed_ids(model) -> list[int]:
    return [
        int(row["entityId"])
        for row in helpers.detail_panel_rows(model)
        if row["selected"]
    ]


async def _open_card(window, wait_for, entity_type: str, entity_id: int):
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


async def _restart(application, db_path):
    """The game switch's own contour: shutdown → start returns the rebuilt
    main window (the new connector restores the saved pins on the way)."""
    await helpers.wait_until_settled()
    await application.shutdown()
    return await application.start(str(db_path))


# ── task 5.1: the slot transitions on the screen ─────────────────────────────


async def test_first_pin_splits_the_column_clears_live_and_persists(
    app, wait_for, menu_qmenu
):
    application, window = app
    db_path = application._db_path
    ban_id = await _create_entity(
        window, wait_for, menu_qmenu, db_path, "character", "Банн"
    )
    _select(window, "character", ban_id)
    await wait_for(lambda: _signature(window) == [(False, ban_id)])

    _press_pin(window, "character", ban_id, False)
    # spec «Первое закрепление делит колонку»: the card stays on screen as a
    # pin, the live area falls empty, storage carries the one pair.
    await wait_for(lambda: _signature(window) == [(True, ban_id)])
    pane = _panes(window)[0]
    assert pane["title"] == "Карточка: Персонаж · Банн"
    assert pane["nameText"] == "Банн"
    assert window.entity_preview.vm.liveEmpty is True
    assert application._wiring._preview_pins == [("character", ban_id)]
    assert application._wiring._preview_live is None
    assert _pins_storage(db_path) == [{"t": "character", "i": ban_id}]


async def test_unpin_removes_the_card_and_leaves_the_live_area(
    app, wait_for, menu_qmenu
):
    application, window = app
    db_path = application._db_path
    ban_id = await _create_entity(
        window, wait_for, menu_qmenu, db_path, "character", "Банн"
    )
    grot_id = await _create_entity(
        window, wait_for, menu_qmenu, db_path, "location", "Грот"
    )
    _select(window, "character", ban_id)
    await wait_for(lambda: _signature(window) == [(False, ban_id)])
    _press_pin(window, "character", ban_id, False)
    await wait_for(lambda: _signature(window) == [(True, ban_id)])
    _select(window, "location", grot_id)
    await wait_for(lambda: _signature(window) == [(True, ban_id), (False, grot_id)])

    _press_pin(window, "character", ban_id, True)
    # spec «Открепление убирает карточку»: the pin leaves, the live card of
    # Грот stays exactly where it was, storage follows immediately.
    await wait_for(lambda: _signature(window) == [(False, grot_id)])
    assert _pins_storage(db_path) == []


async def test_fourth_pin_rejected_on_screen_and_in_model(
    app, wait_for, menu_qmenu
):
    application, window = app
    db_path = application._db_path
    ids = []
    for i, name in enumerate(["А", "Б", "В", "Г"]):
        entity_id = await _create_entity(
            window, wait_for, menu_qmenu, db_path, "character", f"Копия {name}"
        )
        ids.append(entity_id)
        _select(window, "character", entity_id)
        await wait_for(lambda i=entity_id: _signature(window)[-1:] == [(False, i)])
        if i < 3:
            _press_pin(window, "character", entity_id, False)
            await wait_for(lambda n=i + 1: len(_panes(window)) == n)
    # Three pins + the fourth card live: the column is four equal panes.
    assert _signature(window) == [(True, i) for i in ids[:3]] + [(False, ids[3])]
    assert _live_pane(window)["pinState"] == "limit"

    _press_pin(window, "character", ids[3], False)
    await helpers.wait_until_settled()
    # The rejected fourth pin moves NOTHING — neither the screen nor the
    # model nor storage (the island cannot even press it; the connector is
    # the second lock, spec «Четвёртое закрепление невозможно»).
    assert _signature(window) == [(True, i) for i in ids[:3]] + [(False, ids[3])]
    assert application._wiring._preview_pins == [("character", i) for i in ids[:3]]
    assert _pins_storage(db_path) == [{"t": "character", "i": i} for i in ids[:3]]


async def test_duplicate_live_copy_and_noop_reselect(
    app, wait_for, menu_qmenu
):
    application, window = app
    db_path = application._db_path
    ban_id = await _create_entity(
        window, wait_for, menu_qmenu, db_path, "character", "Банн"
    )
    _select(window, "character", ban_id)
    await wait_for(lambda: _signature(window) == [(False, ban_id)])
    _press_pin(window, "character", ban_id, False)
    await wait_for(lambda: _signature(window) == [(True, ban_id)])

    # Selecting the pinned entity again shows the CONSCIOUS duplicate (spec
    # «Выбор закреплённой сущности даёт дубль»); its pin cannot re-seat.
    _select(window, "character", ban_id)
    await wait_for(lambda: _signature(window) == [(True, ban_id), (False, ban_id)])
    assert _live_pane(window)["pinState"] == "duplicate"
    _press_pin(window, "character", ban_id, False)
    await helpers.wait_until_settled()
    assert _signature(window) == [(True, ban_id), (False, ban_id)]

    # A THIRD selection of the pair already live reloads nothing and pushes
    # no frame (spec «Повторный выбор ничего не делает»).
    repaints: list[int] = []
    window.entity_preview.vm.contentChanged.connect(lambda: repaints.append(1))
    loads: list[int] = []
    service = application._entity_services["character"]
    original_get = service.get_entity

    async def counting_get(entity_id):
        loads.append(entity_id)
        return await original_get(entity_id)

    service.get_entity = counting_get
    try:
        _select(window, "character", ban_id)
        await helpers.wait_until_settled()
    finally:
        service.get_entity = original_get
    assert loads == []
    assert repaints == []
    assert _signature(window) == [(True, ban_id), (False, ban_id)]
    assert _pins_storage(db_path) == [{"t": "character", "i": ban_id}]


async def test_unpin_of_a_duplicate_keeps_the_live_copy(
    app, wait_for, menu_qmenu
):
    application, window = app
    db_path = application._db_path
    ban_id = await _create_entity(
        window, wait_for, menu_qmenu, db_path, "character", "Банн"
    )
    _select(window, "character", ban_id)
    await wait_for(lambda: _signature(window) == [(False, ban_id)])
    _press_pin(window, "character", ban_id, False)
    await wait_for(lambda: _signature(window) == [(True, ban_id)])
    _select(window, "character", ban_id)
    await wait_for(lambda: _signature(window) == [(True, ban_id), (False, ban_id)])

    _press_pin(window, "character", ban_id, True)
    # spec «Открепление не съедает живую копию»: only the pinned copy leaves;
    # the shared loaded row keeps serving the live card.
    await wait_for(lambda: _signature(window) == [(False, ban_id)])
    assert _panes(window)[0]["nameText"] == "Банн"
    assert _pins_storage(db_path) == []


# ── task 5.2: storage through the connector ──────────────────────────────────


async def test_restart_restores_the_pins_in_order_live_empty(
    app, wait_for, menu_qmenu
):
    application, window = app
    db_path = application._db_path
    ban_id = await _create_entity(
        window, wait_for, menu_qmenu, db_path, "character", "Банн"
    )
    grot_id = await _create_entity(
        window, wait_for, menu_qmenu, db_path, "location", "Грот"
    )
    _select(window, "character", ban_id)
    await wait_for(lambda: _signature(window) == [(False, ban_id)])
    _press_pin(window, "character", ban_id, False)
    await wait_for(lambda: _signature(window) == [(True, ban_id)])
    _select(window, "location", grot_id)
    await wait_for(lambda: _signature(window) == [(True, ban_id), (False, grot_id)])
    _press_pin(window, "location", grot_id, False)
    await wait_for(lambda: _signature(window) == [(True, ban_id), (True, grot_id)])
    window.close()

    window2 = await _restart(application, db_path)
    try:
        # spec «Перезапуск сохраняет закрепления»: same order, live empty.
        assert _signature(window2) == [(True, ban_id), (True, grot_id)]
        assert window2.entity_preview.vm.liveEmpty is True
        assert _pins_storage(db_path) == [
            {"t": "character", "i": ban_id},
            {"t": "location", "i": grot_id},
        ]
    finally:
        window2.close()
        await helpers.wait_until_settled()


async def test_stale_saved_pair_drops_silently_without_a_rewrite(
    app, wait_for, menu_qmenu
):
    application, window = app
    db_path = application._db_path
    ban_id = await _create_entity(
        window, wait_for, menu_qmenu, db_path, "character", "Банн"
    )
    _select(window, "character", ban_id)
    await wait_for(lambda: _signature(window) == [(False, ban_id)])
    _press_pin(window, "character", ban_id, False)
    await wait_for(lambda: _signature(window) == [(True, ban_id)])
    window.close()
    await helpers.wait_until_settled()
    await application.shutdown()
    # The "another session deleted it" contour, written between the runs: the
    # saved list names a live pair and a vanished one.
    stale = json.dumps(
        [{"t": "character", "i": ban_id}, {"t": "character", "i": 999999}]
    )
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE game_settings SET value = ? WHERE key = 'preview_pins'", (stale,)
    )
    conn.commit()
    conn.close()

    window2 = await application.start(str(db_path))
    try:
        # spec «Исчезнувшая сущность тихо убирается»: the dead pair simply
        # is not there, the healthy one restored, no error shown…
        assert _signature(window2) == [(True, ban_id)]
        assert window2.entity_preview.vm.liveEmpty is True
        # …and storage was NOT rewritten in the background (design Д3 — the
        # clean list arrives with the user's next pin/unpin only).
        assert _pins_storage(db_path) == json.loads(stale)
    finally:
        window2.close()
        await helpers.wait_until_settled()


async def test_deleting_a_pinned_entity_lifts_its_pin_everywhere(
    app, wait_for, menu_qmenu, modal_qdialog
):
    application, window = app
    db_path = application._db_path
    ban_id = await _create_entity(
        window, wait_for, menu_qmenu, db_path, "character", "Банн"
    )
    # The connector's delete channel: the popup child dies when its parent
    # card is rejected. Show it live, PIN it, then reject the parent.
    card = await _open_card(window, wait_for, "character", ban_id)
    await helpers.create_related_via_popup(
        window, wait_for, card, "locations", "location", "Пещера"
    )
    peshchera_id = _entity_id(db_path, "location", "Пещера")
    _select(window, "location", peshchera_id)
    await wait_for(lambda: _signature(window) == [(False, peshchera_id)])
    _press_pin(window, "location", peshchera_id, False)
    await wait_for(lambda: _signature(window) == [(True, peshchera_id)])
    assert _pins_storage(db_path) == [{"t": "location", "i": peshchera_id}]

    card.reject()
    # spec «Удаление снимает закрепление»: the card AND the slot leave the
    # column, and the saved list loses the pair in the same channel.
    await wait_for(lambda: _panes(window) == [])
    await wait_for(lambda: _pins_storage(db_path) == [])
    assert application._wiring._preview_pins == []
    assert query_db(db_path, "SELECT 1 FROM locations WHERE name = ?", ("Пещера",)) == []


async def test_deleting_the_live_entity_clears_only_the_live_area(
    app, wait_for, menu_qmenu, modal_qdialog
):
    application, window = app
    db_path = application._db_path
    ban_id = await _create_entity(
        window, wait_for, menu_qmenu, db_path, "character", "Банн"
    )
    _select(window, "character", ban_id)
    await wait_for(lambda: _signature(window) == [(False, ban_id)])
    _press_pin(window, "character", ban_id, False)
    await wait_for(lambda: _signature(window) == [(True, ban_id)])

    card = await _open_card(window, wait_for, "character", ban_id)
    await helpers.create_related_via_popup(
        window, wait_for, card, "locations", "location", "Пещера"
    )
    peshchera_id = _entity_id(db_path, "location", "Пещера")
    _select(window, "location", peshchera_id)
    await wait_for(lambda: _signature(window) == [(True, ban_id), (False, peshchera_id)])

    card.reject()
    # The pinned Банн survives the delete of the live Пещера untouched; only
    # the live area empties (spec preview-pins «Удаление показанной в живой
    # области»).
    await wait_for(lambda: _signature(window) == [(True, ban_id)])
    assert window.entity_preview.vm.liveEmpty is True
    assert _pins_storage(db_path) == [{"t": "character", "i": ban_id}]


async def test_card_save_repaints_every_copy_of_the_pair(
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
    _select(window, "character", ban_id)
    await wait_for(lambda: _signature(window) == [(False, ban_id)])
    _press_pin(window, "character", ban_id, False)
    await wait_for(lambda: _signature(window) == [(True, ban_id)])
    _select(window, "character", ban_id)
    await wait_for(lambda: _signature(window) == [(True, ban_id), (False, ban_id)])

    # A foreign save leaves the column alone.
    arrow_card = await _open_card(window, wait_for, "item", arrow_id)
    arrow_card.name_input.setText("Стрела-2")
    arrow_card.save_button.click()
    await wait_for(
        lambda: all(p["nameText"] == "Банн" for p in _panes(window))
    )

    # spec «Сохранение карточки перекрашивает все копии»: BOTH the pinned
    # and the live copy show the stored values after the save.
    ban_card = await _open_card(window, wait_for, "character", ban_id)
    ban_card.name_input.setText("Банн-2")
    ban_card.save_button.click()
    await wait_for(lambda: len(_panes(window)) == 2)
    await wait_for(
        lambda: all(p["nameText"] == "Банн-2" for p in _panes(window))
    )
    assert _signature(window) == [(True, ban_id), (False, ban_id)]


# ── tasks 5.2/5.3: what moves the column and what never does ─────────────────


async def test_transition_from_a_pane_targets_live_middle_syncs_scale_stays(
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
    event_id = await _create_linked_event(
        (window, wait_for, modal_qdialog, db_path),
        "Собрание",
        [("characters", "Банн"), ("locations", "Грот")],
    )
    helpers.click_timeline_event(window, "Собрание")
    await wait_for(
        lambda: "Банн" in helpers.detail_panel_names(window.detail_panel.vm.characters)
    )
    await helpers.wait_until_settled()
    canvas = timeline_probe.tape(window)

    _select(window, "character", ban_id)
    await wait_for(lambda: _signature(window) == [(False, ban_id)])
    _press_pin(window, "character", ban_id, False)
    await wait_for(lambda: _signature(window) == [(True, ban_id)])

    # A relation row pressed INSIDE the pinned pane: same bus, same rule —
    # the target goes to the live area, the pinned card stays as it was
    # (spec «Переход из закреплённой карточки не трогает её»).
    window.entity_preview.entity_requested.emit("location", grot_id)
    await wait_for(lambda: _signature(window) == [(True, ban_id), (False, grot_id)])
    assert _panes(window)[0]["nameText"] == "Банн"
    # The middle-column sync of the previous design stays untouched: tab
    # switch + row wash (spec entity-preview «Переход по связи»)…
    await wait_for(lambda: _current_tab(window) == _tab_of(window, "location"))
    assert _washed_ids(window.detail_panel.vm.locations) == [grot_id]
    assert window.detail_panel.vm.last_selected == ("location", grot_id)
    # …and the scale was not touched (spec «шкала не трогается»).
    assert canvas.selected_id == event_id


async def test_event_selection_and_deselect_leave_the_whole_column(
    app, wait_for, menu_qmenu
):
    application, window = app
    db_path = application._db_path
    ban_id = await _create_entity(
        window, wait_for, menu_qmenu, db_path, "character", "Банн"
    )
    grot_id = await _create_entity(
        window, wait_for, menu_qmenu, db_path, "location", "Грот"
    )
    _select(window, "character", ban_id)
    await wait_for(lambda: _signature(window) == [(False, ban_id)])
    _press_pin(window, "character", ban_id, False)
    await wait_for(lambda: _signature(window) == [(True, ban_id)])
    _select(window, "location", grot_id)
    await wait_for(lambda: _signature(window) == [(True, ban_id), (False, grot_id)])

    # Another event appears and is selected on the scale: neither the pin
    # nor the live card moves (spec preview-pins «Смена события колонку не
    # трогает»).
    await helpers.create_event_via_ui(
        window, wait_for, "Весна", start_date=date(1301, 3, 1), end_date=date(1301, 3, 10)
    )
    helpers.click_timeline_event(window, "Весна")
    await wait_for(lambda: window.detail_panel.vm.title == "Весна")
    await helpers.wait_until_settled()
    assert _signature(window) == [(True, ban_id), (False, grot_id)]

    # Deselecting it again (a window that excludes the selection): same.
    window.timeline_widget.window_changed.emit(date(1400, 1, 1), date(1400, 12, 31))
    await wait_for(lambda: window.detail_panel.vm.title == "")
    await helpers.wait_until_settled()
    assert _signature(window) == [(True, ban_id), (False, grot_id)]
