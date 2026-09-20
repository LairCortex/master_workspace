"""Tests for custom month names — date formatting on the active calendar.

Piece C2 (design D7) removed the ``date_utils`` process global; names now
come from the active game calendar, so these formatting tests install a
calendar through ``set_current_calendar``.  Storage-level serialization and
migration moved to the codec/service tests; the dialog-era widget classes at
the bottom are deleted together with the dialog (tasks 6.1/7.1).
"""
from __future__ import annotations

import pytest

from datetime import date

from app.domain.game_calendar import (
    StandardCalendar,
    current_calendar,
    reset_current_calendar,
    set_current_calendar,
)
from app.presentation.utils.date_utils import (
    DEFAULT_MONTHS,
    format_game_date,
    month_name,
)


# ── date_utils formatting on the active calendar ──────────────────────────


@pytest.fixture(autouse=True)
def _default_game_calendar():
    """Names are calendar text — pin the «Стандартный» preset around each
    unit and hand the previously active calendar object back afterwards."""
    saved = current_calendar()
    reset_current_calendar()
    yield
    set_current_calendar(saved)


class TestFormatGameDate:
    def test_default_format(self):
        d = date(2026, 3, 15)
        result = format_game_date(d)
        assert result == "15 Март 2026"

    def test_custom_months(self):
        set_current_calendar(
            StandardCalendar(month_names={1: "Зимостой", 2: "Ветрогон", 3: "Молнеград"})
        )
        d = date(2026, 3, 15)
        result = format_game_date(d)
        assert result == "15 Молнеград 2026"

    def test_none_date(self):
        assert format_game_date(None) == "?"
        assert format_game_date(None, "∞") == "∞"

    # ── add-era-aware-dates 3.1: the «до н.э.» year suffix ─────────────────

    def test_bc_year_gets_the_suffix(self):
        assert format_game_date(date(44, 3, 5), is_bc=True) == "05 Март 44 г. до н.э."

    def test_bc_format_uses_custom_months_too(self):
        set_current_calendar(StandardCalendar(month_names={3: "Молнеград"}))
        assert format_game_date(date(500, 3, 9), is_bc=True) == "09 Молнеград 500 г. до н.э."

    def test_our_era_format_is_unchanged(self):
        assert format_game_date(date(2026, 3, 15), is_bc=False) == "15 Март 2026"

    def test_empty_era_reads_as_our_era(self):
        # Даты без заданной эры (пустой признак) — прежний формат, без суффикса.
        assert format_game_date(date(2026, 3, 15), is_bc=None) == "15 Март 2026"
        assert format_game_date(date(2026, 3, 15)) == "15 Март 2026"

    def test_fallback_carries_no_era(self):
        # Пометка открытого конца «∞» не зависит от эры.
        assert format_game_date(None, "∞", is_bc=True) == "∞"
        assert format_game_date(None, "∞", is_bc=False) == "∞"

    def test_month_name_default(self):
        assert month_name(1) == "Январь"
        assert month_name(12) == "Декабрь"

    def test_month_name_custom(self):
        set_current_calendar(StandardCalendar(month_names={1: "Первомес"}))
        assert month_name(1) == "Первомес"
        # Other months fall back to the Gregorian defaults
        assert month_name(2) == "Февраль"

    def test_month_name_falls_back_to_the_number(self):
        # A number the calendar does not name reads as its own digits.
        assert month_name(13) == "13"

    def test_default_months_reexport_is_the_domain_names(self):
        # DEFAULT_MONTHS is a re-export, not a second copy (design D7).
        from app.domain.game_calendar import DEFAULT_MONTH_NAMES

        assert DEFAULT_MONTHS is DEFAULT_MONTH_NAMES
        assert dict(DEFAULT_MONTHS) == {i: month_name(i) for i in range(1, 13)}
