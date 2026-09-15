"""Focused tests for the reusable single-date popup bridge (era-aware, task 3.2)."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, QRect

from app.presentation.utils.date_utils import get_custom_months, set_custom_months
from app.presentation.views.theme_date_popup import _CustomCalendar, ThemeDatePopup
from app.presentation.views.timeline_date_popup import (
    _DateWindowPopup,
    window_chip_text,
)


def test_popup_owns_exactly_one_reused_calendar(qtbot):
    popup = ThemeDatePopup()
    qtbot.addWidget(popup)
    assert popup.findChildren(_CustomCalendar) == [popup.calendar]


def test_calendar_navigation_slots_cover_invalid_and_selected_values(qtbot):
    calendar = _CustomCalendar()
    qtbot.addWidget(calendar)
    calendar._on_month_selected(-1)
    calendar._month_combo.setItemData(0, None)
    calendar._on_month_selected(0)
    calendar._month_combo.setItemData(0, 3)
    calendar._on_month_selected(0)
    assert calendar.monthShown() == 3
    calendar._on_year_changed(1444)
    assert calendar.yearShown() == 1444


def test_calendar_bounds_and_spin_cover_both_eras(qtbot):
    """Task 3.2: mirrors of years 1…9999 in either era (the calendar paints
    the mirror; the era lives on the check box)."""
    calendar = _CustomCalendar()
    qtbot.addWidget(calendar)
    assert calendar.minimumDate() == QDate(1, 1, 1)
    assert calendar.maximumDate() == QDate(9999, 12, 31)
    assert calendar._year_spin.minimum() == 1
    assert calendar._year_spin.maximum() == 9999


def test_bc_check_toggles_era_without_touching_the_selected_numbers(qtbot):
    """Task 3.2 (design D6): switching the era never shifts the date."""
    calendar = _CustomCalendar()
    qtbot.addWidget(calendar)
    calendar.setSelectedDate(QDate(44, 3, 5))
    calendar.setCurrentPage(44, 3)
    calendar._bc_check.setChecked(True)
    assert calendar.is_bc() is True
    assert calendar.selectedDate() == QDate(44, 3, 5)
    assert (calendar.yearShown(), calendar.monthShown()) == (44, 3)
    calendar._bc_check.setChecked(False)
    assert calendar.is_bc() is False
    assert calendar.selectedDate() == QDate(44, 3, 5)


def test_open_refreshes_months_and_prefills_date_and_era(qtbot):
    saved = get_custom_months()
    popup = ThemeDatePopup()
    qtbot.addWidget(popup)
    try:
        months = {i: f"R4-{i}" for i in range(1, 13)}
        set_custom_months(months)
        # The lower bound moved from 100 to year 1 (task 3.2).
        popup.open_at(QRect(20, 30, 100, 20), (date(1, 2, 3), True))
        assert popup.calendar._month_combo.itemText(1) == "R4-2"
        assert popup.calendar.selectedDate() == QDate(1, 2, 3)
        assert popup.calendar.is_bc() is True
    finally:
        popup.close()
        set_custom_months(saved)


def test_open_without_pair_input_starts_in_our_era(qtbot):
    popup = ThemeDatePopup()
    qtbot.addWidget(popup)
    try:
        popup.calendar.set_era(True)  # stale era must not survive an open
        popup.open_at(QRect(20, 30, 100, 20), date(1200, 5, 5))
        assert popup.calendar.selectedDate() == QDate(1200, 5, 5)
        assert popup.calendar.is_bc() is False
    finally:
        popup.close()


def test_selection_emits_pair_and_closes_whatever_the_era_is(qtbot):
    popup = ThemeDatePopup()
    qtbot.addWidget(popup)
    received = []
    popup.date_selected.connect(received.append)

    popup.show()
    popup.calendar.clicked.emit(QDate(1, 1, 1))
    assert received == [(date(1, 1, 1), False)]
    assert not popup.isVisible()

    popup.show()
    popup.calendar.clicked.emit(QDate(9999, 12, 31))
    assert received[-1] == (date(9999, 12, 31), False)

    popup.show()
    popup.calendar.set_era(True)
    popup.calendar.clicked.emit(QDate(44, 3, 5))
    assert received[-1] == (date(44, 3, 5), True)


def test_open_clamps_both_axes_to_available_geometry(qtbot, monkeypatch):
    popup = ThemeDatePopup()
    qtbot.addWidget(popup)
    geometry = QRect(100, 200, 640, 480)

    class Screen:
        def availableGeometry(self):
            return QRect(geometry)

    class App:
        @staticmethod
        def screenAt(_position):
            return Screen()

        @staticmethod
        def primaryScreen():
            return Screen()

    from app.presentation.views import theme_date_popup

    monkeypatch.setattr(theme_date_popup, "QApplication", App)
    popup.open_at(QRect(1000, 1000, 50, 20), date(1200, 4, 5))
    assert geometry.left() <= popup.x()
    assert popup.x() + popup.width() - 1 <= geometry.right()
    assert geometry.top() <= popup.y()
    assert popup.y() + popup.height() - 1 <= geometry.bottom()
    popup.close()


# ── «Выбор даты» range popover (task 3.3) ────────────────────────────────────


def test_timeline_range_popup_regression_contract_is_unchanged(qtbot):
    popup = _DateWindowPopup()
    qtbot.addWidget(popup)
    assert popup.findChildren(_CustomCalendar) == [
        popup.start_calendar,
        popup.end_calendar,
    ]
    assert callable(popup._fit_low_screen)
    assert window_chip_text(None, None) == "Все дни ▾"
    assert window_chip_text(date(1200, 1, 2), date(1200, 1, 3)) == (
        "02 Январь 1200 — 03 Январь 1200 ▾"
    )


def test_range_popup_has_one_independent_era_check_box_per_calendar(qtbot):
    popup = _DateWindowPopup()
    qtbot.addWidget(popup)
    start_check = popup.start_calendar._bc_check
    end_check = popup.end_calendar._bc_check
    assert start_check is not end_check
    start_check.setChecked(True)
    assert popup.start_calendar.is_bc() is True
    assert popup.end_calendar.is_bc() is False


def test_range_popup_mixed_era_window_returns_two_pairs(qtbot):
    """Task 3.3: окно 500 г. до н.э. … 100 г. н.э. applies as two carried pairs."""
    popup = _DateWindowPopup()
    qtbot.addWidget(popup)
    received: list = []
    popup.range_applied.connect(lambda start, end: received.append((start, end)))
    popup.open_at(QRect(0, 0, 10, 10))
    popup._fit_low_screen(10_000)  # both calendars take the taps

    popup.start_calendar.set_era(True)
    popup.start_calendar.clicked.emit(QDate(500, 1, 1))
    assert received == []  # start alone is not a window yet
    popup.end_calendar.clicked.emit(QDate(100, 12, 31))

    assert received == [
        ((date(500, 1, 1), True), (date(100, 12, 31), False)),
    ]
    assert not popup.isVisible()


def test_range_popup_backwards_check_is_chronological_across_the_eras(qtbot):
    """A second tap chronologically BEFORE the armed start re-arms — with
    eras, «before» follows the single chronological key (design D2), not the
    raw year numbers: 500 г. до н.э. lies EARLIER than 100 г. до н.э. even
    though 500 > 100."""
    popup = _DateWindowPopup()
    qtbot.addWidget(popup)
    received: list = []
    popup.range_applied.connect(lambda start, end: received.append((start, end)))
    popup.open_at(QRect(0, 0, 10, 10))

    popup.start_calendar.set_era(True)
    popup.start_calendar.clicked.emit(QDate(100, 1, 1))  # 100 г. до н.э.
    assert popup._pending_start == (date(100, 1, 1), True)
    popup.start_calendar.clicked.emit(QDate(500, 1, 1))  # 500 г. до н.э. — раньше
    assert popup._pending_start == (date(500, 1, 1), True)  # re-armed
    assert received == []
    popup.end_calendar.set_era(True)
    popup.end_calendar.clicked.emit(QDate(50, 1, 1))  # 50 г. до н.э. — позже
    assert received == [((date(500, 1, 1), True), (date(50, 1, 1), True))]


def test_range_open_prefills_pairs_without_moving_numbers_back(qtbot):
    popup = _DateWindowPopup()
    qtbot.addWidget(popup)
    popup.open_at(
        QRect(0, 0, 10, 10),
        ((date(500, 1, 1), True), (date(100, 12, 31), False)),
    )
    assert popup.start_calendar.selectedDate() == QDate(500, 1, 1)
    assert popup.start_calendar.is_bc() is True
    assert popup.end_calendar.selectedDate() == QDate(100, 12, 31)
    assert popup.end_calendar.is_bc() is False
    popup.close()
