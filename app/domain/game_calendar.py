"""Chronological core of a configurable game calendar (roadmap piece C0).

The module maps a world date coordinate — ``MonthDay`` (year + month + day)
or ``IntercalaryDay`` (year + intercalary slot) — to a monotonic integer
chronological key and back (design D4).  Both eras span years 1…9999, a year
zero exists in neither, and the BC scale is mirrored with a per-year step of
2L (twice the game-year length), so every BC key stays below every CE key —
the same scheme ``app.domain.date_era`` realizes for Gregorian dates.

Pure domain code.  Since piece C1 ``app.domain.date_era.era_key`` lazily
imports the active-calendar accessor from this module (design D1/D3), the
app-wide chronological key follows the active game calendar; the import stays
lazy because the ``GameCalendar`` protocol (design D2) is the only surface
future consumers may depend on, the standard preset delegates to the private
``_gregorian_key`` formula rather than to ``era_key`` (D2, no mutual
recursion) and the custom calendar is built from a fixed ``CalendarSpec`` of
month lengths, week names and intercalary days (D4/D6).  Also since C1 the
module owns the pure invalid-coordinate policy: ``classify``/``shift_invalid``
diagnose exactly three absence reasons and clamp such a coordinate to the
nearest valid one through the protocol, without any storage access (D4/D5).
Finally C1 adds the transfer-report form of design D5: a frozen
``ShiftReportEntry`` (table, row id, ``start``/``end`` field, old and new
coordinate each paired with its era, and a stable ``ShiftReason`` code)
gathered into a ``ShiftReport`` by the pure :func:`build_shift_report` over
caller-supplied coordinate checks — the domain never reads the database nor
names the six tables, and never carries localized captions or entity names.
Piece C2 (designs D1/D7) makes the calendar a stored setting: month display
names become an integral part of the calendar itself — the protocol's
``month_names`` member, the domain-owned ``DEFAULT_MONTH_NAMES`` the standard
preset defaults to, and the pure :func:`encode_calendar` /
:func:`decode_calendar` codec mapping calendars to the versioned
``{"v": 1, "kind": ...}`` JSON value the ``game_settings`` row keeps and back;
an unreadable stored value answers with machine-readable reasons
(``CalendarCorrupted``) instead of raising, and a third calendar implementer
has no storage shape until the C4 wizard gives it one.
Piece C3a (design D2) adds the coordinate storage codec:
:func:`encode_coord` / :func:`decode_coord` turn a single ``GameCoord`` into
the discriminated text ``M:year:month:day`` / ``I:year:index`` and back —
an injective, exactly reversible cycle whose unparseable texts answer with
machine-readable reasons (``CoordCorrupted``) rather than raising; whether
the coordinate exists in any calendar stays the shift policy's question,
never the codec's.
"""
from __future__ import annotations

import bisect
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from enum import Enum
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from app.domain.date_era import BC_YEAR_STEP, _gregorian_key

#: Both eras span years MIN_YEAR…MAX_YEAR (same bound as ``date_era``).
MIN_YEAR = 1
MAX_YEAR = 9999


class InvalidGameDateError(ValueError):
    """Coordinate does not exist in this calendar, so its key refuses.

    Design D6: there is no silent normalization (no clamp to the last valid
    day); callers of ``to_key``/``from_key`` get this distinguishable error
    instead.
    """


# ── Custom calendar spec (design D4) ─────────────────────────────────────

@dataclass(frozen=True)
class MonthSpec:
    """One month of a custom calendar: a name and a fixed length in days
    (``length ≥ 1`` is validated later by ``validate``, design D6)."""

    name: str
    length: int


@dataclass(frozen=True)
class IntercalarySpec:
    """One intercalary day: a name and the host month it follows.

    ``after_month`` is the 1-based month number of the host; several rules
    may share one host and then form consecutive slots in list order
    (spec "Вставной день вне недельного цикла").
    """

    name: str
    after_month: int


@dataclass(frozen=True)
class CalendarSpec:
    """Full immutable description of a custom calendar (design D4).

    The year length ``L`` is identical in every year; intercalary days sit
    after their host month and outside the week cycle.  Validation and the
    prefix tables are built by ``CustomCalendar``/``validate`` (D6/D7,
    task group 2+).
    """

    months: tuple[MonthSpec, ...]
    week_names: tuple[str, ...]
    intercalary: tuple[IntercalarySpec, ...] = ()


# ── Spec validation (design D6) ──────────────────────────────────────────

#: Largest key the SQLite INTEGER column can hold (signed 64-bit).
INT64_MAX = (1 << 63) - 1

#: Maximal year length ``L`` keeping every mirrored key inside int64.
#: Design D6 fixes the guard as ``9999·L·2 < 2⁶³`` expressed by the safe
#: closed form ``L ≤ (2⁶³−1)//19999`` (≈ 4.6·10¹⁴).
MAX_YEAR_LENGTH = INT64_MAX // (2 * MAX_YEAR + 1)


@dataclass(frozen=True)
class SpecProblem:
    """One reason a spec is rejected: a stable machine-readable ``code``
    (for the future wizard C4) and a human-readable ``message``.
    ``validate`` returns the *full* list — never just the first hit (D6)."""

    code: str
    message: str


def _name_problems(names: tuple[str, ...], kind: str) -> list[SpecProblem]:
    """Empty and repeated names inside one dimension (months, weekdays and
    intercalary days are checked strictly among themselves, never across)."""
    problems: list[SpecProblem] = []
    seen: set[str] = set()
    for name in names:
        if not name.strip():
            problems.append(SpecProblem(f"empty_{kind}_name", f"empty {kind} name"))
        elif name in seen:
            problems.append(
                SpecProblem(f"duplicate_{kind}_name", f"duplicate {kind} name {name!r}")
            )
        seen.add(name)
    return problems


def validate(spec: CalendarSpec) -> list[SpecProblem]:
    """Full list of reasons the spec is unusable; empty list means valid.

    Checks (design D6): at least one month; month name non-empty/unique and
    length ≥ 1; week length ≥ 2 and consistent with the names count; week and
    intercalary names non-empty/unique; every intercalary host month exists;
    and the int64 guard ``L ≤ MAX_YEAR_LENGTH``.  No product caps on sizes —
    only physical and logical reasons (spec «Гибкость без продуктовых
    границ»).  A year outside MIN_YEAR…MAX_YEAR is a coordinate error, not a
    spec problem.
    """
    problems: list[SpecProblem] = []
    months = tuple(spec.months)
    if not months:
        problems.append(SpecProblem("no_months", "the calendar has no months"))
    problems += _name_problems(tuple(month.name for month in months), "month")
    for month in months:
        if month.length < 1:
            problems.append(
                SpecProblem(
                    "month_length_below_min",
                    f"month {month.name!r} has length {month.length} < 1",
                )
            )

    week_names = tuple(spec.week_names)
    if len(week_names) < 2:
        problems.append(
            SpecProblem(
                "week_too_short", f"week length {len(week_names)} < 2 (needs at least 2)"
            )
        )
    # ``CalendarSpec`` derives W from the names themselves, so a declared
    # ``week_length`` can only come from surrounding storage shapes (C2 keeps
    # length and names apart); when present it must agree with the names.
    declared_week_length = getattr(spec, "week_length", None)
    if declared_week_length is not None and declared_week_length != len(week_names):
        problems.append(
            SpecProblem(
                "week_length_mismatch",
                f"declared week length {declared_week_length} ≠ "
                f"{len(week_names)} week names given",
            )
        )
    problems += _name_problems(week_names, "week")

    intercalary = tuple(spec.intercalary)
    problems += _name_problems(tuple(rule.name for rule in intercalary), "intercalary")
    for rule in intercalary:
        if not 1 <= rule.after_month <= len(months):
            problems.append(
                SpecProblem(
                    "intercalary_unknown_month",
                    f"intercalary day {rule.name!r} refers to month "
                    f"{rule.after_month}, the calendar has months 1…{len(months)}",
                )
            )

    year_length = sum((month.length for month in months), 0) + len(intercalary)
    if year_length > MAX_YEAR_LENGTH:
        problems.append(
            SpecProblem(
                "year_length_overflow",
                f"year length {year_length} exceeds the int64 bound of "
                f"{MAX_YEAR_LENGTH} days (keys would not fit a 64-bit integer)",
            )
        )
    return problems


# ── Date coordinates (design D3) ─────────────────────────────────────────

@dataclass(frozen=True)
class MonthDay:
    """A regular day: year, 1-based ``month`` (1…len(months)), 1-based
    ``day`` inside that month.  Era is not part of the coordinate — it is a
    ``to_key``/``from_key`` argument, mirroring ``era_key(d, is_bc)``."""

    year: int
    month: int
    day: int


@dataclass(frozen=True)
class IntercalaryDay:
    """An intercalary day: year plus ``index`` — the 0-based position in the
    ordered ``CalendarSpec.intercalary`` rule list.  Stability of positions
    under spec edits is a C1/C4 concern (design D3), not the core's."""

    year: int
    index: int


#: Either kind of world date coordinate (design D3).
GameCoord = MonthDay | IntercalaryDay


def as_game_coord(value: GameCoord | date | None) -> GameCoord | None:
    """Coerce a plain ``datetime.date`` into the equal ``MonthDay`` (piece
    C3a, design D4): the Gregorian date stays a special case of a world
    coordinate, so pre-C3a call sites keep their numbers.  ``None`` passes
    through (an absent date stays absent — coercion is syntax, not a
    default) and an already-game coordinate is returned untouched; anything
    else is not a date carrier and refuses with a ``TypeError`` — like
    ``encode_coord``, the helper never guesses a coordinate into existence.
    Existence in any calendar is NOT checked here: that is the shift policy
    (and the entity validation's ``era_key``) question, never this one.
    """
    if value is None or isinstance(value, (MonthDay, IntercalaryDay)):
        return value
    if isinstance(value, date):
        return MonthDay(value.year, value.month, value.day)
    raise TypeError(
        f"{value!r} is neither a game calendar coordinate nor a calendar date"
    )


# ── Calendar protocol (design D2) ────────────────────────────────────────

@runtime_checkable
class GameCalendar(Protocol):
    """Structural interface the future C1/C3 consumers depend on only.

    Two implementations arrive in later task groups: ``StandardCalendar``
    (delegates to ``_gregorian_key``/``datetime.date``, D1/D2) and
    ``CustomCalendar`` (linear formula over ``CalendarSpec`` prefix tables, D4).
    """

    def to_key(self, coord: GameCoord, is_bc: bool = False) -> int:
        """Monotonic chronological key of a coordinate; raises
        ``InvalidGameDateError`` when the coordinate does not exist."""
        ...

    def from_key(self, key: int, is_bc: bool = False) -> GameCoord:
        """Exact inverse of ``to_key``; raises ``InvalidGameDateError`` when
        the key falls into no slot of this calendar."""
        ...

    def weekday(self, coord: GameCoord) -> int | None:
        """Index into the week-name cycle (anchor: ``MonthDay(1, 1, 1) → 0``
        for custom calendars, Gregorian ``date.weekday()`` for the standard
        preset); ``None`` for intercalary days (design D5)."""
        ...

    def month_length(self, year: int, month: int) -> int:
        """Length in days of a 1-based ``month`` of ``year``; the era
        parameter is absent by design — era never changes the structure."""
        ...

    def is_valid(self, coord: GameCoord) -> bool:
        """Whether the coordinate exists in this calendar (month/day within
        the spec, year within MIN_YEAR…MAX_YEAR)."""
        ...

    @property
    def month_names(self) -> Mapping[int, str]:
        """Month display names by 1-based month number (piece C2, design
        D7) — an integral part of the calendar itself: a custom calendar
        names its months from its spec's order, the standard preset falls
        back to ``DEFAULT_MONTH_NAMES`` and may be overridden at
        construction.  Names never enter keys, orders or coordinate
        arithmetic; overriding them relabels date captions only (spec
        «Источник имён месяцев»)."""
        ...


class StubCalendar:
    """Placeholder for the future implementations: every method raises
    ``NotImplementedError``.

    Exists so the structural contract of ``GameCalendar`` (isinstance
    compatibility of a full-featured implementer) is checkable before the
    real ``StandardCalendar``/``CustomCalendar`` land.
    """

    def to_key(self, coord: GameCoord, is_bc: bool = False) -> int:
        raise NotImplementedError

    def from_key(self, key: int, is_bc: bool = False) -> GameCoord:
        raise NotImplementedError

    def weekday(self, coord: GameCoord) -> int | None:
        raise NotImplementedError

    def month_length(self, year: int, month: int) -> int:
        raise NotImplementedError

    def is_valid(self, coord: GameCoord) -> bool:
        raise NotImplementedError


# ── Standard preset (design D1) ──────────────────────────────────────────

#: Month lengths of a common Gregorian year; February is amended per year by
#: ``_gregorian_is_leap`` — the preset mirrors the real calendar it delegates
#: to, so this table is a plain fact about that calendar, not a second key
#: formula (the key formulas themselves are never copied, D1).
_GREGORIAN_MONTH_LENGTHS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _gregorian_is_leap(year: int) -> bool:
    """Proleptic Gregorian leap rule — the same one ``datetime.date`` applies."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


#: Month display names of the Gregorian calendar by 1-based month number —
#: the app's single source of month names since piece C2 moved this
#: dictionary out of ``presentation.utils.date_utils`` (and its process
#: global) into the domain.  The «Стандартный» preset defaults to it; a name
#: is a caption only and never touches keys or arithmetic (design D7).
DEFAULT_MONTH_NAMES: Mapping[int, str] = MappingProxyType(
    {
        1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
        5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
        9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
    }
)


class StandardCalendar:
    """The «Стандартный» preset — the real Gregorian calendar under ``era_key``.

    Design D1 makes this class a delegation, not a re-implementation, and D2
    aims it at the private formula: ``to_key`` IS a call to ``_gregorian_key``
    (so bit-exact agreement with the existing chronological key is a tautology
    and the gold tests only probe the wiring, while the public ``era_key``
    dispatcher never re-enters itself through its own default), and
    ``from_key`` inverts it with ``date.fromordinal``; BC years are located by
    binary search over ``_gregorian_key`` itself rather than by a second copy
    of the 732-step formula.  ``weekday`` is the Gregorian
    ``date.weekday()`` (Mon=0): by design a BC coordinate IS the mirrored
    Gregorian date carrying the same year number — the current date widget's
    behavior.  The preset has no intercalary days whatsoever, so an
    ``IntercalaryDay`` coordinate never exists here and ``weekday`` never
    answers ``None`` for a valid coordinate.  Era stays a ``to_key``/
    ``from_key`` argument (D3) and never changes the structure.  Since C2
    the preset also carries its month names (design D7): the Gregorian
    defaults, or an override merged over them at construction — captions
    that leave every key of both eras bit-identical.
    """

    def __init__(self, month_names: Mapping[int, str] | None = None) -> None:
        """Build the preset, optionally overriding month display names.

        The override merges over ``DEFAULT_MONTH_NAMES``, so a month left
        out keeps its Gregorian name; per spec «Источник имён месяцев» the
        same preset produced with or without an override keys every
        coordinate of both eras bit-identically.
        """
        merged: dict[int, str] = dict(DEFAULT_MONTH_NAMES)
        if month_names:
            merged.update(month_names)
        self._month_names: Mapping[int, str] = MappingProxyType(merged)

    @property
    def month_names(self) -> Mapping[int, str]:
        return self._month_names

    def to_key(self, coord: GameCoord, is_bc: bool = False) -> int:
        if not self.is_valid(coord):
            raise InvalidGameDateError(
                f"coordinate {coord!r} does not exist in the standard calendar"
            )
        return _gregorian_key(date(coord.year, coord.month, coord.day), is_bc)

    def from_key(self, key: int, is_bc: bool = False) -> GameCoord:
        if not is_bc:
            if not _AD_FIRST_KEY <= key <= _AD_LAST_KEY:
                raise InvalidGameDateError(
                    f"key {key} is outside the AD scale "
                    f"{_AD_FIRST_KEY}…{_AD_LAST_KEY} of the standard calendar"
                )
            day = date.fromordinal(key)
            return MonthDay(day.year, day.month, day.day)
        # BC: the last key of year ``y``, ``_gregorian_key(date(y, 12, 31), True)``,
        # shrinks strictly as ``y`` grows (the 732 step dominates the
        # calendar jump), so scanning years downward with bisect finds the
        # first year whose last key reaches ``key``.  The intentional
        # blank slots between consecutive years and keys past either end of
        # the scale fail the year-start check below.  Only then the ordinal is
        # restored with ``date.fromordinal`` — the very formula
        # ``_gregorian_key`` runs, never a copy of it (D1/D2).
        years = range(MAX_YEAR, MIN_YEAR - 1, -1)  # last BC keys ascend in this order
        position = bisect.bisect_left(
            years, key, key=lambda year: _gregorian_key(date(year, 12, 31), True)
        )
        if position < len(years):
            year = years[position]
            year_start = _gregorian_key(date(year, 1, 1), True)
            if year_start <= key:
                day = date.fromordinal(key + BC_YEAR_STEP * year)
                return MonthDay(day.year, day.month, day.day)
        raise InvalidGameDateError(
            f"key {key} has no BC date in the standard calendar — it sits in "
            f"a {BC_YEAR_STEP}-step blank slot or outside the BC scale"
        )

    def weekday(self, coord: GameCoord) -> int | None:
        """Gregorian ``date.weekday()`` (Mon=0) of the mirrored same-year date.

        Era is not an argument here (D3): a BC coordinate is already carried
        as the mirror date with the same year number, so evaluating
        ``date(year, month, day).weekday()`` reproduces exactly what the date
        widget shows for BC today.  Unlike the custom calendar's cycle (D5)
        the preset has no intercalary days, hence no ``None`` answer —
        coordinates outside the real calendar refuse with
        ``InvalidGameDateError``, no silent normalization (D6).
        """
        if not self.is_valid(coord):
            raise InvalidGameDateError(
                f"coordinate {coord!r} does not exist in the standard calendar"
            )
        return date(coord.year, coord.month, coord.day).weekday()

    def month_length(self, year: int, month: int) -> int:
        if not MIN_YEAR <= year <= MAX_YEAR:
            raise InvalidGameDateError(
                f"year {year} is outside {MIN_YEAR}…{MAX_YEAR}"
            )
        if not 1 <= month <= 12:
            raise InvalidGameDateError(f"month {month} is outside 1…12")
        if month == 2 and _gregorian_is_leap(year):
            return 29
        return _GREGORIAN_MONTH_LENGTHS[month - 1]

    def is_valid(self, coord: GameCoord) -> bool:
        if isinstance(coord, MonthDay):
            return (
                MIN_YEAR <= coord.year <= MAX_YEAR
                and 1 <= coord.month <= 12
                and 1 <= coord.day <= self.month_length(coord.year, coord.month)
            )
        # The standard preset has no intercalary rules at all: no such
        # coordinate exists in it, at any index or year.
        return False


# ── Active calendar accessor (roadmap piece C1, design D3) ───────────────

#: The one active game calendar per process, defaulted to the «Стандартный»
#: preset so every chronological key keeps its pre-C1 numbers until a future
#: piece (C2) switches it.  No locks by design (D3): the whole app runs on the
#: single qasync event loop and game switching is serialized (shutdown +
#: start), so read/set/reset can never interleave.
_current_calendar: GameCalendar = StandardCalendar()


def current_calendar() -> GameCalendar:
    """The active game calendar every chronological key dispatches through."""
    return _current_calendar


def set_current_calendar(calendar: GameCalendar) -> None:
    """Make ``calendar`` the one active calendar of the process (design D3).

    Explicit replacement of the old silent month-name global — the caller
    owns the switch; wiring this to game startup/switching is piece C2 (D6).
    No locking: everything runs on the one qasync event loop, so this plain
    rebinding cannot race with a reader (``era_key`` and friends).
    """
    global _current_calendar
    _current_calendar = calendar


def reset_current_calendar() -> None:
    """Restore the «Стандартный» preset as the active calendar (design D3),
    returning every chronological key to its pre-C1 numbers.  Same
    single-event-loop reasoning as ``set_current_calendar`` — no locks."""
    global _current_calendar
    _current_calendar = StandardCalendar()


#: Ends of the standard AD key scale as ``_gregorian_key`` produces them for
#: the allowed boundary years 1…9999 (``date(1, 1, 1)`` opens, ``date(9999,
#: 12, 31)`` closes it contiguously).  Computed through the private formula,
#: never the ``era_key`` dispatcher: dispatching at module import would come
#: back through the lazy import into this partially initialized module
#: (design D2).
_AD_FIRST_KEY = _gregorian_key(date(MIN_YEAR, 1, 1))
_AD_LAST_KEY = _gregorian_key(date(MAX_YEAR, 12, 31))


# ── Custom calendar (designs D4/D7) ──────────────────────────────────────

class CustomCalendar:
    """A calendar built from a fixed ``CalendarSpec``.

    The constructor is the gate (design D7): the spec is validated and a
    ``ValueError`` listing *every* reason aborts construction, so a
    half-valid calendar is unreachable.      The in-year arithmetic
    (``to_key``/``from_key``/``month_length``/``is_valid``) realizes the
    linear layout of design D4 over prefix tables built once here, and
    ``weekday`` realizes the week cycle of design D5.  BC keys are the D4
    mirror ``to_key(coordinate as CE) − 2L·year``: because the game-year
    length is constant, consecutive BC years abut (the per-year jump is
    ``L < 2L``), so BC keys strictly grow along BC chronology and the whole
    BC scale stays below zero while every AD key starts at one.
    """

    def __init__(self, spec: CalendarSpec) -> None:
        problems = validate(spec)
        if problems:
            reasons = "; ".join(f"{p.code}: {p.message}" for p in problems)
            raise ValueError(f"invalid calendar spec: {reasons}")
        self._spec = spec
        self._month_lengths = tuple(month.length for month in spec.months)
        # Month display names straight from the spec (piece C2, design D7):
        # month ``i + 1`` is called ``spec.months[i].name`` — captions only;
        # intercalary rule names live outside this table by construction.
        self._month_names: Mapping[int, str] = MappingProxyType(
            {number: month.name for number, month in enumerate(spec.months, 1)}
        )

        # Prefix tables (design D4): a month's slot starts after every
        # earlier month *and* the intercalary slots those earlier months
        # host; each intercalary day gets its own one-day slot right after
        # its host month, consecutive rules of one month following the spec
        # list order.  ``segment_starts`` merges both kinds of starts in
        # chronological order and feeds the ``from_key`` binary search; it
        # is strictly increasing by construction.
        rules_by_host: dict[int, list[int]] = {}
        for rule_index, rule in enumerate(spec.intercalary):
            rules_by_host.setdefault(rule.after_month, []).append(rule_index)

        month_starts: list[int] = []
        # Indexed by rule position in ``spec.intercalary`` (not by visit
        # order — hosts may be listed in any interleaving).
        intercalary_starts: list[int] = [0] * len(spec.intercalary)
        segment_starts: list[int] = []
        # (is_month, 1-based month number | 0-based intercalary index)
        segment_ids: list[tuple[bool, int]] = []
        offset = 0
        for month_number, month in enumerate(spec.months, 1):
            month_starts.append(offset)
            segment_starts.append(offset)
            segment_ids.append((True, month_number))
            offset += month.length
            for rule_index in rules_by_host.get(month_number, ()):
                intercalary_starts[rule_index] = offset
                segment_starts.append(offset)
                segment_ids.append((False, rule_index))
                offset += 1

        # Year length ``L`` — the same in every year (design D4 invariant).
        self._year_length = offset
        self._month_starts = tuple(month_starts)
        self._intercalary_starts = tuple(intercalary_starts)
        self._segment_starts = tuple(segment_starts)
        self._segment_ids = tuple(segment_ids)

        # Week-cycle tables (design D5): months laid end to end with their
        # intercalary slots removed, so a month's plain offset counts month
        # days only and stays put no matter how many intercalary days sit in
        # earlier months.  ``month_day_count`` is ``L − n_intercalary``.
        plain_month_starts: list[int] = []
        month_day_count = 0
        for month_length in self._month_lengths:
            plain_month_starts.append(month_day_count)
            month_day_count += month_length
        self._plain_month_starts = tuple(plain_month_starts)
        self._month_day_count = month_day_count
        self._week_length = len(spec.week_names)

    @property
    def spec(self) -> CalendarSpec:
        return self._spec

    @property
    def month_names(self) -> Mapping[int, str]:
        """Month names of the spec by 1-based month number (design D7):
        the spec is the only source, so these stay in lockstep with it."""
        return self._month_names

    @property
    def year_length(self) -> int:
        """Length ``L`` of every year of this calendar, in days
        (months plus intercalary days, design D4)."""
        return self._year_length

    def to_key(self, coord: GameCoord, is_bc: bool = False) -> int:
        if not self.is_valid(coord):
            raise InvalidGameDateError(
                f"coordinate {coord!r} does not exist in this calendar"
            )
        # CE part of the D4 formula: ``1 + (year − MIN_YEAR)·L + offset``,
        # with the epoch ``to_key(MonthDay(1, 1, 1)) == 1``.
        if isinstance(coord, MonthDay):
            offset = self._month_starts[coord.month - 1] + coord.day - 1
        else:
            offset = self._intercalary_starts[coord.index]
        ce_key = 1 + (coord.year - MIN_YEAR) * self._year_length + offset
        if not is_bc:
            return ce_key
        # BC mirror (design D4): ``to_key(coordinate as CE) − 2L·year``.
        # The per-year jump backwards (year − 1 is L days higher) never
        # overtakes the 2L step (L < 2L), so keys strictly grow along BC
        # chronology and year 1 BC closes at ``−L`` — below every AD key.
        return ce_key - 2 * self._year_length * coord.year

    def from_key(self, key: int, is_bc: bool = False) -> GameCoord:
        if not is_bc:
            last_key = MAX_YEAR * self._year_length
            if not 1 <= key <= last_key:
                raise InvalidGameDateError(
                    f"key {key} is outside the AD scale 1…{last_key} of this calendar"
                )
            year = MIN_YEAR + (key - 1) // self._year_length
            return self._coord_in_year(year, (key - 1) % self._year_length)
        # BC mirror inverted (design D4): year ``y`` keys span exactly
        # ``[1 − L·(y + 1), −L·y]``, so consecutive BC years abut with no
        # blank slot and the whole scale is ``[1 − L·(MAX_YEAR + 1), −L]``;
        # ``(-key) // L`` recovers the year and the remainder the slot.
        bottom = 1 - (MAX_YEAR + 1) * self._year_length
        top = -self._year_length
        if not bottom <= key <= top:
            raise InvalidGameDateError(
                f"key {key} is outside the BC scale {bottom}…{top} of this calendar"
            )
        year = (-key) // self._year_length
        return self._coord_in_year(year, key - 1 + (year + 1) * self._year_length)

    def _coord_in_year(self, year: int, in_year: int) -> GameCoord:
        """Coordinate of the ``in_year``-th slot (0-based) of ``year`` —
        binary search over the merged month/intercalary starts table (D4)."""
        position = bisect.bisect_right(self._segment_starts, in_year) - 1
        is_month, index = self._segment_ids[position]
        if is_month:
            return MonthDay(year, index, in_year - self._segment_starts[position] + 1)
        return IntercalaryDay(year, index)

    def weekday(self, coord: GameCoord) -> int | None:
        """Position in the week-name cycle (design D5), era-independent.

        Only month days feed the counter —
        ``counter = (year − 1)·(L − n_intercalary) + plain_month_offset + day − 1``
        — so an intercalary day has no weekday (``None``) and the days around
        it do not shift, exactly as the spec «Вставной день вне недельного
        цикла» requires.  The anchor is the hard rule
        ``MonthDay(1, 1, 1) → 0``; it is arithmetic only and never enters the
        key, so a future cyclic shift of ``week_names`` renames days without
        moving their chronological order (task 4.2).  Era is not an argument
        by design (D3): the same coordinate carries the same weekday in both
        eras.  Invalid coordinates refuse like ``to_key`` (D6, no silent
        normalization).
        """
        if not self.is_valid(coord):
            raise InvalidGameDateError(
                f"coordinate {coord!r} does not exist in this calendar"
            )
        if isinstance(coord, IntercalaryDay):
            return None
        counter = (
            (coord.year - MIN_YEAR) * self._month_day_count
            + self._plain_month_starts[coord.month - 1]
            + coord.day
            - 1
        )
        return counter % self._week_length

    def month_length(self, year: int, month: int) -> int:
        if not MIN_YEAR <= year <= MAX_YEAR:
            raise InvalidGameDateError(
                f"year {year} is outside {MIN_YEAR}…{MAX_YEAR}"
            )
        if not 1 <= month <= len(self._month_lengths):
            raise InvalidGameDateError(
                f"month {month} is outside 1…{len(self._month_lengths)}"
            )
        return self._month_lengths[month - 1]

    def is_valid(self, coord: GameCoord) -> bool:
        if isinstance(coord, MonthDay):
            return (
                MIN_YEAR <= coord.year <= MAX_YEAR
                and 1 <= coord.month <= len(self._month_lengths)
                and 1 <= coord.day <= self._month_lengths[coord.month - 1]
            )
        if isinstance(coord, IntercalaryDay):
            return (
                MIN_YEAR <= coord.year <= MAX_YEAR
                and 0 <= coord.index < len(self._intercalary_starts)
            )
        return False


# ── Textual year preview (design D8) ─────────────────────────────────────

def render_calendar_year(calendar: GameCalendar, year: int) -> str:
    """Render ``year`` of ``calendar`` as text (design D8).

    The preview is deliberately computed through the calendar's own
    arithmetic — every day's column is ``weekday(coord)`` and every month
    title carries ``month_length`` — so the future widget-grid comparison
    (C3) and the core cross-checks compare against one and the same code
    path, never a second layout implementation.  Layout, top to bottom:

    * a header line holding the week names (column order of ``week_names``);
    * per month: a ``# name (length)`` title line, then week rows of exactly
      ``W`` fixed-width cells — a day sits in its ``weekday`` column, a
      month's first day leaves the columns before it empty, and a new row
      starts wherever the columns wrap (the trailing cells after the month's
      last day stay empty and are trimmed);
    * right after a host month: one ``— name —`` plate per intercalary rule
      of that month, in spec list order.  Plates are standalone lines — an
      intercalary day is outside the week cycle (D5), so it never occupies a
      grid cell and never shifts the weeks that follow.

    The calendar must expose its ``spec`` (month/week/intercalary names) —
    ``CustomCalendar`` does.  ``StandardCalendar`` renders once D2's minimal
    standard spec view lands; until then the preset refuses here with a
    ``TypeError`` rather than guessing names (design "Open Questions" leaves
    the preset's week names and column order to C3).
    """
    try:
        spec = calendar.spec
    except AttributeError as exc:
        raise TypeError(
            "this calendar exposes no spec view (month and week names, "
            "intercalary rules), so its year cannot be previewed"
        ) from exc

    week_names = tuple(spec.week_names)
    week_length = len(week_names)
    months = tuple(spec.months)
    month_lengths = [
        calendar.month_length(year, month_number)
        for month_number in range(1, len(months) + 1)
    ]

    # One uniform cell width fits every weekday name and every day number;
    # the fixed stride makes the rendered text machine-readable for the
    # cross-check tests (and the future C3 comparison).
    cell_width = max(
        max(len(name) for name in week_names),
        max(len(str(length)) for length in month_lengths),
    )

    def render_row(fields) -> str:
        return " ".join(f"{field:>{cell_width}}" for field in fields).rstrip()

    lines = [render_row(week_names)]
    for month_number, month in enumerate(months, start=1):
        length = month_lengths[month_number - 1]
        lines.append("")
        lines.append(f"# {month.name} ({length})")

        # Week grid: day columns come from weekday() (D5 — intercalary days
        # are absent here, so weeks never shift around them); the row flips
        # wherever the column stops advancing (the wrap of the cycle, or any
        # general discontinuity a calendar might produce).
        grid: list[dict[int, str]] = []
        previous_column: int | None = None
        for day in range(1, length + 1):
            column = calendar.weekday(MonthDay(year, month_number, day))
            if previous_column is None or column <= previous_column:
                grid.append({})
            grid[-1][column] = str(day)
            previous_column = column
        for row_cells in grid:
            lines.append(
                render_row(row_cells.get(column, "") for column in range(week_length))
            )

        for rule in spec.intercalary:
            if rule.after_month == month_number:
                lines.append(f"— {rule.name} —")
    return "\n".join(lines)


# ── Shifting invalid coordinates (roadmap piece C1, design D4) ───────────

class ShiftReason(Enum):
    """Reason a coordinate does not exist in a calendar — exactly the three
    of design D4, nothing else (a year outside MIN_YEAR…MAX_YEAR is not a
    shift reason but the core's ``InvalidGameDateError``).  The ``value``
    strings are the stable machine-readable codes of the future migration
    report (design D5: ``день_overflow``, ``месяц_вне_числа``,
    ``индекс_вставного``); the domain never localizes them."""

    DAY_OVERFLOW = "день_overflow"
    MONTH_OUT_OF_RANGE = "месяц_вне_числа"
    INTERCALARY_INDEX_OUT_OF_RANGE = "индекс_вставного"


def _intercalary_rule_count(calendar: GameCalendar) -> int:
    """Number of intercalary rules, read through the protocol only: the
    valid indexes of one year are exactly ``0…count−1``, so probing
    ``is_valid`` upward stops at the first missing slot (the standard preset
    has no rules at all and stops at zero immediately)."""
    count = 0
    while calendar.is_valid(IntercalaryDay(MIN_YEAR, count)):
        count += 1
    return count


def _last_month_number(calendar: GameCalendar, year: int) -> int:
    """Number of the last existing month: ``month_length`` is the protocol's
    own gate, so counting upward stops at the first month it refuses (a
    calendar always has month 1 — ``validate`` rejects a monthless spec)."""
    month = 1
    while True:
        try:
            calendar.month_length(year, month + 1)
        except InvalidGameDateError:
            return month
        month += 1


def classify(coord: GameCoord, calendar: GameCalendar) -> ShiftReason | None:
    """Predicate of design D4: ``None`` when the coordinate exists in
    ``calendar``, otherwise the ``ShiftReason`` for its absence — read
    through the protocol alone, with no storage and no active-calendar
    global.  A year outside the scale or a value that is not a coordinate
    refuses with the core's ``InvalidGameDateError`` instead: those are not
    shift reasons (D4), no silent normalization.

    The three reasons are mutually exclusive by construction: with the year
    settled, the month probe (``month_length`` refusing) outranks the day
    probe (the day of a nonexistent month has no length to overflow), and
    intercalary indexes live in their own coordinate kind.
    """
    if not isinstance(coord, (MonthDay, IntercalaryDay)):
        raise InvalidGameDateError(
            f"{coord!r} is not a calendar coordinate"
        )
    if not MIN_YEAR <= coord.year <= MAX_YEAR:
        raise InvalidGameDateError(
            f"year {coord.year} is outside {MIN_YEAR}…{MAX_YEAR} — not a "
            f"shift reason (design D4), the core's own error"
        )
    if isinstance(coord, IntercalaryDay):
        if 0 <= coord.index < _intercalary_rule_count(calendar):
            return None
        return ShiftReason.INTERCALARY_INDEX_OUT_OF_RANGE
    try:
        month_length = calendar.month_length(coord.year, coord.month)
    except InvalidGameDateError:
        return ShiftReason.MONTH_OUT_OF_RANGE
    if not 1 <= coord.day <= month_length:
        return ShiftReason.DAY_OVERFLOW
    return None


def shift_invalid(
    coord: GameCoord, calendar: GameCalendar
) -> tuple[GameCoord, ShiftReason] | None:
    """Turn an invalid coordinate into the nearest valid one of the same
    year/era per design D4, returning ``(shifted, reason)`` — or ``None``
    when ``classify`` finds nothing to shift, which makes the operation
    idempotent (a shifted coordinate always answers ``None``).  Each reason
    has one uniform clamp: an out-of-length day (either side) → the last day
    of that very month; an out-of-count month → the last existing month's
    last day; an out-of-list intercalary index → the last rule of the spec
    list.  Era is not an argument anywhere, so the coordinate's era is
    preserved trivially, and two coordinates may collide onto one date with
    no separation attempt (the spec allows the collision).  Like
    ``classify``, a year outside the scale or a non-coordinate refuses with
    ``InvalidGameDateError``; a rule-less calendar additionally refuses the
    intercalary clamp — there is genuinely no rule to clamp to."""
    reason = classify(coord, calendar)
    if reason is None:
        return None
    if reason is ShiftReason.DAY_OVERFLOW:
        last_day = calendar.month_length(coord.year, coord.month)
        return MonthDay(coord.year, coord.month, last_day), reason
    if reason is ShiftReason.MONTH_OUT_OF_RANGE:
        last_month = _last_month_number(calendar, coord.year)
        return (
            MonthDay(coord.year, last_month,
                     calendar.month_length(coord.year, last_month)),
            reason,
        )
    last_rule_index = _intercalary_rule_count(calendar) - 1
    if last_rule_index < 0:
        raise InvalidGameDateError(
            f"{coord!r} cannot clamp to an intercalary rule: this calendar "
            f"has no intercalary days whatsoever"
        )
    return IntercalaryDay(coord.year, last_rule_index), reason


# ── Transfer report form (roadmap piece C1, design D5) ───────────────────

class DateField(Enum):
    """Which date slot of a record a report entry is about — the pair
    ``{start, end}`` of design D5.  The ``value`` strings are stable ASCII
    machine codes for the future master screen (C4); the domain never
    localizes them and never carries an entity's display name here."""

    START = "start"
    END = "end"


#: A coordinate paired with the era it is keyed under, mirroring the
#: ``(coord, is_bc)`` shape both sides of a report entry hold (design D5).
CoordWithEra = tuple[GameCoord, bool]


@dataclass(frozen=True)
class ShiftReportEntry:
    """One shifted record of the transfer report (design D5).

    Exactly the machine-readable fields the future master screen needs:
    ``table`` and ``row_id`` locate the record in the caller's own traversal,
    ``field`` says whether the ``start`` or the ``end`` coordinate moved, and
    ``old``/``new`` each carry the coordinate together with its era (the era is
    never altered by a shift).  ``reason`` is the stable ``ShiftReason`` code of
    design D4.  Frozen and free of any localized caption or entity name — those
    belong to the presentation layer (C4), never the domain.
    """

    table: str
    row_id: int
    field: DateField
    old: CoordWithEra
    new: CoordWithEra
    reason: ShiftReason


@dataclass(frozen=True)
class ShiftReport:
    """Frozen collection of :class:`ShiftReportEntry` for the C4 master screen.

    The report is *empty* — no ``records`` and a zero ``shift_count`` — exactly
    when no checked coordinate needed a shift (spec «Отчёт о переносе невалидных
    координат», scenario «Пустой отчёт на валидных данных»).  ``shift_count`` is
    the number of transfers, i.e. one per recorded entry.
    """

    records: tuple[ShiftReportEntry, ...] = ()

    @property
    def shift_count(self) -> int:
        """Number of transferred coordinates the report accounts for."""
        return len(self.records)


#: One candidate coordinate of a record the caller wants checked: the record's
#: ``table``/``row_id``, which ``field`` of it, the ``coord`` and its era.
ShiftCheck = tuple[str, int, DateField, GameCoord, bool]


def build_shift_report(checks: Iterable[ShiftCheck], calendar: GameCalendar) -> ShiftReport:
    """Pure transfer-report builder of design D5: turn coordinate ``checks`` into
    a :class:`ShiftReport` against ``calendar``.

    The calendar is an explicit parameter because, like ``classify`` and
    ``shift_invalid``, this pure function never reads the active-calendar global;
    connecting it to the live accessor and iterating the six real tables is the
    C2 traversal's job, not the domain's — no storage is touched here.  A
    coordinate that exists in ``calendar`` (``shift_invalid`` answers ``None``)
    contributes nothing; every invalid one is clamped by ``shift_invalid`` and
    recorded with the same era on both sides.  The entry list preserves the
    order of ``checks``, and the resulting ``shift_count`` is therefore the
    number of genuinely invalid coordinates.
    """
    entries: list[ShiftReportEntry] = []
    for table, row_id, field, coord, is_bc in checks:
        shifted = shift_invalid(coord, calendar)
        if shifted is not None:
            new_coord, reason = shifted
            entries.append(
                ShiftReportEntry(
                    table=table,
                    row_id=row_id,
                    field=field,
                    old=(coord, is_bc),
                    new=(new_coord, is_bc),
                    reason=reason,
                )
            )
    return ShiftReport(tuple(entries))


# ── Storage codec (roadmap piece C2, design D1) ──────────────────────────

#: JSON format version :func:`encode_calendar` writes and
#: :func:`decode_calendar` reads; a value stamped with any other version is
#: reported as ``unknown_version`` rather than silently misread (spec
#: «Календарь-настройки хранятся в базе игры»).
CALENDAR_STORAGE_VERSION = 1

#: ``kind`` discriminators of the stored value (design D1).
_KIND_STANDARD = "standard"
_KIND_CUSTOM = "custom"


@dataclass(frozen=True)
class CalendarDecoded:
    """Successful decode: the stored value describes this calendar."""

    calendar: GameCalendar


@dataclass(frozen=True)
class CalendarCorrupted:
    """Rejected decode: every reason the stored value could not be read.

    The reasons are the machine-readable :class:`SpecProblem` codes design
    D4 reserves for corruption — the codec's own ``corrupt_json``,
    ``unknown_version`` and ``corrupt_shape`` plus the spec-validation
    codes of a rejected custom spec (the full list, never just the first
    hit).  Like ``validate`` these are never localized here; the
    presentation renders the user-facing warning from these codes."""

    reasons: tuple[SpecProblem, ...]


def _corrupt_shape(detail: str) -> CalendarCorrupted:
    """One malformed-payload problem as a decode result."""
    return CalendarCorrupted((SpecProblem("corrupt_shape", detail),))


def encode_calendar(calendar: GameCalendar) -> str:
    """Serialize a calendar into the stored JSON value of design D1.

    ``{"v": 1, "kind": "standard"}`` gains a ``month_names`` object only
    when the preset's names actually differ from ``DEFAULT_MONTH_NAMES`` —
    an empty (or all-default) override stays normalized into "no field", so
    a setting is never stored "про запас" (spec «Календарь-настройки
    хранятся в базе игры», design "Open Questions").  ``kind: "custom"``
    writes the full spec fields one-for-one: ``months`` (name + length),
    ``week_names`` and ``intercalary`` (name + after_month), list order
    meaningful.  Only the two concrete calendars have a storage shape — a
    third implementer of the protocol refuses here until the C4 wizard
    gives it one.
    """
    if isinstance(calendar, CustomCalendar):
        spec = calendar.spec
        payload: dict = {
            "v": CALENDAR_STORAGE_VERSION,
            "kind": _KIND_CUSTOM,
            "months": [{"name": month.name, "length": month.length} for month in spec.months],
            "week_names": list(spec.week_names),
            "intercalary": [
                {"name": rule.name, "after_month": rule.after_month}
                for rule in spec.intercalary
            ],
        }
    elif isinstance(calendar, StandardCalendar):
        payload = {"v": CALENDAR_STORAGE_VERSION, "kind": _KIND_STANDARD}
        overrides = {
            str(number): name
            for number, name in calendar.month_names.items()
            if DEFAULT_MONTH_NAMES.get(number) != name
        }
        if overrides:
            payload["month_names"] = overrides
    else:
        raise TypeError(
            "only StandardCalendar and CustomCalendar can be stored, not "
            f"{type(calendar).__name__}"
        )
    return json.dumps(payload, ensure_ascii=False)


def decode_calendar(raw: str) -> CalendarDecoded | CalendarCorrupted:
    """Read the stored JSON value back into a calendar (design D1).

    A broken value never raises (design D4): the result is either a
    ``CalendarDecoded`` calendar or a ``CalendarCorrupted`` carrying
    machine-readable reasons — the caller chooses its warning phrasing from
    those codes and leaves the corrupted row untouched.  A stored custom
    spec is run through the core's ``validate`` first, so the full reason
    list is reported and the ``CustomCalendar`` constructor — the same
    gate, reached only with a pre-validated spec — cannot raise here.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return CalendarCorrupted(
            (SpecProblem("corrupt_json", "the stored calendar is not parseable JSON"),)
        )
    if not isinstance(data, dict):
        return _corrupt_shape(
            f"stored calendar must be a JSON object, got {type(data).__name__}"
        )
    version = data.get("v")
    if version != CALENDAR_STORAGE_VERSION:
        return CalendarCorrupted(
            (
                SpecProblem(
                    "unknown_version",
                    f"calendar format version {version!r} is not supported "
                    f"(this app reads and writes version {CALENDAR_STORAGE_VERSION})",
                ),
            )
        )
    kind = data.get("kind")
    if kind == _KIND_STANDARD:
        return _decode_standard(data)
    if kind == _KIND_CUSTOM:
        return _decode_custom(data)
    return _corrupt_shape(
        f"unknown calendar kind {kind!r}, expected {_KIND_STANDARD!r} or {_KIND_CUSTOM!r}"
    )


def _decode_standard(data: dict) -> CalendarDecoded | CalendarCorrupted:
    """``kind: standard`` — the preset plus an optional ``month_names``
    override, whose keys are month numbers carried as JSON strings."""
    raw_names = data.get("month_names")
    if raw_names is None:
        return CalendarDecoded(StandardCalendar())
    if not isinstance(raw_names, dict):
        return _corrupt_shape("month_names must be a JSON object")
    month_names: dict[int, str] = {}
    for number, name in raw_names.items():
        if not isinstance(name, str):
            return _corrupt_shape(f"month name for key {number!r} is not a string")
        try:
            month_names[int(number)] = name
        except ValueError:
            return _corrupt_shape(
                f"month_names key {number!r} is not an integer month number"
            )
    return CalendarDecoded(StandardCalendar(month_names=month_names))


def _is_stored_int(value: object) -> bool:
    """An integer of the JSON world — ``bool`` is ``int`` in Python but is
    never a length or a month number in this format."""
    return isinstance(value, int) and not isinstance(value, bool)


def _decode_custom(data: dict) -> CalendarDecoded | CalendarCorrupted:
    """``kind: custom`` — the full spec, fields decoded one-for-one after a
    shape pass (both ``validate`` and ``CustomCalendar`` assume plain ints
    and strings) and the core's own validation of the rebuilt spec."""
    months_raw = data.get("months")
    week_raw = data.get("week_names")
    intercalary_raw = data.get("intercalary")
    if (
        not isinstance(months_raw, list)
        or not isinstance(week_raw, list)
        or not isinstance(intercalary_raw, list)
    ):
        return _corrupt_shape(
            "custom calendar fields months/week_names/intercalary must be JSON lists"
        )
    months: list[MonthSpec] = []
    for entry in months_raw:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("name"), str)
            or not _is_stored_int(entry.get("length"))
        ):
            return _corrupt_shape(
                f"month entry {entry!r} needs a string name and an integer length"
            )
        months.append(MonthSpec(entry["name"], entry["length"]))
    for name in week_raw:
        if not isinstance(name, str):
            return _corrupt_shape(f"week name {name!r} must be a string")
    intercalary: list[IntercalarySpec] = []
    for entry in intercalary_raw:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("name"), str)
            or not _is_stored_int(entry.get("after_month"))
        ):
            return _corrupt_shape(
                f"intercalary entry {entry!r} needs a string name "
                f"and an integer after_month"
            )
        intercalary.append(IntercalarySpec(entry["name"], entry["after_month"]))
    spec = CalendarSpec(
        months=tuple(months), week_names=tuple(week_raw), intercalary=tuple(intercalary)
    )
    spec_problems = validate(spec)
    if spec_problems:
        return CalendarCorrupted(tuple(spec_problems))
    return CalendarDecoded(CustomCalendar(spec))


# ── Coordinate storage codec (roadmap piece C3a, design D2) ───────────────

#: Kind discriminators of the stored coordinate text (design D2): the first
#: field is always the kind, so a regular day and an intercalary day never
#: share one representation and the reading is self-describing.
_COORD_KIND_MONTH = "M"
_COORD_KIND_INTERCALARY = "I"

#: Field names per kind in text order — the stored text is exactly these
#: colon-joined plain ``str()`` integers (no leading zeros written, none
#: demanded on reading; canonicalness is pinned by the round trip).
_COORD_FIELDS = MappingProxyType(
    {
        _COORD_KIND_MONTH: ("year", "month", "day"),
        _COORD_KIND_INTERCALARY: ("year", "index"),
    }
)


@dataclass(frozen=True)
class CoordDecoded:
    """Successful decode: the stored text describes this coordinate."""

    coord: GameCoord


@dataclass(frozen=True)
class CoordCorrupted:
    """Rejected decode: every machine-readable reason the text could not be
    read, in the same :class:`SpecProblem` shape the calendar codec uses —
    ``empty_coord``, ``not_a_string``, ``unknown_kind`` (missing or foreign
    discriminator), ``incomplete_coord``, ``too_many_fields`` and
    ``non_numeric_field`` (one per offending field).  Never localized; the
    caller phrases its warning from these codes."""

    reasons: tuple[SpecProblem, ...]


def encode_coord(coord: GameCoord) -> str:
    """Serialize one coordinate into its stored text (design D2).

    ``"M:year:month:day"`` for a month day, ``"I:year:index"`` for an
    intercalary day — plain ``str()`` digits, which makes the mapping
    injective (distinct kinds differ in the discriminator; same-kind
    coordinates differ in at least one colon-separated number and a number
    cannot swallow the separator) and the cycle ``decode(encode(c)) == c``
    exact.  Era is not part of a coordinate (D3), so it is not part of its
    text either — the same text serves both eras.  Existence in any calendar
    is deliberately NOT checked: the codec owns shape, while
    ``classify``/``shift_invalid`` own existence.  A value that is not one of
    the two D3 coordinate kinds has no storage shape and raises
    ``TypeError`` (same refusal stance as ``encode_calendar``).
    """
    if isinstance(coord, MonthDay):
        return f"{_COORD_KIND_MONTH}:{coord.year}:{coord.month}:{coord.day}"
    if isinstance(coord, IntercalaryDay):
        return f"{_COORD_KIND_INTERCALARY}:{coord.year}:{coord.index}"
    raise TypeError(
        "only MonthDay and IntercalaryDay coordinates can be stored, not "
        f"{type(coord).__name__}"
    )


def decode_coord(raw: str) -> CoordDecoded | CoordCorrupted:
    """Read a stored coordinate text back (design D2).

    Like :func:`decode_calendar` next to it, an unreadable value never
    raises: the answer is a :class:`CoordCorrupted` carrying the *full* list
    of machine-readable reasons, and the storage resolver/C4 caller logs and
    repairs from those codes.  The reader is deliberately more lenient than
    the writer — a hand-edited ``M:044:03:05`` parses, and re-encoding the
    result returns the canonical text — while the format itself stays an
    opaque internal representation read only by this codec.  No number is
    checked against any calendar here: an out-of-calendar coordinate decodes
    exactly, because existence is the shift policy's question, not the
    codec's.
    """
    if not isinstance(raw, str):
        return CoordCorrupted(
            (SpecProblem("not_a_string", f"stored coordinate {raw!r} is not text"),)
        )
    if not raw:
        return CoordCorrupted(
            (SpecProblem("empty_coord", "stored coordinate text is empty"),)
        )
    parts = raw.split(":")
    kind = parts[0]
    field_names = _COORD_FIELDS.get(kind)
    if field_names is None:
        return CoordCorrupted(
            (
                SpecProblem(
                    "unknown_kind",
                    f"coordinate kind {kind!r} is neither {_COORD_KIND_MONTH!r} "
                    f"(month day) nor {_COORD_KIND_INTERCALARY!r} (intercalary day)",
                ),
            )
        )
    given = parts[1:]
    problems: list[SpecProblem] = []
    if len(given) < len(field_names):
        problems.append(
            SpecProblem(
                "incomplete_coord",
                f"coordinate text {raw!r}: kind {kind!r} needs {len(field_names)} "
                f"numbers, found {len(given)}",
            )
        )
    elif len(given) > len(field_names):
        problems.append(
            SpecProblem(
                "too_many_fields",
                f"coordinate text {raw!r}: kind {kind!r} has {len(field_names)} "
                f"numbers, found {len(given)}",
            )
        )
    numbers: list[int] = []
    for name, text in zip(field_names, given):
        try:
            numbers.append(int(text))
        except ValueError:
            problems.append(
                SpecProblem(
                    "non_numeric_field",
                    f"{kind} coordinate field {name} {text!r} is not an integer",
                )
            )
    if problems:
        return CoordCorrupted(tuple(problems))
    if kind == _COORD_KIND_MONTH:
        return CoordDecoded(MonthDay(*numbers))
    return CoordDecoded(IntercalaryDay(*numbers))
