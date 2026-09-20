"""Chronological core of a configurable game calendar (roadmap piece C0).

The module maps a world date coordinate — ``MonthDay`` (year + month + day)
or ``IntercalaryDay`` (year + intercalary slot) — to a monotonic integer
chronological key and back (design D4).  Both eras span years 1…9999, a year
zero exists in neither, and the BC scale is mirrored with a per-year step of
2L (twice the game-year length), so every BC key stays below every CE key —
the same scheme ``app.domain.date_era`` realizes for Gregorian dates.

Pure domain code that nothing imports yet: piece C1 is what wires it into
``era_key``/ORM hooks.  ``GameCalendar`` (design D2) is the only surface
future consumers may depend on, the standard preset delegates to the existing
``era_key`` formula (D1) and the custom calendar is built from a fixed
``CalendarSpec`` of month lengths, week names and intercalary days (D4/D6).
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

from app.domain.date_era import BC_YEAR_STEP, era_key

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


# ── Calendar protocol (design D2) ────────────────────────────────────────

@runtime_checkable
class GameCalendar(Protocol):
    """Structural interface the future C1/C3 consumers depend on only.

    Two implementations arrive in later task groups: ``StandardCalendar``
    (delegates to ``era_key``/``datetime.date``, D1) and
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


#: Ends of the standard AD key scale as the live ``era_key`` produces them for
#: the allowed boundary years 1…9999 (``date(1, 1, 1)`` opens, ``date(9999,
#: 12, 31)`` closes it contiguously) — the preset only delegates, it owns no
#: copy of the formula (design D1).
_AD_FIRST_KEY = era_key(date(MIN_YEAR, 1, 1))
_AD_LAST_KEY = era_key(date(MAX_YEAR, 12, 31))


class StandardCalendar:
    """The «Стандартный» preset — the real Gregorian calendar under ``era_key``.

    Design D1 makes this class a delegation, not a re-implementation:
    ``to_key`` IS a call to the live ``era_key`` (so bit-exact agreement with
    the existing chronological key is a tautology and the gold tests only
    probe the wiring), and
    ``from_key`` inverts it with ``date.fromordinal``; BC years are located by
    binary search over ``era_key`` itself rather than by a second copy
    of the 732-step formula.  ``weekday`` is the Gregorian
    ``date.weekday()`` (Mon=0): by design a BC coordinate IS the mirrored
    Gregorian date carrying the same year number — the current date widget's
    behavior.  The preset has no intercalary days whatsoever, so an
    ``IntercalaryDay`` coordinate never exists here and ``weekday`` never
    answers ``None`` for a valid coordinate.  Era stays a ``to_key``/
    ``from_key`` argument (D3) and never changes the structure.
    """

    def to_key(self, coord: GameCoord, is_bc: bool = False) -> int:
        if not self.is_valid(coord):
            raise InvalidGameDateError(
                f"coordinate {coord!r} does not exist in the standard calendar"
            )
        return era_key(date(coord.year, coord.month, coord.day), is_bc)

    def from_key(self, key: int, is_bc: bool = False) -> GameCoord:
        if not is_bc:
            if not _AD_FIRST_KEY <= key <= _AD_LAST_KEY:
                raise InvalidGameDateError(
                    f"key {key} is outside the AD scale "
                    f"{_AD_FIRST_KEY}…{_AD_LAST_KEY} of the standard calendar"
                )
            day = date.fromordinal(key)
            return MonthDay(day.year, day.month, day.day)
        # BC: the last key of year ``y``, ``era_key(date(y, 12, 31), True)``,
        # shrinks strictly as ``y`` grows (the 732 step dominates the
        # calendar jump), so scanning years downward with bisect finds the
        # first year whose last key reaches ``key``.  The intentional
        # blank slots between consecutive years and keys past either end of
        # the scale fail the year-start check below.  Only then the ordinal is
        # restored with ``date.fromordinal`` — the very formula
        # ``era_key`` runs, never a copy of it (D1).
        years = range(MAX_YEAR, MIN_YEAR - 1, -1)  # last BC keys ascend in this order
        position = bisect.bisect_left(
            years, key, key=lambda year: era_key(date(year, 12, 31), True)
        )
        if position < len(years):
            year = years[position]
            year_start = era_key(date(year, 1, 1), True)
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
