"""Unit tests for the day-ladder core (redesign-timeline-day-ladder tasks 1.1–1.5).

The module must import and run without a QApplication — the ladder core is
plain data (design D1/D10), so these are pure units with event doubles.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.presentation.views.timeline_rows import (
    CALENDAR_MAX,
    CALENDAR_MIN,
    GAP_COLLAPSE_DAYS,
    DayHeaderRow,
    DropAction,
    EmptyDayRow,
    EventRow,
    GapCollapsedRow,
    LadderRow,
    PeriodCardRow,
    PeriodHeaderRow,
    ScaleUnit,
    apply_drop_action,
    build_rows,
    content_bottom,
    drill_target,
    drop_actions,
    period_span,
    zoom_level,
    zoom_target,
)


class _Ev:
    """Minimal event double: the ladder core reads id/start/end/name (+ event_type)."""

    def __init__(self, eid: int, start: date, end: date | None = None, name: str = "") -> None:
        self.id = eid
        self.start_date = start
        self.end_date = end
        self.name = name or f"event-{eid}"


def _cards(rows: list[LadderRow]) -> list[EventRow]:
    return [row for row in rows if isinstance(row, EventRow)]


# ── 1.1 content_bottom / _range_for — «дно ленты» (spec «Лента времени») ─────

def test_content_bottom_open_events_set_the_bottom():
    """Spec scenario «Дно при бессрочных событиях»: closed end 1240, open start
    1240-06-10+ — bottom is the open start plus one year."""
    events = [
        _Ev(1, date(1240, 1, 1), date(1240, 12, 31)),   # latest closed end: 1240
        _Ev(2, date(1250, 6, 10)),                      # open: start 1250
    ]
    assert content_bottom(events) == date(1251, 6, 10)


def test_content_bottom_empty_list_is_the_calendar_floor():
    """An empty sample has no content: the bottom is the calendar's start."""
    assert content_bottom([]) == CALENDAR_MIN


def test_content_bottom_never_precedes_the_latest_open_start():
    """open + 1 year keeps the bottom below every card the tape must paint."""
    events = [_Ev(1, date(1240, 1, 1), date(1240, 3, 1)), _Ev(2, date(1240, 6, 1))]
    assert content_bottom(events) == date(1241, 6, 1)  # past the closed end 1240-03-01


def test_content_bottom_clamps_open_bottom_to_calendar_max():
    """An open event starting in 9999 cannot mint a year the card calendar
    does not have — the bottom clamps to CALENDAR_MAX."""
    assert content_bottom([_Ev(1, date(9999, 6, 1))]) == CALENDAR_MAX


def test_content_bottom_open_leap_start_lands_on_flat_february():
    """Feb 29 + 1 year → Feb 28 of the flat year (no ValueError)."""
    assert content_bottom([_Ev(1, date(2024, 2, 29))]) == date(2025, 2, 28)


def _range(events, window=None):
    from app.presentation.views.timeline_rows import _range_for

    return _range_for(sorted(events, key=lambda e: (e.start_date, e.id)), window)


def test_range_for_without_window_spans_first_start_to_bottom():
    """Spec scenario «Диапазон без окна»: min(start) … content_bottom."""
    events = [_Ev(1, date(1200, 1, 1), date(1200, 1, 3)), _Ev(2, date(1200, 1, 9))]
    assert _range(events) == (date(1200, 1, 1), content_bottom(events))


def test_range_for_with_window_uses_the_window_days():
    assert _range([_Ev(1, date(1200, 1, 1))], (date(1200, 5, 5), date(1200, 5, 20))) == (
        date(1200, 5, 5), date(1200, 5, 20),
    )


def test_range_for_empty_sample_without_window_own_no_span():
    assert _range([]) is None


def test_range_for_inverted_and_partial_windows_behave():
    """Inverted bounds own no days; an incomplete window (a None bound) falls
    back to the content span (the chip only ever sets a complete pair)."""
    assert _range([], (date(1200, 5, 20), date(1200, 5, 5))) is None
    assert _range([_Ev(1, date(1200, 1, 1), date(1200, 1, 1))], (None, None)) == (
        date(1200, 1, 1), date(1200, 1, 1),
    )


# ── 1.2 day level — dubs, empties, collapsed gaps (spec «Лента дней…») ──────

def test_multiday_event_gets_a_card_on_every_day():
    """Spec scenario «Многодневка дублируется по дням»: March 3–10 paints a
    card in each of the eight days, all pointing at the one event."""
    rows = build_rows([_Ev(7, date(1200, 3, 3), date(1200, 3, 10), name="поход")])
    cards = _cards(rows)
    assert [row.date for row in cards] == [date(1200, 3, day) for day in range(3, 11)]
    assert {row.event_id for row in cards} == {7}
    assert all(row.start == date(1200, 3, 3) and row.end == date(1200, 3, 10) for row in cards)
    assert all(row.name == "поход" for row in cards)


def test_open_event_duplicates_down_to_the_bottom():
    """Spec scenario «Бессрочное дублируется до дна»: with the bottom pinned
    at March 30 (a window), an open March 3 event cards every day 3–30."""
    rows = build_rows(
        [_Ev(2, date(1200, 3, 3))],
        window=(date(1200, 3, 1), date(1200, 3, 30)),
    )
    cards = _cards(rows)
    assert [row.date for row in cards] == [date(1200, 3, day) for day in range(3, 31)]
    assert all(row.end is None for row in cards)  # the row never asserts an end


def test_each_day_section_is_header_then_cards():
    """One sticky day header per day; cards follow under it, never before."""
    events = [
        _Ev(1, date(1200, 3, 3), date(1200, 3, 4)),
        _Ev(2, date(1200, 3, 4), date(1200, 3, 4)),
        _Ev(3, date(1200, 3, 6), date(1200, 3, 6)),
    ]
    rows = build_rows(events)
    kinds = [type(row).__name__ for row in rows]
    assert kinds == [
        # Mar 3: e1 · Mar 4: e1,e2 · Mar 5: empty · Mar 6: e3
        "DayHeaderRow", "EventRow",
        "DayHeaderRow", "EventRow", "EventRow",
        "DayHeaderRow", "EmptyDayRow",
        "DayHeaderRow", "EventRow",
    ]


def test_empty_day_occupies_exactly_one_placeholder():
    """Spec scenario «Пустой день — плейсхолдер»: day 2 is one «нет события»
    row under its header; neighboring days do not shift."""
    rows = build_rows([
        _Ev(1, date(1200, 3, 1), date(1200, 3, 1)),
        _Ev(2, date(1200, 3, 3), date(1200, 3, 3)),
    ])
    day2 = [row for row in rows if row.date == date(1200, 3, 2)]
    assert [type(row).__name__ for row in day2] == ["DayHeaderRow", "EmptyDayRow"]
    assert len([row for row in rows if isinstance(row, EmptyDayRow)]) == 1


def test_gap_of_forty_days_is_a_single_position():
    """Spec scenario «Провал схлопнут»: a 40-day eventless run becomes one
    GapCollapsedRow carrying its real bounds, not forty rows."""
    events = [
        _Ev(1, date(1200, 1, 1), date(1200, 1, 1)),
        _Ev(2, date(1200, 2, 15), date(1200, 2, 15)),  # 43 empty days between
    ]
    rows = build_rows(events)
    gaps = [row for row in rows if isinstance(row, GapCollapsedRow)]
    assert len(gaps) == 1
    assert (gaps[0].date, gaps[0].end) == (date(1200, 1, 2), date(1200, 2, 14))
    assert not any(isinstance(row, EmptyDayRow) for row in rows)


def test_gap_collapses_only_above_the_threshold():
    """GAP_COLLAPSE_DAYS=14: a 14-day run stays expanded day by day, a 15-day
    run collapses («провалы … длиннее 14 дней»)"""
    assert GAP_COLLAPSE_DAYS == 14
    run14 = build_rows([
        _Ev(1, date(1200, 1, 1), date(1200, 1, 1)),
        _Ev(2, date(1200, 1, 16), date(1200, 1, 16)),
    ])
    assert not any(isinstance(row, GapCollapsedRow) for row in run14)
    assert len([row for row in run14 if isinstance(row, EmptyDayRow)]) == 14

    run15 = build_rows([
        _Ev(1, date(1200, 1, 1), date(1200, 1, 1)),
        _Ev(2, date(1200, 1, 17), date(1200, 1, 17)),
    ])
    gaps = [row for row in run15 if isinstance(row, GapCollapsedRow)]
    assert len(gaps) == 1 and len([r for r in run15 if isinstance(r, EmptyDayRow)]) == 0


def test_positions_are_uniform_by_row_type():
    """Equal-height contract spelled on the type: every position a mixed day
    ladder yields is one of the six LadderRow dataclasses — the view paints
    each of them at exactly one ROW_HEIGHT."""
    events = [
        _Ev(1, date(1200, 1, 1), date(1200, 1, 3)),
        _Ev(2, date(1200, 1, 25), date(1200, 1, 25)),
        _Ev(3, date(1200, 3, 1)),  # open → runs to the bottom
    ]
    rows = build_rows(events)
    assert rows
    allowed = {DayHeaderRow, EventRow, EmptyDayRow, GapCollapsedRow, PeriodHeaderRow, PeriodCardRow}
    assert {type(row) for row in rows} <= allowed
    for row in rows:
        assert isinstance(row, LadderRow)


def test_day_cards_are_ordered_by_start_then_id():
    """Spec «Порядок карточек внутри дня»: (start_date, id); a longer-running
    event precedes a later-day starter even when its id is bigger — the sort
    key is the span's own start."""
    events = [
        _Ev(4, date(1200, 1, 2), date(1200, 1, 2)),
        _Ev(2, date(1200, 1, 1), date(1200, 1, 3)),
        _Ev(1, date(1200, 1, 1), date(1200, 1, 1)),
    ]
    day1 = [row.event_id for row in build_rows(events) if row.date == date(1200, 1, 1) and isinstance(row, EventRow)]
    assert day1 == [1, 2]  # same start, id order
    day2 = [row.event_id for row in build_rows(events) if row.date == date(1200, 1, 2) and isinstance(row, EventRow)]
    assert day2 == [2, 4]  # e2 started Jan 1 — earlier than e4's Jan 2


def test_single_event_ladder_spans_exactly_its_days():
    rows = build_rows([_Ev(1, date(1200, 1, 3), date(1200, 1, 3))])
    assert [type(row).__name__ for row in rows] == ["DayHeaderRow", "EventRow"]


# ── 1.3 period levels — month/year counter cards ─────────────────────────────

def test_month_level_emits_header_then_counter_card():
    rows = build_rows(
        [_Ev(1, date(1200, 3, 5), date(1200, 3, 20))],
        window=(date(1200, 3, 1), date(1200, 3, 31)),
        level=ScaleUnit.MONTH,
    )
    assert [(type(row).__name__, row.date, row.level) for row in rows] == [
        ("PeriodHeaderRow", date(1200, 3, 1), ScaleUnit.MONTH),
        ("PeriodCardRow", date(1200, 3, 1), ScaleUnit.MONTH),
    ]
    assert rows[1].count == 1


def test_period_counter_counts_events_crossing_the_period():
    """Spec scenario «Строка месяца со счётчиком»: four events running in
    March ⇒ the March card says 4."""
    march = [
        _Ev(1, date(1200, 3, 2), date(1200, 3, 5)),
        _Ev(2, date(1200, 3, 10), date(1200, 3, 10)),
        _Ev(3, date(1200, 2, 25), date(1200, 3, 1)),  # crosses in from February
        _Ev(4, date(1200, 3, 30), date(1200, 4, 3)),  # …and out into April
    ]
    rows = build_rows(march, window=(date(1200, 3, 1), date(1200, 3, 31)), level=ScaleUnit.MONTH)
    card = next(row for row in rows if isinstance(row, PeriodCardRow))
    assert card.count == 4


def test_year_counter_scenario():
    """Spec scenario «Годовая карточка-счётчик»: seven events in 1245 → «7 событий»."""
    events = [
        *[_Ev(i, date(1245, 1, i + 1), date(1245, 2, 1)) for i in range(1, 8)],
        _Ev(9, date(1246, 1, 1)),  # neighboring year must not inflate 1245
    ]
    rows = build_rows(events, window=(date(1245, 1, 1), date(1246, 12, 31)), level=ScaleUnit.YEAR)
    cards = {row.date.year: row.count for row in rows if isinstance(row, PeriodCardRow)}
    assert cards == {1245: 7, 1246: 1}


def test_empty_period_is_a_no_events_position_not_a_gap():
    """Spec scenario «Пустой месяц на ступени месяца»: an empty April keeps a
    muted «нет событий» card; other months do not shift."""
    rows = build_rows(
        [_Ev(1, date(1200, 3, 10), date(1200, 3, 11))],
        window=(date(1200, 3, 1), date(1200, 4, 30)),
        level=ScaleUnit.MONTH,
    )
    pairs = [
        (row.date, row.count)
        for row in rows if isinstance(row, PeriodCardRow)
    ]
    assert pairs == [(date(1200, 3, 1), 1), (date(1200, 4, 1), 0)]
    # every card sits directly under its own period header
    assert [type(row).__name__ for row in rows] == ["PeriodHeaderRow", "PeriodCardRow"] * 2


def test_multiday_and_open_events_cross_period_boundaries():
    """A Feb 20 … Apr 10 span counts into Feb/Mar/Apr once each (unique ids);
    an open start in November counts through the window's end too."""
    span = build_rows(
        [_Ev(9, date(1200, 2, 20), date(1200, 4, 10))],
        window=(date(1200, 2, 1), date(1200, 4, 30)),
        level=ScaleUnit.MONTH,
    )
    assert [row.count for row in span if isinstance(row, PeriodCardRow)] == [1, 1, 1]

    open_run = build_rows(
        [_Ev(7, date(1200, 11, 10))],
        window=(date(1200, 11, 1), date(1200, 12, 31)),
        level=ScaleUnit.MONTH,
    )
    assert [row.count for row in open_run if isinstance(row, PeriodCardRow)] == [1, 1]


def test_year_level_enumerates_every_year_of_the_window():
    rows = build_rows(
        [_Ev(1, date(1240, 6, 1), date(1240, 6, 2)), _Ev(2, date(1243, 1, 1), date(1243, 1, 1))],
        window=(date(1240, 1, 1), date(1243, 12, 31)),
        level=ScaleUnit.YEAR,
    )
    assert [row.date.year for row in rows if isinstance(row, PeriodCardRow)] == [1240, 1241, 1242, 1243]
    assert [row.count for row in rows if isinstance(row, PeriodCardRow)] == [1, 0, 0, 1]


# ── 1.4 zoom / drop pure functions ────────────────────────────────────────────

def test_zoom_level_walks_the_ladder_and_clamps():
    """«отдаление: сутки → месяц → год», «приближение: год → месяц → сутки» —
    steps clamp at both ends; 0 is the identity."""
    assert zoom_level(ScaleUnit.DAY, -1) == ScaleUnit.MONTH
    assert zoom_level(ScaleUnit.MONTH, -1) == ScaleUnit.YEAR
    assert zoom_level(ScaleUnit.YEAR, -1) == ScaleUnit.YEAR   # nothing coarser
    assert zoom_level(ScaleUnit.YEAR, 1) == ScaleUnit.MONTH
    assert zoom_level(ScaleUnit.MONTH, 1) == ScaleUnit.DAY
    assert zoom_level(ScaleUnit.DAY, 1) == ScaleUnit.DAY      # nothing finer
    assert zoom_level(ScaleUnit.MONTH, 0) == ScaleUnit.MONTH
    assert zoom_level(ScaleUnit.DAY, -5) == ScaleUnit.YEAR    # multi-step clamps


def test_zoom_target_from_daily_rows_anchors_on_the_month():
    """Scenario «Якорь при отдалении»: the daily row 14 March anchors March."""
    assert zoom_target(ScaleUnit.DAY, DayHeaderRow(date(1200, 3, 14))) == date(1200, 3, 1)
    card = EventRow(date(1200, 3, 14), event_id=1, start=date(1200, 3, 10), end=None, name="x")
    assert zoom_target(ScaleUnit.DAY, card) == date(1200, 3, 1)
    assert zoom_target(ScaleUnit.DAY, EmptyDayRow(date(1200, 3, 14))) == date(1200, 3, 1)


def test_zoom_target_from_period_rows_anchors_on_the_year():
    monthly = PeriodCardRow(date(1245, 6, 1), ScaleUnit.MONTH, 3)
    assert zoom_target(ScaleUnit.MONTH, monthly) == date(1245, 1, 1)
    header = PeriodHeaderRow(date(1245, 6, 1), ScaleUnit.MONTH)
    assert zoom_target(ScaleUnit.MONTH, header) == date(1245, 1, 1)
    yearly = PeriodCardRow(date(1245, 1, 1), ScaleUnit.YEAR, 3)
    assert zoom_target(ScaleUnit.YEAR, yearly) == date(1245, 1, 1)  # nothing coarser


def test_zoom_target_without_a_card_or_on_a_gap_is_none():
    assert zoom_target(ScaleUnit.DAY, None) is None
    gap = GapCollapsedRow(date(1200, 3, 1), date(1200, 4, 1))
    assert zoom_target(ScaleUnit.DAY, gap) is None


def test_drill_target_month_card_goes_to_days_with_the_whole_month():
    """Task 4.2 (spec «Клик по месяцу приближает»): month→day + window = the
    card's month — the empty card drills identically (count never matters)."""
    level, window = drill_target(PeriodCardRow(date(1200, 3, 1), ScaleUnit.MONTH, 4))
    assert level is ScaleUnit.DAY
    assert window == (date(1200, 3, 1), date(1200, 3, 31))
    assert drill_target(PeriodCardRow(date(1200, 4, 1), ScaleUnit.MONTH, 0)) == (
        ScaleUnit.DAY, (date(1200, 4, 1), date(1200, 4, 30)),
    )
    # February, leap and flat alike
    assert drill_target(PeriodCardRow(date(1200, 2, 1), ScaleUnit.MONTH, 1))[1] == (
        date(1200, 2, 1), date(1200, 2, 29),
    )


def test_drill_target_year_card_goes_to_months_with_the_whole_year():
    """Spec «Провал из года в месяцы»: year→month + window = the whole year."""
    level, window = drill_target(PeriodCardRow(date(1245, 1, 1), ScaleUnit.YEAR, 7))
    assert level is ScaleUnit.MONTH
    assert window == (date(1245, 1, 1), date(1245, 12, 31))


def test_drill_target_clamps_to_the_calendar_edge():
    """The 9999 rung has no following unit — the window ends at the edge."""
    assert drill_target(PeriodCardRow(date(9999, 1, 1), ScaleUnit.YEAR, 0))[1] == (
        date(9999, 1, 1), CALENDAR_MAX,
    )
    assert drill_target(PeriodCardRow(date(9999, 12, 1), ScaleUnit.MONTH, 0))[1] == (
        date(9999, 12, 1), CALENDAR_MAX,
    )


def test_period_span_covers_the_whole_period_of_any_period_row():
    """Task 9 (defect b): the inward wheel installs «окно = период» — the span
    is shared with the drill: card AND header rows of every rung own it, the
    edge clamps, day-level and absent rows have no span."""
    assert period_span(PeriodCardRow(date(1200, 4, 1), ScaleUnit.MONTH, 1)) == (
        date(1200, 4, 1), date(1200, 4, 30),
    )
    # a period HEADER anchors like its card (spec «над sticky/секционным
    # заголовком — в период этого заголовка»)
    assert period_span(PeriodHeaderRow(date(1245, 1, 1), ScaleUnit.YEAR)) == (
        date(1245, 1, 1), date(1245, 12, 31),
    )
    assert period_span(PeriodCardRow(date(9999, 1, 1), ScaleUnit.YEAR, 0))[1] \
        == CALENDAR_MAX
    assert period_span(DayHeaderRow(date(1200, 3, 14))) is None
    assert period_span(EmptyDayRow(date(1200, 3, 14))) is None
    assert period_span(None) is None


def _span(start: date, end: date | None, eid: int = 1) -> _Ev:
    return _Ev(eid, start, end)


def test_drop_actions_below_the_end_offers_extend_down():
    """Task 1.4 «вниз-вне-конца»: a closed 3–10 event dropped on March 15.»"""
    actions = drop_actions(_span(date(1200, 3, 3), date(1200, 3, 10)), date(1200, 3, 15))
    assert actions == {
        DropAction.MOVE: True,
        DropAction.EXTEND_DOWN: True,
        DropAction.START_EARLIER: False,
    }


def test_drop_actions_above_the_start_offers_start_earlier():
    """Task 1.4 «вверх-вне-начала»."""
    actions = drop_actions(_span(date(1200, 3, 3), date(1200, 3, 10)), date(1200, 3, 1))
    assert actions[DropAction.MOVE] and actions[DropAction.START_EARLIER]
    assert not actions[DropAction.EXTEND_DOWN]


def test_drop_actions_inside_the_span_is_move_only():
    """Spec scenario «Дроп внутрь своего промежутка» + task 1.4 same-day: a
    re-drop onto a day the event already owns never suggests boundary moves."""
    inside = drop_actions(_span(date(1200, 3, 3), date(1200, 3, 10)), date(1200, 3, 7))
    assert inside == {DropAction.MOVE: True, DropAction.EXTEND_DOWN: False, DropAction.START_EARLIER: False}
    same_day = drop_actions(_span(date(1200, 3, 7), date(1200, 3, 7)), date(1200, 3, 7))
    assert same_day == inside


def test_drop_actions_open_events_never_offer_extend_down():
    """Spec «Бессрочные события» / scenario «Бессрочное не расширяется вниз»."""
    open_event = _span(date(1200, 3, 5), None)
    later = drop_actions(open_event, date(1200, 3, 20))
    assert later == {DropAction.MOVE: True, DropAction.EXTEND_DOWN: False, DropAction.START_EARLIER: False}
    earlier = drop_actions(open_event, date(1200, 3, 1))
    assert earlier[DropAction.MOVE] and earlier[DropAction.START_EARLIER]
    assert not earlier[DropAction.EXTEND_DOWN]


def test_drop_actions_compare_the_calendar_clamped_target():
    """A target beyond the calendar is clamped before the comparison."""
    closed = _span(date(1200, 3, 3), date(1200, 3, 10))
    assert drop_actions(closed, date(99, 1, 1))[DropAction.START_EARLIER]
    assert drop_actions(closed, date(9999, 12, 31))[DropAction.EXTEND_DOWN]


def test_apply_move_preserves_the_length():
    """Spec scenarios «Перенос многодневки сохраняет длину» / однодневное
    остаётся однодневным; the end follows the clamped target."""
    event = _span(date(1200, 3, 3), date(1200, 3, 10))
    assert apply_drop_action(event, DropAction.MOVE, date(1200, 3, 12)) == (
        date(1200, 3, 12), date(1200, 3, 19),
    )
    pin = _span(date(1200, 3, 5), date(1200, 3, 5))
    assert apply_drop_action(pin, "move", date(1200, 12, 30)) == (date(1200, 12, 30), date(1200, 12, 30))


def test_apply_move_on_an_open_event_keeps_the_end_open():
    """Spec: «у бессрочного end SHALL оставаться открытым» — start only."""
    assert apply_drop_action(_span(date(1200, 3, 5), None), "move", date(1200, 3, 20)) == (
        date(1200, 3, 20), None,
    )


def test_apply_extend_down_moves_only_the_end():
    """Spec scenario «Расширение вниз»: 3–10 → 3–15, начало не изменилось."""
    assert apply_drop_action(_span(date(1200, 3, 3), date(1200, 3, 10)),
                             "extend_down", date(1200, 3, 15)) == (
        date(1200, 3, 3), date(1200, 3, 15),
    )


def test_apply_start_earlier_moves_only_the_start():
    """Spec scenario «Начать раньше»: 3–10 → 1–10, окончание не изменилось;
    an open event stays open."""
    assert apply_drop_action(_span(date(1200, 3, 3), date(1200, 3, 10)),
                             "start_earlier", date(1200, 3, 1)) == (
        date(1200, 3, 1), date(1200, 3, 10),
    )
    assert apply_drop_action(_span(date(1200, 3, 3), None), "start_earlier", date(1200, 3, 1)) == (
        date(1200, 3, 1), None,
    )


def test_apply_extend_down_on_an_open_event_is_a_programming_error():
    """No silent no-op: applying an action drop_actions would not offer raises."""
    import pytest

    with pytest.raises(ValueError):
        apply_drop_action(_span(date(1200, 3, 5), None), DropAction.EXTEND_DOWN, date(1200, 3, 20))


def test_apply_drop_action_clamps_to_the_calendar():
    """Spec scenario «Цель ограничена календарём»: a target outside
    0100-01-01 … 9999-12-31 is clamped, the duration rides along inside."""
    event = _span(date(1200, 3, 3), date(1200, 3, 10))
    early = apply_drop_action(event, DropAction.MOVE, date(50, 1, 1))
    assert early == (CALENDAR_MIN, CALENDAR_MIN + (date(1200, 3, 10) - date(1200, 3, 3)))
    pin = apply_drop_action(_span(date(1200, 6, 1), None), "move", date(50, 1, 1))
    assert pin == (CALENDAR_MIN, None)
    earlier = apply_drop_action(event, "start_earlier", date(1, 1, 1))
    assert earlier == (CALENDAR_MIN, date(1200, 3, 10))


# ── 1.5 hide_empty and window overlap visibility ─────────────────────────────

def _mixed_tape() -> list[_Ev]:
    """Jan 1 card, Jan 3 card, a >14-day gap, then an open Feb event."""
    return [
        _Ev(1, date(1200, 1, 1), date(1200, 1, 1)),
        _Ev(2, date(1200, 1, 3), date(1200, 1, 3)),
        _Ev(3, date(1200, 1, 25)),  # open — the tape runs to its bottom
    ]


def test_hide_empty_takes_empty_rows_away_and_returns_them():
    """The toggle cuts «нет события» placeholders and collapsed gaps and puts
    them back verbatim; card positions never move off their days."""
    off = build_rows(_mixed_tape())
    on = build_rows(_mixed_tape(), hide_empty=True)
    assert any(isinstance(row, EmptyDayRow) for row in off)
    assert any(isinstance(row, GapCollapsedRow) for row in off)
    assert not any(isinstance(row, (EmptyDayRow, GapCollapsedRow)) for row in on)
    assert [(row.date, row.event_id) for row in _cards(on)] == [
        (row.date, row.event_id) for row in _cards(off)
    ]


def test_hide_empty_removes_empty_period_cards_with_their_headers():
    rows_off = build_rows(
        [_Ev(1, date(1200, 3, 10), date(1200, 3, 11))],
        window=(date(1200, 3, 1), date(1200, 4, 30)),
        level=ScaleUnit.MONTH,
    )
    rows_on = build_rows(
        [_Ev(1, date(1200, 3, 10), date(1200, 3, 11))],
        window=(date(1200, 3, 1), date(1200, 4, 30)),
        level=ScaleUnit.MONTH,
        hide_empty=True,
    )
    assert [row.count for row in rows_off if isinstance(row, PeriodCardRow)] == [1, 0]
    assert [row.count for row in rows_on if isinstance(row, PeriodCardRow)] == [1]
    assert all(row.date == date(1200, 3, 1) for row in rows_on)  # April header is gone too


def test_window_limits_the_tape_to_its_days():
    """«Окно SHALL ограничивать ленту»: the first row is the window's first
    day's header; nothing outside the window gets a position."""
    rows = build_rows(
        [_Ev(1, date(1200, 8, 15), date(1200, 8, 16))],
        window=(date(1200, 8, 10), date(1200, 8, 20)),
    )
    assert rows[0] == DayHeaderRow(date(1200, 8, 10))
    assert all(date(1200, 8, 10) <= row.date <= date(1200, 8, 20) for row in rows)


def test_overlapping_event_is_visible_across_the_whole_window():
    """Spec scenario «Пересекающее событие видно в окне»: window Aug 10–20,
    event Jul 1 – Sep 5 ⇒ a card on every day 10–20; events with no overlap
    own no position."""
    rows = build_rows(
        [
            _Ev(9, date(1200, 7, 1), date(1200, 9, 5)),
            _Ev(10, date(1200, 6, 1), date(1200, 6, 30)),  # entirely before
            _Ev(11, date(1200, 10, 1), date(1200, 10, 5)),  # entirely after
        ],
        window=(date(1200, 8, 10), date(1200, 8, 20)),
    )
    cards = _cards(rows)
    assert [row.date for row in cards] == [date(1200, 8, day) for day in range(10, 21)]
    assert {row.event_id for row in cards} == {9}


def test_window_events_keep_their_real_bounds_on_cards():
    """The clip is presentation-only: a card of a window-overflowing event
    still carries the event's true start/end."""
    rows = build_rows(
        [_Ev(9, date(1200, 7, 1), date(1200, 9, 5))],
        window=(date(1200, 8, 10), date(1200, 8, 20)),
    )
    assert all(row.start == date(1200, 7, 1) and row.end == date(1200, 9, 5) for row in _cards(rows))


def test_window_without_events_shows_placeholders_until_hidden():
    """Spec scenario «Пустое окно показано пустотой» + the toggle hides them."""
    rows = build_rows([], window=(date(1200, 8, 10), date(1200, 8, 13)))
    assert [type(row).__name__ for row in rows] == ["DayHeaderRow", "EmptyDayRow"] * 4
    assert build_rows([], window=(date(1200, 8, 10), date(1200, 8, 13)), hide_empty=True) == []


def test_empty_tape_without_window_is_no_rows():
    assert build_rows([]) == []


# ── unit helpers & edge guards (coverage pins, no public caller reaches them) ─


def test_day_unit_helpers_answer_the_plain_calendar_step():
    """DAY is the degenerate unit: its own first day is the day itself and the
    next unit is tomorrow. No public rung feeds DAY into the helpers (the day
    ladder enumerates days directly), so the branches are pinned directly."""
    from app.presentation.views.timeline_rows import _next_unit_start, _unit_start

    assert _unit_start(date(1200, 3, 14), ScaleUnit.DAY) == date(1200, 3, 14)
    assert _next_unit_start(date(1200, 3, 14), ScaleUnit.DAY) == date(1200, 3, 15)


def test_inverted_event_content_owns_no_span():
    """The form never inverts a span, but the guard owns malformed data: a
    closed event ending before its start makes «дно ленты» precede the sample's
    first day — an owning-no-position range, an empty tape."""
    inverted = [_Ev(1, date(9000, 1, 10), date(8999, 12, 1))]
    assert _range(inverted) is None
    assert build_rows(inverted) == []


def test_month_period_at_the_upper_edge_reaches_the_calendar_bottom():
    """After 9999-12 there is no next month (it would mint year 10000): the
    overflow reads as «this period reaches the edge» and the loop breaks —
    the tail period is emitted once, never forever."""
    rows = build_rows(
        [_Ev(1, date(9999, 12, 15))],
        window=(date(9999, 12, 1), CALENDAR_MAX),
        level=ScaleUnit.MONTH,
    )
    assert rows == [
        PeriodHeaderRow(date=date(9999, 12, 1), level=ScaleUnit.MONTH),
        PeriodCardRow(date=date(9999, 12, 1), level=ScaleUnit.MONTH, count=1),
    ]
