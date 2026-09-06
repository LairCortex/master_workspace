"""Top-level single-date popup used by QML date fields."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, QPoint, QRect, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.presentation.utils.date_utils import get_custom_months

MIN_DATE = date(100, 1, 1)
MAX_DATE = date(9999, 12, 31)


class _CustomCalendar(QCalendarWidget):
    """Native popup calendar with fantasy month navigation."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setNavigationBarVisible(False)
        self.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
        )
        self.setMinimumWidth(350)
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
        self._year_spin.setRange(100, 9999)
        self._year_spin.setButtonSymbols(QSpinBox.ButtonSymbols.PlusMinus)
        self._year_spin.setFixedWidth(80)
        self._year_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._year_spin.valueChanged.connect(self._on_year_changed)
        self._next_btn = QPushButton("▶")
        self._next_btn.setFixedSize(28, 28)
        self._next_btn.clicked.connect(self.showNextMonth)
        nav.addWidget(self._prev_btn)
        nav.addWidget(self._month_combo, 1)
        nav.addSpacing(8)
        nav.addWidget(self._year_spin)
        nav.addWidget(self._next_btn)
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


def _clamp_date(value: date) -> date:
    return max(MIN_DATE, min(value, MAX_DATE))


class ThemeDatePopup(QWidget):
    """One reusable calendar, positioned wholly inside available geometry."""

    date_selected = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("themeDatePopup")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self.calendar = _CustomCalendar(self)
        self.calendar.setMinimumDate(QDate(100, 1, 1))
        self.calendar.setMaximumDate(QDate(9999, 12, 31))
        layout.addWidget(self.calendar)
        self.calendar.clicked.connect(self._on_date_clicked)

    def open_at(self, anchor_global: QRect, current: date | None = None) -> None:
        """Refresh, prefill and open below a global QML anchor rectangle."""
        self.calendar.refresh_month_names()
        selected = _clamp_date(current or QDate.currentDate().toPython())
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
        self.date_selected.emit(selected)
        self.close()
