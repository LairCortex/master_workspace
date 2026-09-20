"""Unit tests for era-aware date helpers — chronological key across the era
border, and (C3a task 1.2) the dispatcher's acceptance of game coordinates —
``datetime.date`` stays a special case of a month-day coordinate."""
from datetime import date
from types import SimpleNamespace

import pytest

from app.domain.date_era import (
    BC_YEAR_STEP,
    MAX_YEAR,
    MIN_YEAR,
    _gregorian_key,
    assert_range,
    cmp_era_dates,
    era_key,
)
from app.domain.game_calendar import (
    CalendarSpec,
    CustomCalendar,
    IntercalaryDay,
    IntercalarySpec,
    InvalidGameDateError,
    MonthDay,
    MonthSpec,
    reset_current_calendar,
    set_current_calendar,
)


# --- Ordering through the era border ---

class TestEraOrdering:
    def test_every_bc_date_precedes_every_our_era_date(self):
        assert cmp_era_dates((date(1, 1, 1), True), (date(1, 1, 1), False)) == -1
        assert era_key(date(1, 1, 1), True) < era_key(date(1, 1, 1), False)

    def test_mixed_era_sequence_is_chronologically_sorted(self):
        timeline = [
            (date(500, 1, 1), True),   # 500 г. до н.э.
            (date(44, 3, 5), True),    # 44 г. до н.э.
            (date(1, 12, 31), True),   # 1 г. до н.э.
            (date(1, 1, 1), False),    # 1 г. н.э.
            (date(44, 3, 5), False),   # 44 г. н.э.
            (date(2026, 9, 15), False),
        ]
        for earlier, later in zip(timeline, timeline[1:]):
            assert cmp_era_dates(earlier, later) == -1

    def test_bc_years_count_down_to_the_border(self):
        assert era_key(date(500, 6, 1), True) < era_key(date(44, 6, 1), True)

    def test_equal_pairs_compare_zero(self):
        assert cmp_era_dates((date(44, 3, 5), True), (date(44, 3, 5), True)) == 0
        assert cmp_era_dates((date(2026, 1, 1), False), (date(2026, 1, 1), False)) == 0

    def test_bc_key_matches_the_d2_formula(self):
        d = date(44, 3, 5)
        assert era_key(d, True) == d.toordinal() - BC_YEAR_STEP * d.year < 0
        assert era_key(d, False) == d.toordinal() > 0


# --- Mirrored leap years (BC calendar mirrors ours with the same year number) ---

class TestMirroredLeapYears:
    def test_bc_leap_day_orders_next_to_our_leap_day(self):
        assert_range(date(44, 2, 29), True)
        assert cmp_era_dates((date(44, 2, 28), True), (date(44, 2, 29), True)) == -1
        assert cmp_era_dates((date(44, 2, 29), True), (date(44, 3, 1), True)) == -1

    def test_bc_months_and_days_run_forward_within_bc_year(self):
        assert cmp_era_dates((date(44, 1, 1), True), (date(44, 12, 31), True)) == -1
        assert cmp_era_dates((date(44, 3, 5), True), (date(44, 3, 15), True)) == -1

    def test_bc_leap_day_stays_before_our_era(self):
        assert cmp_era_dates((date(44, 2, 29), True), (date(1, 1, 1), False)) == -1

    def test_common_year_has_no_mirrored_feb_29(self):
        with pytest.raises(ValueError):
            date(45, 2, 29)


# --- Range check 1…9999 of both eras, no year zero ---

class TestEraRange:
    @pytest.mark.parametrize("is_bc", [False, True])
    def test_boundary_years_are_accepted_in_both_eras(self, is_bc):
        assert_range(date(MIN_YEAR, 1, 1), is_bc)
        assert_range(date(MAX_YEAR, 12, 31), is_bc)

    def test_year_zero_is_rejected(self):
        with pytest.raises(ValueError):
            assert_range(SimpleNamespace(year=0), True)  # type: ignore[arg-type]

    def test_year_beyond_max_is_rejected(self):
        with pytest.raises(ValueError):
            assert_range(SimpleNamespace(year=MAX_YEAR + 1), False)  # type: ignore[arg-type]

    def test_datetime_itself_refuses_year_zero(self):
        with pytest.raises(ValueError):
            date(0, 1, 1)


# --- C3a task 1.2: диспетчер принимает координату, date — её частный случай ---

INTERCALARY_NEIGHBOUR_SPEC = CalendarSpec(
    months=(
        MonthSpec("Зимостой", 30),
        MonthSpec("Талолист", 50),
        MonthSpec("Сухочивень", 20),
    ),
    week_names=("Восход", "Тень", "Полдень", "Закат"),
    intercalary=(IntercalarySpec("День Маски", 1),),
)  # хост-месяц 1 не последний: у вставного дня есть сосед слева и справа


class TestEraKeyAcceptsGameCoord:
    """C3a task 1.2 / сценарий «Стандартные числа ключа сохранены»: координата
    обычного дня проходит через тот же диспетчер и даёт побитово те же числа
    пресета, что и прежний вызов с ``date`` (spec «Хронологический ключ…»)."""

    GOLD_DATES = [
        pytest.param(date(1, 1, 1), id="first-day-of-era"),
        pytest.param(date(1, 12, 31), id="border-1-close"),
        pytest.param(date(44, 3, 5), id="bc-mirror-year-44"),
        pytest.param(date(44, 2, 29), id="bc-mirrored-leap-feb-29"),
        pytest.param(date(2024, 2, 29), id="our-leap-feb-29"),
        pytest.param(date(2023, 2, 28), id="common-year-feb-edge"),
        pytest.param(date(9999, 1, 1), id="border-9999-open"),
        pytest.param(date(9999, 12, 31), id="border-9999-close"),
    ]

    @pytest.mark.parametrize("real", GOLD_DATES)
    @pytest.mark.parametrize("is_bc", [False, True], ids=["ad", "bc"])
    def test_coord_key_is_bit_identical_with_the_date_key(self, real, is_bc):
        coord = MonthDay(real.year, real.month, real.day)
        assert era_key(coord, is_bc) == era_key(real, is_bc)
        assert era_key(coord, is_bc) == _gregorian_key(real, is_bc)

    def test_mixed_date_and_coord_pairs_compare_through_one_order(self):
        assert cmp_era_dates((date(44, 3, 5), True), (MonthDay(44, 3, 5), True)) == 0
        assert cmp_era_dates((MonthDay(44, 3, 4), True), (date(44, 3, 5), True)) == -1
        # смешанная эра — единый хронологический порядок через границу
        assert cmp_era_dates((MonthDay(1, 12, 31), True), (MonthDay(1, 1, 1), False)) == -1

    def test_assert_range_accepts_coordinates_with_the_same_year_rule(self):
        assert_range(MonthDay(MIN_YEAR, 1, 1))
        assert_range(MonthDay(MAX_YEAR, 12, 31), True)
        assert_range(IntercalaryDay(MAX_YEAR, 3))  # год — единственное поле проверки
        with pytest.raises(ValueError):
            assert_range(MonthDay(0, 1, 1))
        with pytest.raises(ValueError):
            assert_range(IntercalaryDay(MAX_YEAR + 1, 0), False)

    def test_standard_preset_refuses_intercalary_coordinates_without_normalizing(self):
        # D4/D6: координаты, которой нет в активном календаре, — отличимый
        # отказ ядра, тихой нормализации нет
        with pytest.raises(InvalidGameDateError):
            era_key(IntercalaryDay(44, 0))


class TestIntercalaryKeyInContinuousRow:
    """C3a task 1.2 / сценарий «Ключ вставного дня в непрерывном ряду»: при
    активном кастоме era_key(IntercalaryDay) лежит строго между последним
    днём месяца-хозяина и первым днём следующего месяца — в обеих эрах."""

    @pytest.fixture(autouse=True)
    def isolated_active_calendar(self):
        # accessor — модульный глобал (D3): подмена не должна заражать соседей
        reset_current_calendar()
        yield
        reset_current_calendar()

    @pytest.mark.parametrize("is_bc", [False, True], ids=["ad", "bc"])
    def test_intercalary_key_sits_strictly_between_host_month_neighbours(self, is_bc):
        set_current_calendar(CustomCalendar(INTERCALARY_NEIGHBOUR_SPEC))
        host_last = era_key(MonthDay(44, 1, 30), is_bc)
        intercalary = era_key(IntercalaryDay(44, 0), is_bc)
        next_first = era_key(MonthDay(44, 2, 1), is_bc)
        assert host_last < intercalary < next_first

    def test_intercalary_key_follows_the_calendar_swap_both_ways(self):
        custom = CustomCalendar(INTERCALARY_NEIGHBOUR_SPEC)
        set_current_calendar(custom)
        keyed = era_key(IntercalaryDay(44, 0), True)
        assert keyed == custom.to_key(IntercalaryDay(44, 0), True)
        reset_current_calendar()
        with pytest.raises(InvalidGameDateError):  # пресет вставных не знает
            era_key(IntercalaryDay(44, 0), True)
