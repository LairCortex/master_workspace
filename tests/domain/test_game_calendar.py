"""Table tests for custom-calendar spec validation (task group 2), the
custom calendar's AD arithmetic (task group 3), the week cycle
(task group 4) and the standard preset (task group 5).

Every reason from design D6 / spec «Валидация спеки календаря» is rejected
with the *full* list of problems (never just the first one), while large but
physically fine specs pass — the core carries no product caps.  The group-3
section checks the D4 coordinate ⟷ key mapping: prefix tables, round-trips,
monotonicity, intercalary slots, rejection of out-of-spec coordinates.  The
group-4 section checks the D5 week cycle: month-day-only counter, the hard
anchor ``MonthDay(1, 1, 1) → 0``, intercalary days outside the cycle and the
property that the week anchor never enters the chronological key.  The
group-5 section checks ``StandardCalendar``: keys bit-identical with the live
``era_key`` (gold: boundaries + fixed-seed randoms of both eras), circular
sweeps of leap and common years in both eras, real-Gregorian
``month_length``/``is_valid``, the mirrored-BC weekday and the total absence
of intercalary days in the preset.  The group-6 section checks the custom
calendar's BC mirror (D4): the ``to_key(CE) − 2L·year`` formula, strict
monotonicity and gaplessness across BC year borders, the full-scale
separation ``all BC keys < 0 < all AD keys``, and that the era never changes
the structure (validity, lengths and intra-year positions match across eras,
mirrored coordinates round-trip).  The group-7 section checks the D8 textual
year preview: a frozen snapshot of a small spec with two intercalary days,
and arithmetic cross-checks (week 7 and week 11) — every day column equals
``weekday``, empty cells sit exactly where the cycle no longer lands, month
titles carry ``month_length``, and intercalary plates stay outside the week
grid without shifting the weeks that follow.  The group-8 section is the
acceptance fuzz (design D9): a fixed-seed corpus of random valid specs is
swept day by day for circular round-trip, key monotonicity and contiguity,
gapless week-cycle continuity and intercalary neighbour invariance; the file
closes with the task-8.3 scenario-to-test acceptance map of the delta spec.
The final C2 section checks the month-name source of spec «Источник имён
месяцев» (the protocol's ``month_names``, the preset's default/override, the
custom names straight from the spec, captions-only) and the storage codec of
spec «Календарь-настройки хранятся в базе игры» (design D1): ``{"v": 1,
"kind": ...}`` payloads, lossless round-trips and machine-readable reasons
for every corrupt stored value.  The closing C4 section checks the wizard
draft codec of design D6: the ``{"v": 1, "spec": …, "stage": …}`` envelope
reusing the main spec body, exact round-trips per stage, and "corrupt or
invalid draft = no draft" — machine-readable reasons, never exceptions.
"""
import calendar as gregorian
import inspect
import json
import random
from dataclasses import FrozenInstanceError, fields, replace
from datetime import date
from types import SimpleNamespace

import pytest

from app.domain.date_era import _gregorian_key, era_key
from app.domain.game_calendar import (
    CALENDAR_DRAFT_VERSION,
    CALENDAR_STORAGE_VERSION,
    DEFAULT_MONTH_NAMES,
    DRAFT_STAGE_MONTHS,
    DRAFT_STAGE_PREVIEW,
    DRAFT_STAGE_WEEK,
    DRAFT_STAGES,
    MAX_YEAR,
    MAX_YEAR_LENGTH,
    MIN_YEAR,
    CalendarCorrupted,
    CalendarDecoded,
    CalendarDraft,
    CalendarSpec,
    CoordCorrupted,
    as_game_coord,
    CoordDecoded,
    CustomCalendar,
    DateField,
    DraftCorrupted,
    DraftDecoded,
    GameCalendar,
    IntercalaryDay,
    IntercalarySpec,
    InvalidGameDateError,
    MonthDay,
    MonthSpec,
    ShiftReason,
    ShiftReport,
    ShiftReportEntry,
    SpecProblem,
    StandardCalendar,
    StubCalendar,
    build_shift_report,
    classify,
    current_calendar,
    decode_calendar,
    decode_coord,
    decode_draft,
    encode_calendar,
    encode_coord,
    encode_draft,
    render_calendar_year,
    reset_current_calendar,
    set_current_calendar,
    shift_invalid,
    validate,
)


def make_months(*names_and_lengths: tuple[str, int]) -> tuple[MonthSpec, ...]:
    return tuple(MonthSpec(name, length) for name, length in names_and_lengths)


BASE_MONTHS = make_months(("Зимостой", 30), ("Талолист", 50), ("Сухочивень", 20))
BASE_WEEK = ("Восход", "Тень", "Полдень", "Закат")


def base_spec(
    months: tuple[MonthSpec, ...] = BASE_MONTHS,
    week_names: tuple[str, ...] = BASE_WEEK,
    intercalary: tuple[IntercalarySpec, ...] = (),
) -> CalendarSpec:
    """A small valid spec; each failing case overrides exactly one facet."""
    return CalendarSpec(months=months, week_names=week_names, intercalary=intercalary)


def codes_of(problems) -> set[str]:
    return {problem.code for problem in problems}


# --- Table-driven rejection: one row per validation reason (design D6) ---

REJECT_CASES = [
    pytest.param(
        lambda: base_spec(
            months=make_months(("Зимостой", 30), ("", 50))
        ),
        {"empty_month_name"},
        id="empty-month-name",
    ),
    pytest.param(
        lambda: base_spec(week_names=("Восход", "", "Полдень", "Закат")),
        {"empty_week_name"},
        id="empty-week-name",
    ),
    pytest.param(
        lambda: base_spec(
            intercalary=(IntercalarySpec("", 1),)
        ),
        {"empty_intercalary_name"},
        id="empty-intercalary-name",
    ),
    pytest.param(
        lambda: base_spec(
            months=make_months(("Зимостой", 30), ("Талолист", 50), ("Зимостой", 20))
        ),
        {"duplicate_month_name"},
        id="duplicate-month-name",
    ),
    pytest.param(
        lambda: base_spec(week_names=("Восход", "Тень", "Восход", "Закат")),
        {"duplicate_week_name"},
        id="duplicate-week-name",
    ),
    pytest.param(
        lambda: base_spec(
            intercalary=(IntercalarySpec("Карнавал", 1), IntercalarySpec("Карнавал", 2))
        ),
        {"duplicate_intercalary_name"},
        id="duplicate-intercalary-name",
    ),
    pytest.param(
        lambda: base_spec(months=make_months(("Зимостой", 0), ("Талолист", 50))),
        {"month_length_below_min"},
        id="month-length-zero",
    ),
    pytest.param(
        lambda: base_spec(months=make_months(("Зимостой", -5), ("Талолист", 50))),
        {"month_length_below_min"},
        id="month-length-negative",
    ),
    pytest.param(
        lambda: base_spec(week_names=("Восход",)),
        {"week_too_short"},
        id="week-length-1",
    ),
    pytest.param(
        lambda: base_spec(week_names=()),
        {"week_too_short"},
        id="week-length-0",
    ),
    pytest.param(
        lambda: SimpleNamespace(  # storage shape may declare its own W (C2)
            months=BASE_MONTHS,
            week_names=BASE_WEEK,
            intercalary=(),
            week_length=3,
        ),
        {"week_length_mismatch"},
        id="week-length-not-equal-names-count",
    ),
    pytest.param(
        lambda: base_spec(months=()),
        {"no_months"},
        id="zero-months",
    ),
    pytest.param(
        lambda: base_spec(intercalary=(IntercalarySpec("Карнавал", 0),)),
        {"intercalary_unknown_month"},
        id="intercalary-before-the-first-month",
    ),
    pytest.param(
        lambda: base_spec(intercalary=(IntercalarySpec("Карнавал", 4),)),
        {"intercalary_unknown_month"},
        id="intercalary-after-the-last-month",
    ),
    pytest.param(
        lambda: base_spec(intercalary=(IntercalarySpec("Карнавал", -1),)),
        {"intercalary_unknown_month"},
        id="intercalary-negative-month",
    ),
    # Spec scenario «Пустое имя — отказ»: every reason is reported, not the first.
    pytest.param(
        lambda: base_spec(
            months=make_months(("", 30), ("Талолист", 50)),
            week_names=("Восход",),
        ),
        {"empty_month_name", "week_too_short"},
        id="empty-name-and-week-too-short-both-reported",
    ),
]


class TestSpecRejectionTable:
    @pytest.mark.parametrize("build,expected_codes", REJECT_CASES)
    def test_invalid_spec_reports_exactly_the_expected_reasons(self, build, expected_codes):
        problems = validate(build())
        assert codes_of(problems) == expected_codes


# --- Flexibility without product caps: valid specs validate clean ---

class TestFlexibleSpecsAccepted:
    @pytest.mark.parametrize(
        "spec",
        [
            pytest.param(
                CalendarSpec(
                    months=tuple(MonthSpec(f"Месяц{index}", 10) for index in range(500)),
                    week_names=BASE_WEEK,
                ),
                id="500-months-by-10-days",
            ),
            pytest.param(
                CalendarSpec(
                    months=make_months(("Талолист", 99999)),
                    week_names=BASE_WEEK,
                ),
                id="single-month-99999-days",
            ),
            pytest.param(
                CalendarSpec(
                    months=BASE_MONTHS,
                    week_names=BASE_WEEK,
                    intercalary=(
                        IntercalarySpec("Карнавал", 2),
                        IntercalarySpec("Тишина", 2),
                        IntercalarySpec("Бдение", 2),
                    ),
                ),
                id="three-intercalary-days-after-one-month",
            ),
        ],
    )
    def test_valid_big_but_physical_spec_has_no_problems(self, spec):
        assert validate(spec) == []


# --- int64 guard: L ≤ (2⁶³−1)//19999 (design D6) ---

class TestInt64Guard:
    def test_year_length_exactly_at_the_guard_is_accepted(self):
        spec = CalendarSpec(
            months=make_months(("Бездна", MAX_YEAR_LENGTH)),
            week_names=BASE_WEEK,
        )
        assert validate(spec) == []

    def test_year_length_one_day_over_the_guard_is_rejected(self):
        # Месяц у границы + один вставной день = L на день за guard'ом:
        # вставные дни тоже входят в длину года.
        spec = CalendarSpec(
            months=make_months(("Бездна", MAX_YEAR_LENGTH)),
            week_names=BASE_WEEK,
            intercalary=(IntercalarySpec("Карнавал", 1),),
        )
        assert codes_of(validate(spec)) == {"year_length_overflow"}


# --- CustomCalendar constructor is the gate: full reason list in ValueError ---

class TestCustomCalendarConstructor:
    def test_invalid_spec_raises_value_error_listing_every_reason(self):
        # Два независимых дефекта: пустое имя месяца и неделя из одного имени.
        bad = base_spec(
            months=make_months(("", 30), ("Талолист", 50)),
            week_names=("Восход",),
        )
        expected = validate(bad)  # полный список причин, не первая встретившаяся
        assert codes_of(expected) == {"empty_month_name", "week_too_short"}

        with pytest.raises(ValueError) as excinfo:
            CustomCalendar(bad)

        for problem in expected:
            assert problem.code in str(excinfo.value)
            assert problem.message in str(excinfo.value)

    def test_valid_spec_builds_calendar_exposing_its_spec(self):
        spec = base_spec()
        calendar = CustomCalendar(spec)
        assert calendar.spec is spec


# ═════════════════════════════════════════════════════════════════════════
# Task group 3 — AD arithmetic of the custom calendar (design D4)
# ═════════════════════════════════════════════════════════════════════════

def year_length_of(spec: CalendarSpec) -> int:
    """Independent re-derivation of L used by the round-trip tests."""
    return sum(month.length for month in spec.months) + len(spec.intercalary)


def all_year_coords(calendar: CustomCalendar, year: int):
    """Every coordinate of a year, in chronological order: month days, and
    after each host month its intercalary slots in spec list order."""
    for month_number, month in enumerate(calendar.spec.months, start=1):
        for day in range(1, month.length + 1):
            yield MonthDay(year, month_number, day)
        for index, rule in enumerate(calendar.spec.intercalary):
            if rule.after_month == month_number:
                yield IntercalaryDay(year, index)


class TestCeArithmeticRoundTrip:
    """Task 3.1: prefix tables + to_key/from_key for the AD era (D4), a full
    cyclic sweep of a small spec plus year-1/year-9999 edges."""

    SMALL = base_spec(
        months=make_months(("Кратень", 3), ("Двоень", 4), ("Одиночек", 2)),
    )

    @pytest.mark.parametrize("year", [MIN_YEAR, 2, 500, MAX_YEAR - 1, MAX_YEAR])
    def test_full_year_sweep_round_trips_and_is_strictly_monotonic(self, year):
        calendar = CustomCalendar(self.SMALL)
        coords = list(all_year_coords(calendar, year))
        keys = [calendar.to_key(coord) for coord in coords]

        assert len(set(keys)) == len(keys)  # one slot — one date
        assert all(a < b for a, b in zip(keys, keys[1:]))  # chronology order
        assert keys == list(range(keys[0], keys[0] + len(keys)))  # no gaps
        for coord, key in zip(coords, keys):
            assert calendar.from_key(key) == coord
        # keys == sorted(keys) holds for the whole era too because every
        # year has exactly L consecutive keys.

    def test_epoch_first_day_is_key_one(self):
        calendar = CustomCalendar(self.SMALL)
        assert calendar.to_key(MonthDay(1, 1, 1)) == 1
        assert calendar.from_key(1) == MonthDay(1, 1, 1)

    def test_year_edges_of_era_boundaries(self):
        calendar = CustomCalendar(self.SMALL)
        L = year_length_of(self.SMALL)

        first = MonthDay(MIN_YEAR, 1, 1)
        last = MonthDay(MAX_YEAR, len(self.SMALL.months),
                        tuple(self.SMALL.months)[-1].length)
        assert calendar.to_key(first) == 1
        assert calendar.to_key(last) == MAX_YEAR * L
        assert calendar.from_key(MAX_YEAR * L) == last
        # year k spans exactly [(k−1)·L+1, k·L]
        for year in (MIN_YEAR, 7, MAX_YEAR):
            year_keys = [
                calendar.to_key(coord)
                for coord in all_year_coords(calendar, year)
            ]
            assert year_keys[0] == (year - MIN_YEAR) * L + 1
            assert year_keys[-1] == (year - MIN_YEAR + 1) * L

    def test_year_length_is_months_plus_intercalary(self):
        spec = base_spec(
            months=make_months(("Кратень", 3), ("Двоень", 4)),
            intercalary=(IntercalarySpec("Карнавал", 1),
                         IntercalarySpec("Тишина", 2),
                         IntercalarySpec("Бдение", 2)),
        )
        assert CustomCalendar(spec).year_length == year_length_of(spec) == 10

    @pytest.mark.parametrize("key", [0, -1, -MAX_YEAR * 10, MAX_YEAR * 9 + 1, 10**9])
    def test_from_key_refuses_keys_outside_the_ad_scale(self, key):
        calendar = CustomCalendar(self.SMALL)  # L = 9
        L = calendar.year_length
        assert L == 9
        if 1 <= key <= MAX_YEAR * L:  # guard against silly table entries
            pytest.fail("test table key is inside the scale")
        with pytest.raises(InvalidGameDateError):
            calendar.from_key(key)


class TestIntercalarySlots:
    """Task 3.2: intercalary slots sit right after their host month, in spec
    list order; consecutive days of one host keep consecutive keys."""

    SPEC = base_spec(
        months=make_months(("Кратень", 3), ("Двоень", 4), ("Одиночек", 2)),
        intercalary=(
            IntercalarySpec("Гром", 2),   # listed first, hosts after month 2
            IntercalarySpec("Эхо", 1),    # hosts after month 1
            IntercalarySpec("Гроза", 2),  # second day after month 2
        ),
    )

    def test_slots_follow_host_in_list_order_with_round_trip(self):
        calendar = CustomCalendar(self.SPEC)
        coords = list(all_year_coords(calendar, 5))
        keys = [calendar.to_key(coord) for coord in coords]

        assert keys == sorted(keys)
        for coord, key in zip(coords, keys):
            assert calendar.from_key(key) == coord

        # Year order: Кратень×3, Эхо, Двоень×4, Гром, Гроза, Одиночек×2.
        expected = [
            MonthDay(5, 1, 1), MonthDay(5, 1, 2), MonthDay(5, 1, 3),
            IntercalaryDay(5, 1),                       # Эхо
            MonthDay(5, 2, 1), MonthDay(5, 2, 2), MonthDay(5, 2, 3),
            MonthDay(5, 2, 4),
            IntercalaryDay(5, 0),                       # Гром
            IntercalaryDay(5, 2),                       # Гроза
            MonthDay(5, 3, 1), MonthDay(5, 3, 2),
        ]
        assert coords == expected

    def test_consecutive_after_same_host_get_consecutive_keys(self):
        calendar = CustomCalendar(self.SPEC)
        host_last = calendar.to_key(MonthDay(9, 2, 4))
        slot_first = calendar.to_key(IntercalaryDay(9, 0))  # Гром
        slot_second = calendar.to_key(IntercalaryDay(9, 2))  # Гроза
        next_first = calendar.to_key(MonthDay(9, 3, 1))
        assert host_last + 1 == slot_first < slot_second == next_first - 1
        assert calendar.from_key(slot_first) == IntercalaryDay(9, 0)
        assert calendar.from_key(slot_second) == IntercalaryDay(9, 2)

    def test_intercalary_after_last_month_sits_at_the_year_end(self):
        spec = base_spec(
            months=make_months(("Кратень", 3), ("Двоень", 4)),
            intercalary=(IntercalarySpec("Конечный", 2),),
        )
        calendar = CustomCalendar(spec)
        L = calendar.year_length
        assert L == 8  # 3 + 4 дней + один вставной слот
        for year in (MIN_YEAR, 600, MAX_YEAR):
            key = calendar.to_key(IntercalaryDay(year, 0))
            assert key == (year - MIN_YEAR + 1) * L  # ровно последний слот года
            assert calendar.from_key(key) == IntercalaryDay(year, 0)
            if year < MAX_YEAR:
                assert calendar.to_key(MonthDay(year + 1, 1, 1)) == key + 1

    def test_every_intercalary_of_a_fat_year_round_trips(self):
        spec = base_spec(
            months=make_months(("Один", 1), ("Два", 2), ("Три", 3)),
            intercalary=tuple(
                IntercalarySpec(f"Денёк{position}", host)
                for position, host in enumerate((1, 1, 2, 3, 3, 3))
            ),
        )
        calendar = CustomCalendar(spec)
        for index in range(len(spec.intercalary)):
            coord = IntercalaryDay(42, index)
            assert calendar.is_valid(coord) is True
            key = calendar.to_key(coord)
            assert calendar.from_key(key) == coord
            assert calendar.from_key(key + 1) != coord
            assert calendar.from_key(key - 1) != coord


class TestInvalidCoordinates:
    """Task 3.3: is_valid answers and to_key/from_key refuse coordinates
    outside the spec; nothing is silently clamped (D6 «ошиблись днём — имён
    не меняем»)."""

    SPEC = base_spec(
        months=make_months(("Тридцатник", 30), ("Один", 1)),
        intercalary=(IntercalarySpec("Карнавал", 1),
                     IntercalarySpec("Тишина", 1)),
    )

    @pytest.mark.parametrize("coord", [
        MonthDay(1, 1, 0),                      # день до начала месяца
        MonthDay(1, 1, 31),                     # 31-е в 30-дневном месяце
        MonthDay(9999, 1, 31),
        MonthDay(1, 1, 500),                    # сильно за длиной
        MonthDay(1, 0, 1),                      # месяц до первого
        MonthDay(1, 3, 1),                      # месяц после последнего
        MonthDay(1, -1, 1),
        MonthDay(0, 1, 1),                      # год вне 1…9999
        MonthDay(-5, 1, 1),
        MonthDay(MIN_YEAR - 1, 1, 1),
        MonthDay(MAX_YEAR + 1, 1, 1),
        MonthDay(10_000, 1, 1),
    ])
    def test_month_day_outside_spec_is_invalid_and_refused(self, coord):
        calendar = CustomCalendar(self.SPEC)
        assert calendar.is_valid(coord) is False
        with pytest.raises(InvalidGameDateError):
            calendar.to_key(coord)

    @pytest.mark.parametrize("index", [-1, 2, 3, 10_000])
    def test_intercalary_index_outside_rule_list_is_refused(self, index):
        calendar = CustomCalendar(self.SPEC)  # rule list has size 2
        coord = IntercalaryDay(5, index)
        assert calendar.is_valid(coord) is False
        with pytest.raises(InvalidGameDateError):
            calendar.to_key(coord)

    def test_intercalary_on_calendar_without_rules_is_refused(self):
        calendar = CustomCalendar(base_spec())
        coord = IntercalaryDay(1, 0)
        assert calendar.is_valid(coord) is False
        with pytest.raises(InvalidGameDateError):
            calendar.to_key(coord)

    def test_intercalary_with_out_of_range_year_is_refused(self):
        calendar = CustomCalendar(self.SPEC)
        for year in (0, -1, MAX_YEAR + 1):
            coord = IntercalaryDay(year, 0)
            assert calendar.is_valid(coord) is False
            with pytest.raises(InvalidGameDateError):
                calendar.to_key(coord)

    def test_valid_coordinates_report_valid(self):
        calendar = CustomCalendar(self.SPEC)
        assert calendar.is_valid(MonthDay(1, 1, 1)) is True
        assert calendar.is_valid(MonthDay(1, 1, 30)) is True
        assert calendar.is_valid(MonthDay(MAX_YEAR, 2, 1)) is True
        assert calendar.is_valid(IntercalaryDay(1, 0)) is True
        assert calendar.is_valid(IntercalaryDay(MAX_YEAR, 1)) is True

    def test_wrong_day_is_never_silently_clamped(self):
        calendar = CustomCalendar(self.SPEC)
        wrong = MonthDay(7, 1, 31)  # месяца из 30 дней
        assert calendar.is_valid(wrong) is False
        with pytest.raises(InvalidGameDateError):
            calendar.to_key(wrong)
        # молчаливой нормализации нет: ключ 30-го остаётся ключом 30-го,
        # следующий за ним ключ — это уже второй месяц, а не «сдвиг 31-го»
        key_of_last_valid = calendar.to_key(MonthDay(7, 1, 30))
        assert calendar.from_key(key_of_last_valid) == MonthDay(7, 1, 30)
        assert calendar.from_key(key_of_last_valid + 1) == IntercalaryDay(7, 0)

    def test_invalid_error_is_a_value_error(self):
        calendar = CustomCalendar(self.SPEC)
        with pytest.raises(ValueError):
            calendar.to_key(MonthDay(1, 1, 31))


class TestGiantSpecs:
    """Task 3.4: from_key/to_key stay correct on spec-гигант calendars —
    sampled circular sweeps of every month edge and intercalary slot
    (the 99999-day month contributes only its corners)."""

    @staticmethod
    def chronological_corners(calendar: CustomCalendar, year: int):
        """Corner coordinates in chronological order: first two and last two
        valid days of each month plus every intercalary slot after its host
        — the tail of each month block is always the block's real last day,
        so this list mirrors the year layout with sparse probes."""
        corners: list[MonthDay] = []
        for month_number, month in enumerate(calendar.spec.months, start=1):
            days = sorted(
                {day for day in (1, 2, month.length - 1, month.length)
                 if 1 <= day <= month.length}
            )
            for day in days:
                corners.append(MonthDay(year, month_number, day))
            for index, rule in enumerate(calendar.spec.intercalary):
                if rule.after_month == month_number:
                    corners.append(IntercalaryDay(year, index))
        return corners

    @pytest.mark.parametrize("months", [
        pytest.param(make_months(("Исполин", 99_999)), id="single-99999"),
        pytest.param(make_months(("Исполин", 99_999), ("Кроха", 1),
                                 ("Середь", 500)), id="mixed-giant"),
        pytest.param(tuple(MonthSpec(f"Месяц{n}", 10) for n in range(500)),
                     id="500-months"),
    ])
    @pytest.mark.parametrize("year", [MIN_YEAR, 1234, MAX_YEAR])
    def test_month_edges_and_intercalaries_round_trip(self, months, year):
        intercalary = (
            (IntercalarySpec("Карнавал", 1), IntercalarySpec("Тишина", 1),
             IntercalarySpec("Последыш", len(months)))
            if len(months) > 1
            else (IntercalarySpec("Карнавал", 1),)
        )
        spec = base_spec(months=months, intercalary=intercalary)
        calendar = CustomCalendar(spec)

        corners = self.chronological_corners(calendar, year)
        keys = []
        for coord in corners:
            assert calendar.is_valid(coord) is True
            key = calendar.to_key(coord)
            keys.append(key)
            assert calendar.from_key(key) == coord

        # хронологический обход углов даёт строго растущие ключи без повторов
        assert all(a < b for a, b in zip(keys, keys[1:]))
        assert len(set(keys)) == len(keys)

        # границы годового блока следуют формуле D4: [(year−1)·L+1, year·L]
        L = year_length_of(spec)
        assert calendar.to_key(MonthDay(year, 1, 1)) == (year - MIN_YEAR) * L + 1
        last_month = tuple(spec.months)[-1]
        if spec.intercalary and spec.intercalary[-1].after_month == len(spec.months):
            last_coord = IntercalaryDay(year, len(spec.intercalary) - 1)
        else:
            last_coord = MonthDay(year, len(spec.months), last_month.length)
        assert calendar.to_key(last_coord) == (year - MIN_YEAR + 1) * L
        assert calendar.from_key((year - MIN_YEAR + 1) * L) == last_coord

    def test_giant_month_interior_keys_match_manual_prefix_layout(self):
        spec = base_spec(
            months=make_months(("Исполин", 99_999), ("Кроха", 1)),
            intercalary=(IntercalarySpec("Карнавал", 1),
                         IntercalarySpec("Тишина", 1)),
        )
        calendar = CustomCalendar(spec)
        # L = 99999 + 1 + 2 вставных слота
        L = calendar.year_length
        assert L == 100_000 + 2
        # месяц 2 стартует после гиганта и его двух вставных слотов
        assert calendar.to_key(MonthDay(1, 2, 1)) == 1 + 99_999 + 2
        assert calendar.from_key(1 + 99_999 + 2) == MonthDay(1, 2, 1)
        # год 2 начинается ровно через L от эпохи
        assert calendar.to_key(MonthDay(2, 1, 1)) == 1 + L
        # вставные слоты — сразу за месяцем 1, по порядку списка
        assert calendar.to_key(IntercalaryDay(1, 0)) == 1 + 99_999
        assert calendar.to_key(IntercalaryDay(1, 1)) == 1 + 99_999 + 1
        # день внутри гиганта: смещение day−1 от старта месяца
        assert calendar.to_key(MonthDay(1, 1, 50_000)) == 50_000


# ═════════════════════════════════════════════════════════════════════════
# Task group 4 — week cycle (design D5)
# ═════════════════════════════════════════════════════════════════════════

WEEK_11 = tuple(f"Имя{index}" for index in range(11))


class TestWeekdayAnchorAndCycle:
    """Task 4.1: counter of month days only (D5), the hard anchor
    ``MonthDay(1, 1, 1) → 0``, intercalary days have no weekday, and the
    era argument plays no role."""

    FLAT = base_spec(months=make_months(("Перелень", 4), ("Двупень", 7)))

    ELEVEN = base_spec(
        months=make_months(("Тридцать", 30), ("Пятьдесят", 50), ("Двадцать", 20)),
        week_names=WEEK_11,
    )  # month lengths 30/50/20 and the year's 100 month days are no
    # multiple of 11 — the cycle shifts at every month and year edge.

    def test_anchor_first_day_of_first_month_of_first_year_is_index_zero(self):
        calendar = CustomCalendar(self.ELEVEN)
        assert calendar.weekday(MonthDay(MIN_YEAR, 1, 1)) == 0
        assert calendar.spec.week_names[0] == WEEK_11[0]

    def test_weekday_walks_the_year_counter_day_by_day(self):
        calendar = CustomCalendar(self.FLAT)  # months 4 + 7, W = 4
        for day in range(1, 5):
            assert calendar.weekday(MonthDay(1, 1, day)) == day - 1
        # второй месяц стартует с «плоского» офсета 4 (без вставных дней нет)
        assert calendar.weekday(MonthDay(1, 2, 1)) == 4 % 4
        # годовой сдвиг цикла = месячных дней в году mod W = 11 mod 4
        assert calendar.weekday(MonthDay(2, 1, 1)) == 11 % 4
        assert calendar.weekday(MonthDay(MAX_YEAR, 1, 1)) == (MAX_YEAR - 1) * 11 % 4

    def test_eleven_named_week_cycles_gaplessly_over_month_edges(self):
        calendar = CustomCalendar(self.ELEVEN)
        for year in (MIN_YEAR, 2, 3, 4, MAX_YEAR):
            coords = [
                coord
                for coord in all_year_coords(calendar, year)
                if isinstance(coord, MonthDay)
            ]
            weekdays = [calendar.weekday(coord) for coord in coords]
            assert all((previous + 1) % 11 == nxt
                       for previous, nxt in zip(weekdays, weekdays[1:]))

    def test_eleven_named_week_continues_strictly_over_year_boundaries(self):
        calendar = CustomCalendar(self.ELEVEN)
        coords = [
            coord
            for year in (1, 2, 3, 4)
            for coord in all_year_coords(calendar, year)
            if isinstance(coord, MonthDay)
        ]
        weekdays = [calendar.weekday(coord) for coord in coords]
        assert all((previous + 1) % 11 == nxt
                   for previous, nxt in zip(weekdays, weekdays[1:]))

        # имена идут строго по кругу без пропусков и повторов: все 11 имён
        # встречаются, а порядок имён — это порядок индексов mod 11
        names = [WEEK_11[weekday] for weekday in weekdays]
        assert set(names) == set(WEEK_11)

        # числовые проверки сдвигов: месяц 2 продолжает цикл, а не «сбрасывается»
        assert calendar.weekday(MonthDay(1, 2, 1)) == 30 % 11
        assert calendar.weekday(MonthDay(1, 3, 1)) == 80 % 11
        # год 2: 100 месячных дней → естественный годовой сдвиг 100 mod 11 = 1
        assert (calendar.weekday(MonthDay(1, 3, 20)) + 1) % 11 == \
            calendar.weekday(MonthDay(2, 1, 1))
        assert calendar.weekday(MonthDay(2, 1, 1)) == 100 % 11

    def test_weekday_never_takes_an_era_argument(self):
        # Эра — аргумент to_key/from_key (D3); у weekday её нет вовсе,
        # поэтому одна координата физически не может «попросить» другой день
        # недели — н.э. и до н.э. живут в одном цикле.
        weekday_params = list(inspect.signature(CustomCalendar.weekday).parameters)
        assert weekday_params == ["self", "coord"]
        assert "is_bc" in inspect.signature(CustomCalendar.to_key).parameters
        assert "is_bc" in inspect.signature(CustomCalendar.from_key).parameters

    @pytest.mark.parametrize("coord", [
        MonthDay(1, 1, 31),          # 31-е в 30-дневном месяце
        MonthDay(1, 0, 1),
        MonthDay(1, 3, 1),           # месяца всего два
        MonthDay(MIN_YEAR - 1, 1, 1),
        MonthDay(MAX_YEAR + 1, 1, 1),
        IntercalaryDay(1, 2),        # правил всего два: индексы 0 и 1
        IntercalaryDay(0, 0),
    ])
    def test_weekday_refuses_coordinates_outside_the_spec(self, coord):
        calendar = CustomCalendar(base_spec(
            months=make_months(("Тридцатник", 30), ("Один", 1)),
            intercalary=(IntercalarySpec("Карнавал", 1),
                         IntercalarySpec("Тишина", 1)),
        ))
        assert calendar.is_valid(coord) is False
        with pytest.raises(InvalidGameDateError):
            calendar.weekday(coord)


class TestIntercalaryOutsideWeekCycle:
    """Task 4.1 (spec «Вставной день вне недельного цикла»): the intercalary
    day itself has no weekday, and neither neighbour shifts — the first day
    of the following month keeps the weekday it would have had without any
    intercalary days."""

    ODD = make_months(("Нечетай", 5), ("Заутрин", 2))  # нечётная длина хозяина
    WITHOUT = base_spec(months=ODD, week_names=WEEK_11)
    WITH = base_spec(months=ODD, week_names=WEEK_11,
                     intercalary=(IntercalarySpec("Карнавал", 1),))

    @pytest.mark.parametrize("year", [MIN_YEAR, 7, 742, MAX_YEAR])
    def test_intercalary_day_has_no_weekday(self, year):
        calendar = CustomCalendar(self.WITH)
        assert calendar.weekday(IntercalaryDay(year, 0)) is None

    def test_first_day_of_next_month_unshifted_by_intercalary(self):
        plain = CustomCalendar(self.WITHOUT)
        with_day = CustomCalendar(self.WITH)
        for year in (MIN_YEAR, 100, MAX_YEAR):
            for coord in all_year_coords(plain, year):
                assert with_day.weekday(coord) == plain.weekday(coord)
        # месяц-хозяин нечётный (5 дней): считай ядро хронологию вместе с
        # вставным — первый день второго месяца уехал бы на +1 mod 11
        host_last = plain.weekday(MonthDay(1, 1, 5))
        assert host_last == 4
        assert plain.weekday(MonthDay(1, 2, 1)) == host_last + 1
        assert with_day.weekday(MonthDay(1, 2, 1)) == host_last + 1

    @pytest.mark.parametrize("count", [1, 2, 3])
    def test_any_number_of_intercalaries_leaves_month_weekdays_untouched(
        self, count
    ):
        plain = CustomCalendar(self.WITHOUT)
        spec = base_spec(
            months=self.ODD,
            week_names=WEEK_11,
            intercalary=tuple(
                IntercalarySpec(f"Денёк{index}", 1) for index in range(count)
            ),
        )
        calendar = CustomCalendar(spec)
        for year in (MIN_YEAR, 500):
            for month, length in ((1, 5), (2, 2)):
                for day in range(1, length + 1):
                    coord = MonthDay(year, month, day)
                    assert calendar.weekday(coord) == plain.weekday(coord)
            for index in range(count):
                assert calendar.weekday(IntercalaryDay(year, index)) is None
            # соседские месячные дни через гирлянду вставных остаются подряд
            before = calendar.weekday(MonthDay(year, 1, 5))
            after = calendar.weekday(MonthDay(year, 2, 1))
            assert (before + 1) % 11 == after

    def test_intercalary_at_year_end_does_not_break_year_edge_cycle(self):
        spec = base_spec(months=self.ODD, week_names=WEEK_11,
                         intercalary=(IntercalarySpec("Конечный", 2),))
        calendar = CustomCalendar(spec)
        for year in (1, 2, 3):
            assert calendar.weekday(IntercalaryDay(year, 0)) is None
            last_month_day = calendar.weekday(MonthDay(year, 2, 2))
            next_year_first = calendar.weekday(MonthDay(year + 1, 1, 1))
            assert (last_month_day + 1) % 11 == next_year_first


class TestAnchorNotInTheKey:
    """Task 4.2: the week anchor is not part of the key.  Two calendars that
    differ only by a cyclic shift of ``week_names`` give equal keys for every
    coordinate (a future week-cycle shift must never reorder dates) while the
    weekdays as names — and each weekday's index in the list — do move."""

    MONTHS = make_months(("Тридцать", 30), ("Пятьдесят", 50), ("Двадцать", 20))
    INTERCALARY = (IntercalarySpec("Карнавал", 2), IntercalarySpec("Тишина", 2))
    SHIFT = 4  # ненулевой и взаимно прост с 11: ни одно имя не остаётся на месте

    def test_shifted_names_equal_keys_but_different_weekday_indices(self):
        shifted_names = WEEK_11[self.SHIFT:] + WEEK_11[:self.SHIFT]
        first = CustomCalendar(base_spec(
            months=self.MONTHS, week_names=WEEK_11, intercalary=self.INTERCALARY))
        second = CustomCalendar(base_spec(
            months=self.MONTHS, week_names=shifted_names,
            intercalary=self.INTERCALARY))

        coords = [
            coord
            for year in (1, 2, 3)
            for coord in all_year_coords(first, year)
        ]

        # «якорь не в ключе»: ни один ключ, ни одна обратно декодированная
        # координата не сдвинулись — порядок дат целиком от арифметики D4
        for coord in coords:
            key_first = first.to_key(coord)
            assert second.to_key(coord) == key_first
            assert second.from_key(key_first) == coord

        # «разные индексы дней»: каждый день недели (по имени) занимает в
        # двух списках разные позиции
        for index, name in enumerate(WEEK_11):
            assert shifted_names.index(name) != index
            assert shifted_names.index(name) == (index - self.SHIFT) % 11

        for coord in coords:
            weekday_first = first.weekday(coord)
            weekday_second = second.weekday(coord)
            if isinstance(coord, IntercalaryDay):
                assert weekday_first is weekday_second is None
                continue
            # сам счётчик (D5: counter mod W) от имён не зависит — сдвиг
            # проявляется в именах, а не в хронологии
            assert weekday_first == weekday_second
            name_first = WEEK_11[weekday_first]
            name_second = shifted_names[weekday_second]
            assert name_first != name_second
            # день обрёл имя того дня недели, который в старом списке стоял
            # на SHIFT позиций дальше — то есть индекс прежнего дня недели
            # для этой же даты изменился
            assert WEEK_11.index(name_second) == (weekday_first + self.SHIFT) % 11


# ═════════════════════════════════════════════════════════════════════════
# Task group 5 — StandardCalendar, the «Стандартный» preset (design D1)
# ═════════════════════════════════════════════════════════════════════════

def all_gregorian_days(year: int):
    """Every real date of Gregorian ``year`` in chronological order
    (stdlib monthrange as the independent source of month lengths)."""
    for month in range(1, 13):
        for day in range(1, gregorian.monthrange(year, month)[1] + 1):
            yield date(year, month, day)


class TestStandardCalendarProtocol:
    def test_standard_calendar_is_a_game_calendar(self):
        assert isinstance(StandardCalendar(), GameCalendar)


class TestStandardLeapYearSweeps:
    """Task 5.1: era-parameterised circular sweeps of whole years — every
    day's key equals the live ``era_key`` for the requested era, round-trips
    back to the same coordinate, weekdays follow the Gregorian calendar and
    the AD key scale is contiguous day by day."""

    STANDARD = StandardCalendar()  # the calendar is stateless, share freely

    @pytest.mark.parametrize(
        ("year", "is_leap"),
        [
            pytest.param(2024, True, id="leap-2024"),
            pytest.param(2023, False, id="common-2023"),
            pytest.param(2000, True, id="leap-2000-div-400"),
            pytest.param(1900, False, id="common-1900-div-100"),
        ],
    )
    def test_full_year_sweep_both_eras_round_trips(self, year, is_leap):
        assert self.STANDARD.month_length(year, 2) == (29 if is_leap else 28)
        expected_days = 366 if is_leap else 365

        visited = 0
        previous_ad_key = None
        for real in all_gregorian_days(year):
            coord = MonthDay(real.year, real.month, real.day)
            assert self.STANDARD.is_valid(coord) is True
            visited += 1
            keys = set()
            for is_bc in (False, True):
                key = self.STANDARD.to_key(coord, is_bc)
                assert key == era_key(real, is_bc)
                assert self.STANDARD.from_key(key, is_bc) == coord
                keys.add(key)
            assert keys == {  # эра — параметр: один и тот же день получает два ключа
                era_key(real),
                era_key(real, True),
            }
            ad_key = era_key(real)
            assert self.STANDARD.to_key(coord) == ad_key
            if previous_ad_key is not None:
                # н.э.-шкала плотная: соседние дни различаются ровно на 1
                assert ad_key - previous_ad_key == 1
            previous_ad_key = ad_key
            assert self.STANDARD.weekday(coord) == real.weekday()

        assert visited == expected_days

    @pytest.mark.parametrize("year", [MIN_YEAR, 4, 1900, 2000, 2023, 2024, MAX_YEAR])
    def test_month_lengths_are_the_real_gregorian_ones(self, year):
        standard = StandardCalendar()
        for month in range(1, 13):
            assert standard.month_length(year, month) == gregorian.monthrange(
                year, month
            )[1]

    @pytest.mark.parametrize("year", [MIN_YEAR - 1, 0, MAX_YEAR + 1, 10_000])
    @pytest.mark.parametrize("month", [0, 1, 2, 12, 13])
    def test_month_length_refuses_out_of_calendar_numbers(self, year, month):
        standard = StandardCalendar()
        with pytest.raises(InvalidGameDateError):
            standard.month_length(year, month)


class TestStandardGoldMatchWithEraKey:
    """Task 5.2: gold — the core's key is bit-identical with the live
    ``app.domain.date_era.era_key`` on the boundaries and on a fixed-seed
    random sample of both eras; the inverse decoding agrees too."""

    GOLD_DATES = [
        # 29 февраля високосного года и соседи
        pytest.param(date(2024, 2, 28), id="leap-feb-28"),
        pytest.param(date(2024, 2, 29), id="leap-feb-29"),
        pytest.param(date(2024, 3, 1), id="leap-mar-01"),
        # февраль невисокосного года: 29-го не существует, соседями идут 28/01
        pytest.param(date(2023, 2, 28), id="common-feb-28"),
        pytest.param(date(2023, 3, 1), id="common-mar-01"),
        # вековые правила: 1900 не високосный, 2000 високосный
        pytest.param(date(1900, 2, 28), id="1900-feb-28"),
        pytest.param(date(1900, 3, 1), id="1900-mar-01"),
        pytest.param(date(2000, 2, 29), id="2000-feb-29"),
        pytest.param(date(2000, 3, 1), id="2000-mar-01"),
        # границы 1 год / 9999 год (обе эры проверяются в теле теста)
        pytest.param(date(1, 1, 1), id="first-day-of-era"),
        pytest.param(date(1, 1, 2), id="second-day-of-era"),
        pytest.param(date(1, 12, 31), id="last-day-of-year-1"),
        pytest.param(date(9999, 1, 1), id="first-day-of-year-9999"),
        pytest.param(date(9999, 12, 30), id="penultimate-day"),
        pytest.param(date(9999, 12, 31), id="last-day-of-era"),
        # соседи границ месяцев разной длины
        pytest.param(date(2024, 1, 31), id="jan-31-31day"),
        pytest.param(date(2024, 2, 1), id="feb-01-after-long-month"),
        pytest.param(date(2024, 4, 30), id="apr-30-30day"),
        pytest.param(date(2024, 5, 1), id="may-01-after-30day"),
        pytest.param(date(2024, 12, 31), id="dec-31"),
        pytest.param(date(2025, 1, 1), id="jan-01-new-year"),
        pytest.param(date(1, 2, 28), id="feb-28-year-1"),
        pytest.param(date(2, 1, 1), id="jan-01-year-2"),
    ]

    @pytest.mark.parametrize("real", GOLD_DATES)
    def test_boundary_keys_equal_live_era_key_in_both_eras(self, real):
        standard = StandardCalendar()
        coord = MonthDay(real.year, real.month, real.day)
        for is_bc in (False, True):
            key = standard.to_key(coord, is_bc)
            assert key == era_key(real, is_bc)
            assert standard.from_key(key, is_bc) == coord

    def test_fixed_seed_random_sample_of_both_eras_matches_era_key(self):
        rng = random.Random(20_260_918)  # seed фиксирован — выборка воспроизводима
        standard = StandardCalendar()
        probes = 0
        for _ in range(400):
            year = rng.randint(MIN_YEAR, MAX_YEAR)
            month = rng.randint(1, 12)
            day = rng.randint(1, gregorian.monthrange(year, month)[1])
            real = date(year, month, day)
            coord = MonthDay(year, month, day)
            for is_bc in (False, True):
                key = standard.to_key(coord, is_bc)
                assert key == era_key(real, is_bc)
                assert standard.from_key(key, is_bc) == coord
                probes += 1
        assert probes == 800  # 400 дат × обе эры

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            pytest.param((2024, 1, 31), (2024, 2, 1), id="jan-feb"),
            pytest.param((2024, 2, 29), (2024, 3, 1), id="feb-mar-leap"),
            pytest.param((2023, 2, 28), (2023, 3, 1), id="feb-mar-common"),
            pytest.param((1900, 2, 28), (1900, 3, 1), id="feb-mar-1900"),
            pytest.param((2000, 2, 29), (2000, 3, 1), id="feb-mar-2000"),
            pytest.param((2024, 4, 30), (2024, 5, 1), id="apr-may"),
        ],
    )
    def test_month_boundary_neighbours_stay_one_key_apart(self, left, right):
        # соседи границ месяцев внутри одного года различаются ровно на один
        # ключ в обеих эрах (постоянное смещение −732·year от эры не мешает);
        # граница года — отдельная территория: в BC там штатный пропуск шага
        # 732, он покрыт золотыми границами и тестами blank-слотов выше
        standard = StandardCalendar()
        for is_bc in (False, True):
            left_key = standard.to_key(MonthDay(*left), is_bc)
            right_key = standard.to_key(MonthDay(*right), is_bc)
            assert left_key + 1 == right_key == era_key(date(*right), is_bc)


class TestStandardEraDomains:
    """Task 5.1 (эра-параметр) / spec «Хронология до н.э. — зеркало»:
    домены ключей двух эр не пересекаются, blank-слоты шага 732 и ключи за
    концами шкалы отказывают."""

    STANDARD = StandardCalendar()

    def test_both_eras_of_one_day_have_different_keys_bc_is_negative(self):
        coord = MonthDay(2024, 6, 10)
        ad_key = self.STANDARD.to_key(coord, is_bc=False)
        bc_key = self.STANDARD.to_key(coord, is_bc=True)
        assert ad_key == era_key(date(2024, 6, 10))
        assert bc_key == era_key(date(2024, 6, 10), True)
        assert bc_key < 0 < ad_key

    def test_bc_scale_lies_strictly_below_the_ad_epoch(self):
        # верх BC-шкалы — 31.12.1 года до н.э., низ AD-шкалы — 01.01.1 г. н.э.
        assert self.STANDARD.to_key(MonthDay(1, 12, 31), is_bc=True) == era_key(
            date(1, 12, 31), True
        )
        assert self.STANDARD.to_key(MonthDay(1, 12, 31), is_bc=True) < \
            self.STANDARD.to_key(MonthDay(1, 1, 1)) == 1

    @pytest.mark.parametrize(
        ("key", "is_bc"),
        [
            pytest.param(era_key(date(1, 1, 1)), True, id="first-ad-key-as-bc"),
            pytest.param(era_key(date(9999, 12, 31)), True, id="last-ad-key-as-bc"),
            pytest.param(era_key(date(1, 12, 31), True), False, id="top-bc-key-as-ad"),
            pytest.param(era_key(date(9999, 1, 1), True), False, id="bottom-bc-key-as-ad"),
            pytest.param(0, False, id="zero-as-ad"),
            pytest.param(0, True, id="zero-as-bc"),
            pytest.param(era_key(date(MAX_YEAR, 12, 31)) + 1, False,
                         id="past-the-9999-end"),
        ],
    )
    def test_keys_of_the_other_eras_domain_refuse(self, key, is_bc):
        with pytest.raises(InvalidGameDateError):
            self.STANDARD.from_key(key, is_bc)

    @pytest.mark.parametrize("year", [MIN_YEAR + 1, 5, 6, 500, 9000, MAX_YEAR])
    def test_blank_slot_before_a_bc_year_refuses(self, year):
        # день перед началом BC-года всегда попадает в пустой слот шага 732:
        # год year+1 хронологически раньше и его ключи заканчиваются ниже,
        # а до начала года year остаётся непригодный зазор
        blank_key = era_key(date(year, 1, 1), True) - 1
        with pytest.raises(InvalidGameDateError):
            self.STANDARD.from_key(blank_key, True)

    def test_keys_below_the_bc_bottom_refuse_but_the_bottom_round_trips(self):
        bc_bottom = era_key(date(MAX_YEAR, 1, 1), True)
        assert self.STANDARD.from_key(bc_bottom, True) == MonthDay(MAX_YEAR, 1, 1)
        with pytest.raises(InvalidGameDateError):
            self.STANDARD.from_key(bc_bottom - 1, True)


class TestStandardInvalidCoordinates:
    """Task 5.1/5.3: дней, которых нет в григорианском календаре, в пресете
    не существует — проверка ``is_valid`` и отказ ``to_key``/``weekday`` как
    у кастомного ядра (D6, молчаливой нормализации нет)."""

    @pytest.mark.parametrize("coord", [
        MonthDay(1900, 2, 29),        # вековой не-високосный
        MonthDay(2100, 2, 29),
        MonthDay(2023, 2, 29),        # обычный год
        MonthDay(2024, 2, 30),
        MonthDay(2024, 1, 32),
        MonthDay(2024, 4, 31),        # в апреле 30 дней
        MonthDay(2024, 1, 0),
        MonthDay(2024, 0, 1),
        MonthDay(2024, 13, 1),
        MonthDay(0, 1, 1),            # нулевого года нет
        MonthDay(-5, 6, 6),
        MonthDay(MAX_YEAR + 1, 12, 31),
    ])
    def test_nonexistent_gregorian_days_are_invalid_and_refused(self, coord):
        standard = StandardCalendar()
        assert standard.is_valid(coord) is False
        for is_bc in (False, True):
            with pytest.raises(InvalidGameDateError):
                standard.to_key(coord, is_bc)
        with pytest.raises(InvalidGameDateError):
            standard.weekday(coord)

    def test_refusal_is_a_value_error(self):
        with pytest.raises(ValueError):
            StandardCalendar().to_key(MonthDay(2023, 2, 29))


class TestStandardWeekdayAndNoIntercalary:
    """Task 5.3: григорианский ``weekday()`` для BC-даты — по дате-зеркалу с
    тем же номером года (текущее поведение виджета); вставных дней у пресета
    нет вообще."""

    MIRRORED_DAYS = [
        pytest.param(date(1, 1, 1), id="year-1-epoch"),
        pytest.param(date(44, 3, 15), id="ancient-year-44"),
        pytest.param(date(777, 7, 7), id="year-777"),
        pytest.param(date(1900, 2, 28), id="1900-common-feb"),
        pytest.param(date(2000, 2, 29), id="2000-leap-feb"),
        pytest.param(date(2024, 2, 29), id="2024-leap-feb"),
        pytest.param(date(9999, 12, 31), id="era-end"),
    ]

    @pytest.mark.parametrize("real", MIRRORED_DAYS)
    def test_weekday_is_gregorian_of_the_mirrored_same_year_date(self, real):
        # у weekday эры нет (D3), поэтому BC-координата физически это та же
        # григорианская дата с тем же номером года — день недели берётся
        # ровно из неё, как в нынешнем календарном виджете
        standard = StandardCalendar()
        coord = MonthDay(real.year, real.month, real.day)
        assert standard.weekday(coord) == date(real.year, real.month, real.day).weekday()

    def test_weekday_never_takes_an_era_argument(self):
        weekday_params = list(inspect.signature(StandardCalendar.weekday).parameters)
        assert weekday_params == ["self", "coord"]
        assert "is_bc" in inspect.signature(StandardCalendar.to_key).parameters
        assert "is_bc" in inspect.signature(StandardCalendar.from_key).parameters

    @pytest.mark.parametrize("coord", [
        IntercalaryDay(1, 0),
        IntercalaryDay(500, 0),
        IntercalaryDay(MAX_YEAR, 17),
        IntercalaryDay(5, -1),
    ])
    def test_preset_has_no_intercalary_days(self, coord):
        standard = StandardCalendar()
        assert standard.is_valid(coord) is False
        for is_bc in (False, True):
            with pytest.raises(InvalidGameDateError):
                standard.to_key(coord, is_bc)
        with pytest.raises(InvalidGameDateError):
            standard.weekday(coord)


# ═════════════════════════════════════════════════════════════════════════
# Task group 6 — the BC mirror of the custom calendar (design D4)
# ═════════════════════════════════════════════════════════════════════════

def all_coords_of_chronological_bc_run(calendar: CustomCalendar, newer_year: int):
    """Every day of BC years ``newer_year + 1`` and ``newer_year`` in strict
    chronological order: in BC the older year carries the bigger number and
    runs first, while months and days inside each year still run forward."""
    yield from all_year_coords(calendar, newer_year + 1)
    yield from all_year_coords(calendar, newer_year)


class TestBcMirrorOrder:
    """Task 6.1: the BC key is the D4 mirror ``to_key(CE) − 2L·year`` —
    strictly monotonic through BC year borders over all days of two adjacent
    years, and the whole BC scale sits under the whole AD scale."""

    MIRROR_SPEC = base_spec(
        months=make_months(("Кратень", 3), ("Двоень", 4), ("Одиночек", 2)),
        intercalary=(IntercalarySpec("Карнавал", 1), IntercalarySpec("Эхо", 2)),
    )  # L = 3 + 4 + 2 days + 2 intercalary slots = 11

    def test_bc_key_is_exactly_the_d4_mirror_formula(self):
        calendar = CustomCalendar(self.MIRROR_SPEC)
        L = calendar.year_length
        assert L == 11
        for year in (MIN_YEAR, 2, 42, MAX_YEAR - 1, MAX_YEAR):
            for coord in all_year_coords(calendar, year):
                expected = calendar.to_key(coord, is_bc=False) - 2 * L * year
                assert calendar.to_key(coord, is_bc=True) == expected

    @pytest.mark.parametrize("newer_year", [MIN_YEAR, 2, 500, MAX_YEAR - 1])
    def test_two_adjacent_bc_years_sweep_monotonically_and_contiguously(
        self, newer_year
    ):
        calendar = CustomCalendar(self.MIRROR_SPEC)
        coords = list(all_coords_of_chronological_bc_run(calendar, newer_year))
        keys = [calendar.to_key(coord, is_bc=True) for coord in coords]

        # chronological BC order (older = bigger year first) ⇒ strictly…
        assert all(a < b for a, b in zip(keys, keys[1:]))
        # …and with no blank slot across the year border: two years are 2L
        # consecutive keys, exactly what the 2L step leaves between years.
        L = calendar.year_length
        assert len(coords) == 2 * L
        assert keys == list(range(keys[0], keys[-1] + 1))
        # year 2L-block of BC year y spans exactly [1 − L·(y+1), −L·y]
        assert keys[0] == 1 - L * (newer_year + 2)
        assert keys[-1] == -L * newer_year
        for coord, key in zip(coords, keys):
            assert calendar.from_key(key, is_bc=True) == coord

    def test_year_9999_bc_bottom_and_year_1_bc_top_are_the_scale_edges(self):
        calendar = CustomCalendar(self.MIRROR_SPEC)
        L = calendar.year_length

        bottom = calendar.to_key(MonthDay(MAX_YEAR, 1, 1), is_bc=True)
        assert bottom == 1 - L * (MAX_YEAR + 1)
        assert calendar.from_key(bottom, is_bc=True) == MonthDay(MAX_YEAR, 1, 1)
        with pytest.raises(InvalidGameDateError):
            calendar.from_key(bottom - 1, is_bc=True)

        top = calendar.to_key(MonthDay(MIN_YEAR, 3, 2), is_bc=True)  # last day of year 1 BC
        assert top == -L
        assert calendar.from_key(top, is_bc=True) == MonthDay(MIN_YEAR, 3, 2)
        # keys above the top are the no-man's land between the eras — the
        # nonexistent year zero — and never decode as BC
        with pytest.raises(InvalidGameDateError):
            calendar.from_key(top + 1, is_bc=True)

    @pytest.mark.parametrize("key", [-1, 0])
    def test_keys_between_the_era_scales_refuse_in_both_eras(self, key):
        calendar = CustomCalendar(self.MIRROR_SPEC)
        for is_bc in (False, True):
            with pytest.raises(InvalidGameDateError):
                calendar.from_key(key, is_bc)

    def test_full_bc_scale_is_contiguous_under_zero_and_round_trips(self):
        # a two-day year keeps the whole 1…9999 BC scale cheap to sweep:
        # 9999·2 consecutive keys from 1 − 2·L·10⁴ up to −L, all < 0.
        calendar = CustomCalendar(base_spec(months=make_months(("Пара", 2))))
        L = calendar.year_length
        assert L == 2

        keys = [
            calendar.to_key(coord, is_bc=True)
            for year in range(MAX_YEAR, MIN_YEAR - 1, -1)
            for coord in all_year_coords(calendar, year)
        ]
        assert len(keys) == MAX_YEAR * L
        assert keys == sorted(keys)                      # strict chronology…
        assert all(a < b for a, b in zip(keys, keys[1:]))  # …with distinct keys
        assert keys[0] == 1 - L * (MAX_YEAR + 1)
        assert keys[-1] == -L < 0                        # every BC key is negative
        assert set(keys) == set(range(keys[0], -L + 1))   # no skipped slot…
        for year in (MIN_YEAR, 500, MAX_YEAR):
            for coord in all_year_coords(calendar, year):  # …and it round-trips
                key = calendar.to_key(coord, is_bc=True)
                assert calendar.from_key(key, is_bc=True) == coord

    def test_every_bc_key_precedes_every_ad_key(self):
        calendar = CustomCalendar(self.MIRROR_SPEC)
        L = calendar.year_length
        # the maxima/minima realize the boundary: the top of BC is the last
        # day of year 1 BC, the bottom of AD is the epoch — nothing in
        # between, and the two scales cannot interleave.
        bc_top = max(
            calendar.to_key(coord, is_bc=True)
            for year in (MIN_YEAR, MAX_YEAR)
            for coord in all_year_coords(calendar, year)
        )
        ad_bottom = calendar.to_key(MonthDay(MIN_YEAR, 1, 1), is_bc=False)
        assert bc_top == -L
        assert ad_bottom == 1
        assert bc_top < 0 < ad_bottom


class TestEraDoesNotChangeStructure:
    """Task 6.2 / spec «Эра не меняет строение»: validity, month lengths and
    intra-year positions are era-independent, and mirrored coordinates
    round-trip in both eras."""

    SPEC = base_spec(
        months=make_months(("Кратень", 3), ("Двоень", 4), ("Одиночек", 2)),
        intercalary=(IntercalarySpec("Карнавал", 1), IntercalarySpec("Эхо", 2)),
    )

    @pytest.mark.parametrize("year", [MIN_YEAR, 2, 42, MAX_YEAR])
    def test_intra_year_positions_lengths_and_intercalary_slots_match_across_eras(
        self, year
    ):
        calendar = CustomCalendar(self.SPEC)
        first = MonthDay(year, 1, 1)

        # every day of the year — month days and intercalary slots alike —
        # is valid and addressable in both eras, and stands on the same
        # month length in both eras
        coords = list(all_year_coords(calendar, year))
        assert all(calendar.is_valid(coord) for coord in coords)
        for coord in coords:
            if isinstance(coord, MonthDay):
                assert coord.day <= calendar.month_length(year, coord.month)

        # day k of the year carries the same intra-year offset in both eras:
        # each year is one L-key block, the era only shifts the block
        ad_first = calendar.to_key(first, is_bc=False)
        bc_first = calendar.to_key(first, is_bc=True)
        offsets_ad = [calendar.to_key(coord, is_bc=False) - ad_first for coord in coords]
        offsets_bc = [calendar.to_key(coord, is_bc=True) - bc_first for coord in coords]
        assert offsets_ad == offsets_bc == list(range(calendar.year_length)), (
            "era never changes month/day lengths or intercalary positions"
        )

    def test_invalid_coordinates_refuse_in_both_eras(self):
        calendar = CustomCalendar(self.SPEC)
        invalid = [
            MonthDay(42, 1, 4),    # one day past a 3-day month
            MonthDay(42, 0, 1),    # month below 1
            MonthDay(42, 4, 1),    # month past the spec
            MonthDay(42, 1, 0),    # day below 1
            MonthDay(0, 1, 1),     # zero year…
            MonthDay(MAX_YEAR + 1, 1, 1),  # …and above 9999 — neither era
            IntercalaryDay(42, 2),  # index outside the rule list
            IntercalaryDay(42, -1),
            IntercalaryDay(0, 0),
            IntercalaryDay(MAX_YEAR + 1, 0),
        ]
        for coord in invalid:
            assert calendar.is_valid(coord) is False
            for is_bc in (False, True):
                with pytest.raises(InvalidGameDateError):
                    calendar.to_key(coord, is_bc)

    @pytest.mark.parametrize("year", [MIN_YEAR, 44, 500, 9998, MAX_YEAR])
    def test_mirrored_coordinates_round_trip_in_both_eras(self, year):
        calendar = CustomCalendar(self.SPEC)
        for coord in all_year_coords(calendar, year):
            for is_bc in (False, True):
                key = calendar.to_key(coord, is_bc)
                assert calendar.from_key(key, is_bc) == coord


# ═════════════════════════════════════════════════════════════════════════
# Task group 7 — textual year preview (design D8)
# ═════════════════════════════════════════════════════════════════════════

RENDER_WEEK = ("Восход", "Тень", "Полдень", "Закат")
WEEK_7 = ("Восход", "Зенит", "Полдень", "Закат", "Сумерки", "Ночь", "Утро")

RENDER_SPEC = base_spec(
    months=make_months(("Кратень", 4), ("Двоень", 5), ("Одиночек", 3)),
    intercalary=(IntercalarySpec("Гром", 2), IntercalarySpec("Эхо", 2)),
)  # year 1: Кратень runs weekdays 0…3, Двоень starts at 4 % 4 = 0 and ends
# at 0 again, the two intercalary days sit between Двоень and Одиночек, and
# Одиночек starts at 9 % 4 = 1 — leading and trailing empty cells, two
# consecutive plates after one host.


def parse_year_preview(text: str):
    """Read ``render_calendar_year`` output back into a structure: the list
    of week header names, then one dict per month with its declared title
    length, grid rows (stripped ``W``-cell lists) and intercalary plate
    names, in rendering order.  The day-agnostic ``classify`` list is the
    same text lines typed, for structural (order) assertions."""
    lines = text.split("\n")
    header = lines[0]
    week_names = [cell for cell in header.split() if cell]
    assert week_names, "the render must open with a week-name header line"
    cell_width = (len(header) + 1) // len(week_names) - 1

    kinds = []
    months: list[dict] = []
    for line in lines[1:]:
        if not line.strip():
            kinds.append("blank")
        elif line.startswith("# "):
            kinds.append("title")
            title, _, declared = line[2:].rpartition(" (")
            months.append({
                "name": title,
                "declared_length": int(declared.rstrip(")")),
                "rows": [],
                "plates": [],
            })
        elif line.startswith("— "):
            kinds.append("plate")
            assert line.endswith(" —")
            assert months, "a plate must follow its host month title"
            months[-1]["plates"].append(line[2:-2])
        else:
            kinds.append("grid")
            assert months, "grid line outside a month block"
            padded = line.ljust((cell_width + 1) * len(week_names))
            months[-1]["rows"].append([
                padded[column * (cell_width + 1):
                        column * (cell_width + 1) + cell_width].strip()
                for column in range(len(week_names))
            ])
    return week_names, months, kinds


class TestYearPreviewSnapshot:
    """Task 7.1: the rendered text of a small spec with two intercalary days
    is byte-for-byte the expected sheet — week header, month grids of W
    cells, «— name —» plates after the host month (design D8)."""

    EXPECTED = "\n".join([
        " Восход    Тень Полдень   Закат",
        "",
        "# Кратень (4)",
        "      1       2       3       4",
        "",
        "# Двоень (5)",
        "      1       2       3       4",
        "      5",
        "— Гром —",
        "— Эхо —",
        "",
        "# Одиночек (3)",
        "              1       2       3",
    ])

    def test_small_spec_with_two_intercalary_days_renders_exactly(self):
        calendar = CustomCalendar(RENDER_SPEC)
        assert render_calendar_year(calendar, 1) == self.EXPECTED

    def test_calendar_without_a_spec_view_refuses_the_preview(self):
        # open question design.md: the standard preset's names/columns are
        # not fixed, and until its minimal spec view (D2) lands there is
        # nothing to render — an explicit refusal, not a guessed layout
        with pytest.raises(TypeError):
            render_calendar_year(StubCalendar(), 1)


class TestYearPreviewMatchesArithmetic:
    """Task 7.2: for week 7 and week 11 specs the parsed preview agrees with
    the arithmetic day by day — every day's column equals ``weekday``, empty
    cells are exactly the slots the day run no longer lands on, the title
    carries ``month_length``, and intercalary plates never enter the week
    grids nor shift the weeks around them."""

    CROSS_CASES = [
        pytest.param(
            WEEK_7,
            make_months(("Длиннень", 23), ("Коротюшень", 11)),
            id="week-7",
        ),
        pytest.param(
            WEEK_11,
            make_months(("Длиннень", 14), ("Коротюшень", 25)),
            id="week-11",
        ),
    ]
    INTERCALARY = (
        IntercalarySpec("Карнавал", 1),
        IntercalarySpec("Тишина", 1),
    )

    @pytest.mark.parametrize("week_names,months", CROSS_CASES)
    @pytest.mark.parametrize("year", [MIN_YEAR, 2])
    def test_columns_empties_and_title_lengths_follow_the_arithmetic(
        self, week_names, months, year
    ):
        spec = base_spec(months=months, week_names=week_names,
                         intercalary=self.INTERCALARY)
        calendar = CustomCalendar(spec)
        week_length = len(week_names)

        header, parsed, _ = parse_year_preview(render_calendar_year(calendar, year))
        assert header == list(week_names)
        assert len(parsed) == len(months)

        for month_number, month in enumerate(parsed, start=1):
            length = calendar.month_length(year, month_number)
            assert month["name"] == months[month_number - 1].name
            assert month["declared_length"] == length  # numeric length matches

            # the D5 counter steps exactly one weekday per month day, so the
            # arithmetic says a priori which cells the month occupies
            first_weekday = calendar.weekday(MonthDay(year, month_number, 1))
            occupied = {}
            for day in range(1, length + 1):
                weekday = calendar.weekday(MonthDay(year, month_number, day))
                assert weekday == (first_weekday + day - 1) % week_length
                occupied[((first_weekday + day - 1) // week_length, weekday)] = day

            row_count = (first_weekday + length - 1) // week_length + 1
            assert len(month["rows"]) == row_count  # no phantom week rows
            filled = 0
            for row_index, row in enumerate(month["rows"]):
                # the grid is a plain W-wide week matrix, W cells per row
                assert len(row) == week_length
                for column, cell in enumerate(row):
                    expected = occupied.get((row_index, column))
                    if expected is None:
                        # empty cell exactly where weekday no longer lands a
                        # day of this month — padding before the first day,
                        # trailing gap after the last one
                        assert cell == "", f"stray cell {cell!r} in the grid"
                    else:
                        assert cell == str(expected)
                        filled += 1
            assert filled == length  # every day present exactly once

            host = [rule.name for rule in self.INTERCALARY
                    if rule.after_month == month_number]
            assert month["plates"] == host  # after the host month only

    @pytest.mark.parametrize("week_names,months", CROSS_CASES)
    def test_intercalary_plates_stay_out_of_the_week_grids(
        self, week_names, months
    ):
        spec = base_spec(months=months, week_names=week_names,
                         intercalary=self.INTERCALARY)
        calendar = CustomCalendar(spec)
        _, _, kinds = parse_year_preview(render_calendar_year(calendar, MIN_YEAR))

        # structural role of a plate: a standalone line that closes the
        # host's week block — whatever follows is a plate/blank/title line,
        # never another grid row of the same month
        for position, kind in enumerate(kinds):
            if kind == "plate":
                assert kinds[position - 1] in {"grid", "plate"}
                if position + 1 < len(kinds):
                    assert kinds[position + 1] in {"plate", "blank", "title"}
        # and the intercalary day itself: no weekday ⇒ nothing to place on
        # the week grid at all (spec «Вставной день вне недельного цикла»)
        for index in range(len(self.INTERCALARY)):
            assert calendar.weekday(IntercalaryDay(MIN_YEAR, index)) is None

    @pytest.mark.parametrize("week_names,months", CROSS_CASES)
    def test_weeks_after_the_host_month_continue_unshifted(
        self, week_names, months
    ):
        # spec scenario «Предпросмотр видит вставной день»: the plate shows
        # after the host grid, and the next month starts on the very column
        # it would have had without any intercalary days
        with_rules = CustomCalendar(base_spec(
            months=months, week_names=week_names, intercalary=self.INTERCALARY))
        without = CustomCalendar(base_spec(
            months=months, week_names=week_names))

        _, parsed_with, _ = parse_year_preview(render_calendar_year(with_rules, MIN_YEAR))
        _, parsed_without, _ = parse_year_preview(render_calendar_year(without, MIN_YEAR))

        host_month = self.INTERCALARY[0].after_month
        # the host grid itself and the entire next month are pixel-identical;
        # the plates are the only addition after the host
        assert parsed_with[host_month - 1]["rows"] == parsed_without[host_month - 1]["rows"]
        next_month = host_month + 1  # months are two here, host is the first
        assert parsed_with[next_month - 1]["rows"] == parsed_without[next_month - 1]["rows"]
        assert parsed_with[host_month - 1]["plates"] == [
            rule.name for rule in self.INTERCALARY
        ]
        assert parsed_without[host_month - 1]["plates"] == []


# ═════════════════════════════════════════════════════════════════════════
# Task group 8 — acceptance fuzz on random valid specs (design D9, task 8.1)
# ═════════════════════════════════════════════════════════════════════════

#: Fuzz corpus seed — every run rebuilds the very same 40 specs.
FUZZ_SEED = 20_260_919

#: Consecutive-year blocks swept day by day — the era edges and the scale middle.
FUZZ_YEAR_BLOCKS = (
    (MIN_YEAR, MIN_YEAR + 1, MIN_YEAR + 2),
    (500, 501, 502),
    (MAX_YEAR - 2, MAX_YEAR - 1, MAX_YEAR),
)


def build_fuzz_corpus(count: int = 40, seed: int = FUZZ_SEED) -> tuple[CalendarSpec, ...]:
    """Random *valid* specs (design D9): 1…7 months of unique names and
    lengths 1…13, a week of 2…13 unique names, 0…6 intercalary rules on
    random hosts.  Every draw keeps the spec valid by construction, so the
    constructor never refuses and the fuzz tests stay about the core
    properties, not about validation (already table-tested in group 2).
    Names never clash across specs — uniqueness is per dimension (D6) anyway."""
    rng = random.Random(seed)
    specs: list[CalendarSpec] = []
    for number in range(count):
        month_count = rng.randint(1, 7)
        months = tuple(
            MonthSpec(f"ФМес{number}-{index}", rng.randint(1, 13))
            for index in range(1, month_count + 1)
        )
        week_names = tuple(f"ФНед{index}" for index in range(rng.randint(2, 13)))
        intercalary = tuple(
            IntercalarySpec(f"ФВс{number}-{index}", rng.randint(1, month_count))
            for index in range(rng.randint(0, 6))
        )
        specs.append(
            CalendarSpec(months=months, week_names=week_names, intercalary=intercalary)
        )
    return tuple(specs)


FUZZ_SPECS = build_fuzz_corpus()
FUZZ_SPEC_IDS = tuple(f"spec-{position}" for position in range(len(FUZZ_SPECS)))


def fuzz_sweep(calendar: CustomCalendar, block, is_bc: bool):
    """Every coordinate of the consecutive-years ``block`` in true
    chronological order of the requested era: AD counts years forward, BC
    runs them downward (the older year carries the bigger number)."""
    for year in sorted(block, reverse=is_bc):
        yield from all_year_coords(calendar, year)


def last_coord_of_year(calendar: CustomCalendar, year: int):
    """The year's last slot: its last intercalary rule hosted by the last
    month if any, otherwise the last day of the last month."""
    spec = calendar.spec
    hosted = [
        index
        for index, rule in enumerate(spec.intercalary)
        if rule.after_month == len(spec.months)
    ]
    if hosted:
        return IntercalaryDay(year, max(hosted))
    return MonthDay(year, len(spec.months), spec.months[-1].length)


class TestFuzzCorpusShape:
    """Task 8.1: the fixed-seed corpus is meaningful — every spec validates
    clean and builds a calendar whose ``L`` matches independent re-derivation,
    and the corpus contains the shapes the properties below need (seed 2026-09-19
    gives 4 specs without intercalary days, 30 with several rules on one host,
    6 with a two-day week, 12 single-month specs)."""

    def test_every_spec_validates_builds_and_shapes_are_covered(self):
        assert len(FUZZ_SPECS) == 40
        without_intercalary = 0
        multi_slot_host = 0
        two_day_week = 0
        single_month = 0
        for spec in FUZZ_SPECS:
            assert validate(spec) == []
            calendar = CustomCalendar(spec)
            assert calendar.year_length == year_length_of(spec)
            hosts = [rule.after_month for rule in spec.intercalary]
            without_intercalary += int(not hosts)
            multi_slot_host += int(len(hosts) > len(set(hosts)))
            two_day_week += int(len(spec.week_names) == 2)
            single_month += int(len(spec.months) == 1)
        assert without_intercalary >= 1
        assert multi_slot_host >= 1
        assert two_day_week >= 1
        assert single_month >= 1


class TestFuzzCoreProperties:
    """Task 8.1 — the four invariants of design D9 on every random spec:
    circular round-trip over whole years in both eras, strict and gapless
    key monotonicity, gapless week-cycle continuity and intercalary-neighbour
    invariance."""

    @pytest.mark.parametrize("spec", FUZZ_SPECS, ids=FUZZ_SPEC_IDS)
    def test_circular_sweep_round_trips_in_both_eras(self, spec):
        calendar = CustomCalendar(spec)
        L = calendar.year_length
        for is_bc in (False, True):
            for block in FUZZ_YEAR_BLOCKS:
                coords = list(fuzz_sweep(calendar, block, is_bc))
                assert len(coords) == 3 * L  # exhaustive: every slot exactly once
                for coord in coords:
                    assert calendar.is_valid(coord) is True
                    key = calendar.to_key(coord, is_bc)
                    assert calendar.from_key(key, is_bc) == coord
        # extreme keys of both scales decode exactly (spec «Круговой обход всех
        # видов дней»): the epoch, the AD top, the 1 BC top and the 9999 BC bottom
        assert calendar.from_key(1) == MonthDay(MIN_YEAR, 1, 1)
        assert calendar.from_key(MAX_YEAR * L) == last_coord_of_year(calendar, MAX_YEAR)
        assert calendar.from_key(-L, is_bc=True) == last_coord_of_year(calendar, MIN_YEAR)
        assert calendar.from_key(1 - (MAX_YEAR + 1) * L, is_bc=True) == MonthDay(MAX_YEAR, 1, 1)

    @pytest.mark.parametrize("spec", FUZZ_SPECS, ids=FUZZ_SPEC_IDS)
    def test_keys_are_strictly_monotonic_contiguous_and_era_separated(self, spec):
        calendar = CustomCalendar(spec)
        seen_ad: list[int] = []
        seen_bc: list[int] = []
        for is_bc in (False, True):
            for block in FUZZ_YEAR_BLOCKS:
                coords = list(fuzz_sweep(calendar, block, is_bc))
                keys = [calendar.to_key(coord, is_bc) for coord in coords]
                # consecutive chronological days step exactly one key, no
                # slot of the block is skipped and no key repeats
                assert keys == list(range(keys[0], keys[-1] + 1))
                assert len(set(keys)) == len(keys)  # «Один слот — одна дата»
                (seen_bc if is_bc else seen_ad).extend(keys)
        # «одна дата обеих эр» — эры физически не могут дать равный ключ
        assert max(seen_bc) < 0 < min(seen_ad)

    @pytest.mark.parametrize("spec", FUZZ_SPECS, ids=FUZZ_SPEC_IDS)
    def test_weekday_cycle_runs_gaplessly_over_month_and_year_edges(self, spec):
        calendar = CustomCalendar(spec)
        week_length = len(spec.week_names)
        assert calendar.weekday(MonthDay(MIN_YEAR, 1, 1)) == 0  # хард-якорь D5
        for block in FUZZ_YEAR_BLOCKS:
            weekdays = [
                calendar.weekday(coord)
                for year in sorted(block)
                for coord in all_year_coords(calendar, year)
                if isinstance(coord, MonthDay)
            ]
            assert weekdays  # months always have ≥ 1 day
            assert all(0 <= weekday < week_length for weekday in weekdays)
            assert all(
                (previous + 1) % week_length == following
                for previous, following in zip(weekdays, weekdays[1:])
            )

    @pytest.mark.parametrize("spec", FUZZ_SPECS, ids=FUZZ_SPEC_IDS)
    def test_intercalary_days_have_no_weekday_and_never_shift_neighbours(self, spec):
        with_rules = CustomCalendar(spec)
        plain = CustomCalendar(replace(spec, intercalary=()))  # тот же календарь без вставных
        week_length = len(spec.week_names)
        for year in (MIN_YEAR, 500, MAX_YEAR):
            # ни один месячный день не сдвинулся от вставных дней — ни в этом
            # году, ни когда бы цепочка ни сидела
            for month_number, month in enumerate(spec.months, start=1):
                for day in range(1, month.length + 1):
                    coord = MonthDay(year, month_number, day)
                    assert with_rules.weekday(coord) == plain.weekday(coord)
            for index in range(len(spec.intercalary)):
                assert with_rules.weekday(IntercalaryDay(year, index)) is None
            # локальные соседи каждой гирлянды: слоты сидят плотной цепочкой
            # сразу за хозяином и занимают ключи, «недостающие» между соседями,
            # а цикл недельного счёта делает ровно +1 через всю гирлянду
            for host in sorted({rule.after_month for rule in spec.intercalary}):
                chain = [
                    index
                    for index, rule in enumerate(spec.intercalary)
                    if rule.after_month == host
                ]
                host_last = MonthDay(year, host, spec.months[host - 1].length)
                key_before = with_rules.to_key(host_last)
                for slot, index in enumerate(chain, start=1):
                    assert with_rules.to_key(IntercalaryDay(year, index)) == key_before + slot
                if host < len(spec.months):
                    after = MonthDay(year, host + 1, 1)
                elif year < MAX_YEAR:
                    after = MonthDay(year + 1, 1, 1)
                else:
                    after = None  # год-край: следующего просто нет
                if after is not None:
                    assert with_rules.to_key(after) == key_before + len(chain) + 1
                    assert (
                        with_rules.weekday(host_last) + 1
                    ) % week_length == with_rules.weekday(after)


# ═════════════════════════════════════════════════════════════════════════
# Task group 8 — direct delta-spec scenario probes (acceptance, task 8.3)
# ═════════════════════════════════════════════════════════════════════════

class TestScenarioUnevenMonths:
    """Сценарий «Неравномерные месяцы» буквой delta-спека: месяцы именно
    «Зимостой 30, Талолист 500, Сухочивень 99999» — все три длины действуют
     каждый год, круговой обход координат и ключей корректен в каждом месяце
    (спец-проверка поверх произвольных гигантов группы 3.4)."""

    SPEC = CalendarSpec(
        months=make_months(("Зимостой", 30), ("Талолист", 500), ("Сухочивень", 99_999)),
        week_names=BASE_WEEK,
    )

    @pytest.mark.parametrize("year", [MIN_YEAR, 777, MAX_YEAR])
    @pytest.mark.parametrize("is_bc", [False, True], ids=["ad", "bc"])
    def test_three_lengths_hold_every_year_and_corner_sweep_round_trips(self, year, is_bc):
        calendar = CustomCalendar(self.SPEC)
        assert validate(self.SPEC) == []
        corners = []
        for month_number, expected_length in enumerate((30, 500, 99_999), start=1):
            for probe_year in (MIN_YEAR, MAX_YEAR):  # обе границы лет — длина постоянна
                assert calendar.month_length(probe_year, month_number) == expected_length
            corners.extend(
                MonthDay(year, month_number, day)
                for day in (1, 2, expected_length - 1, expected_length)
            )
        keys = [calendar.to_key(coord, is_bc) for coord in corners]
        assert all(left < right for left, right in zip(keys, keys[1:]))
        assert len(set(keys)) == len(keys)
        for coord, key in zip(corners, keys):
            assert calendar.from_key(key, is_bc) == coord


class TestScenarioPreviewSeesPlateAfterSecondMonth:
    """Сценарий «Предпросмотр видит вставной день»: плашка стоит сразу после
    сетки второго месяца, а недели следующего месяца продолжаются без сдвига
    (сравнительная форма — ровно как в требовании)."""

    MONTHS = make_months(("Первый", 6), ("Второй", 5), ("Третий", 9))

    def test_plate_after_second_month_and_next_month_weeks_unshifted(self):
        with_day = CustomCalendar(base_spec(
            months=self.MONTHS, week_names=WEEK_7,
            intercalary=(IntercalarySpec("Карнавал", 2),)))
        without = CustomCalendar(base_spec(months=self.MONTHS, week_names=WEEK_7))

        _, parsed_with, _ = parse_year_preview(render_calendar_year(with_day, MIN_YEAR))
        _, parsed_without, _ = parse_year_preview(render_calendar_year(without, MIN_YEAR))

        assert [month["plates"] for month in parsed_with] == [[], ["Карнавал"], []]
        # сетки месяца-хозяина и следующего месяца — как будто вставного дня нет
        assert parsed_with[1]["rows"] == parsed_without[1]["rows"]
        assert parsed_with[2]["rows"] == parsed_without[2]["rows"]
        assert with_day.weekday(MonthDay(MIN_YEAR, 3, 1)) == without.weekday(MonthDay(MIN_YEAR, 3, 1))
        assert with_day.weekday(IntercalaryDay(MIN_YEAR, 0)) is None


class TestProtocolStubSurfaceAndGuards:
    """Task 8.3 приёмка: строки модуля, до которых поведение сценарных тестов
    не доходит — «тело-многоточие» протокола (1.2), ``NotImplementedError``
    заглушки-предшественника (1.2) и год/месяц-стражи ``month_length`` обеих
    реализаций — проверяются явно: CI-гейт построчного покрытия
    (``--cov=app``, ``fail_under = 100``) считает их, и приёмочный прогон
    обязан держать зелёными и его."""

    def test_game_calendar_protocol_methods_are_bodyless_stubs(self):
        # протокол (D2) даёт только контракт: вызовы вне какого-либо
        # реализатора обязаны быть безвредными заглушками, возвращающими None
        dummy = object()
        coord = MonthDay(1, 1, 1)
        assert GameCalendar.to_key(dummy, coord, False) is None
        assert GameCalendar.from_key(dummy, 1, False) is None
        assert GameCalendar.weekday(dummy, coord) is None
        assert GameCalendar.month_length(dummy, 1, 1) is None
        assert GameCalendar.is_valid(dummy, coord) is None

    @pytest.mark.parametrize("call", [
        lambda stub: stub.to_key(MonthDay(1, 1, 1)),
        lambda stub: stub.from_key(1),
        lambda stub: stub.weekday(MonthDay(1, 1, 1)),
        lambda stub: stub.month_length(1, 1),
        lambda stub: stub.is_valid(MonthDay(1, 1, 1)),
    ])
    def test_stub_calendar_methods_stay_not_implemented(self, call):
        with pytest.raises(NotImplementedError):
            call(StubCalendar())

    @pytest.mark.parametrize("month", [-1, 0, 13])
    def test_standard_month_length_refuses_month_outside_one_to_twelve(self, month):
        with pytest.raises(InvalidGameDateError):
            StandardCalendar().month_length(2024, month)

    @pytest.mark.parametrize("year", [MIN_YEAR - 1, 0, -5, MAX_YEAR + 1])
    def test_custom_month_length_refuses_year_outside_the_scale(self, year):
        with pytest.raises(InvalidGameDateError):
            CustomCalendar(base_spec()).month_length(year, 1)

    @pytest.mark.parametrize("month", [-1, 0, len(BASE_MONTHS) + 1])
    def test_custom_month_length_refuses_month_outside_the_spec(self, month):
        with pytest.raises(InvalidGameDateError):
            CustomCalendar(base_spec()).month_length(5, month)

    def test_is_valid_answers_no_for_things_that_are_not_coordinates(self):
        # ни MonthDay, ни IntercalaryDay — для обеих реализаций «такого дня нет»
        for calendar in (CustomCalendar(base_spec()), StandardCalendar()):
            assert calendar.is_valid("Зимостой, 5") is False
            assert calendar.is_valid(None) is False
            assert calendar.is_valid((1, 1, 1)) is False


# ═════════════════════════════════════════════════════════════════════════
# C1 (wire-game-calendar-key-binding) task group 2 — active calendar
# accessor (design D3)
# ═════════════════════════════════════════════════════════════════════════

CUSTOM_ACCESSOR_SPEC = base_spec(
    months=make_months(("Кратень", 5), ("Двоень", 7), ("Одиночек", 3)),
)  # L = 15: каждый кастомный день месяц 1…3 × день 1…7 остаётся и
# реальным datetime.date, поэтому публичный era_key (его аргумент — date)
# проводит кастомную ветку сквозняком


class TestActiveCalendarAccessor:
    """C1 task 2.1: спека «Accessor активного игрового календаря» — дефолт
    «Стандартный», явные установка и сброс одного общего значения — и
    сценарий «Порядок следует за активным календарём»: era_key отдаёт ключи
    активного календаря, а порядок «ключ ↔ дата» совпадает с обходом
    кастомного года."""

    STANDARD_GOLD = [
        pytest.param(date(1, 1, 1), id="first-day-of-era"),
        pytest.param(date(44, 3, 5), id="bc-mirror-year-44"),
        pytest.param(date(2024, 2, 29), id="leap-feb-29"),
        pytest.param(date(9999, 12, 31), id="last-day-of-era"),
    ]

    PROBE_DATES = [
        date(44, 1, 1),
        date(44, 1, 5),
        date(44, 2, 1),
        date(44, 3, 3),
        date(500, 2, 6),
        date(2024, 2, 7),
    ]

    @pytest.fixture(autouse=True)
    def isolated_active_calendar(self):
        # accessor — модульный глобал (D3): подмена ни в одну сторону
        # не должна заражать ни эти тесты, ни соседей по прогону
        reset_current_calendar()
        yield
        reset_current_calendar()

    @pytest.mark.parametrize("real", STANDARD_GOLD)
    def test_default_accessor_is_standard_and_reproduces_era_key(self, real):
        # сценарий «Дефолт — Стандартный»: без явной установки accessor
        # отдаёт пресет, а его ключ побитово равен действующей era_key
        calendar = current_calendar()
        assert isinstance(calendar, StandardCalendar)
        coord = MonthDay(real.year, real.month, real.day)
        for is_bc in (False, True):
            assert calendar.to_key(coord, is_bc) == _gregorian_key(real, is_bc)
            assert calendar.to_key(coord, is_bc) == era_key(real, is_bc)

    def test_set_and_reset_share_the_one_active_calendar(self):
        # сценарий «Явная смена и сброс»: между установкой и сбросом
        # accessor отдаёт подставленный календарь, после сброса — пресет
        custom = CustomCalendar(CUSTOM_ACCESSOR_SPEC)
        set_current_calendar(custom)
        assert current_calendar() is custom
        reset_current_calendar()
        restored = current_calendar()
        assert isinstance(restored, StandardCalendar)

    def test_active_custom_calendar_moves_every_probe_key(self):
        # сценарий «Порядок следует за активным календарём» (первая половина:
        # era_key возвращает ключи активного календаря) + «Явная смена и
        # сброс» на уровне самих ключей
        standard_snapshot = {
            (real, is_bc): era_key(real, is_bc)
            for real in self.PROBE_DATES
            for is_bc in (False, True)
        }
        custom = CustomCalendar(CUSTOM_ACCESSOR_SPEC)
        set_current_calendar(custom)
        for (real, is_bc), standard_key in standard_snapshot.items():
            coord = MonthDay(real.year, real.month, real.day)
            key = era_key(real, is_bc)
            assert key == custom.to_key(coord, is_bc)  # сверка с CustomCalendar напрямую
            assert key != standard_key  # ключ реально уехал со стандартного числа
        # день за коротким кастомным месяцем теперь не существует…
        with pytest.raises(InvalidGameDateError):
            era_key(date(44, 1, 6))
        # …а после сброса Стандартный принимает его с прежним ключом
        reset_current_calendar()
        assert isinstance(current_calendar(), StandardCalendar)
        for (real, is_bc), standard_key in standard_snapshot.items():
            assert era_key(real, is_bc) == standard_key == _gregorian_key(real, is_bc)
        assert era_key(date(44, 1, 6)) == _gregorian_key(date(44, 1, 6))

    @pytest.mark.parametrize("is_bc", [False, True], ids=["ad", "bc"])
    def test_key_order_follows_the_custom_year_sweep(self, is_bc):
        # сценарий «Порядок следует за активным календарём» (вторая
        # половина): обход кастомного года даёт строго растущие плотные
        # ключи, а from_key активного календаря возвращает ту же дату
        custom = CustomCalendar(CUSTOM_ACCESSOR_SPEC)
        set_current_calendar(custom)
        year = 44
        sweep = [
            date(year, month_number, day)
            for month_number, length in ((1, 5), (2, 7), (3, 3))
            for day in range(1, length + 1)
        ]
        assert len(sweep) == custom.year_length == 15

        keys = [era_key(real, is_bc) for real in sweep]
        assert all(left < right for left, right in zip(keys, keys[1:]))
        assert keys == list(range(keys[0], keys[0] + len(keys)))
        calendar = current_calendar()
        for real, key in zip(sweep, keys):
            assert calendar.from_key(key, is_bc) == MonthDay(
                real.year, real.month, real.day
            )


# ═════════════════════════════════════════════════════════════════════════
# C1 (wire-game-calendar-key-binding) task group 3 — чистый предикат и
# сдвиг невалидных координат (design D4)
# ═════════════════════════════════════════════════════════════════════════

SHIFT_SPEC = base_spec(
    months=make_months(("Коротень", 28), ("Двойной", 10)),
    intercalary=(IntercalarySpec("Гром", 1), IntercalarySpec("Эхо", 2)),
)  # ровно две вставные правила: индексы 0 и 1, крайнее — 1
SHIFT_CUSTOM = CustomCalendar(SHIFT_SPEC)
SHIFT_STANDARD = StandardCalendar()

# Таблица D4: три причины, ожидаемая координата и ожидаемая координата +
# код; валидная строка — None/None (пустые предикат и сдвиг).
SHIFT_CASES = [
    # ── «день_overflow»: день вне длины месяца → последний день того же ──
    # сценарий спеки «Сдвиг переполненного дня»: месяц из 28 дней, 31-е число
    pytest.param(
        SHIFT_CUSTOM, MonthDay(7, 1, 31), MonthDay(7, 1, 28),
        ShiftReason.DAY_OVERFLOW, id="custom-day-31-of-28-day-month",
    ),
    pytest.param(
        SHIFT_CUSTOM, MonthDay(7, 1, 999), MonthDay(7, 1, 28),
        ShiftReason.DAY_OVERFLOW, id="custom-day-far-past-month-end",
    ),
    pytest.param(
        SHIFT_CUSTOM, MonthDay(7, 2, 0), MonthDay(7, 2, 10),
        ShiftReason.DAY_OVERFLOW, id="custom-day-below-one-to-month-end",
    ),
    pytest.param(
        SHIFT_STANDARD, MonthDay(2024, 2, 30), MonthDay(2024, 2, 29),
        ShiftReason.DAY_OVERFLOW, id="std-leap-feb-30",
    ),
    pytest.param(
        SHIFT_STANDARD, MonthDay(2023, 2, 29), MonthDay(2023, 2, 28),
        ShiftReason.DAY_OVERFLOW, id="std-common-feb-29",
    ),
    pytest.param(
        SHIFT_STANDARD, MonthDay(2024, 4, 45), MonthDay(2024, 4, 30),
        ShiftReason.DAY_OVERFLOW, id="std-april-45",
    ),
    # ── «месяц_вне_числа»: месяц вне числа месяцев → последний день ──────
    # последнего существующего месяца того же года (день-компаньон игнорируется)
    pytest.param(
        SHIFT_CUSTOM, MonthDay(7, 3, 1), MonthDay(7, 2, 10),
        ShiftReason.MONTH_OUT_OF_RANGE, id="custom-month-past-last",
    ),
    pytest.param(
        SHIFT_CUSTOM, MonthDay(7, 0, 500), MonthDay(7, 2, 10),
        ShiftReason.MONTH_OUT_OF_RANGE, id="custom-month-before-first-outranks-day",
    ),
    pytest.param(
        SHIFT_CUSTOM, MonthDay(7, 501, 17), MonthDay(7, 2, 10),
        ShiftReason.MONTH_OUT_OF_RANGE, id="custom-month-far-past",
    ),
    pytest.param(
        SHIFT_STANDARD, MonthDay(2024, 13, 1), MonthDay(2024, 12, 31),
        ShiftReason.MONTH_OUT_OF_RANGE, id="std-month-13",
    ),
    pytest.param(
        SHIFT_STANDARD, MonthDay(2024, 0, 7), MonthDay(2024, 12, 31),
        ShiftReason.MONTH_OUT_OF_RANGE, id="std-month-0",
    ),
    # ── «индекс_вставного»: номер вне списка правил → крайнее ────────────
    # существующее правило в порядке спецификации
    pytest.param(
        SHIFT_CUSTOM, IntercalaryDay(7, 2), IntercalaryDay(7, 1),
        ShiftReason.INTERCALARY_INDEX_OUT_OF_RANGE, id="intercalary-index-past-list",
    ),
    pytest.param(
        SHIFT_CUSTOM, IntercalaryDay(7, 10_000), IntercalaryDay(7, 1),
        ShiftReason.INTERCALARY_INDEX_OUT_OF_RANGE, id="intercalary-index-far-past",
    ),
    pytest.param(
        SHIFT_CUSTOM, IntercalaryDay(7, -1), IntercalaryDay(7, 1),
        ShiftReason.INTERCALARY_INDEX_OUT_OF_RANGE, id="intercalary-index-below-zero",
    ),
    # ── валидная на входе координата: предикат молчит, сдвиг пуст ─────────
    pytest.param(
        SHIFT_CUSTOM, MonthDay(7, 1, 28), None, None, id="valid-custom-month-end",
    ),
    pytest.param(
        SHIFT_CUSTOM, IntercalaryDay(7, 0), None, None, id="valid-intercalary-first",
    ),
    pytest.param(
        SHIFT_STANDARD, MonthDay(2024, 2, 29), None, None,
        id="valid-std-leap-feb-29",
    ),
]

#: Только невалидные строки таблицы — для проверок, которым нужна причина.
SHIFT_INVALID_CASES = [case for case in SHIFT_CASES if case.values[2] is not None]


class TestShiftInvalidCoordinatesTable:
    """C1 task 3.1: таблица предиката/сдвига ровно по трём причинам D4 —
    переполнение дня, месяц вне числа месяцев, номер вставного дня вне
    списка — с ожидаемой координатой и стабильным кодом причины."""

    @pytest.mark.parametrize(
        ("calendar", "coord", "expected_coord", "reason"), SHIFT_CASES
    )
    def test_classify_reports_exactly_the_reason_or_stays_none_for_valid(
        self, calendar, coord, expected_coord, reason
    ):
        assert classify(coord, calendar) is reason

    @pytest.mark.parametrize(
        ("calendar", "coord", "expected_coord", "reason"), SHIFT_CASES
    )
    def test_shift_returns_coordinate_with_reason_or_none_for_valid(
        self, calendar, coord, expected_coord, reason
    ):
        result = shift_invalid(coord, calendar)
        if expected_coord is None:
            assert result is None
            return
        shifted, shifted_reason = result
        assert shifted == expected_coord
        assert shifted_reason is reason
        assert calendar.is_valid(shifted) is True
        # сценарий «Сдвиг переполненного дня»: ключ сдвинутой координаты определён
        for is_bc in (False, True):
            key = calendar.to_key(shifted, is_bc)
            assert calendar.from_key(key, is_bc) == shifted

    @pytest.mark.parametrize(
        ("calendar", "coord", "expected_coord", "reason"), SHIFT_CASES
    )
    def test_classify_agrees_with_the_calendar_own_is_valid(
        self, calendar, coord, expected_coord, reason
    ):
        assert (classify(coord, calendar) is None) is calendar.is_valid(coord)

    def test_reason_codes_are_the_stable_d5_strings(self):
        # коды — контракт для отчёта переноса (D5): стабильные строки
        assert ShiftReason.DAY_OVERFLOW.value == "день_overflow"
        assert ShiftReason.MONTH_OUT_OF_RANGE.value == "месяц_вне_числа"
        assert (
            ShiftReason.INTERCALARY_INDEX_OUT_OF_RANGE.value == "индекс_вставного"
        )

    @pytest.mark.parametrize("coord", [
        MonthDay(0, 1, 1),                       # нулевого года нет…
        MonthDay(-5, 1, 5),
        MonthDay(MAX_YEAR + 1, 12, 31),           # …как и 10000-го
        MonthDay(10_000, 13, 99),                 # год первым: месяц/день не причина
        IntercalaryDay(0, 0),
        IntercalaryDay(MAX_YEAR + 1, 2),
    ])
    def test_year_outside_the_scale_stays_a_core_error_not_a_shift_reason(
        self, coord
    ):
        # D4: год вне 1…9999 причиной сдвига НЕ является — остаётся
        # InvalidGameDateError из ядра, ни classify, ни shift его не выдают
        for calendar in (SHIFT_CUSTOM, SHIFT_STANDARD):
            with pytest.raises(InvalidGameDateError):
                classify(coord, calendar)
            with pytest.raises(InvalidGameDateError):
                shift_invalid(coord, calendar)

    @pytest.mark.parametrize("junk", ["Зимостой, 5", None, (1, 1, 1)])
    def test_not_a_coordinate_is_a_core_error_too(self, junk):
        with pytest.raises(InvalidGameDateError):
            classify(junk, SHIFT_CUSTOM)
        with pytest.raises(InvalidGameDateError):
            shift_invalid(junk, SHIFT_CUSTOM)

    def test_index_reason_without_any_rule_refuses_the_shift_for_lack_of_target(self):
        # причина «индекс_вставного» констатируется и на календаре без правил…
        coord = IntercalaryDay(5, 0)
        assert classify(coord, SHIFT_STANDARD) is (
            ShiftReason.INTERCALARY_INDEX_OUT_OF_RANGE
        )
        # …но clamp не к чему: цели сдвига нет — отказ ядра (InvalidGameDateError)
        with pytest.raises(InvalidGameDateError):
            shift_invalid(coord, SHIFT_STANDARD)


class TestShiftCoordinateProperties:
    """C1 task 3.3: свойства сдвига — идемпотентность, допустимое
    столкновение двух координат на одной дате, сохранность эры и её
    независимость от результата (сценарии «Идемпотентность сдвига» и
    «Эра не влияет на сдвиг»)."""

    @pytest.mark.parametrize(
        ("calendar", "coord", "expected_coord", "reason"), SHIFT_INVALID_CASES
    )
    def test_shift_is_idempotent_the_repeat_moves_nothing(
        self, calendar, coord, expected_coord, reason
    ):
        first, _ = shift_invalid(coord, calendar)
        assert first == expected_coord
        # сценарий «Идемпотентность сдвига»: ставшая валидной координата
        # не меняется, а повторный сдвиг и предикат пусты
        assert classify(first, calendar) is None
        assert calendar.is_valid(first) is True
        assert shift_invalid(first, calendar) is None

    def test_two_invalid_coordinates_colliding_on_one_day_are_tolerated(self):
        # «Столкновение двух координат на одной дате допускается»: разъезда
        # нет — обе приземляются ровно на последний день того же месяца
        first, first_reason = shift_invalid(MonthDay(7, 1, 29), SHIFT_CUSTOM)
        second, second_reason = shift_invalid(MonthDay(7, 1, 99), SHIFT_CUSTOM)
        assert first == second == MonthDay(7, 1, 28)
        assert first_reason is second_reason is ShiftReason.DAY_OVERFLOW
        assert SHIFT_CUSTOM.to_key(first) == SHIFT_CUSTOM.to_key(second)

    def test_the_shift_carries_no_era_argument_at_all(self):
        # D3: эра — аргумент only у to_key/from_key; раз у classify/
        # shift_invalid её нет физически, календарная часть результата не
        # может зависеть от эры — она сохраняется тривиально
        for func in (classify, shift_invalid):
            assert "is_bc" not in inspect.signature(func).parameters

    @pytest.mark.parametrize(
        ("calendar", "coord", "expected_coord", "reason"), SHIFT_INVALID_CASES
    )
    def test_same_coordinate_shifts_identically_under_both_eras(
        self, calendar, coord, expected_coord, reason
    ):
        # сценарий «Эра не влияет на сдвиг»: одна и та же координата
        # сдвинута «в эрах н.э. и до н.э.» — календарная часть результата
        # одинакова (сдвиг эру не знает) и эра сохранена: ключ каждой эры
        # декодируется ровно в эту координату обратно
        shifted, shift_reason = shift_invalid(coord, calendar)
        assert shift_reason is reason
        for is_bc in (False, True):
            assert calendar.from_key(calendar.to_key(shifted, is_bc), is_bc) == shifted
        assert shifted == expected_coord

    def test_era_choice_never_moves_a_valid_coordinate(self):
        # валидность/пустота сдвига тоже эра-независимы: предикат и сдвиг
        # отдают None irrespective of the era the record will be keyed under
        for coord in (MonthDay(7, 1, 28), IntercalaryDay(7, 1)):
            assert classify(coord, SHIFT_CUSTOM) is None
            assert shift_invalid(coord, SHIFT_CUSTOM) is None
            for is_bc in (False, True):
                assert SHIFT_CUSTOM.from_key(
                    SHIFT_CUSTOM.to_key(coord, is_bc), is_bc
                ) == coord


# ═════════════════════════════════════════════════════════════════════════
# C1 (wire-game-calendar-key-binding) task group 4 — форма отчёта о переносе
# невалидных координат (design D5): пустой отчёт, форма записи, отсутствие
# локализованных подписей и имён сущностей.  Домен обход шести таблиц не
# делает и БД не читает — чистый билдер получает готовые проверки с координатами
# и календарь параметром (у чистых функций активный accessor не читается).
# ═════════════════════════════════════════════════════════════════════════

class TestShiftReportOnValidData:
    """Сценарий «Пустой отчёт на валидных данных»: когда все проверяемые
    координаты валидны в переданном календаре, отчёт содержит ноль записей и
    нулевой счётчик переносов валидации."""

    VALID_CHECKS = [
        # (таблица, id строки, поле, координата, эра) — все валидны в SHIFT_CUSTOM
        ("campaign", 1, DateField.START, MonthDay(7, 1, 1), False),
        ("campaign", 1, DateField.END, MonthDay(7, 2, 10), False),
        ("world_date", 4, DateField.START, IntercalaryDay(7, 0), True),
    ]

    def test_all_valid_coordinates_give_an_empty_report(self):
        report = build_shift_report(self.VALID_CHECKS, SHIFT_CUSTOM)
        assert report.records == ()          # ноль записей
        assert report.shift_count == 0       # и нулевой счётчик переносов

    def test_no_checks_at_all_give_an_empty_report(self):
        report = build_shift_report((), SHIFT_STANDARD)
        assert report.records == ()
        assert report.shift_count == 0


class TestShiftReportRecordForm:
    """Сценарий «Форма записи отчёта»: невалидная координата начала сдвинута —
    отчёт содержит запись с полем ``start``, обеими координатами с эрами и кодом
    причины, без имени сущности."""

    def test_shifted_start_yields_one_record_with_both_coords_and_reason(self):
        shift_invalid(MonthDay(7, 1, 31), SHIFT_CUSTOM)  # sanity: это невалидно
        report = build_shift_report(
            [("event", 42, DateField.START, MonthDay(7, 1, 31), True)], SHIFT_CUSTOM
        )
        assert report.shift_count == 1 == len(report.records)
        (record,) = report.records
        assert record.table == "event"
        assert record.row_id == 42
        assert record.field is DateField.START
        assert record.old == (MonthDay(7, 1, 31), True)   # старая координата + эра
        assert record.new == (MonthDay(7, 1, 28), True)   # новая координата + эра сохранена
        assert record.reason is ShiftReason.DAY_OVERFLOW
        # старая координата genuinely отсутствовала, новая — адресна (обе эры)
        assert SHIFT_CUSTOM.is_valid(record.old[0]) is False
        assert SHIFT_CUSTOM.is_valid(record.new[0]) is True
        for is_bc in (False, True):
            key = SHIFT_CUSTOM.to_key(record.new[0], is_bc)
            assert SHIFT_CUSTOM.from_key(key, is_bc) == record.new[0]

    def test_report_covers_all_three_reasons_and_valid_rows_are_skipped(self):
        report = build_shift_report(
            [
                ("event", 1, DateField.START, MonthDay(7, 1, 31), False),  # день_overflow
                ("event", 1, DateField.END, MonthDay(7, 3, 5), True),      # месяц_вне_числа
                ("event", 2, DateField.END, IntercalaryDay(7, 9), False),  # индекс_вставного
                ("event", 3, DateField.START, MonthDay(7, 1, 5), False),   # валид — пропускается
            ],
            SHIFT_CUSTOM,
        )
        assert [record.field for record in report.records] == [
            DateField.START, DateField.END, DateField.END,
        ]
        assert [record.reason for record in report.records] == [
            ShiftReason.DAY_OVERFLOW,
            ShiftReason.MONTH_OUT_OF_RANGE,
            ShiftReason.INTERCALARY_INDEX_OUT_OF_RANGE,
        ]
        assert [record.new for record in report.records] == [
            (MonthDay(7, 1, 28), False),
            (MonthDay(7, 2, 10), True),      # эра True сохранена на новой координате
            (IntercalaryDay(7, 1), False),
        ]
        assert report.shift_count == len(report.records) == 3


class TestShiftReportCarriesNoCaptionsOrNames:
    """Требование «не содержать локализованных подписей и имён сущностей»:
    запись — ровно шесть машинных полей D5, frozen, значения — машинные коды."""

    SAMPLE = ShiftReportEntry(
        "event", 1, DateField.START,
        (MonthDay(7, 1, 31), False), (MonthDay(7, 1, 28), False),
        ShiftReason.DAY_OVERFLOW,
    )

    def test_record_exposes_exactly_the_six_machine_fields(self):
        assert {f.name for f in fields(ShiftReportEntry)} == {
            "table", "row_id", "field", "old", "new", "reason",
        }

    def test_record_is_frozen(self):
        with pytest.raises(FrozenInstanceError):
            self.SAMPLE.field = DateField.END      # type: ignore[misc]

    def test_field_and_reason_are_machine_codes_not_captions(self):
        assert self.SAMPLE.field.value == "start"          # ∈ {start, end}
        assert self.SAMPLE.reason.value == "день_overflow"  # стабильный код D5
        assert isinstance(self.SAMPLE.table, str)          # машинный id таблицы обхода
        assert isinstance(self.SAMPLE.row_id, int)         # машинный id строки

    def test_report_of_entries_is_frozen_and_counts_shifts(self):
        report = ShiftReport(records=(self.SAMPLE,))
        assert report.shift_count == 1
        with pytest.raises(FrozenInstanceError):
            report.records = ()                  # type: ignore[misc]


# ── Task 8.3 — приёмочная карта: сценарий delta-спека → зелёный тест ─────
#
# «Круговой обход всех видов дней»      → TestCeArithmeticRoundTrip::
#         test_full_year_sweep_round_trips_and_is_strictly_monotonic,
#         TestGiantSpecs::test_month_edges_and_intercalaries_round_trip,
#         TestBcMirrorOrder::test_full_bc_scale_is_contiguous_under_zero_and_round_trips,
#         TestFuzzCoreProperties::test_circular_sweep_round_trips_in_both_eras
# «Один слот — одна дата»               → TestCeArithmeticRoundTrip::
#         test_full_year_sweep_round_trips_and_is_strictly_monotonic (уникальность и
#         непрерывность ключей года), TestBcMirrorOrder::test_every_bc_key_precedes_every_ad_key,
#         TestFuzzCoreProperties::test_keys_are_strictly_monotonic_contiguous_and_era_separated
# «Совпадение со старым ключом на границах» → TestStandardGoldMatchWithEraKey::
#         test_boundary_keys_equal_live_era_key_in_both_eras,
#         test_fixed_seed_random_sample_of_both_eras_matches_era_key,
#         test_month_boundary_neighbours_stay_one_key_apart
# «Неравномерные месяцы»                → TestScenarioUnevenMonths::
#         test_three_lengths_hold_every_year_and_corner_sweep_round_trips
#         (плюс произвольные гиганты TestGiantSpecs)
# «Эра не меняет строение»              → TestEraDoesNotChangeStructure (все три теста)
# «Соседи не сдвигаются»                → TestIntercalaryOutsideWeekCycle (все четыре теста),
#         TestFuzzCoreProperties::test_intercalary_days_have_no_weekday_and_never_shift_neighbours
# «Несколько вставных дней подряд»      → TestIntercalarySlots::
#         test_slots_follow_host_in_list_order_with_round_trip,
#         test_consecutive_after_same_host_get_consecutive_keys,
#         test_every_intercalary_of_a_fat_year_round_trips
# «Одиннадцатидневная неделя через границы» → TestWeekdayAnchorAndCycle::
#         test_eleven_named_week_cycles_gaplessly_over_month_edges,
#         test_eleven_named_week_continues_strictly_over_year_boundaries
#         (требование целиком: якорь — test_anchor_first_day_of_first_month_of_first_year_is_index_zero,
#         якорь не в ключе — TestAnchorNotInTheKey, std из григорианского —
#         TestStandardWeekdayAndNoIntercalary::test_weekday_is_gregorian_of_the_mirrored_same_year_date)
# «Строгость BC-зеркала»                → TestBcMirrorOrder::
#         test_two_adjacent_bc_years_sweep_monotonically_and_contiguously,
#         test_full_bc_scale_is_contiguous_under_zero_and_round_trips (вся шкала 1…9999),
#         test_every_bc_key_precedes_every_ad_key
# «Пустое имя — отказ»                  → TestSpecRejectionTable (id
#         «empty-name-and-week-too-short-both-reported» — обе причины сразу),
#         TestCustomCalendarConstructor::test_invalid_spec_raises_value_error_listing_every_reason
# «Гибкость без продуктовых границ»     → TestFlexibleSpecsAccepted
#         (ids «500-months-by-10-days», «single-month-99999-days»),
#         TestInt64Guard (границы физической причины)
# «День, которого нет»                  → TestInvalidCoordinates::
#         test_month_day_outside_spec_is_invalid_and_refused (31-е в 30-дневном),
#         test_wrong_day_is_never_silently_clamped (стандартный пресет —
#         TestStandardInvalidCoordinates)
# «Предпросмотр видит вставной день»    → TestScenarioPreviewSeesPlateAfterSecondMonth::
#         test_plate_after_second_month_and_next_month_weeks_unshifted,
#         TestYearPreviewSnapshot::test_small_spec_with_two_intercalary_days_renders_exactly,
#         TestYearPreviewMatchesArithmetic::test_weeks_after_the_host_month_continue_unshifted

# ═════════════════════════════════════════════════════════════════════════
# C2 (wire-game-calendar-settings) task group 1 — источник имён месяцев
# (spec «Источник имён месяцев») и кодек хранения (spec
# «Календарь-настройки хранятся в базе игры», design D1)
# ═════════════════════════════════════════════════════════════════════════

GREGORIAN_NAMES = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}


class TestMonthNamesSource:
    """C2 task 1.1 / spec «Источник имён месяцев»: имена месяцев —
    неотъемлемая часть календаря (дефолт и переопределение пресета, спека
    кастома) и меняют только подписи дат, никогда — ключи."""

    PROBE_COORDS = [
        pytest.param(MonthDay(1, 1, 1), id="epoch"),
        pytest.param(MonthDay(44, 6, 15), id="mid-era"),
        pytest.param(MonthDay(2024, 2, 29), id="leap-feb-29"),
        pytest.param(MonthDay(9999, 12, 31), id="last-day-of-era"),
    ]

    def test_default_names_are_the_gregorian_dictionary(self):
        # перенесённый из date_utils словарь — теперь единоличная правда домена
        assert dict(DEFAULT_MONTH_NAMES) == GREGORIAN_NAMES
        assert dict(StandardCalendar().month_names) == GREGORIAN_NAMES

    def test_name_tables_are_read_only(self):
        with pytest.raises(TypeError):
            DEFAULT_MONTH_NAMES[1] = "Снежень"                # type: ignore[index]
        with pytest.raises(TypeError):
            StandardCalendar().month_names[7] = "Грозень"     # type: ignore[index]
        with pytest.raises(TypeError):
            CustomCalendar(base_spec()).month_names[1] = "Снежень"  # type: ignore[index]

    def test_preset_override_merges_over_the_defaults(self):
        # сценарий «Пресет с переопределением имён», первая половина:
        # переопределённый месяц отдаёт новое имя, забытые — григорианские
        renamed = StandardCalendar(month_names={3: "Медвежарь"})
        assert renamed.month_names[3] == "Медвежарь"
        assert renamed.month_names[1] == "Январь"
        assert renamed.month_names[12] == "Декабрь"

    @pytest.mark.parametrize("coord", PROBE_COORDS)
    @pytest.mark.parametrize("is_bc", [False, True], ids=["ad", "bc"])
    def test_override_relabels_captions_and_leaves_every_key_intact(self, coord, is_bc):
        # сценарий «Пресет с переопределением имён», вторая половина:
        # ключи всех координат обеих эр побитово равны ключам пресета
        # без переопределения (и обратный ход, и структура не тронуты)
        plain = StandardCalendar()
        renamed = StandardCalendar(month_names={3: "Медвежарь"})
        key = plain.to_key(coord, is_bc)
        assert renamed.to_key(coord, is_bc) == key
        assert renamed.from_key(key, is_bc) == coord
        assert renamed.month_length(coord.year, coord.month) == \
            plain.month_length(coord.year, coord.month)
        assert renamed.weekday(coord) == plain.weekday(coord)

    def test_custom_names_come_from_the_spec_in_month_order(self):
        # сценарий «Имена кастомного календаря — из спеки»
        calendar = CustomCalendar(base_spec())
        assert dict(calendar.month_names) == {
            1: "Зимостой", 2: "Талолист", 3: "Сухочивень",
        }

    def test_custom_names_follow_spec_order_and_ignore_intercalary(self):
        spec = base_spec(
            months=make_months(("Первый", 3), ("Второй", 4), ("Третий", 5)),
            intercalary=(IntercalarySpec("Гром", 2),),
        )
        calendar = CustomCalendar(spec)
        assert dict(calendar.month_names) == {
            1: "Первый", 2: "Второй", 3: "Третий",
        }  # вставные имена — не месяцы, их здесь нет

    def test_protocol_exposes_month_names_as_a_bodyless_property(self):
        # протокол (D2) даёт только контракт: член C2 — безвредная заглушка
        # наравне с методами протокола (строки-«тело-многоточие» считает
        # CI-гейт построчного покрытия)
        assert isinstance(GameCalendar.month_names, property)
        assert GameCalendar.month_names.fget(object()) is None
        assert isinstance(StandardCalendar(), GameCalendar)
        assert isinstance(CustomCalendar(base_spec()), GameCalendar)

    def test_namesless_calendar_no_longer_satisfies_the_runtime_protocol(self):
        # заглушка-предшественник имён не знает — расширенный протокол её
        # больше не пропускает (member проверяется isinstance'ом runtime)
        assert not isinstance(StubCalendar(), GameCalendar)


# ── кодек хранения: стандартный пресет (design D1) ──────────────────────


class TestCodecStandardPreset:
    """C2 task 1.2 / сценарий «Пресет с переименованными месяцами» +
    дизайн-нормализация «пустой словарь имён → нет поля»."""

    def test_plain_preset_encodes_without_any_payload_fields(self):
        assert json.loads(encode_calendar(StandardCalendar())) == {
            "v": 1, "kind": "standard",
        }

    def test_empty_or_default_equal_override_normalizes_to_no_field(self):
        # «про запас» не пишем: пустое переопределение и переопределение,
        # побайтово равное дефолту, не порождают поля month_names
        all_default = {number: DEFAULT_MONTH_NAMES[number] for number in range(1, 13)}
        for names in ({}, {5: "Май"}, all_default):
            payload = json.loads(encode_calendar(StandardCalendar(month_names=names)))
            assert "month_names" not in payload
            assert payload == {"v": 1, "kind": "standard"}

    def test_override_is_written_as_string_month_numbers(self):
        raw = encode_calendar(StandardCalendar(month_names={3: "Медвежарь"}))
        assert json.loads(raw) == {
            "v": 1,
            "kind": "standard",
            "month_names": {"3": "Медвежарь"},
        }
        assert "\\u" not in raw  # ensure_ascii=False — кириллица ложится как есть

    def test_plain_preset_round_trips_to_the_default_names(self):
        decoded = decode_calendar(encode_calendar(StandardCalendar()))
        assert isinstance(decoded, CalendarDecoded)
        assert decoded.calendar.month_names == DEFAULT_MONTH_NAMES

    def test_override_round_trip_keeps_names_and_keys(self):
        original = StandardCalendar(month_names={3: "Медвежарь"})
        decoded = decode_calendar(encode_calendar(original))
        assert isinstance(decoded, CalendarDecoded)
        restored = decoded.calendar
        assert restored.month_names == original.month_names
        for is_bc in (False, True):
            for coord in (MonthDay(2024, 3, 9), MonthDay(1, 1, 1)):
                assert restored.to_key(coord, is_bc) == original.to_key(coord, is_bc)


# ── кодек хранения: кастомная спека, круговой проход ────────────────────


CODEC_SPEC = base_spec(
    months=make_months(("Зимостой", 30), ("Талолист", 50), ("Сухочивень", 20)),
    week_names=BASE_WEEK,
    intercalary=(
        IntercalarySpec("Гром", 2),
        IntercalarySpec("Эхо", 2),
        IntercalarySpec("Тишина", 3),
    ),
)  # все три facet'а спеки сразу: месяцы разной длины, неделя, правила при хостах


class TestCodecCustomRoundTrip:
    """C2 task 1.2 / сценарий «Круговой проход через хранилище»: сохранённая
    спека равна прочитанной, ключи совпадают побитово."""

    def test_full_spec_fields_are_written_one_for_one(self):
        raw = json.loads(encode_calendar(CustomCalendar(CODEC_SPEC)))
        assert raw == {
            "v": 1,
            "kind": "custom",
            "months": [
                {"name": "Зимостой", "length": 30},
                {"name": "Талолист", "length": 50},
                {"name": "Сухочивень", "length": 20},
            ],
            "week_names": ["Восход", "Тень", "Полдень", "Закат"],
            "intercalary": [
                {"name": "Гром", "after_month": 2},
                {"name": "Эхо", "after_month": 2},
                {"name": "Тишина", "after_month": 3},
            ],
        }

    def test_saved_spec_is_equal_to_the_read_one(self):
        original = CustomCalendar(CODEC_SPEC)
        decoded = decode_calendar(encode_calendar(original))
        assert isinstance(decoded, CalendarDecoded)
        restored = decoded.calendar
        assert isinstance(restored, CustomCalendar)
        assert restored.spec == original.spec == CODEC_SPEC

    def test_restored_calendar_keys_are_bit_identical_in_both_eras(self):
        original = CustomCalendar(CODEC_SPEC)
        decoded = decode_calendar(encode_calendar(original))
        restored = decoded.calendar
        probes = [
            MonthDay(1, 1, 1), MonthDay(44, 2, 50), MonthDay(9999, 3, 20),
            IntercalaryDay(44, 0), IntercalaryDay(44, 1), IntercalaryDay(9999, 2),
        ]
        for coord in probes:
            for is_bc in (False, True):
                key = original.to_key(coord, is_bc)
                assert restored.to_key(coord, is_bc) == key
                assert restored.from_key(key, is_bc) == coord

    def test_empty_intercalary_round_trips_as_empty(self):
        original = CustomCalendar(base_spec())  # intercalary = ()
        decoded = decode_calendar(encode_calendar(original))
        assert decoded.calendar.spec.intercalary == ()

    def test_encode_is_deterministic_across_a_decode_cycle(self):
        raw_once = encode_calendar(CustomCalendar(CODEC_SPEC))
        decoded = decode_calendar(raw_once)
        assert encode_calendar(decoded.calendar) == raw_once


# ── кодек хранения: повреждённые значения никогда не бросают ────────────

CODEC_CORRUPT_CASES = [
    # ── битый JSON ────────────────────────────────────────────────────────
    pytest.param("{not json at all", {"corrupt_json"}, id="broken-json"),
    pytest.param("", {"corrupt_json"}, id="empty-string"),
    pytest.param(None, {"corrupt_json"}, id="value-is-not-a-string"),
    # ── распарсилось, но это не объект-календаря ──────────────────────────
    pytest.param("[1, 2]", {"corrupt_shape"}, id="json-array-not-object"),
    pytest.param('"просто строка"', {"corrupt_shape"}, id="json-string-not-object"),
    # ── версия формата ────────────────────────────────────────────────────
    pytest.param('{"kind": "standard"}', {"unknown_version"}, id="missing-v"),
    pytest.param('{"v": 2, "kind": "standard"}', {"unknown_version"}, id="future-v"),
    pytest.param('{"v": 0, "kind": "custom"}', {"unknown_version"}, id="zero-v"),
    # ── дискриминатор kind ────────────────────────────────────────────────
    pytest.param('{"v": 1}', {"corrupt_shape"}, id="missing-kind"),
    pytest.param('{"v": 1, "kind": "lunar"}', {"corrupt_shape"}, id="unknown-kind"),
    # ── standard: битый month_names ───────────────────────────────────────
    pytest.param(
        '{"v": 1, "kind": "standard", "month_names": []}',
        {"corrupt_shape"}, id="names-not-an-object",
    ),
    pytest.param(
        '{"v": 1, "kind": "standard", "month_names": {"3": 7}}',
        {"corrupt_shape"}, id="name-is-not-a-string",
    ),
    pytest.param(
        '{"v": 1, "kind": "standard", "month_names": {"январь": "X"}}',
        {"corrupt_shape"}, id="name-key-is-not-a-month-number",
    ),
    # ── custom: поля не списки ────────────────────────────────────────────
    pytest.param(
        '{"v": 1, "kind": "custom", "week_names": [], "intercalary": []}',
        {"corrupt_shape"}, id="custom-without-months",
    ),
    pytest.param(
        '{"v": 1, "kind": "custom", "months": {}, "week_names": [], "intercalary": []}',
        {"corrupt_shape"}, id="months-is-not-a-list",
    ),
    # ── custom: битые записи month/week/intercalary ───────────────────────
    pytest.param(
        '{"v": 1, "kind": "custom", "months": [30],'
        ' "week_names": ["a", "b"], "intercalary": []}',
        {"corrupt_shape"}, id="month-entry-is-not-an-object",
    ),
    pytest.param(
        '{"v": 1, "kind": "custom", "months": [{"name": 5, "length": 30}],'
        ' "week_names": ["a", "b"], "intercalary": []}',
        {"corrupt_shape"}, id="month-name-is-not-a-string",
    ),
    pytest.param(
        '{"v": 1, "kind": "custom", "months": [{"name": "x", "length": true}],'
        ' "week_names": ["a", "b"], "intercalary": []}',
        {"corrupt_shape"}, id="month-length-is-a-bool",
    ),
    pytest.param(
        '{"v": 1, "kind": "custom", "months": [{"name": "x", "length": 3}],'
        ' "week_names": [1], "intercalary": []}',
        {"corrupt_shape"}, id="week-name-is-not-a-string",
    ),
    pytest.param(
        '{"v": 1, "kind": "custom", "months": [{"name": "x", "length": 3}],'
        ' "week_names": ["a", "b"], "intercalary": [{"name": "Гром"}]}',
        {"corrupt_shape"}, id="intercalary-entry-without-host",
    ),
    pytest.param(
        '{"v": 1, "kind": "custom", "months": [{"name": "x", "length": 3}],'
        ' "week_names": ["a", "b"], "intercalary": [3]}',
        {"corrupt_shape"}, id="intercalary-entry-is-not-an-object",
    ),
]


class TestCodecCorruptedValue:
    """C2 task 1.2 / требование «Повреждённое значение календарь-ключа»,
    часть кодека: битое значение никогда не бросает — оно отдаёт полный
    список машинных причин (дальше их локализирует presentation, D4)."""

    @pytest.mark.parametrize(("raw", "expected_codes"), CODEC_CORRUPT_CASES)
    def test_broken_values_decode_to_corruption_not_exceptions(self, raw, expected_codes):
        result = decode_calendar(raw)
        assert isinstance(result, CalendarCorrupted)
        assert codes_of(result.reasons) == expected_codes

    def test_reasons_are_specproblem_shaped_machine_codes(self):
        result = decode_calendar('{"v": 1}')
        (reason,) = result.reasons
        assert isinstance(reason, SpecProblem)
        assert isinstance(reason.code, str) and reason.code
        assert isinstance(reason.message, str) and reason.message  # всегда есть деталь

    def test_broken_custom_spec_reports_kernel_validation_reason(self):
        # сценарий «Битая кастомная спека»: вставной день ссылается на
        # несуществующий месяц — причина из валидации ядра, не заглушка
        result = decode_calendar(
            '{"v": 1, "kind": "custom",'
            ' "months": [{"name": "Короткий", "length": 5}],'
            ' "week_names": ["а", "б"],'
            ' "intercalary": [{"name": "Гром", "after_month": 2}]}'
        )
        assert isinstance(result, CalendarCorrupted)
        assert codes_of(result.reasons) == {"intercalary_unknown_month"}

    def test_kernel_reports_every_spec_reason_not_only_the_first(self):
        # полный список причин D6 проходит через кодек без потерь
        result = decode_calendar(
            '{"v": 1, "kind": "custom",'
            ' "months": [{"name": "", "length": 0}],'
            ' "week_names": ["а"],'
            ' "intercalary": []}'
        )
        assert isinstance(result, CalendarCorrupted)
        assert codes_of(result.reasons) == {
            "empty_month_name", "month_length_below_min", "week_too_short",
        }

    def test_encode_refuses_a_calendar_without_a_storage_shape(self):
        # третий реализатор протокола храниться пока не умеет (D1: форма
        # есть только у пресета и кастома; мастер — C4)
        with pytest.raises(TypeError):
            encode_calendar(StubCalendar())


# ═════════════════════════════════════════════════════════════════════════
# C3a (wire-game-calendar-coordinates) task group 1.1 — доменный кодек
# координаты: spec «Доменный кодек хранимого представления координаты»
# и design D2: инъективный точный цикл "M:год:месяц:день" / "I:год:индекс",
# машиночитаемые причины вместо исключений, существование проверяет не
# кодек, а чистая политика сдвига
# ═════════════════════════════════════════════════════════════════════════

COORD_SWEEP_SPEC = base_spec(
    intercalary=(IntercalarySpec("Гром", 2), IntercalarySpec("Маска", 3)),
)  # 30+50+20 дней + два вставных: году есть и координаты рода M, и рода I


class TestCoordCodecExactCycle:
    """C3a task 1.1 / сценарий «Точный цикл координаты»: декодирование
    результата возвращает ровно ту же координату обоих родов; эра в текст не
    входит (D3), а ключ каждой эры переживает цикл побитово."""

    ROUND_TRIP_COORDS = [
        pytest.param(MonthDay(1, 1, 1), id="ad-epoch"),
        pytest.param(MonthDay(44, 3, 5), id="bc-year-44"),
        pytest.param(MonthDay(2024, 2, 29), id="leap-feb-29"),
        pytest.param(MonthDay(9999, 12, 31), id="last-day-of-scale"),
        pytest.param(IntercalaryDay(1, 0), id="first-intercalary"),
        pytest.param(IntercalaryDay(44, 2), id="bc-intercalary"),
        pytest.param(IntercalaryDay(9999, 12), id="far-index"),
    ]

    @pytest.mark.parametrize("coord", ROUND_TRIP_COORDS)
    def test_cycle_returns_exactly_the_original_coordinate(self, coord):
        text = encode_coord(coord)
        decoded = decode_coord(text)
        assert isinstance(decoded, CoordDecoded)
        assert decoded.coord == coord
        # канон без ведущих нулей и лишних полей фиксируется round-trip'ом
        assert encode_coord(decoded.coord) == text

    @pytest.mark.parametrize(
        "coord",
        [
            pytest.param(MonthDay(1, 1, 1), id="ad-epoch"),
            pytest.param(MonthDay(44, 3, 5), id="bc-year-44"),
            pytest.param(MonthDay(2024, 2, 29), id="leap-feb-29"),
            pytest.param(MonthDay(9999, 12, 31), id="last-day-of-scale"),
        ],
    )
    @pytest.mark.parametrize("is_bc", [False, True], ids=["ad", "bc"])
    def test_both_era_keys_survive_the_cycle_under_the_preset(self, coord, is_bc):
        # текста на оба применения одинаков — эру различает только to_key
        preset = StandardCalendar()
        key = preset.to_key(coord, is_bc)
        restored = decode_coord(encode_coord(coord)).coord
        assert preset.to_key(restored, is_bc) == key
        assert preset.from_key(key, is_bc) == restored

    def test_intercalary_key_survives_the_cycle_under_custom(self):
        custom = CustomCalendar(COORD_SWEEP_SPEC)
        coord = IntercalaryDay(44, 1)
        for is_bc in (False, True):
            key = custom.to_key(coord, is_bc)
            restored = decode_coord(encode_coord(coord)).coord
            assert custom.to_key(restored, is_bc) == key
            assert custom.from_key(key, is_bc) == restored

    def test_text_is_the_discriminated_plain_number_format(self):
        # design D2: дискриминатор рода + десятичные числа как есть
        assert encode_coord(MonthDay(44, 3, 5)) == "M:44:3:5"
        assert encode_coord(MonthDay(1, 1, 1)) == "M:1:1:1"
        assert encode_coord(IntercalaryDay(44, 0)) == "I:44:0"
        assert set(encode_coord(MonthDay(9999, 12, 31))) <= set(".-:0123456789M")
        assert "is_bc" not in inspect.signature(encode_coord).parameters

    def test_leading_zeros_parse_but_the_encoding_stays_canonical(self):
        # рукописная правка базы переживёт чтение, а повторная запись
        # вернётся каноническим текстом того же round-trip'а
        decoded = decode_coord("M:044:03:05")
        assert isinstance(decoded, CoordDecoded)
        assert decoded.coord == MonthDay(44, 3, 5)
        assert encode_coord(decoded.coord) == "M:44:3:5"


class TestCoordCodecInjective:
    """C3a task 1.1 / тот же сценарий, вторая половина: разные координаты
    дают разные тексты — ловушки «цифры переехали между полями» и оба рода
    сразу не сталкиваются."""

    COLLISION_TRAPS = [
        MonthDay(1, 11, 1), MonthDay(11, 1, 1), MonthDay(1, 1, 11),
        MonthDay(2, 2, 2), MonthDay(22, 2, 2), MonthDay(2, 22, 2),
        MonthDay(4, 4, 4), MonthDay(44, 4, 4), MonthDay(4, 44, 44),
        IntercalaryDay(1, 0), IntercalaryDay(10, 0), IntercalaryDay(1, 10),
        IntercalaryDay(11, 1), IntercalaryDay(111, 1),
        MonthDay(1, 1, 1), MonthDay(11, 11, 11),
    ]

    def test_neighbours_by_digits_never_share_a_text(self):
        # цифры, переехавшие между полями, и разные роды при равных числах
        # обязаны давать разные тексты
        unique_coords = list(dict.fromkeys(self.COLLISION_TRAPS))
        texts = [encode_coord(coord) for coord in unique_coords]
        assert len(set(texts)) == len(unique_coords)

    def test_full_custom_year_sweep_is_pairwise_distinct_and_round_trips(self):
        # весь год кастома разом: рow M-координат месяцами + все вставные слоты
        custom = CustomCalendar(COORD_SWEEP_SPEC)
        base = custom.to_key(MonthDay(44, 1, 1))
        coords = [custom.from_key(base + offset) for offset in range(custom.year_length)]
        assert len(coords) == custom.year_length == 102
        assert len(set(coords)) == len(coords)
        texts = [encode_coord(coord) for coord in coords]
        assert len(set(texts)) == len(coords)  # сценарий: разные координаты → разные тексты
        for coord, text in zip(coords, texts):
            decoded = decode_coord(text)
            assert isinstance(decoded, CoordDecoded)
            assert decoded.coord == coord


class TestCoordCodecCorruptedText:
    """C3a task 1.1 / сценарий «Чужой текст отвечает причинами»: ни один
    неразбираемый текст не бросает — только полный набор машинных причин по
    образцу календарь-кодека (SpecProblem, не локалиzaция)."""

    CORRUPT_CASES = [
        pytest.param("", {"empty_coord"}, id="empty-text"),
        pytest.param(None, {"not_a_string"}, id="value-is-not-a-string"),
        pytest.param(404, {"not_a_string"}, id="value-is-a-number"),
        # ── без дискриминатора рода / неизвестный дискриминатор ──────────
        pytest.param("44:3:5", {"unknown_kind"}, id="missing-kind-discriminator"),
        pytest.param("сорок четыре", {"unknown_kind"}, id="no-separator-at-all"),
        pytest.param("L:44:3:5", {"unknown_kind"}, id="unknown-kind"),
        pytest.param("m:44:3:5", {"unknown_kind"}, id="case-is-significant"),
        pytest.param(":44:3:5", {"unknown_kind"}, id="empty-kind"),
        # ── неполный текст ────────────────────────────────────────────────
        pytest.param("M:44:3", {"incomplete_coord"}, id="month-day-missing-field"),
        pytest.param("I:44", {"incomplete_coord"}, id="intercalary-missing-index"),
        pytest.param("M:", {"incomplete_coord", "non_numeric_field"},
                     id="incomplete-and-non-numeric-together"),
        # ── нечисловые поля ───────────────────────────────────────────────
        pytest.param("M:a:b:c", {"non_numeric_field"}, id="all-fields-non-numeric"),
        pytest.param("M:44:x:5", {"non_numeric_field"}, id="month-is-not-a-number"),
        pytest.param("I:44:второй", {"non_numeric_field"}, id="index-is-not-a-number"),
        pytest.param("M:::", {"non_numeric_field"}, id="all-fields-empty"),
        # ── лишние поля ───────────────────────────────────────────────────
        pytest.param("M:44:3:5:9", {"too_many_fields"}, id="extra-field"),
    ]

    @pytest.mark.parametrize(("raw", "expected_codes"), CORRUPT_CASES)
    def test_strange_texts_answer_reasons_not_exceptions(self, raw, expected_codes):
        result = decode_coord(raw)
        assert isinstance(result, CoordCorrupted)
        assert codes_of(result.reasons) == expected_codes
        assert all(isinstance(problem, SpecProblem) for problem in result.reasons)

    @pytest.mark.parametrize(("raw", "expected_codes"), CORRUPT_CASES)
    def test_every_reason_carries_a_detail_message(self, raw, expected_codes):
        result = decode_coord(raw)
        assert result.reasons  # причин хотя бы одна
        for problem in result.reasons:
            assert isinstance(problem.code, str) and problem.code
            assert isinstance(problem.message, str) and problem.message

    def test_encode_refuses_a_value_that_is_not_a_coordinate(self):
        # вне двух D3-родов хранимой формы нет — по образцу encode_calendar
        with pytest.raises(TypeError):
            encode_coord(date(2026, 9, 20))
        with pytest.raises(TypeError):
            encode_coord("M:1:1:1")


class TestCoordCodecResultShapes:
    """Среза результатов кодекса — те же frozen-доменные формы, что у
    календарь-кодека (design D2 «тот же контракт»)."""

    def test_decoded_exposes_only_the_coordinate_and_is_frozen(self):
        assert {f.name for f in fields(CoordDecoded)} == {"coord"}
        result = CoordDecoded(MonthDay(1, 1, 1))
        with pytest.raises(FrozenInstanceError):
            result.coord = MonthDay(2, 1, 1)  # type: ignore[misc]

    def test_corrupted_exposes_only_reasons_and_is_frozen(self):
        assert {f.name for f in fields(CoordCorrupted)} == {"reasons"}
        result = decode_coord("M:44:3")
        assert isinstance(result, CoordCorrupted)
        with pytest.raises(FrozenInstanceError):
            result.reasons = ()  # type: ignore[misc]


class TestCoordCodecNeverChecksExistence:
    """C3a task 1.1: кодек отвечает за разбор и форму, существование — дело
    чистой политики сдвига (spec «Доменный кодек…»)."""

    NONEXISTENT_COORDS = [
        pytest.param(MonthDay(2026, 13, 40), id="month-13-day-40"),
        pytest.param(MonthDay(44, 0, 0), id="zero-month-and-day"),
        pytest.param(IntercalaryDay(44, 99), id="index-beyond-any-spec"),
        pytest.param(MonthDay(0, 99, 99), id="year-zero-absurd-fields"),
    ]

    @pytest.mark.parametrize("coord", NONEXISTENT_COORDS)
    def test_absurd_coordinates_still_round_trip_exactly(self, coord):
        # ни один календарь в декод не заглядывает: ровно та же координата
        assert decode_coord(encode_coord(coord)).coord == coord

    def test_existence_judges_the_policy_not_the_codec(self):
        coord = MonthDay(2026, 13, 40)
        assert decode_coord(encode_coord(coord)).coord == coord  # кодек принял
        with pytest.raises(InvalidGameDateError):
            StandardCalendar().to_key(coord)                     # ядро отказало
        assert classify(coord, StandardCalendar()) is ShiftReason.MONTH_OUT_OF_RANGE
        assert shift_invalid(coord, StandardCalendar())[0] == MonthDay(2026, 12, 31)


# ── C4: черновик мастера (task 4.1, design D6) ────────────────────────────


#: Спека-сквозняк: та же форма, что пишет основной ключ kind=custom, но с
#: вставным днём — черновик обязан нести все три facet'а без потерь.
DRAFT_SPEC = base_spec(
    months=make_months(("Черновершь", 12), ("Разливань", 18)),
    week_names=("Буд", "Ведь", "Творец", "Грозник", "Светлай"),
    intercalary=(IntercalarySpec("Гром", 1),),
)


def draft_body(spec: CalendarSpec, stage: str = DRAFT_STAGE_MONTHS, **envelope) -> dict:
    """Собрать JSON-конверт черновика: тело спеки отдаёт основной кодек,
    чтобы тесты битого черновика говорили на том же формате, что пишет app."""
    payload = {
        "v": CALENDAR_DRAFT_VERSION,
        "spec": json.loads(encode_calendar(CustomCalendar(spec))),
        "stage": stage,
    }
    payload.update(envelope)
    return payload


class TestDraftCodecRoundTrip:
    """Круговой проход design D6: версия + спека + индекс ступени возвращаются
    ровно теми же, а тело спеки побайтово совпадает с телом основного ключа."""

    def test_envelope_shape_is_version_spec_and_stage(self):
        raw = encode_draft(CalendarDraft(spec=DRAFT_SPEC, stage=DRAFT_STAGE_MONTHS))
        payload = json.loads(raw)
        assert payload == {
            "v": CALENDAR_DRAFT_VERSION,
            "spec": json.loads(encode_calendar(CustomCalendar(DRAFT_SPEC))),
            "stage": DRAFT_STAGE_MONTHS,
        }
        assert "\\u" not in raw  # ensure_ascii=False — спека читается глазами

    @pytest.mark.parametrize("stage", DRAFT_STAGES)
    def test_every_stage_survives_the_cycle(self, stage):
        draft = CalendarDraft(spec=DRAFT_SPEC, stage=stage)
        decoded = decode_draft(encode_draft(draft))
        assert isinstance(decoded, DraftDecoded)
        assert decoded.draft == draft

    def test_custom_body_rides_inside_the_draft_byte_identical(self):
        # «то же тело, что у custom-значения game_calendar» — переиспользование
        # encode_calendar/decode_calendar, а не второй формат хранения
        draft = CalendarDraft(spec=DRAFT_SPEC, stage=DRAFT_STAGE_WEEK)
        inner = json.loads(encode_draft(draft))["spec"]
        assert encode_calendar(CustomCalendar(DRAFT_SPEC)) == json.dumps(
            inner, ensure_ascii=False
        )

    def test_round_trip_keys_are_bit_identical_in_both_eras(self):
        original = CustomCalendar(DRAFT_SPEC)
        decoded = decode_draft(encode_draft(CalendarDraft(original.spec, DRAFT_STAGE_PREVIEW)))
        assert isinstance(decoded, DraftDecoded)
        restored = CustomCalendar(decoded.draft.spec)
        for coord in (MonthDay(1, 1, 1), MonthDay(9999, 2, 18), IntercalaryDay(44, 0)):
            for is_bc in (False, True):
                key = original.to_key(coord, is_bc)
                assert restored.to_key(coord, is_bc) == key
                assert restored.from_key(key, is_bc) == coord

    def test_encode_is_deterministic_across_a_decode_cycle(self):
        raw_once = encode_draft(CalendarDraft(spec=DRAFT_SPEC, stage=DRAFT_STAGE_PREVIEW))
        decoded = decode_draft(raw_once)
        assert isinstance(decoded, DraftDecoded)
        assert encode_draft(decoded.draft) == raw_once

    def test_draft_and_main_key_are_the_separate_shapes(self):
        # основной ключ не содержит stage, черновик не умеет kind=standard —
        # перепутать их местами можно только написав JSON руками
        assert "stage" not in json.loads(encode_calendar(StandardCalendar()))
        draft = CalendarDraft(spec=base_spec(), stage=DRAFT_STAGE_WEEK)
        assert json.loads(encode_draft(draft))["spec"]["kind"] == "custom"

    def test_draft_form_is_a_frozen_pair_of_spec_and_stage(self):
        assert {f.name for f in fields(CalendarDraft)} == {"spec", "stage"}
        draft = CalendarDraft(spec=DRAFT_SPEC, stage=DRAFT_STAGE_WEEK)
        with pytest.raises(FrozenInstanceError):
            draft.spec = base_spec()  # type: ignore[misc]

    def test_stage_is_not_interpreted_beyond_being_a_known_marker(self):
        # индекс ступени — данные черновика, а не условие кодирования:
        # предпросмотр собирается из той же спеки, что и месяцы
        for stage in (DRAFT_STAGE_WEEK, DRAFT_STAGE_MONTHS, DRAFT_STAGE_PREVIEW):
            assert decode_draft(
                encode_draft(CalendarDraft(spec=base_spec(), stage=stage))
            ).draft.stage == stage


class TestDraftCodecWriteGuards:
    """Писатель строже читателя: в хранилище не попадает ни битая спека,
    ни неизвестная ступень — и то и другое拒绝 на глазах у мастера."""

    def test_unknown_stage_refuses_to_be_written(self):
        with pytest.raises(ValueError, match="unknown wizard draft stage"):
            encode_draft(CalendarDraft(spec=base_spec(), stage="interstice"))

    def test_invalid_spec_refuses_through_the_kernel_validation(self):
        broken = base_spec(
            months=make_months(("Первый", 5), ("Первый", 6)),
        )  # дубликат имени месяца — ядро reject'ит спеку целиком
        with pytest.raises(ValueError, match="duplicate month name"):
            encode_draft(CalendarDraft(spec=broken, stage=DRAFT_STAGE_MONTHS))


DRAFT_CORRUPT_CASES = [
    # ── битый конверт ──────────────────────────────────────────────────────
    pytest.param("{это не json", {"corrupt_json"}, id="broken-json"),
    pytest.param("", {"corrupt_json"}, id="empty-string"),
    pytest.param(None, {"corrupt_json"}, id="value-is-not-a-string"),
    pytest.param("[1, 2]", {"corrupt_shape"}, id="json-array-not-object"),
    pytest.param('"черновик"', {"corrupt_shape"}, id="json-string-not-object"),
    # ── версия формата черновика ──────────────────────────────────────────
    pytest.param(
        {"spec": {}, "stage": DRAFT_STAGE_WEEK}, {"unknown_version"}, id="missing-v"
    ),
    pytest.param(
        draft_body(base_spec(), v=2), {"unknown_version"}, id="future-v"
    ),
    # ── тело спеки ────────────────────────────────────────────────────────
    pytest.param(
        {"v": CALENDAR_DRAFT_VERSION, "stage": DRAFT_STAGE_WEEK},
        {"corrupt_shape"},
        id="no-spec-field",
    ),
    pytest.param(
        {"v": CALENDAR_DRAFT_VERSION, "spec": [], "stage": DRAFT_STAGE_WEEK},
        {"corrupt_shape"},
        id="spec-not-an-object",
    ),
    pytest.param(
        {"v": CALENDAR_DRAFT_VERSION, "spec": json.loads(encode_calendar(StandardCalendar())),
         "stage": DRAFT_STAGE_WEEK},
        {"corrupt_shape"},
        id="spec-is-the-standard-preset",
    ),
    # ── ступень ───────────────────────────────────────────────────────────
    pytest.param(
        {"v": CALENDAR_DRAFT_VERSION, "spec": json.loads(
            encode_calendar(CustomCalendar(base_spec())))},
        {"corrupt_shape"},
        id="no-stage-field",
    ),
    pytest.param(
        draft_body(base_spec(), stage="interstice"),
        {"corrupt_shape"},
        id="unknown-stage",
    ),
    pytest.param(
        draft_body(base_spec(), stage=3), {"corrupt_shape"}, id="stage-is-not-a-string"
    ),
]


class TestDraftCodecCorruptedDraft:
    """Требование «Битой черновик — как его нет»: кодекс никогда не бросает и
    отдаёт машинные причины, из которых вызывающий делает вывод «черновика
    нет» (сервис логирует, мастер начинает сызнова)."""

    @pytest.mark.parametrize(("raw", "expected_codes"), DRAFT_CORRUPT_CASES)
    def test_unreadable_values_answer_reasons_not_exceptions(self, raw, expected_codes):
        # dict/list-параметры — это заготовки конвертов; строка (и None)
        # уходит в кодекс как есть, ровно так, как их видит хранилище
        stored = json.dumps(raw) if isinstance(raw, (dict, list)) else raw
        result = decode_draft(stored)
        assert isinstance(result, DraftCorrupted)
        assert codes_of(result.reasons) == expected_codes
        assert all(
            isinstance(problem, SpecProblem)
            and problem.code
            and problem.message
            for problem in result.reasons
        )

    def test_uncodable_value_type_never_reaches_the_caller_as_a_crash(self):
        assert isinstance(decode_draft(None), DraftCorrupted)
        assert codes_of(decode_draft(None).reasons) == {"corrupt_json"}

    @pytest.mark.parametrize(
        ("spec", "expected_codes"),
        [
            pytest.param(
                base_spec(
                    months=make_months(("Первый", 3)),
                    intercalary=(IntercalarySpec("Гром", 2),),
                ),
                {"intercalary_unknown_month"},
                id="kernel-rejects-the-half-built-spec",
            ),
            pytest.param(
                base_spec(months=(), week_names=("а", "б")),
                {"no_months"},
                id="months-not-entered-yet",
            ),
            pytest.param(
                base_spec(
                    months=make_months(("", 5), ("Второй", -1)),
                    week_names=("а",),
                ),
                {"empty_month_name", "month_length_below_min", "week_too_short"},
                id="every-kernel-reason-survives",
            ),
        ],
    )
    def test_a_stored_but_invalid_spec_is_the_same_absence(self, spec, expected_codes):
        # валидация тела идёт тем же _decode_calendar_data, что и у основного
        # ключа: черновик не может «протащить» спеку, которую не принял бы он
        body = {
            "v": CALENDAR_DRAFT_VERSION,
            "spec": {
                "v": CALENDAR_STORAGE_VERSION,
                "kind": "custom",
                "months": [
                    {"name": m.name, "length": m.length} for m in spec.months
                ],
                "week_names": list(spec.week_names),
                "intercalary": [
                    {"name": r.name, "after_month": r.after_month}
                    for r in spec.intercalary
                ],
            },
            "stage": DRAFT_STAGE_MONTHS,
        }
        result = decode_draft(json.dumps(body))
        assert isinstance(result, DraftCorrupted)
        assert codes_of(result.reasons) == expected_codes


@pytest.fixture(params=[30, "M:44:3:5", object()], ids=["int", "coord-text", "object"])
def any_non_coord(request):
    """Anything that is neither a coordinate, nor a date, nor absence."""
    return request.param


class TestDraftCodecCorruptedValueBoundary:
    """Кодек черновика стоит поверх D3-координатного контракта: координата в
    спеке — не параметр, а часть тела, поэтому проверка рода координаты
    живёт в `as_game_coord`, которую черновик обязан унаследовать без мягкости
    (design D6: «spec — то же тело» ⇒ те же отказы)."""

    def test_non_coordinate_values_refuse_rather_than_become_days(
        self, any_non_coord
    ):
        with pytest.raises(TypeError):
            as_game_coord(any_non_coord)

    def test_dates_and_coordinates_pass_through_the_same_gate(self):
        assert as_game_coord(date(2024, 3, 9)) == MonthDay(2024, 3, 9)
        coord = MonthDay(44, 2, 1)
        assert as_game_coord(coord) is coord
        assert as_game_coord(None) is None  # absence is not a coordinate carrier
