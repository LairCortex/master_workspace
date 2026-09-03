"""Gap-fillers for the ladder core and the tape: branches no UI flow reaches.

The behavioural suites own the interactions; this file only pins the guards
around them — calendar edges and the empty ladder in the Qt-free core, the
per-guard early returns of the list view (a missing item, an invalid index, an
index without ladder data, a gesture whose record left the sample) and the
panel's knob/Window guards. Each call is the smallest input that reaches the
branch, so a removed guard shows up as a crash or a painted pixel here.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from PySide6.QtCore import QEvent, QModelIndex, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

from app.presentation.views.timeline_rows import (
    CALENDAR_MAX,
    CALENDAR_MIN,
    DayHeaderRow,
    EventRow,
    ScaleUnit,
    StickyState,
    _build_period_ladder,
    _next_unit_start,
    _range_for,
    _unit_start,
    clamp_calendar,
    sticky_state,
)
from app.presentation.views.timeline_widget import (
    DRAG_START_THRESHOLD_PX,
    OPEN_MARK,
    OPEN_MARK_SEP,
    ROW_HEIGHT,
    STICKY_HEIGHT,
    TimelineListView,
    TimelineWidget,
    _card_line,
)


def _evt(eid: int, start: date, end: date | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=eid, name=f"event-{eid}", start_date=start, end_date=end)


def _view(qtbot, events=(), rows_visible: int = 4) -> TimelineListView:
    view = TimelineListView()
    view.resize(300, ROW_HEIGHT * rows_visible + STICKY_HEIGHT + 8)
    qtbot.addWidget(view)
    view.show()
    if events:
        view.update_events(events)
    return view


def _row_center(view: TimelineListView, idx: int) -> QPoint:
    return view.visualItemRect(view.item(idx)).center()


def _mouse(view, kind, point, *, button, buttons) -> None:
    vp = view.viewport()
    QApplication.sendEvent(vp, QMouseEvent(
        kind, QPointF(point), vp.mapToGlobal(point),
        button, buttons, Qt.KeyboardModifier.NoModifier,
    ))


def _press(view, point: QPoint) -> None:
    _mouse(view, QEvent.Type.MouseButtonPress, point,
           button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.LeftButton)


def _drag_to(view, point: QPoint) -> None:
    _mouse(view, QEvent.Type.MouseMove, point,
           button=Qt.MouseButton.NoButton, buttons=Qt.MouseButton.LeftButton)


def _release(view, point: QPoint, button=Qt.MouseButton.LeftButton) -> None:
    _mouse(view, QEvent.Type.MouseButtonRelease, point,
           button=button, buttons=Qt.MouseButton.NoButton)


# ── the Qt-free ladder core: calendar edges and the empty ladder ────────────

def test_unit_start_is_the_day_itself_on_the_daily_rung():
    day = date(1200, 5, 17)
    assert _unit_start(day, ScaleUnit.DAY) == day
    assert _unit_start(day, ScaleUnit.MONTH) == date(1200, 5, 1)
    assert _unit_start(day, ScaleUnit.YEAR) == date(1200, 1, 1)


def test_next_unit_start_steps_a_single_day_on_the_daily_rung():
    assert _next_unit_start(date(1200, 5, 17), ScaleUnit.DAY) == date(1200, 5, 18)
    assert _next_unit_start(date(1200, 12, 1), ScaleUnit.MONTH) == date(1201, 1, 1)
    assert _next_unit_start(date(1200, 1, 1), ScaleUnit.YEAR) == date(1201, 1, 1)


def test_clamp_calendar_clips_both_calendar_edges():
    assert clamp_calendar(CALENDAR_MIN) == CALENDAR_MIN
    assert clamp_calendar(CALENDAR_MAX) == CALENDAR_MAX
    assert clamp_calendar(date(50, 1, 1)) == CALENDAR_MIN
    assert clamp_calendar(date(9999, 12, 31)) == CALENDAR_MAX
    assert clamp_calendar(date(1200, 1, 1)) == date(1200, 1, 1)


def test_sticky_state_of_an_empty_ladder_owns_no_caption():
    assert sticky_state([], 0) == StickyState(None, "", None, "")


def test_range_without_content_below_its_own_start_owns_no_position():
    """A record whose bottom precedes its start owns no ladder position."""
    inverted = SimpleNamespace(
        id=1, name="x", start_date=CALENDAR_MAX, end_date=date(9999, 12, 1),
    )
    assert _range_for([inverted], None) is None


def test_period_ladder_reaching_the_calendar_edge_does_not_overflow():
    """December 9999 has no following period: the ladder ends on the edge."""
    rows = _build_period_ladder(
        [], date(9999, 12, 20), CALENDAR_MAX, ScaleUnit.MONTH, False,
    )
    assert [row.date for row in rows if isinstance(row, DayHeaderRow)] == []
    assert [row.date for row in rows] == [date(9999, 12, 1), date(9999, 12, 1)]


def test_card_line_marks_open_events_and_prints_the_name_otherwise():
    open_row = EventRow(
        date=date(1200, 1, 1), event_id=1, start=date(1200, 1, 1), end=None,
        name="Открытое",
    )
    closed = EventRow(
        date=date(1200, 1, 1), event_id=2, start=date(1200, 1, 1),
        end=date(1200, 1, 5), name="Закрытое",
    )
    assert _card_line(open_row) == f"Открытое{OPEN_MARK_SEP}{OPEN_MARK}"
    assert _card_line(closed) == "Закрытое"


# ── list view: the guards around the interactions ──────────────────────────

def test_delegate_leaves_an_index_without_ladder_data_untouched(qtbot):
    """The defensive branch of the delegate: no ladder row — no painting."""
    view = _view(qtbot)
    image = QImage(8, 8, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.magenta)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 8, 8)
    painter = QPainter(image)
    try:
        view.itemDelegate().paint(painter, option, QModelIndex())
    finally:
        painter.end()
    assert image.pixelColor(4, 4).name() == "#ff00ff"


def test_scroll_to_unknown_event_and_missing_row_are_inert(qtbot):
    view = _view(qtbot, [_evt(1, date(1200, 1, 1))], rows_visible=4)
    before = view.verticalScrollBar().value()
    view.scroll_to_event(9999)  # no card for an unknown id
    assert view.verticalScrollBar().value() == before
    view._scroll_row_to_top(9999)  # no item at that row


def test_click_and_double_click_of_an_invalid_index_are_inert(qtbot):
    view = _view(qtbot, [_evt(1, date(1200, 1, 1))], rows_visible=4)
    selected: list[int] = []
    double: list[int] = []
    view.event_selected.connect(selected.append)
    view.event_double_clicked.connect(double.append)
    view._on_clicked(QModelIndex())
    view._on_double_clicked(QModelIndex())
    assert view._event_id_at(QModelIndex()) is None
    assert selected == [] and double == []


def test_selection_is_dropped_when_its_event_leaves_the_sample(qtbot):
    view = _view(qtbot, [_evt(1, date(1200, 1, 1)), _evt(2, date(1200, 2, 1))],
                 rows_visible=8)
    view.set_selected(1)
    assert view._selected_id == 1
    view.update_events([_evt(2, date(1200, 2, 1))])
    assert view._selected_id is None


def test_event_scan_starts_at_the_pictured_card_of_the_selection(qtbot):
    view = _view(qtbot, [_evt(1, date(1200, 1, 1)), _evt(2, date(1200, 1, 9))],
                 rows_visible=12)
    view.set_selected(1)
    own = view.index_for_event(1)
    ahead = view._scan_event_index(back=False)
    behind = view._scan_event_index(back=True)
    assert own is not None
    assert ahead is not None and ahead > own
    assert behind is None  # nothing of another event above the first card


def test_inline_editor_skips_a_missing_row_and_a_laid_out_less_one(qtbot):
    """No item, or no laid-out geometry for it — the field never opens."""
    view = _view(qtbot, [_evt(1, date(1200, 1, 1)), _evt(2, date(1200, 6, 1))],
                 rows_visible=2)
    last = view.count() - 1
    assert last > 0
    view._show_editor(date(1200, 1, 1), 9999)  # no item at that row
    view.item(last).setHidden(True)  # a row the view no longer lays out
    assert not view.visualItemRect(view.item(last)).isValid()
    view._show_editor(date(1200, 1, 1), last)
    assert view._editor_day is None
    assert not view._editor.isVisible()


def test_finished_sticky_push_without_animations_is_reentrant(qtbot):
    view = _view(qtbot, [_evt(1, date(1200, 1, 1))], rows_visible=4)
    view._finish_sticky_push()  # nothing in flight — the re-entrant branch
    assert view._push_anims == ()


def test_leaving_the_view_clears_the_hovered_row(qtbot):
    view = _view(qtbot, [_evt(1, date(1200, 1, 1))], rows_visible=4)
    _mouse(view, QEvent.Type.MouseMove, _row_center(view, 0),
           button=Qt.MouseButton.NoButton, buttons=Qt.MouseButton.NoButton)
    assert view._hover_row == 0  # the hover landed on the top row
    view.leaveEvent(QEvent(QEvent.Type.Leave))
    assert view._hover_row == -1


def test_gesture_arming_guards_an_empty_point_and_an_empty_ladder(qtbot):
    view = _view(qtbot, [_evt(1, date(1200, 1, 1))], rows_visible=8)
    assert view._arm_gesture(QPoint(-40, -40)) is None  # no item under the press
    idx = view.indexes_for_event(1)[0]
    saved = view._rows
    view._rows = []  # the list still holds items the ladder no longer owns
    try:
        assert view._arm_gesture(_row_center(view, idx)) is None
    finally:
        view._rows = saved


def test_release_of_another_button_mid_gesture_cancels_inertly(qtbot):
    view = _view(qtbot, [_evt(1, date(1200, 1, 1), date(1200, 1, 3))], rows_visible=8)
    selected: list[int] = []
    view.event_selected.connect(selected.append)
    p0 = _row_center(view, view.indexes_for_event(1)[0])
    _press(view, p0)
    armed = QPoint(p0.x(), p0.y() + DRAG_START_THRESHOLD_PX)
    _drag_to(view, armed)
    assert view._drag is not None and view._drag.active
    _release(view, armed, button=Qt.MouseButton.RightButton)
    assert view._drag is None
    assert selected == []  # a cancelled gesture never becomes a selection


def test_drop_of_a_record_that_left_the_sample_opens_no_menu(qtbot, monkeypatch):
    view = _view(qtbot, [_evt(1, date(1200, 1, 1), date(1200, 1, 2))], rows_visible=8)
    menus: list[tuple] = []
    monkeypatch.setattr(view, "_open_drop_menu", lambda *args: menus.append(args))
    p0 = _row_center(view, view.indexes_for_event(1)[0])
    _press(view, p0)
    target = _row_center(view, view.indexes_for_event(1)[0] + 2)
    _drag_to(view, QPoint(p0.x(), p0.y() + DRAG_START_THRESHOLD_PX))
    _drag_to(view, target)
    drag = view._drag
    assert drag is not None and drag.active
    assert drag.target_day is not None and drag.target_day != drag.source_day
    view._events = []  # the sample no longer holds the dragged record
    _release(view, target)
    assert menus == []
    assert view._drag is None


def test_trackpad_glide_without_vertical_delta_is_left_to_qt(qtbot):
    """No vertical delta (a horizontal glide) is not a ladder step (task 4.1).

    The ladder is scrolled first and a real notch follows, so "the value did
    not move" below cannot be vacuous: the bar is proven movable, and a step by
    ``sign(0)`` would have moved it.
    """
    view = _view(qtbot, [_evt(1, date(1200, 1, 1)), _evt(2, date(1200, 3, 1))],
                 rows_visible=3)
    bar = view.verticalScrollBar()
    assert bar.maximum() > 0
    view._scroll_row_to_top(5)
    parked = bar.value()
    assert parked > 0

    vp = view.viewport()
    pos = QPointF(vp.rect().center())
    QApplication.sendEvent(vp, QWheelEvent(
        pos, vp.mapToGlobal(pos.toPoint()), QPoint(120, 0), QPoint(0, 0),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    ))
    assert bar.value() == parked  # the glide did not step the ladder

    QApplication.sendEvent(vp, QWheelEvent(
        pos, vp.mapToGlobal(pos.toPoint()), QPoint(0, 0), QPoint(0, -120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    ))
    assert bar.value() == parked + 1  # a notch does step exactly one row


# ── panel: the knob and window guards ──────────────────────────────────────

def _panel(qtbot, vm=None) -> TimelineWidget:
    class _VM:
        events: list = []

    panel = TimelineWidget(vm or _VM())
    qtbot.addWidget(panel)
    panel.resize(280, 160)
    panel.show()
    return panel


def test_panel_ignores_a_viewmodel_exposing_unknown_knobs(qtbot):
    panel = _panel(qtbot, SimpleNamespace(
        events=[], level=ScaleUnit.MONTH, window="not-a-pair", hide_empty=True,
    ))
    assert panel._view_knobs() is None


def test_covering_a_span_already_inside_the_window_is_a_no_op(qtbot):
    """The wiring widens the window before a drop commit — but only when the
    span actually sticks out (task 5.3): inside the window nothing moves."""
    panel = _panel(qtbot)
    applied: list[tuple] = []
    panel.window_changed.connect(lambda start, end: applied.append((start, end)))
    panel._on_window_range(date(1200, 1, 1), date(1200, 12, 31))  # popover apply
    assert panel._window_range == (date(1200, 1, 1), date(1200, 12, 31))

    applied.clear()
    panel.cover_window_for_span(date(1200, 6, 1), None)
    assert panel._window_range == (date(1200, 1, 1), date(1200, 12, 31))
    assert applied == []  # no re-apply, so the caption/signal pair stayed put
