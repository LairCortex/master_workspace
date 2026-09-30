"""NRI-0023 task 8.1 — the single event-start caption helper (design Д9).

Spec event-time «Время на поверхностях события»: every surface that prints
an event's start date (ladder, card, preview, search, snapshot) calls
``format_event_start``; with a chosen time the caption gains the ', HH:MM'
tail, with no time it stays the pre-NRI-0023 print word-for-word. This file
is the task's pin: the ``None`` half compares against the OLD formulation
(``format_game_date`` — the very call every surface used to make) so a
regression in the empty-time caption fails here even where a surface test
would print the same wrong string on both sides of the helper.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.domain.game_calendar import (
    CalendarSpec,
    CustomCalendar,
    IntercalaryDay,
    IntercalarySpec,
    MonthDay,
    MonthSpec,
    current_calendar,
    reset_current_calendar,
    set_current_calendar,
)
from app.domain.time_of_day import TimeOfDay
from app.presentation.utils.date_utils import (
    event_start_time,
    format_event_start,
    format_game_date,
)

CUSTOM_SPEC = CalendarSpec(
    months=(
        MonthSpec("Первомес", 30),
        MonthSpec("Второмес", 40),
        MonthSpec("Третьемес", 28),
    ),
    week_names=("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"),
    intercalary=(IntercalarySpec("День Маски", 1),),
)


@pytest.fixture(autouse=True)
def _standard_calendar_around_each_test():
    saved = current_calendar()
    reset_current_calendar()
    yield
    set_current_calendar(saved)


class TestEmptyTimeKeepsTheOldCaption:
    """The task pin: at ``start_time=None`` the print is bit-for-bit what
    ``format_game_date`` — the pre-time formulation — produced."""

    @pytest.mark.parametrize(
        "coord,is_bc",
        [
            (MonthDay(2026, 3, 15), False),
            (MonthDay(44, 3, 5), True),
            (date(2026, 12, 1), False),
            (MonthDay(2026, 1, 1), True),
        ],
    )
    def test_standard_calendar_captions_are_bit_identical(self, coord, is_bc):
        assert format_event_start(coord, is_bc, None) == format_game_date(
            coord, is_bc=is_bc
        )

    def test_intercalary_and_custom_month_names_are_bit_identical(self):
        calendar = CustomCalendar(CUSTOM_SPEC)
        set_current_calendar(calendar)
        for coord, is_bc in (
            (MonthDay(3, 2, 40), True),
            (MonthDay(3, 1, 1), False),
        ):
            assert format_event_start(coord, is_bc, None) == format_game_date(
                coord, is_bc=is_bc
            )

    def test_missing_date_fallback_is_untouched(self):
        assert format_event_start(None, False, None) == format_game_date(None)


class TestChosenTimeRidesTheCaption:
    def test_time_appends_comma_hhmm_with_zero_padding(self):
        assert format_event_start(MonthDay(2026, 3, 15), False, TimeOfDay(9, 5)) == (
            "15 Март 2026, 09:05"
        )
        assert format_event_start(MonthDay(2026, 3, 15), False, TimeOfDay(14, 30)) == (
            "15 Март 2026, 14:30"
        )
        assert format_event_start(MonthDay(2026, 3, 15), False, TimeOfDay(0, 0)) == (
            "15 Март 2026, 00:00"
        )

    def test_time_follows_the_era_suffix_as_part_of_the_date(self):
        # The « г. до н.э.» suffix belongs to the date; the time tail comes
        # after the whole date caption, never between year and era.
        assert format_event_start(MonthDay(44, 3, 5), True, TimeOfDay(23, 59)) == (
            "05 Март 44 г. до н.э., 23:59"
        )

    def test_custom_month_names_and_intercalary_days_carry_the_same_tail(self):
        set_current_calendar(CustomCalendar(CUSTOM_SPEC))
        assert format_event_start(MonthDay(3, 2, 40), False, TimeOfDay(1, 2)) == (
            "40 Второмес 3, 01:02"
        )
        assert format_event_start(IntercalaryDay(3, 0), False, TimeOfDay(10, 0)) == (
            "День Маски 3, 10:00"
        )


class TestEventStartTimeReaderIsDuckTyped:
    """``event_start_time`` only accepts an actual ``TimeOfDay``; absent or
    foreign attributes read as «без времени» (auto-Mock doubles included)."""

    def test_real_time_passes_through(self):
        moment = TimeOfDay(7, 45)
        assert event_start_time(SimpleNamespace(start_time=moment)) is moment

    @pytest.mark.parametrize(
        "event",
        [
            SimpleNamespace(),  # no attribute at all
            SimpleNamespace(start_time=None),
            SimpleNamespace(start_time=570),  # raw minutes are not the domain face
            Mock(),  # the auto-Mock of a test double
        ],
    )
    def test_foreign_values_read_as_no_time(self, event):
        assert event_start_time(event) is None
