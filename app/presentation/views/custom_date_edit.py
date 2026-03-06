"""QDateEdit with custom month names in both text display and calendar popup."""
from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCalendarWidget,
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.presentation.utils.date_utils import get_custom_months, month_name


# ── Custom Calendar Widget ────────────────────────────────────────────────

class _CustomCalendar(QCalendarWidget):
    """QCalendarWidget with custom navigation bar showing fantasy month names."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setNavigationBarVisible(False)
        self.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.setMinimumWidth(350)

        # Build custom navigation bar
        self._nav = QWidget(self)
        nav_lay = QHBoxLayout(self._nav)
        nav_lay.setContentsMargins(6, 4, 6, 4)
        nav_lay.setSpacing(2)

        # ◀ prev month
        self._prev_btn = QPushButton("◀")
        self._prev_btn.setFixedSize(28, 28)
        self._prev_btn.clicked.connect(self.showPreviousMonth)

        # Month combo
        self._month_combo = QComboBox()
        self._month_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._populate_months()
        self._month_combo.currentIndexChanged.connect(self._on_month_selected)

        # Year spin box
        self._year_spin = QSpinBox()
        self._year_spin.setRange(100, 9999)
        self._year_spin.setButtonSymbols(QSpinBox.ButtonSymbols.PlusMinus)
        self._year_spin.setFixedWidth(80)
        self._year_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._year_spin.valueChanged.connect(self._on_year_changed)

        # ▶ next month
        self._next_btn = QPushButton("▶")
        self._next_btn.setFixedSize(28, 28)
        self._next_btn.clicked.connect(self.showNextMonth)

        nav_lay.addWidget(self._prev_btn)
        nav_lay.addWidget(self._month_combo, 1)
        nav_lay.addSpacing(8)
        nav_lay.addWidget(self._year_spin)
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


# ── Custom Date Edit ──────────────────────────────────────────────────────

class CustomDateEdit(QDateEdit):
    """QDateEdit that displays dates with custom month names."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCalendarPopup(False)
        self.setMinimumDate(QDate(100, 1, 1))
        self.setMaximumDate(QDate(9999, 12, 31))

        # Underlying calendar is kept for month name updates but not shown
        self._calendar = _CustomCalendar()

        # Replace default line edit with composite widget: day/month/year + filter
        self._container = QWidget(self)
        layout = QHBoxLayout(self._container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._day_combo = QComboBox()
        self._day_combo.setEditable(True)
        self._day_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)

        self._month_combo = QComboBox()
        self._month_combo.setEditable(True)
        self._month_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)

        self._year_combo = QComboBox()
        self._year_combo.setEditable(True)
        self._year_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)

        layout.addWidget(self._day_combo, 1)
        layout.addWidget(self._month_combo, 2)
        layout.addWidget(self._year_combo, 1)

        self.setLayout(layout)

        self._populate_months()
        self._populate_days()
        self._populate_years()

        self._day_combo.currentIndexChanged.connect(self._on_part_changed)
        self._month_combo.currentIndexChanged.connect(self._on_part_changed)
        self._year_combo.currentIndexChanged.connect(self._on_part_changed)

        self._setup_filtering(self._day_combo, self._all_days())
        self._setup_filtering(self._month_combo, self._all_month_labels())
        self._setup_filtering(self._year_combo, self._all_years())

        # Initialize with today's date
        self.setDate(QDate.currentDate())

    # --- Filtering helpers -------------------------------------------------

    def _setup_filtering(self, combo: QComboBox, source: list[str]) -> None:
        edit = combo.lineEdit()
        if not isinstance(edit, QLineEdit):
            return

        def _on_text_changed(text: str, c=combo, base=source, line_edit=edit):
            t = text.strip().lower()
            c.blockSignals(True)
            if line_edit:
                line_edit.blockSignals(True)
            try:
                c.clear()
                if not t:
                    for v in base:
                        c.addItem(v)
                else:
                    filtered = [v for v in base if t in v.lower()]
                    for v in filtered:
                        c.addItem(v)
            finally:
                c.blockSignals(False)
                if line_edit:
                    line_edit.blockSignals(False)

        edit.textChanged.connect(_on_text_changed)

    def _all_days(self) -> list[str]:
        return [f"{i:02d}" for i in range(1, 32)]

    def _all_month_labels(self) -> list[str]:
        months = get_custom_months()
        return [months.get(i, str(i)) for i in range(1, 13)]

    def _all_years(self) -> list[str]:
        # Reasonable range; still supports manual typing outside
        return [str(y) for y in range(100, 100 + 3000)]

    # --- Population --------------------------------------------------------

    def _populate_days(self) -> None:
        self._day_combo.clear()
        for d in self._all_days():
            self._day_combo.addItem(d)

    def _populate_months(self) -> None:
        self._month_combo.clear()
        months = get_custom_months()
        for i in range(1, 13):
            self._month_combo.addItem(months.get(i, str(i)), i)

    def _populate_years(self) -> None:
        self._year_combo.clear()
        for y in self._all_years():
            self._year_combo.addItem(y)

    # --- Synchronization with QDateEdit API --------------------------------

    def _on_part_changed(self) -> None:
        try:
            day = int(self._day_combo.currentText() or "1")
            year = int(self._year_combo.currentText() or "100")
            month_data = self._month_combo.currentData()
            if month_data is None:
                # fallback: try index + 1
                month = self._month_combo.currentIndex() + 1
            else:
                month = int(month_data)
            new_date = QDate(year, month, min(day, QDate(year, month, 1).daysInMonth()))
            if new_date.isValid():
                super().setDate(new_date)
        except Exception:
            # Ignore invalid combinations until user fixes them
            pass

    def setDate(self, date: QDate) -> None:  # type: ignore[override]
        super().setDate(date)
        self._sync_from_date(date)

    def _sync_from_date(self, d: QDate) -> None:
        self._day_combo.blockSignals(True)
        self._month_combo.blockSignals(True)
        self._year_combo.blockSignals(True)
        try:
            self._day_combo.setCurrentText(f"{d.day():02d}")
            months = get_custom_months()
            label = months.get(d.month(), str(d.month()))
            self._month_combo.setCurrentText(label)
            self._year_combo.setCurrentText(str(d.year()))
        finally:
            self._day_combo.blockSignals(False)
            self._month_combo.blockSignals(False)
            self._year_combo.blockSignals(False)

    def textFromDateTime(self, dt: QDate) -> str:
        """Keep existing behavior for tests and formatting."""
        if hasattr(dt, "date"):
            d = dt.date() if hasattr(dt, "date") else dt
        else:
            d = dt
        if isinstance(d, QDate):
            return f"{d.day():02d} {month_name(d.month())} {d.year()}"
        return super().textFromDateTime(dt)

    def refresh_month_names(self) -> None:
        """Refresh display after month names change."""
        self._calendar.refresh_month_names()
        self._populate_months()
        self._sync_from_date(self.date())
