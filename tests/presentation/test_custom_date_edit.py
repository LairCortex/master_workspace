"""Tests for CustomDateEdit — custom month display, calendar navigation."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QDate

from app.presentation.utils.date_utils import set_custom_months
from app.presentation.views.custom_date_edit import CustomDateEdit, _CustomCalendar


@pytest.fixture(autouse=True)
def _default_months():
    """Month names are shared global state — restore defaults per test."""
    set_custom_months(None)
    yield
    set_custom_months(None)


class TestCustomDateEditDisplay:
    def test_default_month_name_in_field(self, qtbot):
        w = CustomDateEdit()
        qtbot.addWidget(w)
        w.setDate(QDate(1200, 5, 15))
        assert w.text() == "15 Май 1200"

    def test_custom_month_name_in_field(self, qtbot):
        w = CustomDateEdit()
        qtbot.addWidget(w)
        set_custom_months({5: "Медвежарь"})
        w.setDate(QDate(1200, 5, 15))
        assert w.text() == "15 Медвежарь 1200"

    def test_refresh_month_names_updates_display(self, qtbot):
        w = CustomDateEdit()
        qtbot.addWidget(w)
        w.setDate(QDate(1200, 5, 15))
        assert w.text() == "15 Май 1200"

        set_custom_months({5: "Медвежарь"})
        w.refresh_month_names()
        assert w.text() == "15 Медвежарь 1200"

    def test_refresh_month_names_updates_calendar_combo(self, qtbot):
        w = CustomDateEdit()
        qtbot.addWidget(w)
        cal = w._calendar
        assert cal._month_combo.itemText(4) == "Май"

        set_custom_months({5: "Медвежарь"})
        w.refresh_month_names()
        assert cal._month_combo.itemText(4) == "Медвежарь"

    def test_text_from_datetime_non_qdate_fallback(self, qtbot):
        """Defensive fallback: an object without a QDate date() goes to the base class."""
        w = CustomDateEdit()
        qtbot.addWidget(w)
        with pytest.raises(Exception):
            w.textFromDateTime(object())


class TestCustomCalendar:
    def test_prev_next_buttons_change_month(self, qtbot):
        cal = _CustomCalendar()
        qtbot.addWidget(cal)
        cal.setCurrentPage(1200, 5)
        cal._prev_btn.click()
        assert cal.monthShown() == 4
        assert cal._month_combo.currentIndex() == 3
        cal._next_btn.click()
        assert cal.monthShown() == 5
        assert cal._month_combo.currentIndex() == 4

    def test_month_combo_select_changes_page(self, qtbot):
        cal = _CustomCalendar()
        qtbot.addWidget(cal)
        cal.setCurrentPage(1200, 1)
        cal._month_combo.setCurrentIndex(7)  # August (data = month number)
        assert cal.monthShown() == 8

    def test_month_selected_ignores_invalid_index(self, qtbot):
        cal = _CustomCalendar()
        qtbot.addWidget(cal)
        cal.setCurrentPage(1200, 5)
        cal._on_month_selected(-1)
        assert cal.monthShown() == 5

    def test_year_spin_changes_page(self, qtbot):
        cal = _CustomCalendar()
        qtbot.addWidget(cal)
        cal.setCurrentPage(1200, 5)
        cal._year_spin.setValue(1500)
        assert cal.yearShown() == 1500
        assert cal._month_combo.currentIndex() == 4  # month kept in sync

    def test_custom_month_names_in_calendar(self, qtbot):
        cal = _CustomCalendar()
        qtbot.addWidget(cal)
        set_custom_months({1: "Велесар"})
        cal.refresh_month_names()
        assert cal._month_combo.itemText(0) == "Велесар"
