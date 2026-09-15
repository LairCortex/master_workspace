"""Top-level single-date popup used by QML date fields."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, QPoint, QRect, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.presentation.utils.date_utils import get_custom_months, split_date_era

#: Both eras span years 1…9999 (add-era-aware-dates, design D6); the BC era
#: is a mirror of these very dates behind the «до н.э.» checkbox, so the
#: calendar widget itself only ever navigates this range.
MIN_DATE = date(1, 1, 1)
MAX_DATE = date(9999, 12, 31)


class _CustomCalendar(QCalendarWidget):
    """Native popup calendar with fantasy month navigation and an era flag.

    The «до н.э.» check box (task 3.2) is a pure flag: toggling it NEVER
    changes the selected date or the shown page — the BC year mirrors the
    Gregorian year with the same number (design D2/Q11), so the very same
    calendar paints the chosen day of either era.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setNavigationBarVisible(False)
        self.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
        )
        self.setMinimumWidth(350)
        self.setMinimumDate(QDate(1, 1, 1))
        self.setMaximumDate(QDate(9999, 12, 31))
        self._nav = QWidget(self)
        nav = QHBoxLayout(self._nav)
        nav.setContentsMargins(6, 4, 6, 4)
        nav.setSpacing(2)
        self._prev_btn = QPushButton("◀")
        self._prev_btn.setFixedSize(28, 28)
        self._prev_btn.clicked.connect(self.showPreviousMonth)
        self._month_combo = QComboBox()
        self._month_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        self._populate_months()
        self._month_combo.currentIndexChanged.connect(self._on_month_selected)
        self._year_spin = QSpinBox()
        self._year_spin.setRange(1, 9999)
        self._year_spin.setButtonSymbols(QSpinBox.ButtonSymbols.PlusMinus)
        self._year_spin.setFixedWidth(80)
        self._year_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._year_spin.valueChanged.connect(self._on_year_changed)
        self._next_btn = QPushButton("▶")
        self._next_btn.setFixedSize(28, 28)
        self._next_btn.clicked.connect(self.showNextMonth)
        self._bc_check = QCheckBox("до н.э.")
        nav.addWidget(self._prev_btn)
        nav.addWidget(self._month_combo, 1)
        nav.addSpacing(8)
        nav.addWidget(self._year_spin)
        nav.addWidget(self._next_btn)
        nav.addSpacing(8)
        nav.addWidget(self._bc_check)
        layout = self.layout()
        if layout is not None:
            layout.insertWidget(0, self._nav)
        self.currentPageChanged.connect(self._sync_nav)
        self._sync_nav(self.yearShown(), self.monthShown())

    def refresh_month_names(self) -> None:
        self._populate_months()
        self._sync_nav(self.yearShown(), self.monthShown())

    def _populate_months(self) -> None:
        self._month_combo.blockSignals(True)
        self._month_combo.clear()
        months = get_custom_months()
        for number in range(1, 13):
            self._month_combo.addItem(months.get(number, str(number)), number)
        self._month_combo.blockSignals(False)

    def _sync_nav(self, year: int, month: int) -> None:
        self._month_combo.blockSignals(True)
        self._month_combo.setCurrentIndex(month - 1)
        self._month_combo.blockSignals(False)
        self._year_spin.blockSignals(True)
        self._year_spin.setValue(year)
        self._year_spin.blockSignals(False)

    def _on_month_selected(self, index: int) -> None:
        if index < 0:
            return
        month = self._month_combo.itemData(index)
        if month is not None:
            self.setCurrentPage(self.yearShown(), month)

    def _on_year_changed(self, year: int) -> None:
        self.setCurrentPage(year, self.monthShown())

    # ── era flag (task 3.2: mirror calendar, era is a pure flag) ────────────

    def is_bc(self) -> bool:
        """The chosen era: True = «до н.э.»."""
        return self._bc_check.isChecked()

    def set_era(self, is_bc: bool) -> None:
        """Pre-fill the era check box without touching the selected date."""
        self._bc_check.setChecked(bool(is_bc))


def _clamp_date(value: date) -> date:
    return max(MIN_DATE, min(value, MAX_DATE))


class ThemeDatePopup(QWidget):
    """One reusable calendar, positioned wholly inside available geometry."""

    #: ``(date, is_bc)`` — the popup hands its bridge a (date, era) pair.
    date_selected = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("themeDatePopup")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self.calendar = _CustomCalendar(self)
        layout.addWidget(self.calendar)
        self.calendar.clicked.connect(self._on_date_clicked)

    def open_at(
        self, anchor_global: QRect, current: date | tuple[date, bool] | None = None
    ) -> None:
        """Refresh, prefill and open below a global QML anchor rectangle.

        ``current`` is the bridge's (date, era) pair (a bare date reads as
        «н.э.»); the numbers are clamped to the calendar range regardless of
        the era, and the check box takes the era without moving the date.
        """
        self.calendar.refresh_month_names()
        prefilled, prefilled_bc = split_date_era(current)
        selected = _clamp_date(prefilled or QDate.currentDate().toPython())
        self.calendar.set_era(bool(prefilled_bc))
        qdate = QDate(selected.year, selected.month, selected.day)
        self.calendar.setSelectedDate(qdate)
        self.calendar.setCurrentPage(qdate.year(), qdate.month())

        position = QPoint(
            anchor_global.x(),
            anchor_global.y() + anchor_global.height() + 2,
        )
        screen = QApplication.screenAt(position) or QApplication.primaryScreen()
        self.adjustSize()
        if screen is not None:
            geometry = screen.availableGeometry()
            position.setX(
                max(
                    geometry.left(),
                    min(position.x(), geometry.right() - self.width() + 1),
                )
            )
            position.setY(
                max(
                    geometry.top(),
                    min(position.y(), geometry.bottom() - self.height() + 1),
                )
            )
        self.move(position)
        self.show()
        if screen is not None:
            frame = self.frameGeometry()
            dx = max(geometry.left() - frame.left(), 0)
            dx += min(geometry.right() - (frame.right() + dx), 0)
            dy = max(geometry.top() - frame.top(), 0)
            dy += min(geometry.bottom() - (frame.bottom() + dy), 0)
            if dx or dy:
                self.move(self.pos() + QPoint(dx, dy))

    def _on_date_clicked(self, value: QDate) -> None:
        selected = _clamp_date(value.toPython())
        self.date_selected.emit((selected, self.calendar.is_bc()))
        self.close()
