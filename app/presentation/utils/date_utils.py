"""Date formatting utilities reading the active game calendar.

Since piece C2 (design D7) the month names are an integral part of the
active :class:`~app.domain.game_calendar.GameCalendar` — the old process
global (``_current_months``), its ``set/get_custom_months`` accessors and
the ``custom_months`` serialization helpers are gone.  Formatting helpers
here are thin delegates to ``current_calendar().month_names``; who sets and
resets the active calendar is the application lifecycle's concern.
Since piece C3a (designs D4/D5) every date carrier below speaks game
calendar coordinates: a plain ``datetime.date`` is still accepted on input
(the ``MonthDay`` of the same numbers), a regular coordinate keeps the
previous 'dd MonthName yyyy[ г. до н.э.]' caption bit-for-bit, and an
intercalary coordinate is captioned by its rule name and year with no day
number (spec «Отображение эры», scenario «Вставной день в строке»).
Since piece C3b (design D3) the picture-only popup pre-fill clamp and its
intercalary display helper are gone as well: the game-calendar grid paints
every valid coordinate itself, so no display-side number substitution
remains anywhere downstream of a stored coordinate.
"""
from __future__ import annotations

from datetime import date

from app.domain.game_calendar import (
    DEFAULT_MONTH_NAMES,
    GameCoord,
    IntercalaryDay,
    MonthDay,
    as_game_coord,
    current_calendar,
)
from app.infrastructure.calendar_storage import (
    encode_coord,
)

#: Re-export of the domain's Gregorian month names (piece C2, design D7) —
#: the single source lives in ``app.domain.game_calendar``; this alias keeps
#: existing display-side imports on one name (read-only mapping).
DEFAULT_MONTHS = DEFAULT_MONTH_NAMES

#: Russian weekday names of the «Стандартный» preset week, Monday first
#: (piece C3b, design D2) — a PRESENTATION-side preset constant: the domain
#: never localizes (piece C0 principle), and the preset calendar exposes no
#: week-name view, so the grid subscribes these names to its columns
#: (column 0 = ``Понедельник``, fixing the Monday-first order grill chose over
#: the old locale-dependent Qt calendar widget header).  A custom calendar
#: never reads this constant: its columns come from ``spec.week_names``.
STANDARD_WEEK_NAMES: tuple[str, ...] = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
)


def month_name(month: int) -> str:
    """Return the display name for a month number in the active calendar.

    A month the calendar does not name falls back to its number as text —
    the same defensive caption the old global map gave.
    """
    return current_calendar().month_names.get(month, str(month))


def _intercalary_caption(coord: IntercalaryDay) -> str:
    """Display name of an intercalary coordinate in the active calendar.

    The rule name is reached through the same structural ``spec`` view the
    year preview (``render_calendar_year``) reads — the ``GameCalendar``
    protocol stays untouched (piece C0, design D2).  A calendar exposing no
    spec view, or a rule index its spec has moved past (a rule edited away in
    the stored settings before the start-shift pass), captions as the bare
    index — the same defensive caption ``month_name`` gives an unnamed month.
    """
    spec = getattr(current_calendar(), "spec", None)
    if spec is None:
        return str(coord.index)
    rules = tuple(spec.intercalary)
    if not 0 <= coord.index < len(rules):
        return str(coord.index)
    return rules[coord.index].name


def format_game_date(
    d: GameCoord | date | None,
    fallback: str = "?",
    is_bc: bool | None = False,
) -> str:
    """Format a date coordinate using the active calendar's month names.

    A regular day (a ``MonthDay`` or a plain ``date``, piece C3a design D4)
    keeps the previous 'dd MonthName yyyy' caption bit-for-bit (spec
    «Отображение эры»). An intercalary coordinate (design D5) prints its rule
    name and year with no day number — 'DayName yyyy'. Either kind of the BC
    era (add-era-aware-dates, design D6) appends ' г. до н.э.' to the year;
    our-era dates carry no suffix. An empty era (``None``) reads as «н.э.» —
    the open-end mark ``fallback`` never carries an era either way.
    """
    if d is None:
        return fallback
    era = " г. до н.э." if is_bc else ""
    if isinstance(d, IntercalaryDay):
        return f"{_intercalary_caption(d)} {d.year}{era}"
    return f"{d.day:02d} {month_name(d.month)} {d.year}{era}"


def iso_or_coord(coord: GameCoord | date) -> str:
    """The QML ``*Iso`` string for a coordinate (piece C3a, design D5).

    ISO (the previous ``date.isoformat()`` string, bit-for-bit) whenever the
    coordinate is representable as a real Gregorian date; anything else —
    an intercalary day, a day a real month does not have, a year outside the
    ``date`` range — rides the domain codec text ``encode_coord`` instead.
    The contract holds because no observer parses these strings: QML reads
    ``*Iso`` verbatim and never writes it back (the spike's flow map), while
    a display-side reader tells the kinds apart through ``*Display``.
    """
    coord = as_game_coord(coord)
    if isinstance(coord, MonthDay):
        try:
            return date(coord.year, coord.month, coord.day).isoformat()
        except ValueError:
            pass
    return encode_coord(coord)


def split_date_era(
    value: GameCoord | date | tuple[GameCoord | date | None, bool] | None,
) -> tuple[GameCoord | date | None, bool | None]:
    """Coerce a coordinate-or-(coordinate, era) value into a pair.

    Since piece C3a the bridges carry game coordinates (design D5 — the
    generalized splitter the design notes as ``split_coord_era``, kept under
    this established name), but the body is content-agnostic: a (coord,
    is_bc) tuple splits as it always did, while a bare ``date`` or ``None``
    stays a legal legacy input — a bare coordinate comes back with era
    ``None`` («era not stated — keep whatever the receiver holds»), ``None``
    is «no date» and reads as our era.
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
