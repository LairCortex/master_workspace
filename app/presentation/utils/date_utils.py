"""Date formatting utilities reading the active game calendar.

Since piece C2 (design D7) the month names are an integral part of the
active :class:`~app.domain.game_calendar.GameCalendar` — the old process
global (``_current_months``), its ``set/get_custom_months`` accessors and
the ``custom_months`` serialization helpers are gone.  Formatting helpers
here are thin delegates to ``current_calendar().month_names``; who sets and
resets the active calendar is the application lifecycle's concern.
"""
from __future__ import annotations

from datetime import date

from app.domain.game_calendar import DEFAULT_MONTH_NAMES, current_calendar

#: Re-export of the domain's Gregorian month names (piece C2, design D7) —
#: the single source lives in ``app.domain.game_calendar``; this alias keeps
#: existing display-side imports on one name (read-only mapping).
DEFAULT_MONTHS = DEFAULT_MONTH_NAMES


def month_name(month: int) -> str:
    """Return the display name for a month number in the active calendar.

    A month the calendar does not name falls back to its number as text —
    the same defensive caption the old global map gave.
    """
    return current_calendar().month_names.get(month, str(month))


def format_game_date(
    d: date | None, fallback: str = "?", is_bc: bool | None = False
) -> str:
    """Format a date using the active calendar's month names: 'dd MonthName yyyy'.

    A date of the BC era (add-era-aware-dates, design D6) prints its year as
    'dd MonthName yyyy г. до н.э.'; our-era dates keep the previous format.
    An empty era (``None``) reads as «н.э.» — the open-end mark ``fallback``
    never carries an era either way.
    """
    if d is None:
        return fallback
    era = " г. до н.э." if is_bc else ""
    return f"{d.day:02d} {month_name(d.month)} {d.year}{era}"


def split_date_era(value: date | tuple[date, bool] | None) -> tuple[date | None, bool | None]:
    """Coerce a date-or-(date, era) value into a ``(date | None, era)`` pair.

    The bridges between popups and dialogs pass (date, is_bc) tuples, while a
    bare ``date`` stays a legal legacy input: it comes back with era ``None``
    («era not stated — keep whatever the receiver holds»). ``None`` is
    «no date» and reads as our era.
    """
    if value is None:
        return None, False
    if isinstance(value, tuple) and len(value) == 2:
        return value[0], bool(value[1])
    return value, None


def era_flag(value: object) -> bool:
    """Read an era flag stored on a row/dataclass (int 0/1 or bool).

    Anything that is not an int/bool (e.g. an attribute-less stand-in) is
    «н.э.» — the same default as the ``DEFAULT 0`` column of design D3.
    """
    return bool(value) if isinstance(value, (bool, int)) else False
