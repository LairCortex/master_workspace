"""Unit tests for era-aware date helpers — chronological key across the era border."""
from datetime import date
from types import SimpleNamespace

import pytest

from app.domain.date_era import (
    BC_YEAR_STEP,
    MAX_YEAR,
    MIN_YEAR,
    assert_range,
    cmp_era_dates,
    era_key,
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
