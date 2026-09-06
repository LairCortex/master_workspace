"""Focused tests for the reusable single-date popup bridge."""
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


def test_open_refreshes_months_and_prefills_clamped_current_date(qtbot):
    saved = get_custom_months()
    popup = ThemeDatePopup()
    qtbot.addWidget(popup)
    try:
        months = {i: f"R4-{i}" for i in range(1, 13)}
        set_custom_months(months)
        popup.open_at(QRect(20, 30, 100, 20), date(1, 2, 3))
        assert popup.calendar._month_combo.itemText(1) == "R4-2"
        assert popup.calendar.selectedDate() == QDate(100, 1, 1)
    finally:
        popup.close()
        set_custom_months(saved)


def test_selection_clamps_bounds_emits_once_and_closes(qtbot):
    popup = ThemeDatePopup()
    qtbot.addWidget(popup)
    received = []
    popup.date_selected.connect(received.append)

    popup.show()
    popup.calendar.clicked.emit(QDate(1, 1, 1))
    assert received == [date(100, 1, 1)]
    assert not popup.isVisible()

    popup.show()
    popup.calendar.clicked.emit(QDate(9999, 12, 31))
    assert received == [date(100, 1, 1), date(9999, 12, 31)]


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
