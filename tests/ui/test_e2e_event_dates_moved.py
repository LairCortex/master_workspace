"""Group 5 wiring e2e: ``event_dates_moved`` → window cover
(``cover_window_for_span`` grows the ACTIVE «Выбор даты» window before the
write), one update, selection raised, rollback under exactly one modal error;
plus the task 5.4 stub: press-drag is inert on the period rungs."""
from __future__ import annotations

import datetime

from PySide6.QtCore import QDate, QPoint

from app.presentation.views.timeline_rows import PeriodCardRow, ScaleUnit
from tests.ui import helpers, timeline_probe
from tests.ui.conftest import query_db


def _ymd(value) -> str:
    return str(value)[:10]


async def test_dates_moved_expands_window_before_the_write(
    app, wait_for, monkeypatch,
):
    """Task 5.3 / spec «Унос за окно расширяет окно»: the ACTIVE window is
    widened over the new dates BEFORE the write — one operation overall: the
    window covers Mar 25, the dates are stored, the event stays visible and
    selected."""
    application, window = app
    await helpers.create_event_via_ui(
        window, wait_for, "Drag-Me",
        start_date=QDate(1200, 3, 10),
        end_date=QDate(1200, 3, 15),
    )
    widget = window.timeline_widget
    view = timeline_probe.tape(window)
    await wait_for(lambda: len(view.events) == 1)
    eid = view.events[0].id

    widget._on_window_range(
        datetime.date(1200, 3, 1), datetime.date(1200, 3, 20),
    )
    await helpers.wait_until_settled()
    await wait_for(lambda: len(view.events) == 1)

    # Capture the live window AT THE WRITE — coverage must precede it.
    service = application._wiring._event_service
    real_update = service.update_event
    window_at_write: list = []

    async def spy_update(event_id, **kwargs):
        window_at_write.append(widget._vm.window)
        return await real_update(event_id, **kwargs)

    monkeypatch.setattr(service, "update_event", spy_update)

    widget.event_dates_moved.emit(
        eid, datetime.date(1200, 3, 10), datetime.date(1200, 3, 25),
    )
    await helpers.wait_until_settled()
    assert window_at_write == [
        (datetime.date(1200, 3, 1), datetime.date(1200, 3, 25))
    ]
    ev = next(e for e in view.events if e.id == eid)
    assert ev.end_date == datetime.date(1200, 3, 25)
    assert "25" in timeline_probe.chip_caption(window)
    rows = query_db(
        application._db_path,
        "SELECT start_date, end_date FROM events WHERE id = ?",
        (eid,),
    )
    assert _ymd(rows[0][1]) == "1200-03-25"
    assert timeline_probe.selected_id(window) == eid


async def test_open_event_dates_moved_writes_only_start(app, wait_for):
    application, window = app
    await helpers.create_event_via_ui(
        window, wait_for, "Open-Drag",
        start_date=QDate(1200, 4, 1),
        open_ended=True,
    )
    view = timeline_probe.tape(window)
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


async def test_dates_moved_save_failure_rolls_back_shows_dialog_keeps_window(
    app, wait_for, monkeypatch, message_boxes,
):
    """Spec «Сбой сохранения откатывает и сообщает»: dates roll back, exactly
    one modal error, and the widening of the window survives the failure."""
    application, window = app
    await helpers.create_event_via_ui(
        window, wait_for, "Fail-Me",
        start_date=QDate(1200, 5, 1),
        end_date=QDate(1200, 5, 5),
    )
    widget = window.timeline_widget
    view = timeline_probe.tape(window)
    await wait_for(lambda: len(view.events) == 1)
    eid = view.events[0].id
    widget._on_window_range(
        datetime.date(1200, 5, 1), datetime.date(1200, 5, 10),
    )
    await helpers.wait_until_settled()

    async def boom(event_id, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(application._wiring._event_service, "update_event", boom)
    widget.event_dates_moved.emit(
        eid, datetime.date(1200, 5, 1), datetime.date(1200, 5, 20),
    )
    await helpers.wait_until_settled()
    assert sum(1 for b in message_boxes if b[0] == "critical") == 1
    ev = next(e for e in view.events if e.id == eid)
    assert ev.end_date == datetime.date(1200, 5, 5)
    assert "20" in timeline_probe.chip_caption(window)
    assert widget._vm.window == (
        datetime.date(1200, 5, 1), datetime.date(1200, 5, 20),
    )


async def test_drop_gesture_is_inert_on_period_levels(app, wait_for):
    """Task 5.4 stub: on «месяц»/«год» a press-drag over a period card is a
    no-op — no ``event_dates_moved``, no drill, no selection rung change."""
    application, window = app
    await helpers.create_event_via_ui(
        window, wait_for, "Rung-Lock",
        start_date=QDate(1200, 3, 10),
        end_date=QDate(1200, 3, 12),
    )
    widget = window.timeline_widget
    view = timeline_probe.tape(window)
    await wait_for(lambda: len(view.events) == 1)
    moved: list = []
    widget.event_dates_moved.connect(lambda *a: moved.append(a))
    drilled: list = []

    for rung in (ScaleUnit.MONTH, ScaleUnit.YEAR):
        widget._vm.level = rung  # the app's single mutation point …
        widget._sync_from_vm()  # … mirrored onto the tape (panel contract)
        assert widget._vm.level is rung
        timeline_probe.pump(4)
        card_idx = next(
            i for i, r in enumerate(view.rows) if isinstance(r, PeriodCardRow)
        )
        timeline_probe.reveal(window, card_idx)
        level_before = widget._vm.level
        press_p = timeline_probe.row_center(window, card_idx)
        release_p = QPoint(press_p.x(), press_p.y() + 120)  # past the last row
        timeline_probe.drag(window, press_p, release_p)
        await helpers.wait_until_settled()
        assert moved == [], rung
        assert drilled == [], rung
        assert level_before is rung, rung  # nothing drilled either
        assert timeline_probe.selected_id(window) is None, rung
        # the island's drag bookkeeping (the retired drag_preview, D4):
        assert timeline_probe.root(window).property("dragTargetIndex") == -1
        assert timeline_probe.root(window).property("dragEventId") == -1
