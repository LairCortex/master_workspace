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
normalization).
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.game_calendar import GameCoord

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


def era_key(coord: GameCoord | date, is_bc: bool = False) -> int:
    """Chronological key of a (coordinate, era) pair through the active calendar.

    The dispatcher takes a ``GameCoord`` (design D4) and still accepts a
    plain ``datetime.date``, coerced to the ``MonthDay`` carrying the same
    numbers, so every pre-C3a call keeps its bit-identical result.  A
    coordinate absent from the active calendar (e.g. an intercalary day
    under the standard preset) is refused by the calendar's own
    ``InvalidGameDateError`` — no silent normalization.
    """
    # Lazy import breaks the load-order cycle: game_calendar imports this
    # module at module level, so importing it back here is the one edge that
    # must stay inside the function (documented in design D2).
    from app.domain.game_calendar import MonthDay, current_calendar

    if isinstance(coord, date):
        coord = MonthDay(coord.year, coord.month, coord.day)
    return current_calendar().to_key(coord, is_bc)


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
