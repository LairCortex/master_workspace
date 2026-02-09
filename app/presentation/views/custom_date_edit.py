"""QDateEdit with custom month names in both text display and calendar popup."""
from __future__ import annotations

from PySide6.QtCore import QDate, QLocale, Qt
from PySide6.QtGui import QTextCharFormat
from PySide6.QtWidgets import (
    QCalendarWidget, QComboBox, QDateEdit, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from app.presentation.utils.date_utils import get_custom_months, month_name


# ── Custom Calendar Widget ────────────────────────────────────────────────

class _CustomCalendar(QCalendarWidget):
    """QCalendarWidget with custom navigation bar showing fantasy month names."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setNavigationBarVisible(False)
        self.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)

        # Build custom navigation bar
        self._nav = QWidget(self)
        nav_lay = QHBoxLayout(self._nav)
        nav_lay.setContentsMargins(4, 2, 4, 2)

        self._prev_btn = QPushButton("◀")
        self._prev_btn.setFixedWidth(30)
        self._prev_btn.clicked.connect(self.showPreviousMonth)

        self._month_combo = QComboBox()
        self._month_combo.setMinimumWidth(120)
        self._populate_months()
        self._month_combo.currentIndexChanged.connect(self._on_month_selected)

        self._year_label = QLabel()
        self._year_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._year_label.setStyleSheet("font-weight: bold; font-size: 13px; min-width: 50px;")

        self._prev_year_btn = QPushButton("«")
        self._prev_year_btn.setFixedWidth(24)
        self._prev_year_btn.clicked.connect(self.showPreviousYear)

        self._next_year_btn = QPushButton("»")
        self._next_year_btn.setFixedWidth(24)
        self._next_year_btn.clicked.connect(self.showNextYear)

        self._next_btn = QPushButton("▶")
        self._next_btn.setFixedWidth(30)
        self._next_btn.clicked.connect(self.showNextMonth)

        nav_lay.addWidget(self._prev_btn)
        nav_lay.addWidget(self._month_combo, 1)
        nav_lay.addWidget(self._prev_year_btn)
        nav_lay.addWidget(self._year_label)
        nav_lay.addWidget(self._next_year_btn)
        nav_lay.addWidget(self._next_btn)

        # Insert nav bar at the top of calendar layout
        cal_layout = self.layout()
        if cal_layout is not None:
            cal_layout.insertWidget(0, self._nav)

        self.currentPageChanged.connect(self._sync_nav)
        self._sync_nav(self.yearShown(), self.monthShown())

    def refresh_month_names(self) -> None:
        """Reload month names from global state (after settings change)."""
        self._populate_months()
        self._sync_nav(self.yearShown(), self.monthShown())

    def _populate_months(self) -> None:
        self._month_combo.blockSignals(True)
        self._month_combo.clear()
        months = get_custom_months()
        for i in range(1, 13):
            self._month_combo.addItem(months.get(i, str(i)), i)
        self._month_combo.blockSignals(False)

    def _sync_nav(self, year: int, month: int) -> None:
        self._month_combo.blockSignals(True)
        self._month_combo.setCurrentIndex(month - 1)
        self._month_combo.blockSignals(False)
        self._year_label.setText(str(year))

    def _on_month_selected(self, index: int) -> None:
        if index < 0:
            return
        month = self._month_combo.itemData(index)
        if month is not None:
            self.setCurrentPage(self.yearShown(), month)


# ── Custom Date Edit ──────────────────────────────────────────────────────

class CustomDateEdit(QDateEdit):
    """QDateEdit that displays dates with custom month names."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.setMinimumDate(QDate(100, 1, 1))
        self.setMaximumDate(QDate(9999, 12, 31))
        self._calendar = _CustomCalendar()
        self.setCalendarWidget(self._calendar)

    def textFromDateTime(self, dt: QDate) -> str:
        """Override to show custom month name in the date edit field."""
        if hasattr(dt, 'date'):
            # QDateTime
            d = dt.date() if hasattr(dt, 'date') else dt
        else:
            d = dt
        if isinstance(d, QDate):
            return f"{d.day():02d} {month_name(d.month())} {d.year()}"
        return super().textFromDateTime(dt)

    def refresh_month_names(self) -> None:
        """Refresh display after month names change."""
        self._calendar.refresh_month_names()
        self.update()
        # Force text refresh
        self.setDate(self.date())
