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
remains anywhere downstream of a stored coordinate.  Since NRI-0021 (design
Д3) the module also owns the word form of durations — ``format_duration_words``
(«3 года 2 мес.», «12 дней», «сегодня», prefix «через ») with the Russian
counting table, and ``format_age_words`` assembling the single domain age
rule (``entity_age_duration``) into those words.
"""
from __future__ import annotations

from datetime import date

from app.domain.date_era import DurationParts, entity_age_duration
from app.domain.game_calendar import (
    DEFAULT_MONTH_NAMES,
    MAX_YEAR,
    GameCoord,
    IntercalaryDay,
    MonthDay,
    as_game_coord,
    current_calendar,
)
from app.domain.time_of_day import TimeOfDay
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


def format_event_start(
    coord: GameCoord | date | None,
    is_bc: bool,
    start_time: TimeOfDay | None,
) -> str:
    """The one caption of an event's start moment (NRI-0023 task 8.1, design
    Д9 — spec event-time «Время на поверхностях события»).

    Every surface that prints an event's start date (the ladder row, the
    event card, the entity preview, the search result, the world snapshot)
    calls THIS helper: with a chosen time the caption gains the ', HH:MM'
    tail (both parts zero-padded to two digits, straight after the date, a
    comma between); with ``start_time`` None the print is bit-for-bit the
    plain :func:`format_game_date` caption — the empty time means «весь день,
    с утра» and never invents a «00:00» (spec «Пустое время ничего не
    меняет», the task's pin).
    """
    caption = format_game_date(coord, is_bc=is_bc)
    if start_time is None:
        return caption
    return f"{caption}, {start_time.format_hhmm()}"


def event_start_time(event: object) -> TimeOfDay | None:
    """The event's optional wall-clock start, duck-typed like every other
    display reader (NRI-0023 task 8.1): the surfaces receive ORM rows and
    domain doubles alike, so only an actual :class:`TimeOfDay` counts —
    absent/foreign attributes (the auto-Mock of a test double, say) read as
    «без времени», exactly what :func:`format_event_start` then prints as
    the untouched date caption."""
    start_time = getattr(event, "start_time", None)
    return start_time if isinstance(start_time, TimeOfDay) else None


def worst_case_date_caption() -> str:
    """The widest date caption the active calendar can print (NRI-0017
    task 1.1, design F1 — ThemeDateField's width floor, spec qml-components
    «Поле даты — именованную нажимаемую кнопку предсказуемой ширины»).

    Every coordinate kind contributes its own widest print
    (``format_game_date`` contracts): a regular month pairs its own name
    with ``:02d``-padded field of its own length, an intercalary rule
    prints its name and a year, and every caption is taken in the BC era —
    the « г. до н.э.» tail is the widest tail there is, and the year sits at
    the shared ``MAX_YEAR`` bound. The result is a width HINT measured by
    the component's TextMetrics, never a displayed text, so character
    length is the comparison; hosts pass it into ``worstCaseText`` so the
    field's minimum width always contains the worst form and the display
    elide stays the secondary fallback (M2: the year is no longer cut).
    """
    calendar = current_calendar()
    widest_year = str(MAX_YEAR)
    era = " г. до н.э."
    captions = [
        f"{calendar.month_length(MAX_YEAR, month):02d} {name} {widest_year}{era}"
        for month, name in calendar.month_names.items()
    ]
    spec = getattr(calendar, "spec", None)
    if spec is not None:
        captions += [f"{rule.name} {widest_year}{era}" for rule in spec.intercalary]
    return max(captions, key=len)


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


# ── Word form of a duration (NRI-0021 tasks 1.3/1.4, design Д3) ──────────

#: Russian cardinal forms per unit, table helper of design Д3:
#: ``(one, few, many)`` — 1 год / 2 года / 5 лет, 1 день / 2 дня / 5 дней.
#: The month unit prints the fixed abbreviation «мес.» (the spec scenarios
#: pin «2 года 3 мес.» and «через 3 мес.», so it never declines).
_YEAR_FORMS = ("год", "года", "лет")
_DAY_FORMS = ("день", "дня", "дней")
_MONTH_UNIT = "мес."


def _plural_ru(count: int, forms: tuple[str, str, str]) -> str:
    """One of ``(one, few, many)`` chosen by the Russian counting rule:
    teens (11…14) and a last digit 0 or 5…9 take ``many``, a last digit 1
    takes ``one``, 2…4 take ``few``."""
    teens = count % 100
    last = teens % 10
    if 11 <= teens <= 19 or last == 0 or last >= 5:
        return forms[2]
    if last == 1:
        return forms[0]
    return forms[1]


def format_duration_words(parts: DurationParts, ahead: bool | None = None) -> str:
    """The one word formula for a duration (spec «Словесная формула
    длительности»).

    Whole years and months («3 года 2 мес.», whole years carry no zero
    months remainder), less than a year — whole months («3 мес.»), less
    than a month — whole days («12 дней»), zero — «сегодня».  A date ahead
    of the reference point reads with the «через » prefix; the direction
    arrives as the explicit ``ahead`` argument or, by default, through
    ``parts.ahead`` carried from ``duration_parts`` (sign stays outside the
    numbers until this wording step, design Д3)."""
    if ahead is None:
        ahead = parts.ahead
    if parts.years:
        words = f"{parts.years} {_plural_ru(parts.years, _YEAR_FORMS)}"
        if parts.months:
            words += f" {parts.months} {_MONTH_UNIT}"
    elif parts.months:
        words = f"{parts.months} {_MONTH_UNIT}"
    elif parts.days:
        words = f"{parts.days} {_plural_ru(parts.days, _DAY_FORMS)}"
    else:
        return "сегодня"
    return f"через {words}" if ahead else words


def format_age_words(
    start: GameCoord | date,
    start_bc: bool,
    end: GameCoord | date | None,
    end_bc: bool,
    now: GameCoord | date,
    now_bc: bool,
) -> str:
    """Entity age as words — the single implementation of the age rule for
    the detail-panel summary and the entity card (NRI-0021 task 1.4,
    design Д5).

    Counts to «now»; when the entity has an end strictly earlier than
    «now», counts to the end; a start later than «now» reads forward
    («через N»).  The rule itself lives in ``entity_age_duration`` (domain,
    no text), this helper only assembles the standard duration words.
    """
    parts = entity_age_duration(start, start_bc, end, end_bc, now, now_bc)
    return format_duration_words(parts)


#: Entity types carrying the age line (NRI-0021 group 4, spec «Возраст
#: персонажа и предмета»): character and item; locations and organizations
#: stay age-free in every display (spec «Локации и организации SHALL
#: оставаться без строки возраста»).  The detail summary and the entity card
#: read this one tuple — the type selection lives in a single place (Д5).
AGE_ENTITY_TYPES = ("character", "item")

#: The «Возраст» label both age surfaces print (spec «Read-only отображение
#: производных величин» pins the visible «Возраст: <формула>» for the summary
#: and the card alike; only the markup differs — HTML caption vs plain text).
AGE_LABEL = "Возраст"
