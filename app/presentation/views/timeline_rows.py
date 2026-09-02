"""Pure row model of the vertical event timeline — no Qt imports.

redesign-timeline-day-ladder (design D2): the ladder core is ``build_rows`` —
sticky day headers with per-day *duplicates* of every event card (an open
event runs to the tape's ``content_bottom``), collapsing eventless gaps,
month/year period levels with per-period counters, ``hide_empty`` windowing of
empty positions, plus the pure zoom/drop helpers (``zoom_target``/
``zoom_level``, ``drop_actions``/``apply_drop_action``). Input contract:
event-like objects (anything exposing ``id``/``start_date``/``end_date``/
``name``, e.g. domain ``Event`` instances), the «Выбор даты» navigation
``window`` and the view knobs — the ladder *level* (сутки/месяц/год) and the
hide-empty toggle.

Event cards carry ``token_key`` — ``"color.chart.{color_index}"`` when the
event has a ``event_type.color_index`` (duck-typed, the core never imports the
domain), ``None`` otherwise — so delegates color type dots without knowing
about types. The pre-redesign side rail — its geometry hit-tests, lane packing
and stretch handles — was deleted with the rail (design D9); only the helpers
the drop gesture still uses survived (``clamp_calendar``, ``translate_span``).
All of this is plain deterministic data, testable without a QApplication.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Protocol, Sequence

from app.presentation.utils.date_utils import format_game_date, month_name

#: Inclusive calendar bounds of ``CustomDateEdit`` (W5 D2/D7). A drop target
#: never leaves this interval — the gesture cannot mint a date the card
#: cannot display.
CALENDAR_MIN = date(100, 1, 1)
CALENDAR_MAX = date(9999, 12, 31)


class ScaleUnit(Enum):
    """One rung of the view ladder: the unit a position stands for."""

    DAY = "day"
    MONTH = "month"
    YEAR = "year"


class _EventLike(Protocol):
    """The minimal shape ``build_rows`` reads off an event.

    An optional ``event_type`` attribute (duck-typed, ``.color_index`` read off
    it) only decorates event cards with ``token_key``; doubles may omit it.
    """

    id: int
    start_date: date
    end_date: date | None
    name: str


def _unit_start(day: date, unit: ScaleUnit) -> date:
    """First day of the unit of the ladder ``unit`` that contains ``day``."""
    if unit is ScaleUnit.MONTH:
        return date(day.year, day.month, 1)
    if unit is ScaleUnit.YEAR:
        return date(day.year, 1, 1)
    return day


def _next_unit_start(unit_first: date, unit: ScaleUnit) -> date:
    """First day of the unit following the one starting at ``unit_first``."""
    if unit is ScaleUnit.MONTH:
        if unit_first.month == 12:
            return date(unit_first.year + 1, 1, 1)
        return date(unit_first.year, unit_first.month + 1, 1)
    if unit is ScaleUnit.YEAR:
        return date(unit_first.year + 1, 1, 1)
    return unit_first + timedelta(days=1)


def _event_token_key(event: _EventLike) -> str | None:
    """Type-dot token of an event ("color.chart.N"), None when untyped.

    Duck-typed on purpose: the core stays Qt-free *and* domain-free, it only
    mirrors the token key the ui-theme palette defines (W4 D5).
    """
    event_type = getattr(event, "event_type", None)
    color_index = getattr(event_type, "color_index", None)
    if color_index is None:
        return None
    return f"color.chart.{color_index}"


def clamp_calendar(day: date) -> date:
    """Clip ``day`` to :data:`CALENDAR_MIN` … :data:`CALENDAR_MAX` (W5 1.5)."""
    if day < CALENDAR_MIN:
        return CALENDAR_MIN
    if day > CALENDAR_MAX:
        return CALENDAR_MAX
    return day


def translate_span(start: date, end: date, delta_days: int) -> tuple[date, date]:
    """Shift a closed span by ``delta_days``, duration intact (W5 1.3).

    Both bounds move by the same amount, so the length never changes and the
    pair never inverts (for a closed input, ``end ≥ start`` is
    shift-invariant). This layer is *only* the shift — clamping to the model
    or the view's window clamp is the view/wiring's business, not the arithmetic's.
    """
    shift = timedelta(days=delta_days)
    return start + shift, end + shift


# ── the day-ladder contract (design D2/D5/D6) ────────────────────────────────
# Sticky day sections with per-day card duplicates, collapsing eventless gaps,
# month/year period levels with counters, the zoom/drop pure helpers and the
# ``hide_empty`` / window knobs. All positions are equal-height by construction
# — the row TYPE is the height invariant (the view renders every ladder row at
# ROW_HEIGHT).

#: An eventless run LONGER than this many days collapses into a single
#: :class:`GapCollapsedRow` position (spec «Лента времени», design D2).
GAP_COLLAPSE_DAYS = 14

#: The ladder knob of the core: the three period rungs (сутки/месяц/год).
Level = ScaleUnit


class DropAction(Enum):
    """One mutation the drop gesture's release menu can commit (D5)."""

    MOVE = "move"
    EXTEND_DOWN = "extend_down"
    START_EARLIER = "start_earlier"


@dataclass(frozen=True)
class DayHeaderRow:
    """Sticky section head of one day (daily level); ``date`` is the day."""

    date: date


@dataclass(frozen=True)
class EventRow:
    """One event card sitting in one day — a multi-day event repeats.

    ``date`` is the day this duplicate card belongs to; ``start``/``end``
    mirror the event's REAL bounds (``end is None`` = open, the delegate
    paints the «бессрочно» mark from it), so every card of one event reads
    identical and any edit acts on the whole record. ``token_key`` is the
    duck-typed ``"color.chart.N"`` type-dot token (``None`` = untyped).
    """

    date: date
    event_id: int
    start: date
    end: date | None
    name: str
    token_key: str | None = None


@dataclass(frozen=True)
class EmptyDayRow:
    """The one-and-only placeholder position of an eventless day."""

    date: date


@dataclass(frozen=True)
class GapCollapsedRow:
    """One position standing for an eventless run longer than the threshold.

    ``date``/``end`` are the gap's real bounds — the delegate formats them
    with the game calendar; the row answers no event selection.
    """

    date: date
    end: date


@dataclass(frozen=True)
class PeriodHeaderRow:
    """Sticky header of one month/year period (MONTH/YEAR levels)."""

    date: date  # first day of the period
    level: ScaleUnit


@dataclass(frozen=True)
class PeriodCardRow:
    """The one clickable card of a period: ``count`` events cross it.

    ``count == 0`` is the muted «нет событий» position — still a position,
    still drills a level down (design D6).
    """

    date: date  # first day of the period
    level: ScaleUnit
    count: int


#: Union of every ladder position type (the equal-height contract: the view
#: paints each of these at exactly one ROW_HEIGHT).
LadderRow = DayHeaderRow | EventRow | EmptyDayRow | GapCollapsedRow | PeriodHeaderRow | PeriodCardRow

_ONE_DAY = timedelta(days=1)


# ── sticky overlay state (design D3: the two push-out QLabel captions) ──────


def is_header_row(row: object) -> bool:
    """Whether ``row`` opens a sticky section (day or period header)."""
    return isinstance(row, DayHeaderRow | PeriodHeaderRow)


def header_caption(row: DayHeaderRow | PeriodHeaderRow) -> str:
    """The game-calendar caption of a section header row.

    Re-reads the live month map on every call (a month rename repaints without
    a rebuild): full game date per day, «Март 1245» per month, «1245» per year
    (spec «Липкий заголовок периода», «Игровые месяцы»).
    """
    if isinstance(row, PeriodHeaderRow):
        if row.level is ScaleUnit.MONTH:
            return f"{month_name(row.date.month)} {row.date.year}"
        return str(row.date.year)
    return format_game_date(row.date)


@dataclass(frozen=True)
class StickyState:
    """Core-side truth behind the view's two sticky overlays (design D3).

    ``current_index``/``current_text`` describe the header of the section the
    tape's top edge sits in (``None``/``""`` while no section has started —
    e.g. the tape opens on a collapsed gap); ``next_index``/``next_text`` are
    the chasing header the view animates its second label with (``None`` when
    the current section runs to the end of the tape).
    """

    current_index: int | None
    current_text: str
    next_index: int | None
    next_text: str


def sticky_state(rows: Sequence[LadderRow], first_visible_index: int) -> StickyState:
    """The sticky captions for a tape scrolled so ``first_visible_index`` is
    the top row (design D3 — the equal-height contract makes the view's
    top-row hit-test this index; a negative/out-of-range value is clamped).

    Pure and Qt-free: the view owns geometry and the ~120 ms push-out
    animation, the core owns *what* the two overlays say — the section header
    of the row at the top edge and the header coming up behind it.
    """
    if not rows:
        return StickyState(None, "", None, "")
    top = min(max(first_visible_index, 0), len(rows) - 1)
    current_index = next(
        (i for i in range(top, -1, -1) if is_header_row(rows[i])), None
    )
    start = 0 if current_index is None else current_index + 1
    next_index = next(
        (i for i in range(start, len(rows)) if is_header_row(rows[i])), None
    )
    return StickyState(
        current_index,
        header_caption(rows[current_index]) if current_index is not None else "",
        next_index,
        header_caption(rows[next_index]) if next_index is not None else "",
    )


def _add_one_year(day: date) -> date:
    """``day`` one calendar year later clamped to the calendar edge; Feb 29
    lands on Feb 28 of the flat year."""
    if day.year >= CALENDAR_MAX.year:
        return CALENDAR_MAX  # there is no year 10000 to shift into
    try:
        return day.replace(year=day.year + 1)
    except ValueError:  # Feb 29 → the flat year has no such day
        return day.replace(year=day.year + 1, day=28)


def content_bottom(events: Sequence[_EventLike]) -> date:
    """The tape's bottom edge — the last day any card may stand on (D2).

    ``max(latest closed end_date, latest open start + 1 year)`` clamped to
    :data:`CALENDAR_MAX`; the bottom therefore never precedes the latest
    start (open + 1 year always does). An empty sample bottoms at
    :data:`CALENDAR_MIN` (an empty tape has no content); moving an event past
    the bottom re-derives a lower bottom on the next rebuild — days grow in.
    """
    bottom = CALENDAR_MIN
    for event in events:
        if event.end_date is not None:
            candidate = event.end_date
        else:
            candidate = _add_one_year(event.start_date)
        if candidate > bottom:
            bottom = candidate
    return clamp_calendar(bottom)


def _range_for(
    events: Sequence[_EventLike],
    window: tuple[date | None, date | None] | None,
) -> tuple[date, date] | None:
    """The day span the ladder enumerates, ``None`` when it owns no position.

    With a complete window (both bounds, the «Выбор даты» selection or a
    drilled period) → exactly the window's days, clamped to the calendar.
    Without one (``None``/partial) → the content span: from the earliest event
    start down to :func:`content_bottom`; no events at all → ``None`` (an
    empty tape shows only the view-level hint). Inverted bounds → ``None``.
    """
    if window is not None:
        win_start, win_end = window
        if win_start is not None and win_end is not None:
            win_start = clamp_calendar(win_start)
            win_end = clamp_calendar(win_end)
            if win_end < win_start:
                return None
            return win_start, win_end
    if not events:
        return None
    range_start = clamp_calendar(min(e.start_date for e in events))
    range_end = content_bottom(events)
    if range_end < range_start:
        return None
    return range_start, range_end


def build_rows(
    events: Sequence[_EventLike],
    window: tuple[date | None, date | None] | None = None,
    level: ScaleUnit = ScaleUnit.DAY,
    hide_empty: bool = False,
) -> list[LadderRow]:
    """Lay ``events`` out as the ladder's positions at ``level`` (design D2).

    * Range — :func:`_range_for`: the window's days, or the content span from
      the earliest start down to :func:`content_bottom` («дно ленты» without a
      window). Events are visible by OVERLAP with the range
      (``start <= range_end and (end is None or end >= range_start)``): one
      crossing the left edge enters with its cards inside the window, one
      running past the right edge is clipped to it, an open end runs to the
      bottom.
    * DAY — per day: :class:`DayHeaderRow` then one :class:`EventRow` per
      covering event in ``(start_date, id)`` order, or one
      :class:`EmptyDayRow`; an eventless run longer than
      :data:`GAP_COLLAPSE_DAYS` days stands as a single
      :class:`GapCollapsedRow` carrying its bounds.
    * MONTH/YEAR — per period: :class:`PeriodHeaderRow` plus one
      :class:`PeriodCardRow` counting the UNIQUE events crossing the period;
      an empty period keeps its («нет событий») position.
    * ``hide_empty`` — cuts :class:`EmptyDayRow`/:class:`GapCollapsedRow` and
      empty :class:`PeriodCardRow` (with their headers); days of cards, the
      window and everything else are untouched, disabling restores all.
    """
    ordered = sorted(events, key=lambda e: (e.start_date, e.id))
    span = _range_for(ordered, window)
    if span is None:
        return []
    range_start, range_end = span
    if level is ScaleUnit.DAY:
        return _build_day_ladder(ordered, range_start, range_end, hide_empty)
    return _build_period_ladder(ordered, range_start, range_end, level, hide_empty)


def _build_day_ladder(
    ordered: Sequence[_EventLike],
    range_start: date,
    range_end: date,
    hide_empty: bool,
) -> list[LadderRow]:
    """Daily level: header + per-day card duplicates, empties, collapsed gaps.

    Membership of a day in an event's card run changes only at an event start
    or the day after its (clipped) end, so the sweep walks the constant-
    coverage segments between those boundary days instead of every single day
    of a potentially millennia-wide range.
    """
    # (event, first card day, last card day) clipped into the range; the
    # overlap rule of the docstring is exactly ``s <= e`` here.
    runs: list[tuple[_EventLike, date, date]] = []
    for event in ordered:
        end_clipped = range_end if event.end_date is None else min(event.end_date, range_end)
        if event.start_date > range_end or end_clipped < range_start:
            continue  # no overlap with the range — not visible at all
        runs.append((event, event.start_date, end_clipped))

    boundaries = {range_start}
    boundaries.update(s for _e, s, _end in runs if s > range_start)
    boundaries.update(end + _ONE_DAY for _e, _s, end in runs if end < range_end)
    ordered_bounds = sorted(b for b in boundaries if range_start <= b <= range_end)

    rows: list[LadderRow] = []
    for idx, segment_start in enumerate(ordered_bounds):
        segment_end = ordered_bounds[idx + 1] - _ONE_DAY if idx + 1 < len(ordered_bounds) else range_end
        covering = [event for event, s, end in runs if s <= segment_start <= end]
        if covering:  # order inherited from ``runs`` = (start_date, id)
            day = segment_start
            while day <= segment_end:
                rows.append(DayHeaderRow(date=day))
                rows.extend(
                    EventRow(
                        date=day,
                        event_id=event.id,
                        start=event.start_date,
                        end=event.end_date,
                        name=event.name,
                        token_key=_event_token_key(event),
                    )
                    for event in covering
                )
                day += _ONE_DAY
            continue
        if hide_empty:  # empty days and collapses are cut wholesale
            continue
        run = (segment_end - segment_start).days + 1
        if run > GAP_COLLAPSE_DAYS:
            rows.append(GapCollapsedRow(date=segment_start, end=segment_end))
        else:
            day = segment_start
            while day <= segment_end:
                rows.append(DayHeaderRow(date=day))
                rows.append(EmptyDayRow(date=day))
                day += _ONE_DAY
    return rows


def _build_period_ladder(
    ordered: Sequence[_EventLike],
    range_start: date,
    range_end: date,
    level: ScaleUnit,
    hide_empty: bool,
) -> list[LadderRow]:
    """MONTH/YEAR level: header + one counter card per window period."""
    rows: list[LadderRow] = []
    cursor = _unit_start(range_start, level)
    while True:
        try:
            next_first: date | None = _next_unit_start(cursor, level)
        except ValueError:  # 9999-12 overflow: this period reaches the edge
            next_first = None
        period_last = (next_first - _ONE_DAY) if next_first is not None else CALENDAR_MAX
        # The card/header anchor is the period's own first day (a drill-in
        # derives «окно = период» straight off it); the count only sees the
        # part of the period that lies inside the visible range.
        first = max(cursor, range_start)
        last = min(period_last, range_end)
        count = len({
            event.id for event in ordered
            if event.start_date <= last
            and (event.end_date is None or event.end_date >= first)
        })
        if not (hide_empty and count == 0):  # a hidden «нет событий» loses its
            rows.append(PeriodHeaderRow(date=cursor, level=level))  # header too
            rows.append(PeriodCardRow(date=cursor, level=level, count=count))
        if next_first is None or next_first > range_end:
            break  # the period just emitted ended the range
        cursor = next_first
    return rows


def zoom_level(level: ScaleUnit, delta: int) -> ScaleUnit:
    """Rung after ``delta`` zoom steps (design D6): + zooms in toward DAY.

    ``delta`` counts rungs (the view passes its wheel notches normalized to
    ±1 per event); coarser lives higher in the ladder (DAY→MONTH→YEAR), so a
    negative delta steps out and a positive one in, the ladder clamping at
    both ends and ``0`` being the identity.
    """
    ladder = (ScaleUnit.DAY, ScaleUnit.MONTH, ScaleUnit.YEAR)
    index = min(max(ladder.index(level) - delta, 0), len(ladder) - 1)
    return ladder[index]


def zoom_target(level: ScaleUnit, anchor_row: LadderRow | None) -> date | None:
    """The period the wheel zoom anchors on, from the row under the cursor.

    Zoom-out keeps the anchor's unit on top: a daily row (header/card/empty
    day) anchors on its MONTH, a monthly period row on its YEAR; the YEAR
    rung has nothing coarser and anchors on its own period. A collapsed gap
    or no row under the cursor gives ``None`` — the view then zooms without
    an anchor (spec pins anchors only for cards and headers).
    """
    if anchor_row is None or isinstance(anchor_row, GapCollapsedRow):
        return None
    day = anchor_row.date
    if level is ScaleUnit.DAY:
        return _unit_start(day, ScaleUnit.MONTH)
    if level is ScaleUnit.MONTH:
        return _unit_start(day, ScaleUnit.YEAR)
    return day


def period_span(row: LadderRow | None) -> tuple[date, date] | None:
    """The whole calendar period ``row`` stands on, ``None`` for non-period rows.

    The row's ``date`` is already its period's first day, so the span runs
    from it to the day before the next unit (the 9999-12/9999 edge clamps to
    :data:`CALENDAR_MAX`). Both writers of «окно = период» read this: the drill
    click and the inward Alt/Opt wheel (spec «Приближение от карточки события»:
    «ступень — сутки, окно — август»). A period HEADER anchors like its card
    (spec «Лестница ступеней просмотра»: «над sticky/секционным заголовком —
    в период этого заголовка»); day-level rows own no period span.
    """
    if not isinstance(row, (PeriodHeaderRow, PeriodCardRow)):
        return None
    try:
        period_end = _next_unit_start(row.date, row.level) - _ONE_DAY
    except ValueError:  # the period reaches the calendar's upper edge
        period_end = CALENDAR_MAX
    return (row.date, clamp_calendar(period_end))


def drill_target(period_row: PeriodCardRow) -> tuple[ScaleUnit, tuple[date, date]]:
    """What a drill click on ``period_row`` installs (design D6, task 4.2).

    The pair is ``(deeper_level, window)``: the level one rung finer than the
    card's own (year → month, month → day) and the window equal to the card's
    whole period (spec «Проваливание выставляет окно»). A drill never selects,
    it only re-models: the view applies the pair through its knobs and the
    ViewModel mirrors it.
    """
    deeper = zoom_level(period_row.level, 1)
    window = period_span(period_row)
    assert window is not None  # a PeriodCardRow always owns a span
    return deeper, window


def drop_actions(
    event: _EventLike, target_day: date
) -> dict[DropAction, bool]:
    """Which release-menu items ``event`` earns at ``target_day`` (D5).

    * «Перенести» — always;
    * «Расширить вниз» — closed events only, and only below the current end
      (an open end reaches the bottom already — nothing to extend);
    * «Начать раньше» — any event, only above the current start.
    A target inside the span therefore yields MOVE only; a same-day re-drop
    yields MOVE only as well (the view skips the menu against the source day).
    The target is calendar-clamped before it is compared.
    """
    target = clamp_calendar(target_day)
    return {
        DropAction.MOVE: True,
        DropAction.EXTEND_DOWN: event.end_date is not None and target > event.end_date,
        DropAction.START_EARLIER: target < event.start_date,
    }


def apply_drop_action(
    event: _EventLike, action: DropAction | str, target_day: date
) -> tuple[date, date | None]:
    """The new ``(start, end)`` of applying ``action`` at ``target_day``.

    Every result is clamped to the app calendar and never inverts:
    * MOVE — ``start :=`` target, the duration rides along (an event open at
      one end stays open), a shift against the edge clips the far bound;
    * EXTEND_DOWN — closed events only (an open end raises ``ValueError``,
      mirroring :func:`drop_actions`), ``end :=`` the target, held ≥ start,
      ``start`` untouched;
    * START_EARLIER — ``start :=`` the target, held ≤ the old start (open
      ends stay open), ``end`` untouched.
    """
    action = DropAction(action)
    target = clamp_calendar(target_day)
    start, end = event.start_date, event.end_date
    if action is DropAction.MOVE:
        if end is None:
            return target, None
        new_start, new_end = translate_span(start, end, (target - start).days)
        return clamp_calendar(new_start), clamp_calendar(new_end)
    if action is DropAction.EXTEND_DOWN:
        if end is None:
            raise ValueError("an open-ended event has no end to extend down to")
        return start, max(target, start)
    return min(target, start), end
