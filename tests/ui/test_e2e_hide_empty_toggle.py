"""Group 7 e2e: the «Скрыть даты без событий» toggle (task 7.3, spec
«Скрытие дат без событий»).

Full user path through the running app: the header toggle sits next to
«Выбор даты» and defaults to OFF; switching it on cuts the empty positions of
EVERY rung — «нет события» placeholders and the collapsed gap corridor on
«сутки», the muted «нет событий» counters on «месяц» and «год» — while the
event cards, counters and the date window survive; switching it off restores
the cut positions verbatim. The knob rides every reload yet lives in no store:
pure session state (spec «Вид не переживает перезапуск»).
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate

from app.presentation.views.timeline_rows import (
    EmptyDayRow, EventRow, GapCollapsedRow, PeriodCardRow, ScaleUnit,
)
from tests.ui import helpers
from tests.ui.conftest import query_db


def _empty_positions(view):
    """Every empty position on the current rung: placeholders, collapsed
    gaps, «нет событий» counter cards."""
    return [
        r for r in view.rows
        if isinstance(r, EmptyDayRow | GapCollapsedRow)
        or (isinstance(r, PeriodCardRow) and r.count == 0)
    ]


def _descend(application, window, level: ScaleUnit) -> None:
    """Move the rung the way the app's own descent paths do it: the VM setter
    (single mutation point) plus the mirror reload every reload performs
    (``update_events`` re-reads the knobs into the list)."""
    vm = application._wiring._timeline_vm
    vm.level = level
    window.timeline_widget.update_events(vm.events)


async def _seed_spread(window, wait_for) -> None:
    """March 1200 + a short early-May 1200 pair: the two-month corridor
    collapses into one gap row, the three-day run between the May events stays
    plain «нет события» placeholders (≤ GAP_COLLAPSE_DAYS)."""
    await helpers.create_event_via_ui(
        window, wait_for, "Старт",
        start_date=QDate(1200, 3, 1), end_date=QDate(1200, 3, 1),
    )
    await helpers.create_event_via_ui(
        window, wait_for, "Середина",
        start_date=QDate(1200, 5, 1), end_date=QDate(1200, 5, 1),
    )
    await helpers.create_event_via_ui(
        window, wait_for, "Финиш",
        start_date=QDate(1200, 5, 5), end_date=QDate(1200, 5, 5),
    )


async def test_toggle_hides_and_restores_emptiness_on_all_levels(app, wait_for):
    """Spec «Пустые дни исчезают» + «Пустые периоды исчезают»: emptiness cuts
    and returns on сутки, месяц and год alike; the toggle defaults to off."""
    application, window = app
    widget = window.timeline_widget
    view = widget.rows_view
    await _seed_spread(window, wait_for)
    await wait_for(lambda: len(view.events) == 3)

    toggle = widget.hide_empty_toggle
    assert toggle.text() == "Скрыть даты без событий"
    assert not toggle.isChecked()  # spec: «по умолчанию выключена»
    assert widget.window_chip.toolTip() == "Выбор даты"  # the header neighbor

    # ── DAY: empty days AND a collapsed corridor stand while the toggle is off
    day_empty = _empty_positions(view)
    assert any(isinstance(r, EmptyDayRow) for r in day_empty)
    assert any(isinstance(r, GapCollapsedRow) for r in day_empty)

    toggle.setChecked(True)
    await wait_for(lambda: _empty_positions(view) == [])
    assert [(type(r).__name__, r.date) for r in view.rows] == [
        ("DayHeaderRow", date(1200, 3, 1)), ("EventRow", date(1200, 3, 1)),
        ("DayHeaderRow", date(1200, 5, 1)), ("EventRow", date(1200, 5, 1)),
        ("DayHeaderRow", date(1200, 5, 5)), ("EventRow", date(1200, 5, 5)),
    ]  # cards and section headers survive: only emptiness was cut

    toggle.setChecked(False)
    await wait_for(lambda: _empty_positions(view) == day_empty)

    # ── MONTH: the eventless corridor months are muted «нет событий»
    _descend(application, window, ScaleUnit.MONTH)
    await helpers.wait_until_settled()
    empty_months = [r.date for r in _empty_positions(view)]
    assert date(1200, 3, 1) not in empty_months
    assert date(1200, 4, 1) in empty_months  # April sits between the events
    assert date(1200, 5, 1) not in empty_months

    toggle.setChecked(True)
    await wait_for(lambda: _empty_positions(view) == [])
    assert [r.date for r in view.rows if isinstance(r, PeriodCardRow)] == [
        date(1200, 3, 1), date(1200, 5, 1),
    ]  # the two counters with events keep their places on the rung

    # ── YEAR: widen through the window so 1199/1201 are eventless years, then
    # the year rung carries its own «нет событий» counters
    toggle.setChecked(False)
    await helpers.wait_until_settled()
    widget._on_window_range(date(1199, 1, 1), date(1201, 12, 31))
    await helpers.wait_until_settled()
    _descend(application, window, ScaleUnit.YEAR)
    await helpers.wait_until_settled()
    year_empty = _empty_positions(view)
    assert [r.date for r in year_empty] == [date(1199, 1, 1), date(1201, 1, 1)]
    assert not any(isinstance(r, EventRow) for r in view.rows)

    toggle.setChecked(True)
    await wait_for(lambda: _empty_positions(view) == [])
    assert [r.date for r in view.rows if isinstance(r, PeriodCardRow)] == [
        date(1200, 1, 1),
    ]  # the year with events stays

    # ── off again on the year rung — the cut positions return verbatim
    toggle.setChecked(False)
    await wait_for(lambda: _empty_positions(view) == year_empty)

    # the sample never moved through all of this
    assert len(view.events) == 3


async def test_toggle_survives_reloads_but_lives_in_no_store(app, wait_for):
    """A reload must not silently re-grow emptiness (the knob rides every
    reload) — yet nothing persists the knob: no game_settings row anywhere."""
    application, window = app
    widget = window.timeline_widget
    view = widget.rows_view
    await _seed_spread(window, wait_for)
    await wait_for(lambda: len(view.events) == 3)
    widget._on_window_range(date(1200, 5, 1), date(1200, 5, 20))
    await helpers.wait_until_settled()
    # the March event fell out of the window — the May pair stays visible
    await wait_for(lambda: len(view.events) == 2)
    await helpers.wait_until_settled()
    assert _empty_positions(view)  # May 2–4 and May 6–20 stand empty

    widget.hide_empty_toggle.setChecked(True)
    await wait_for(lambda: _empty_positions(view) == [])
    assert window.timeline_widget._vm.hide_empty is True

    # An unrelated write + reload keeps the hidden state (knobs ride reloads).
    await helpers.create_event_via_ui(
        window, wait_for, "Друг",
        start_date=QDate(1200, 5, 15), end_date=QDate(1200, 5, 16),
    )
    await helpers.wait_until_settled()
    assert window.timeline_widget._vm.hide_empty is True
    assert not any(isinstance(r, EmptyDayRow) for r in view.rows)

    # …and NOTHING persisted it: the game settings table knows no such key.
    keys = [
        row[0] for row in query_db(
            application._db_path, "SELECT key FROM game_settings", ()
        )
    ]
    assert not [
        k for k in keys if "hide" in str(k).lower() or "скрыт" in str(k).lower()
    ]
