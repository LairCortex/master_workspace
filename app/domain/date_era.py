"""Era-aware date helpers — the single chronological key for (date, is_bc) pairs.

Each game date is a pair (``datetime.date``, ``is_bc``). All comparisons,
sorts and interval filters SHALL go through this module (design D2):
``era_key(d, is_bc) = d.toordinal()`` for our era and
``d.toordinal() - 732 * d.year`` for BC, so every BC date precedes every CE
date, BC years count down toward 1 г. до н.э. while months and days inside a
BC year run forward. Both eras span years 1…9999; a year zero exists in
neither era, and BC months / leap years mirror our calendar with the same
year number.
"""
from __future__ import annotations

from datetime import date

MIN_YEAR = 1
MAX_YEAR = 9999

#: Design D2 per-year step of BC keys (2×366): dominates the maximal backward
#: ordinal jump at the year border (365 + 366), so BC keys strictly grow along
#: the real BC chronology (older = smaller) and stay below all CE keys (< 0).
BC_YEAR_STEP = 732


def era_key(d: date, is_bc: bool = False) -> int:
    """Chronological key of a (date, era) pair (design D2)."""
    if is_bc:
        return d.toordinal() - BC_YEAR_STEP * d.year
    return d.toordinal()


def cmp_era_dates(left: tuple[date, bool], right: tuple[date, bool]) -> int:
    """Compare two (date, is_bc) pairs chronologically, returning -1 / 0 / 1."""
    left_key = era_key(*left)
    right_key = era_key(*right)
    return (left_key > right_key) - (left_key < right_key)


def assert_range(d: date, is_bc: bool = False) -> None:
    """Raise ValueError if the date's year is outside 1…9999 of the given era."""
    if not MIN_YEAR <= d.year <= MAX_YEAR:
        era = "до н.э." if is_bc else "н.э."
        raise ValueError(
            f"year {d.year} is out of range {MIN_YEAR}…{MAX_YEAR} ({era})"
        )
