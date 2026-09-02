"""Group 5 wiring e2e: ``event_dates_moved`` → window cover
(``cover_window_for_span`` grows the ACTIVE «Выбор даты» window before the
write), one update, selection raised, rollback under exactly one modal error;
plus the task 5.4 stub: press-drag is inert on the period rungs."""
from __future__ import annotations

import datetime

from PySide6.QtCore import QDate, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from app.presentation.views.timeline_rows import PeriodCardRow, ScaleUnit
from tests.ui import helpers
from tests.ui.conftest import query_db


def _ymd(value) -> str:
    return str(value)[:10]


def _press_drag_release(view, start_p, end_p) -> None:
    """A left press at ``start_p``, one dragged move and a release at
    ``end_p`` — viewport coordinates, offscreen delivery."""
    vp = view.viewport()
    for kind, point, buttons in (
        (QEvent.Type.MouseButtonPress, start_p, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseMove, end_p, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, end_p, Qt.MouseButton.NoButton),
    ):
        QApplication.sendEvent(vp, QMouseEvent(
            kind, QPointF(point), vp.mapToGlobal(point),
            Qt.MouseButton.LeftButton, buttons,
            Qt.KeyboardModifier.NoModifier,
        ))


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
    view = widget.rows_view
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
    chip = widget.window_chip.text()
    assert "25" in chip
    rows = query_db(
        application._db_path,
        "SELECT start_date, end_date FROM events WHERE id = ?",
        (eid,),
    )
    assert _ymd(rows[0][1]) == "1200-03-25"
    assert view.selected_id == eid


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
    view = widget.rows_view
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
    assert "20" in widget.window_chip.text()
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
    view = widget.rows_view
    await wait_for(lambda: len(view.events) == 1)
    moved: list = []
    widget.event_dates_moved.connect(lambda *a: moved.append(a))
    drilled: list = []
    view.period_drilled.connect(lambda *a: drilled.append(a))

    for rung in (ScaleUnit.MONTH, ScaleUnit.YEAR):
        widget._vm.level = rung  # the app's single mutation point …
        widget._sync_from_vm()  # … mirrored onto the tape (panel contract)
        assert view.level is rung
        card_idx = next(
            i for i, r in enumerate(view.rows) if isinstance(r, PeriodCardRow)
        )
        press_p = view.visualItemRect(view.item(card_idx)).center()
        release_p = QPoint(press_p.x(), press_p.y() + 120)  # past the last row
        _press_drag_release(view, press_p, release_p)
        await helpers.wait_until_settled()
        assert moved == [], rung
        assert drilled == [], rung
        assert view.level is rung, rung  # nothing drilled either
        assert view.selected_id is None, rung
        assert view.drag_preview is None, rung
