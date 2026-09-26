"""Era-aware date helpers — the single chronological key for (coordinate, is_bc) pairs.

Each game date is a pair (a game calendar ``GameCoord`` — or, since piece
C3a, a plain ``datetime.date``, which is the month-day coordinate carrying
the same numbers — together with ``is_bc``). All comparisons,
sorts and interval filters SHALL go through this module (design D2):
``era_key(coord, is_bc)`` is the single public ordering, and with the default
«Стандартный» calendar it equals ``d.toordinal()`` for our era and
``d.toordinal() - 732 * d.year`` for BC, so every BC date precedes every CE
date, BC years count down toward 1 г. до н.э. while months and days inside a
BC year run forward. Both eras span years 1…9999; a year zero exists in
neither era, and BC months / leap years mirror our calendar with the same
year number.

Since piece C1 ``era_key`` is a thin dispatcher on the active game calendar
(design D1); the Gregorian formula itself lives in the private
``_gregorian_key``, which the standard preset calls back directly (D2) so the
dispatcher and its default calendar never recurse into each other.  Since
C3a (design D4) the dispatcher takes the game coordinate itself and a plain
``date`` is coerced to the equal ``MonthDay`` — every pre-existing call keeps
its bit-identical numbers, and a coordinate the active calendar does not
contain is refused by that calendar's own ``InvalidGameDateError`` (no silent
normalization).  Since NRI-0021 (design Д3) the module also owns the pure
duration family — ``duration_parts``/``entity_age_duration``: ordering and
era crossing come from ``era_key``, day counting from the calendar's
contiguous ``day_index``; the calendar accessors they build coordinates with
arrive through the same explicit hand-off as the era-key resolver.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.game_calendar import GameCalendar, GameCoord

MIN_YEAR = 1
MAX_YEAR = 9999

#: Design D2 per-year step of BC keys (2×366): dominates the maximal backward
#: ordinal jump at the year border (365 + 366), so BC keys strictly grow along
#: the real BC chronology (older = smaller) and stay below all CE keys (< 0).
BC_YEAR_STEP = 732


def _gregorian_key(d: date, is_bc: bool = False) -> int:
    """The live Gregorian key formula (design D2) behind the standard preset.

    Private: it is the formula itself, while ``era_key`` is the public
    dispatcher on the active calendar.  ``StandardCalendar`` calls this one
    instead of ``era_key`` so the dispatcher never re-enters itself (D2).
    """
    if is_bc:
        return d.toordinal() - BC_YEAR_STEP * d.year
    return d.toordinal()


#: Resolution strategy injected once by ``app.domain.game_calendar`` at its
#: module import: maps a (coordinate, is_bc) pair through the ACTIVE game
#: calendar.  ``game_calendar`` imports this module top-level, so the former
#: lazy ``date_era ↔ game_calendar`` cycle is gone — the dependency is now
#: passed explicitly instead of imported back inside ``era_key`` (wave-6,
#: task 6.7; audit finding «скрытая связанность» in docs/refactoring-audit.md).
_ERA_KEY_RESOLVER: Callable[[GameCoord | date, bool], int] | None = None


def bind_era_key_resolver(resolver: Callable[[GameCoord | date, bool], int]) -> None:
    """Install the calendar dispatch used by :func:`era_key`.

    Called by ``app.domain.game_calendar`` when it loads; importing the
    calendar module is the one requirement of using the dispatcher."""
    global _ERA_KEY_RESOLVER
    _ERA_KEY_RESOLVER = resolver


def era_key(coord: GameCoord | date, is_bc: bool = False) -> int:
    """Chronological key of a (coordinate, era) pair through the active calendar.

    The dispatcher takes a ``GameCoord`` (design D4) and still accepts a
    plain ``datetime.date``, coerced to the ``MonthDay`` carrying the same
    numbers, so every pre-C3a call keeps its bit-identical result.  A
    coordinate absent from the active calendar (e.g. an intercalary day
    under the standard preset) is refused by the calendar's own
    ``InvalidGameDateError`` — no silent normalization.  The coercion and
    dispatch themselves live in ``game_calendar`` and arrive through
    :func:`bind_era_key_resolver` (task 6.7), so this module keeps no import
    edge of its own into the calendar.
    """
    if _ERA_KEY_RESOLVER is None:
        raise RuntimeError(
            "the era-key calendar resolver is not bound — import "
            "app.domain.game_calendar before using era_key"
        )
    return _ERA_KEY_RESOLVER(coord, is_bc)


def cmp_era_dates(
    left: tuple[GameCoord | date, bool], right: tuple[GameCoord | date, bool]
) -> int:
    """Compare two (coordinate, is_bc) pairs chronologically, returning -1 / 0 / 1."""
    left_key = era_key(*left)
    right_key = era_key(*right)
    return (left_key > right_key) - (left_key < right_key)


def assert_range(coord: GameCoord | date, is_bc: bool = False) -> None:
    """Raise ValueError if the coordinate's year is outside 1…9999 of the given era."""
    if not MIN_YEAR <= coord.year <= MAX_YEAR:
        era = "до н.э." if is_bc else "н.э."
        raise ValueError(
            f"year {coord.year} is out of range {MIN_YEAR}…{MAX_YEAR} ({era})"
        )


# ── Durations between two era coordinates (NRI-0021, design Д3) ──────────

@dataclass(frozen=True)
class DurationParts:
    """Calendar duration split greedily into years, months and days.

    The numbers are absolute (never negative); the direction lives in
    ``ahead`` — ``True`` when the pair was given end-first, i.e. the first
    coordinate lies strictly after the second one (a date that has not
    happened yet as seen from the second).  Zero duration is directionless:
    ``ahead`` is ``False`` whenever all three counts are zero."""

    years: int
    months: int
    days: int
    ahead: bool = False


#: Duration machinery as date_era sees it (NRI-0021 task 1.2): the live
#: calendar reader and the two coordinate classes the step helpers build —
#: the same explicit one-way hand-off as ``bind_era_key_resolver`` (task 6.7),
#: so this module keeps no import edge into ``game_calendar``.
_CALENDAR_PROVIDER: Callable[[], GameCalendar] | None = None
_MONTH_DAY: type | None = None
_INTERCALARY_DAY: type | None = None


def bind_duration_helpers(
    *,
    calendar_provider: Callable[[], GameCalendar],
    month_day: type,
    intercalary_day: type,
) -> None:
    """Install the calendar accessors :func:`duration_parts` builds with.

    Called by ``app.domain.game_calendar`` when it loads (next to
    :func:`bind_era_key_resolver`); importing that module is the one
    requirement of using the duration functions."""
    global _CALENDAR_PROVIDER, _MONTH_DAY, _INTERCALARY_DAY
    _CALENDAR_PROVIDER = calendar_provider
    _MONTH_DAY = month_day
    _INTERCALARY_DAY = intercalary_day


def _duration_calendar() -> GameCalendar:
    """The active calendar, refusing loudly when the helpers are not bound —
    the same posture as the unbound ``era_key`` resolver."""
    if _CALENDAR_PROVIDER is None or _MONTH_DAY is None or _INTERCALARY_DAY is None:
        raise RuntimeError(
            "the duration calendar helpers are not bound — import "
            "app.domain.game_calendar before using duration_parts"
        )
    return _CALENDAR_PROVIDER()


def _as_coord(value: GameCoord | date):
    """Coerce a plain ``date`` to the equal MonthDay for the step helpers
    (``era_key`` has already accepted and keyed it at this point); an already
    game coordinate passes through untouched."""
    if isinstance(value, (_MONTH_DAY, _INTERCALARY_DAY)):
        return value
    return _MONTH_DAY(value.year, value.month, value.day)


def _last_month(calendar: GameCalendar) -> int:
    """Highest 1-based month number the active calendar names."""
    return max(calendar.month_names)


def _future_year(year: int, is_bc: bool) -> tuple[int, bool] | None:
    """The same calendar position one year later, era included.

    BC years count down toward the era border and year 1 до н.э. steps
    straight into year 1 н.э. — a year zero exists in neither era; the last
    AD year has no successor within the 1…9999 scale (``None``)."""
    if is_bc:
        if year > MIN_YEAR:
            return year - 1, True
        return MIN_YEAR, False
    if year < MAX_YEAR:
        return year + 1, False
    return None


def _advance_year(calendar: GameCalendar, coord, is_bc: bool):
    """The coordinate's anniversary one calendar year toward the future:
    month day clamped to the target year's month length (a February 29
    anniversary lands on the last February day of a common year), an
    intercalary slot keeps its rule index — slots exist in every year.
    ``None`` when no future year exists (end of the AD scale)."""
    stepped = _future_year(coord.year, is_bc)
    if stepped is None:
        return None
    year, era = stepped
    if isinstance(coord, _INTERCALARY_DAY):
        return _INTERCALARY_DAY(year, coord.index), era
    return (
        _MONTH_DAY(year, coord.month, min(coord.day, calendar.month_length(year, coord.month))),
        era,
    )


def _intercalary_host(calendar: GameCalendar, coord) -> int:
    """Host month of an intercalary slot, read through the protocol only:
    the slot sits between its host's last day and the next month's first
    day, so the host is the last month whose first day is not after the
    slot (the in-year layout is era-independent, hence the AD-era counter)."""
    index = calendar.day_index(coord)
    host = 1
    for month in range(2, _last_month(calendar) + 1):
        if calendar.day_index(_MONTH_DAY(coord.year, month, 1)) > index:
            break
        host = month
    return host


def _advance_month(calendar: GameCalendar, coord, is_bc: bool):
    """The same day of the next month toward the future, day clamped to the
    target month's length; stepping past the last month crosses into the next
    year (BC year 1 crosses into н.э., MAX_YEAR of н.э. has no successor).
    An intercalary day first steps onto the first day of the month after its
    host — its own one-day slot keeps the day remainder of the greedy
    decomposition honest (design Д3).  ``None`` past the end of the scale."""
    if isinstance(coord, _INTERCALARY_DAY):
        month, day = _intercalary_host(calendar, coord), 1
    else:
        month, day = coord.month, coord.day
    year = coord.year
    if month < _last_month(calendar):
        month += 1
    else:
        stepped = _future_year(year, is_bc)
        if stepped is None:
            return None
        year, is_bc = stepped
        month = 1
    return _MONTH_DAY(year, month, min(day, calendar.month_length(year, month))), is_bc


def duration_parts(
    a: GameCoord | date, bc_a: bool, b: GameCoord | date, bc_b: bool
) -> DurationParts:
    """Greedy years/months/days between two era coordinates (design Д3).

    Order and the «до н.э. → н.э.» crossing come from ``era_key`` — there is
    no year zero there — while the counting runs on the calendar's contiguous
    ``day_index``.  The decomposition walks actual calendar positions: whole
    anniversary years first (each spanning its actual year's day count, so
    leap and intercalary years are exact), then same-day month steps from the
    starting month, the remainder in days.  A day that does not exist in a
    target month (February 29 anniversaries) counts on that month's last day.
    ``DurationParts.ahead`` is ``True`` exactly when ``a`` lies strictly
    after ``b``; equal coordinates give the zero parts with ``ahead=False``,
    and swapping the arguments keeps the parts and flips the direction."""
    calendar = _duration_calendar()
    key_a = era_key(a, bc_a)
    key_b = era_key(b, bc_b)
    if key_a == key_b:
        return DurationParts(0, 0, 0)
    ahead = key_a > key_b
    if ahead:
        a, b = b, a
        bc_a, bc_b = bc_b, bc_a
    a = _as_coord(a)
    b = _as_coord(b)
    end_index = calendar.day_index(b, bc_b)
    years = 0
    pos, pos_bc = a, bc_a
    while True:
        stepped = _advance_year(calendar, pos, pos_bc)
        if stepped is None or calendar.day_index(*stepped) > end_index:
            break
        years += 1
        pos, pos_bc = stepped
    months = 0
    while True:
        stepped = _advance_month(calendar, pos, pos_bc)
        if stepped is None or calendar.day_index(*stepped) > end_index:
            break
        months += 1
        pos, pos_bc = stepped
    days = end_index - calendar.day_index(pos, pos_bc)
    return DurationParts(years, months, days, ahead)


def entity_age_duration(
    start: GameCoord | date,
    start_bc: bool,
    end: GameCoord | date | None,
    end_bc: bool,
    now: GameCoord | date,
    now_bc: bool,
) -> DurationParts:
    """The single entity-age rule (NRI-0021 task 1.4, design Д5).

    Start later than «now» → the span «now»→start, marked ``ahead`` (read as
    «через N»); an end set strictly before «now» → the span start→end (an
    entity that has ended ages to its close, not past it); everything else →
    the span start→now.  The parts are absolute and direction-free in the two
    counting-to branches; both the detail-panel summary and the entity card
    read this one rule, word assembly is ``format_age_words`` (presentation).
    """
    start_key = era_key(start, start_bc)
    now_key = era_key(now, now_bc)
    if start_key > now_key:
        # ``duration_parts`` walks start→now backward and flags the direction,
        # which is exactly the «через N» reading the surfaces present.
        return duration_parts(start, start_bc, now, now_bc)
    if end is not None and era_key(end, end_bc) < now_key:
        parts = duration_parts(start, start_bc, end, end_bc)
        return DurationParts(parts.years, parts.months, parts.days)
    return duration_parts(start, start_bc, now, now_bc)
