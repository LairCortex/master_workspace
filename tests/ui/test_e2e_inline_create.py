"""Group 6 e2e: inline create from an empty day (task 6.1, design D4).

Full user path through the wiring: click the «нет события» row → the reused
inline field opens on it → Enter commits ``event_create_requested`` →
``vm.create_event_at`` writes a single-day untyped event, reloads and selects
it → the new card is visible and washed, the detail panel is filled, and the
row is committed in the DB. An empty draft is not a create.
"""
from __future__ import annotations

import datetime

from PySide6.QtCore import QDate, Qt
from PySide6.QtTest import QTest

from app.presentation.views.timeline_rows import EmptyDayRow
from tests.ui import helpers, timeline_probe
from tests.ui.conftest import query_db


def _ymd(value) -> str:
    return str(value)[:10]


def _click_empty_day(window, day) -> None:
    """Reveal the given day's placeholder on the island and click it."""
    rows = timeline_probe.rows(window)
    idx = next(
        i for i, r in enumerate(rows)
        if isinstance(r, EmptyDayRow) and r.date == day
    )
    timeline_probe.reveal(window, idx)
    timeline_probe.click(window, timeline_probe.row_center(window, idx))


def _editor(window):
    """The one reused inline TextField of the island."""
    return timeline_probe.item(window, "timelineInlineEditor")


async def test_inline_create_from_empty_day(app, wait_for):
    """Spec «Быстрое создание»: Enter in the empty-day field creates a
    14–14 event without a type, reloads the tape, and selects the new card."""
    application, window = app
    await helpers.create_event_via_ui(
        window, wait_for, "Anchor",
        start_date=QDate(1200, 3, 1),
        end_date=QDate(1200, 3, 1),
    )
    widget = window.timeline_widget
    view = timeline_probe.tape(window)
    await wait_for(lambda: len(view.events) == 1)
    # Pin a 6-day window so the eventless Mar 2..Mar 6 stand as placeholders.
    widget._on_window_range(
        datetime.date(1200, 3, 1), datetime.date(1200, 3, 6),
    )
    await helpers.wait_until_settled()
    assert any(
        isinstance(r, EmptyDayRow) and r.date == datetime.date(1200, 3, 3)
        for r in view.rows
    )

    _click_empty_day(window, datetime.date(1200, 3, 3))
    timeline_probe.pump(4)
    assert _editor(window).property("visible") is True
    assert timeline_probe.root(window).property("editingDayIndex") >= 0

    # Mirrors the retired widget's e2e (direct ``setText`` on the field):
    # QTest.keyClicks is ASCII-only — it aborts on anything non-Latin1.
    _editor(window).setProperty("text", "Засека")
    timeline_probe.pump(2)
    QTest.keyClick(timeline_probe.quick(window), Qt.Key.Key_Return)
    await helpers.wait_until_settled()

    assert helpers.has_event_named(window, "Засека")
    eid = helpers.find_event_id(window, "Засека")
    # The new event is selected and its card is pictured (spec «карточка
    # видна и выбрана»).
    assert timeline_probe.selected_id(window) == eid
    assert view.index_for_event(eid) is not None
    assert _editor(window).property("visible") is False  # field dismissed

    row = query_db(
        application._db_path,
        "SELECT start_date, end_date, event_type_id FROM events WHERE id = ?",
        (eid,),
    )[0]
    assert _ymd(row[0]) == "1200-03-03"  # start == end == the clicked day
    assert _ymd(row[1]) == "1200-03-03"
    assert row[2] is None  # no type on an inline quick create


async def test_inline_create_empty_draft_creates_nothing(app, wait_for):
    """Spec «Пустое поле не создаёт»: an empty inline field dismissed on Enter
    adds no event and leaves the selected detail panel untouched."""
    application, window = app
    await helpers.create_event_via_ui(
        window, wait_for, "Anchor",
        start_date=QDate(1200, 3, 1),
        end_date=QDate(1200, 3, 1),
    )
    widget = window.timeline_widget
    view = timeline_probe.tape(window)
    await wait_for(lambda: len(view.events) == 1)
    widget._on_window_range(
        datetime.date(1200, 3, 1), datetime.date(1200, 3, 6),
    )
    await helpers.wait_until_settled()
    before = {e.id for e in view.events}

    _click_empty_day(window, datetime.date(1200, 3, 3))
    timeline_probe.pump(4)
    assert _editor(window).property("visible") is True
    QTest.keyClick(timeline_probe.quick(window), Qt.Key.Key_Return)  # empty draft
    await helpers.wait_until_settled()

    assert {e.id for e in view.events} == before  # nothing added
    assert _editor(window).property("visible") is False
    rows = query_db(
        application._db_path, "SELECT COUNT(*) FROM events", ()
    )[0][0]
    assert rows == len(before)
