"""Final acceptance of the flat-list scale on the REAL application (task 6.2).

The scenarios the delta pins and this file drives end-to-end (full app,
real ViewModel/facade/QML island, real wiring): one event — one row (the
multi-day event is not duplicated per day, same-day events keep the
``(start_date, id)`` order), the open-ended row shows ``∞`` without inventing
a closing date, the «Выбор даты» chip opens the popover and filters by the
INTERSECTION rule (including reset), and the «+» menu opens the event
editor.

The remaining 6.2 scenarios are accepted in the sibling suites that already
drive them through this same fixture: click → detail panel (test_e2e_events,
test_e2e_wiring_gaps), double-click → editor (test_e2e_events,
test_e2e_crud), «+» entity items (test_e2e_crud), «Типы событий…» and the
token type mark on live rows (test_e2e_event_types), search highlight with
the window reset from outside (test_e2e_wiring_gaps).

Two interaction scenarios ride the REAL QML geometry here (spec «Выбор и
открытие события»): the per-row tooltip with the full name and the range,
and a click past every row dropping the selection in every layer.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QPointF, Qt

from app.domain.game_calendar import MonthDay
from app.presentation.views.event_dialog import EventDialog

from tests.ui import helpers, timeline_probe


async def _create(window, wait_for, name, *, start=None, end=None,
                  open_ended=False, characteristics="Описание события",
                  backstory=""):
    await helpers.create_event_via_ui(
        window, wait_for, name, characteristics=characteristics, backstory=backstory,
        start_date=start, end_date=end, open_ended=open_ended,
    )


def _row_text(window, delegate) -> str:
    """The painted ``rowText`` (the caption line) of one materialized delegate."""
    return next(
        i.property("text") for i in timeline_probe.walk_items(delegate)
        if i.objectName() == "rowText"
    )


def _row_detail(window, delegate):
    """The row's second painted line item (the description glimpse)."""
    return next(
        i for i in timeline_probe.walk_items(delegate)
        if i.objectName() == "rowDetail"
    )


async def test_flat_list_one_row_per_event_with_captions(app, wait_for):
    """Spec «Плоский список событий»: a multi-day event is ONE row, the
    sample order is (start_date, id) ascending, the delivered caption is the
    game-formatted ``start — end · name`` the delegate paints."""
    application, window = app
    await _create(window, wait_for, "Долгая зима",
                  start=date(1200, 3, 3), end=date(1200, 3, 10))
    await _create(window, wait_for, "Совет первый",
                  start=date(1200, 5, 5), end=date(1200, 5, 5))
    await _create(window, wait_for, "Совет второй",
                  start=date(1200, 5, 5), end=date(1200, 5, 5))
    await helpers.wait_until_settled()

    tape = timeline_probe.tape(window)
    assert len(tape.rows) == len(tape.events) == 3  # one row per event
    ids = [row.event_id for row in tape.rows]
    assert len(set(ids)) == 3
    winter = helpers.find_event_id(window, "Долгая зима")
    assert ids.count(winter) == 1                    # eight days, still one row
    first = helpers.find_event_id(window, "Совет первый")
    second = helpers.find_event_id(window, "Совет второй")
    assert ids == [winter, first, second]            # (start_date, id), ascending
    assert [row.start for row in tape.rows] == sorted(row.start for row in tape.rows)

    delegate = timeline_probe.reveal(window, tape.index_for_event(winter))
    caption = "03 Март 1200 — 10 Март 1200 · Долгая зима"
    assert delegate.property("caption") == caption   # the delivered scalar
    assert _row_text(window, delegate) == caption    # what the row paints


async def test_open_ended_row_shows_infinity(app, wait_for):
    """Spec «Бессрочные события в списке»: one row, the explicit ``∞`` end,
    no closing date invented anywhere on the scale."""
    application, window = app
    await _create(window, wait_for, "Вечный лес",
                  start=date(1200, 6, 1), open_ended=True)
    await helpers.wait_until_settled()

    tape = timeline_probe.tape(window)
    event_id = helpers.find_event_id(window, "Вечный лес")
    rows = [row for row in tape.rows if row.event_id == event_id]
    assert len(rows) == 1
    assert rows[0].end is None                       # the row never asserts an end
    caption = "01 Июнь 1200 — ∞ · Вечный лес"
    assert rows[0].caption == caption
    delegate = timeline_probe.reveal(window, tape.index_for_event(event_id))
    assert delegate.property("caption") == caption
    assert "∞" in _row_text(window, delegate)


async def test_window_chip_filters_by_intersection_and_resets(app, wait_for):
    """Spec «Окно фильтрации и пустое состояние» + «Фильтр Выбор даты» on the
    real chip: the popover two taps apply the window LIVE, only interval-
    crossing events stay (an event ending inside and an open event started
    earlier are in, a closed earlier event is out), «Сбросить» returns all."""
    application, window = app
    await _create(window, wait_for, "Через окно",
                  start=date(1200, 7, 1), end=date(1200, 9, 5))
    await _create(window, wait_for, "До окна",
                  start=date(1200, 6, 1), end=date(1200, 6, 20))
    await _create(window, wait_for, "Открытый раньше",
                  start=date(1200, 5, 1), open_ended=True)
    await helpers.wait_until_settled()
    tape = timeline_probe.tape(window)
    assert len(tape.events) == 3

    # The real chip click opens the popover (the island reports its scene rect).
    timeline_probe.click_object(window, "windowChip")
    popup = window.timeline_widget.window_popup
    await wait_for(lambda: popup.isVisible())

    # Two taps in the popover: start arms, finish applies live (no «Применить»).
    # The game-calendar grid taps answer with coordinates (piece C3b, D3).
    popup.start_calendar.day_selected.emit(MonthDay(1200, 8, 10))
    popup.start_calendar.day_selected.emit(MonthDay(1200, 8, 20))
    await helpers.wait_until_settled()

    visible = {event.name for event in tape.events}
    assert visible == {"Через окно", "Открытый раньше"}
    assert timeline_probe.chip_caption(window) == "10 Август 1200 — 20 Август 1200 ▾"

    popup.reset_button.click()  # «Сбросить» — the window's only reset
    await helpers.wait_until_settled()
    assert {event.name for event in tape.events} == {
        "Через окно", "До окна", "Открытый раньше",
    }
    assert timeline_probe.chip_caption(window) == "Все дни ▾"


async def test_add_menu_new_event_item_opens_the_editor(app, wait_for, menu_qmenu):
    """The «+» menu's first item creates an event (its dialog); the entity
    items and «Типы событий…» run their dialogs through the same dispatch in
    test_e2e_crud / test_e2e_event_types."""
    application, window = app
    helpers.pick_menu_action(menu_qmenu, "Новое событие")
    timeline_probe.click_object(window, "addButton", button=Qt.MouseButton.RightButton)
    await wait_for(lambda: any(
        d.isVisible() for d in window.findChildren(EventDialog)
    ))
    dialog = next(d for d in window.findChildren(EventDialog) if d.isVisible())
    dialog.close()


async def test_row_tooltip_carries_name_and_range(app, wait_for):
    """Spec «Подсказка с названием и датами»: every row declares its full
    caption (name + real range) as its tooltip — shown even when the text
    fits — and the island's bridge reports exactly that text on hover."""
    application, window = app
    await _create(window, wait_for, "Совет теней",
                  start=date(1200, 4, 1), end=date(1200, 4, 9))
    await helpers.wait_until_settled()

    tape = timeline_probe.tape(window)
    event_id = helpers.find_event_id(window, "Совет теней")
    idx = tape.index_for_event(event_id)
    delegate = timeline_probe.reveal(window, idx)
    caption = tape.rows[idx].caption
    assert caption == "01 Апрель 1200 — 09 Апрель 1200 · Совет теней"
    # declared on the row itself (the Nri shim scope the delegate pins)
    assert timeline_probe.tooltip_of_item(delegate) == caption
    # the preserved header chrome keeps its own declared tooltips
    assert timeline_probe.tooltip_of(window, "windowChip") == "Выбор даты"
    assert timeline_probe.tooltip_of(window, "addButton") == (
        "Добавить событие (правый клик — другие сущности)"
    )

    # hover the row: the bridge (the QToolTip half of the shim) gets the text
    panel = window.timeline_widget
    point = QPointF(delegate.width() * 0.5, delegate.height() * 0.5)
    scene = delegate.mapToScene(point)
    timeline_probe.move_over(window, scene.toPoint())
    await wait_for(lambda: panel._tooltip_bridge.last_request is not None)
    text, _pos = panel._tooltip_bridge.last_request
    assert text == caption

    # leaving the row releases the tooltip (empty report)
    list_view = timeline_probe.item(window, "eventList")
    below = list_view.mapToScene(QPointF(30, list_view.height() - 4)).toPoint()
    timeline_probe.move_over(window, below)
    await wait_for(lambda: panel._tooltip_bridge.last_request
                   and not panel._tooltip_bridge.last_request[0])


async def test_click_past_every_row_clears_every_layer(app, wait_for):
    """Spec «Клик-промах сбрасывает выбор» through the REAL island geometry:
    a click landing past every row drops the wash, the ViewModel's selection
    and the detail panel — and is not an id-contract selection."""
    application, window = app
    await _create(window, wait_for, "Один день",
                  start=date(1200, 2, 2), end=date(1200, 2, 2))
    await helpers.wait_until_settled()
    tape = timeline_probe.tape(window)

    event_id = helpers.click_timeline_event(window, "Один день")
    await wait_for(lambda: "Один день" in window.detail_panel.vm.title)
    assert tape.selected_id == event_id

    # Click under the single row: past every row of the flat list.
    list_view = timeline_probe.item(window, "eventList")
    y = int(list_view.height() * 0.7)
    assert y > timeline_probe.row_delegate(window, 0).height()
    timeline_probe.click(
        window, list_view.mapToScene(QPointF(30, y)).toPoint()
    )
    await helpers.wait_until_settled()

    assert tape.selected_id is None                       # wash dropped
    assert application._wiring._timeline_vm.selected_event is None
    assert window.detail_panel.vm.title == ""             # panel emptied


async def test_row_paints_the_description_line_under_the_caption(app, wait_for):
    """Spec «Плоский список событий»: the row shows the event's own description as
    its second line — the characteristics, the backstory as the fallback, the
    caption line above unchanged, the tooltip still the name + range."""
    application, window = app
    await _create(window, wait_for, "Зимний поход",
                  characteristics="Снег укрыл перевалы",
                  start=date(1200, 11, 1), end=date(1200, 12, 20))
    await _create(window, wait_for, "Летопись",
                  characteristics="", backstory="летописи молчат",
                  start=date(1200, 11, 2), end=date(1200, 11, 2))
    await helpers.wait_until_settled()

    tape = timeline_probe.tape(window)
    for name, expected, caption in (
        ("Зимний поход", "Снег укрыл перевалы",
         "01 Ноябрь 1200 — 20 Декабрь 1200 · Зимний поход"),
        ("Летопись", "летописи молчат",
         "02 Ноябрь 1200 — 02 Ноябрь 1200 · Летопись"),
    ):
        event_id = helpers.find_event_id(window, name)
        idx = tape.index_for_event(event_id)
        delegate = timeline_probe.reveal(window, idx)
        assert tape.rows[idx].detail == expected     # the delivered scalar
        detail = _row_detail(window, delegate)
        assert detail.property("text") == expected   # what the row paints
        assert detail.property("visible") is True
        assert delegate.property("height") == (
            timeline_probe.root(window).property("detailedRowHeight"))
        assert _row_text(window, delegate) == caption  # the caption line intact
        assert timeline_probe.tooltip_of_item(delegate) == caption


async def test_list_rows_are_tied_to_the_column_field(app, wait_for):
    """The flat list lives INSIDE the same bordered content field every other
    column puts its body in — the rows read as this column's content, not as
    loose text on the window background."""
    application, window = app
    await _create(window, wait_for, "Один день",
                  start=date(1200, 2, 2), end=date(1200, 2, 2))
    await helpers.wait_until_settled()

    card = timeline_probe.item(window, "timelineListCard")
    assert card.property("visible") is True
    assert card.property("radius") > 0            # the card role's rounding
    # …and its hairline frame, painted (the exact border token is pinned in
    # test_e2e_timeline_theme; here the point is that a frame exists at all).
    assert card.property("borderColor").isValid()
    assert card.property("borderColor") != card.property("color")

    delegate = timeline_probe.reveal(window, 0)
    top_left = delegate.mapToItem(card, QPointF(0, 0))
    bottom_right = delegate.mapToItem(card, QPointF(delegate.width(), delegate.height()))
    assert 0 <= top_left.x() and bottom_right.x() <= card.width() + 1
    assert 0 <= top_left.y() and bottom_right.y() <= card.height() + 1

    # The empty state rides the same field (one hint, inside the frame).
    hint = timeline_probe.item(window, "emptyHint")
    hint_center = hint.mapToItem(card, QPointF(hint.width() / 2, hint.height() / 2))
    assert 0 < hint_center.x() < card.width()
    assert 0 < hint_center.y() < card.height()
