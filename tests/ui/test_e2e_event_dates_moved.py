"""W5 wiring: event_dates_moved → filter cover, update_event, select, rollback."""
from __future__ import annotations

import datetime

from PySide6.QtCore import QDate

from tests.ui import helpers
from tests.ui.conftest import query_db


def _ymd(value) -> str:
    return str(value)[:10]


async def test_dates_moved_expands_filter_and_writes(app, wait_for):
    application, window = app
    await helpers.create_event_via_ui(
        window, wait_for, "Drag-Me",
        start_date=QDate(1200, 3, 10),
        end_date=QDate(1200, 3, 15),
    )
    view = window.timeline_widget.rows_view
    await wait_for(lambda: len(view.events) == 1)
    eid = view.events[0].id

    window.timeline_widget._on_filter_range(
        datetime.date(1200, 3, 1), datetime.date(1200, 3, 20),
    )
    await helpers.wait_until_settled()
    await wait_for(lambda: len(view.events) == 1)

    window.timeline_widget.event_dates_moved.emit(
        eid, datetime.date(1200, 3, 10), datetime.date(1200, 3, 25),
    )
    await helpers.wait_until_settled()
    ev = next(e for e in view.events if e.id == eid)
    assert ev.end_date == datetime.date(1200, 3, 25)
    chip = window.timeline_widget.filter_chip.text()
    assert "25" in chip
    rows = query_db(
        application._db_path,
        "SELECT start_date, end_date FROM events WHERE id = ?",
        (eid,),
    )
    assert _ymd(rows[0][1]) == "1200-03-25"
    assert window.timeline_widget.rows_view.selected_id == eid


async def test_open_event_dates_moved_writes_only_start(app, wait_for):
    application, window = app
    await helpers.create_event_via_ui(
        window, wait_for, "Open-Drag",
        start_date=QDate(1200, 4, 1),
        open_ended=True,
    )
    view = window.timeline_widget.rows_view
    await wait_for(lambda: len(view.events) == 1)
    eid = view.events[0].id
    window.timeline_widget.event_dates_moved.emit(
        eid, datetime.date(1200, 4, 8), None,
    )
    await helpers.wait_until_settled()
    ev = next(e for e in view.events if e.id == eid)
    assert ev.start_date == datetime.date(1200, 4, 8)
    assert ev.end_date is None
    row = query_db(
        application._db_path,
        "SELECT start_date, end_date FROM events WHERE id = ?",
        (eid,),
    )[0]
    assert _ymd(row[0]) == "1200-04-08"
    assert row[1] is None or row[1] == ""


async def test_dates_moved_save_failure_rolls_back_and_shows_dialog(
    app, wait_for, monkeypatch, message_boxes,
):
    application, window = app
    await helpers.create_event_via_ui(
        window, wait_for, "Fail-Me",
        start_date=QDate(1200, 5, 1),
        end_date=QDate(1200, 5, 5),
    )
    view = window.timeline_widget.rows_view
    await wait_for(lambda: len(view.events) == 1)
    eid = view.events[0].id
    window.timeline_widget._on_filter_range(
        datetime.date(1200, 5, 1), datetime.date(1200, 5, 10),
    )
    await helpers.wait_until_settled()

    async def boom(event_id, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(application._wiring._event_service, "update_event", boom)
    window.timeline_widget.event_dates_moved.emit(
        eid, datetime.date(1200, 5, 1), datetime.date(1200, 5, 20),
    )
    await helpers.wait_until_settled()
    assert sum(1 for b in message_boxes if b[0] == "critical") == 1
    ev = next(e for e in view.events if e.id == eid)
    assert ev.end_date == datetime.date(1200, 5, 5)
    assert "20" in window.timeline_widget.filter_chip.text()
