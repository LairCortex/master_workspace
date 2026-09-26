"""The game-calendar day grid shared by the date popups and the wizard (C3b).

Design D1: a composited ``QWidget`` + ``QGridLayout`` of NAMED buttons —
navigation panel (◀, month combo of the ACTIVE calendar, year spin 1…9999, ▶,
«до н.э.» check box), a week-name header, day cells and per-host-month rows of
intercalary chips.  A composited widget was chosen over ``QTableView``+delegate
(clickable chips and per-class theming are cheaper this way) and over
sub-classing Qt's own Gregorian calendar widget (which cannot express the week
length or the month count at all — confirmed by the spike).

Coordinate contract (spec «Сетка говорит координатами»): a click on a cell or
a chip emits the pure game coordinate ``MonthDay``/``IntercalaryDay`` — never a
Gregorian ``QDate``; pre-filling takes a coordinate and paints its real cell
or chip, and a coordinate the active calendar does not contain (a year outside
the 1…9999 scale foremost) simply leaves the grid un-prefilled — no page jump
and no number substituted for the picture.  The era check box is a pure flag:
switching it never moves the page or the selection (spec «Переключатель эры —
чистый флаг»).

Design minimalism (spec «Минимализм оформления сетки»): no system-«today»
marker, no neighbouring-month days, incomplete weeks are filled with empty
unclickable cells; a cell has exactly the normal/hover/selected looks.

The classes ``GameCalendarGrid``, ``GameCalendarCell``,
``GameCalendarIntercalaryChip``, ``GameCalendarDayName`` and
``GameCalendarEraCheck`` are STYLE-FACING names: the app-wide popup sheet
(``compile_popup_qss``) skins them by class name (``GameCalendarCell``
additionally through its ``selected`` property, ``GameCalendarEraCheck``
through its ``::indicator`` sub-control, NRI-0018 Д8), so renaming one
silently drops the grid's theme — rename only together with the sheet
(design D4; guarded by the pair test in ``test_calendar_nav_band``).
"""
from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.domain.game_calendar import (
    MAX_YEAR,
    MIN_YEAR,
    GameCoord,
    IntercalaryDay,
    IntercalarySpec,
    MonthDay,
    as_game_coord,
    current_calendar,
)
from app.presentation.utils.date_utils import STANDARD_WEEK_NAMES

#: The navigation row's single control band (NRI-0018 Д8, spec «Строка
#: навигации — единая полоса высот»): arrows, month combo, year spin and the
#: era flag all clamp to this height and share its vertical centre.
NAV_ROW_HEIGHT = 32


class GameCalendarDayName(QLabel):
    """One weekday caption of the header row (STYLE-FACING, see module)."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


class GameCalendarCell(QPushButton):
    """One day cell of the grid (STYLE-FACING, see module).

    The ``selected`` dynamic property is the styling handle for the third
    cell state (``[selected="true"]`` in the popup sheet); the bool
    :attr:`selected` simply mirrors it.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("selected", False)

    @property
    def selected(self) -> bool:
        return bool(self.property("selected"))


class GameCalendarEraCheck(QCheckBox):
    """The «до н.э.» era flag of the navigation row (STYLE-FACING, see module).

    A named class because the app-wide popup sheet may never carry a generic
    ``QCheckBox`` rule (every checkbox of the process would repaint — W2a D2):
    the indicator's theme is addressed through this one name
    (``GameCalendarEraCheck::indicator`` in ``compile_popup_qss``).  Off-skin
    the sheet is empty and the box falls back to the native OS look untouched
    (ui-widget-catalog «Off-skin не ломается»).
    """


class GameCalendarIntercalaryChip(QPushButton):
    """Chip of one intercalary day, picked like an ordinary cell
    (STYLE-FACING, see module).  Chips live in their own full-width row
    after the host month, never in a weekday column (spec «Вставные дни
    строкой-плашкой»)."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("selected", False)

    @property
    def selected(self) -> bool:
        return bool(self.property("selected"))


def _mark_selected(button: QPushButton, selected: bool) -> None:
    """Mirror the selection onto the style-facing ``selected`` property,
    re-polishing only when the state actually flips."""
    if bool(button.property("selected")) is selected:
        return
    button.setProperty("selected", selected)
    button.style().unpolish(button)
    button.style().polish(button)


class GameCalendarGrid(QWidget):
    """Day grid of the ACTIVE game calendar (designs D1/D2).

    Navigation panel (◀ / month combo / year spin 1…9999 / ▶ + «до н.э.»
    check box), a header of week-name labels and a ``QGridLayout`` of day
    cells; intercalary rules hosted by the shown month follow its weeks as a
    full-width chip row in spec list order.  Public API: :meth:`refresh`
    re-reads the active calendar, :meth:`set_selection` pre-fills a
    coordinate (and optionally the era), :meth:`selection` reads it back,
    :meth:`is_bc`/:meth:`set_era` carry the pure era flag; the
    ``day_selected`` signal emits the clicked :data:`GameCoord` and
    ``page_changed`` the new (year, month) page.

    The ``interactive`` mode turns the cells and chips off (wizard live
    preview — navigation keeps working), ``show_era`` hides the era check
    box (spec calendar-wizard «Живой предпросмотр сеткой»).
    """

    #: A day cell or an intercalary chip was clicked — a pure GameCoord;
    #: the era travels separately through :meth:`is_bc` (pure flag, D1).
    day_selected = Signal(object)
    #: The shown page changed: ``(year, month)``.
    page_changed = Signal(int, int)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        interactive: bool = True,
        show_era: bool = True,
    ) -> None:
        super().__init__(parent)
        # A plain QWidget paints the sheet's ``GameCalendarGrid`` background
        # only with this flag on (same recipe as _DateWindowPopup).
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._interactive = interactive
        self._selected: GameCoord | None = None
        self._calendar = current_calendar()
        self._week_names: tuple[str, ...] = STANDARD_WEEK_NAMES
        self._intercalary_rules: tuple[IntercalarySpec, ...] = ()
        self._year, self._month = MIN_YEAR, 1
        self._day_cells: dict[int, GameCalendarCell] = {}
        self._chips: dict[int, GameCalendarIntercalaryChip] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        nav = QHBoxLayout()
        nav.setContentsMargins(6, 4, 6, 4)
        nav.setSpacing(2)
        # One 32 px band for the whole row (NRI-0018 Д8): the arrows join the
        # library's square glyph gauge (28→32), the native combo/spinner/
        # checkbox clamp their height to the same value.
        self._prev_btn = QPushButton("◀")
        self._prev_btn.setFixedSize(NAV_ROW_HEIGHT, NAV_ROW_HEIGHT)
        self._prev_btn.clicked.connect(partial(self._step_month, -1))
        self._month_combo = QComboBox()
        self._month_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        self._month_combo.setFixedHeight(NAV_ROW_HEIGHT)
        self._month_combo.currentIndexChanged.connect(self._on_month_selected)
        self._year_spin = QSpinBox()
        self._year_spin.setRange(MIN_YEAR, MAX_YEAR)
        self._year_spin.setButtonSymbols(QSpinBox.ButtonSymbols.PlusMinus)
        self._year_spin.setFixedWidth(80)
        self._year_spin.setFixedHeight(NAV_ROW_HEIGHT)
        self._year_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._year_spin.valueChanged.connect(self._on_year_changed)
        self._next_btn = QPushButton("▶")
        self._next_btn.setFixedSize(NAV_ROW_HEIGHT, NAV_ROW_HEIGHT)
        self._next_btn.clicked.connect(partial(self._step_month, 1))
        self._bc_check = GameCalendarEraCheck("до н.э.")
        self._bc_check.setFixedHeight(NAV_ROW_HEIGHT)
        nav.addWidget(self._prev_btn)
        nav.addWidget(self._month_combo, 1)
        nav.addSpacing(8)
        nav.addWidget(self._year_spin)
        nav.addWidget(self._next_btn)
        nav.addSpacing(8)
        nav.addWidget(self._bc_check)
        layout.addLayout(nav)
        self._grid = QGridLayout()
        layout.addLayout(self._grid)
        self._bc_check.setVisible(show_era)

        self.refresh()

    # ── active calendar ─────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Re-read the ACTIVE game calendar (names included) and repaint.

        The popups call this on every open (spec «Имена перечитываются при
        показе»); a page past the new calendar's month count is clamped
        silently — the repaint stays a state refresh, not a navigation, so no
        ``page_changed`` noise.
        """
        self._calendar = current_calendar()
        spec = getattr(self._calendar, "spec", None)
        self._week_names = (
            STANDARD_WEEK_NAMES if spec is None else tuple(spec.week_names)
        )
        self._intercalary_rules = () if spec is None else tuple(spec.intercalary)
        self._month_combo.blockSignals(True)
        self._month_combo.clear()
        names = self._calendar.month_names
        for number in range(1, len(names) + 1):
            self._month_combo.addItem(names.get(number, str(number)), number)
        self._month_combo.blockSignals(False)
        self._month = max(1, min(self._month, len(names)))
        self._paint()
        self._sync_nav()

    # ── page navigation ─────────────────────────────────────────────────────

    def _month_count(self) -> int:
        """Number of months of the active calendar (its names table)."""
        return len(self._calendar.month_names)

    def _goto(self, year: int, month: int) -> None:
        year = max(MIN_YEAR, min(MAX_YEAR, year))
        month = max(1, min(self._month_count(), month))
        if (year, month) == (self._year, self._month):
            return
        self._year, self._month = year, month
        self._paint()
        self._sync_nav()
        self.page_changed.emit(self._year, self._month)

    def _step_month(self, delta: int, _checked: bool = False) -> None:
        year, month = self._year, self._month + delta
        if month < 1:
            year -= 1
            if year < MIN_YEAR:  # the scale simply stops at (1, first month)
                return
            month = self._month_count()
        elif month > self._month_count():
            year += 1
            if year > MAX_YEAR:
                return
            month = 1
        self._goto(year, month)

    def _on_month_selected(self, index: int) -> None:
        self._goto(self._year, int(self._month_combo.itemData(index)))

    def _on_year_changed(self, year: int) -> None:
        self._goto(year, self._month)

    def _sync_nav(self) -> None:
        self._month_combo.blockSignals(True)
        self._month_combo.setCurrentIndex(self._month - 1)
        self._month_combo.blockSignals(False)
        self._year_spin.blockSignals(True)
        self._year_spin.setValue(self._year)
        self._year_spin.blockSignals(False)

    # ── era flag (pure: never moves the page or the selection) ──────────────

    def is_bc(self) -> bool:
        """The chosen era: True = «до н.э.»."""
        return self._bc_check.isChecked()

    def set_era(self, is_bc: bool) -> None:
        """Pre-fill the era flag without touching the page or selection."""
        self._bc_check.setChecked(bool(is_bc))

    # ── coordinate contract ─────────────────────────────────────────────────

    def selection(self) -> GameCoord | None:
        """The selected coordinate (cell or chip), ``None`` = un-prefilled."""
        return self._selected

    def set_selection(
        self, coord: GameCoord | None = None, is_bc: bool | None = None
    ) -> None:
        """Pre-fill ``coord``: navigate to its page and mark its cell or
        chip; a coordinate the active calendar does not contain leaves the
        grid un-prefilled WITHOUT any crash or substitution (spec «Сетка
        говорит координатами»).  ``is_bc=None`` keeps the era flag as is."""
        if is_bc is not None:
            self.set_era(bool(is_bc))
        self._selected = self._prefillable(coord)
        if self._selected is not None:
            self._goto(self._selected.year, self._page_month(self._selected))
        self._apply_selection()

    def _prefillable(self, coord: GameCoord | None) -> GameCoord | None:
        if coord is None:
            return None
        coord = as_game_coord(coord)
        if self._calendar.is_valid(coord):
            return coord
        return None

    def _page_month(self, coord: GameCoord) -> int:
        """Page showing ``coord``: its own month, or the host month of an
        intercalary day (the validity gate already bounds the rule index)."""
        if isinstance(coord, MonthDay):
            return coord.month
        return self._intercalary_rules[coord.index].after_month

    def _select_coord(self, coord: GameCoord, _checked: bool = False) -> None:
        self._selected = coord
        self._apply_selection()
        self.day_selected.emit(coord)

    def set_page(self, year: int, month: int) -> None:
        """Navigate the shown page to ``(year, month)``, clamped to this
        calendar's scale (the year 1…9999 bound, the existing months).

        Public because the wizard's preview panel owes the spec a page it can
        only express as navigation: «текущая игровая дата, иначе год 1» — when
        the assembled calendar has no room for the current date, the panel
        lands on year 1 by navigating there, the same way its own ◀/▶ and
        month combo would.
        """
        self._goto(year, month)

    # ── painting ────────────────────────────────────────────────────────────

    def _apply_selection(self) -> None:
        selected = self._selected
        month_day = selected if isinstance(selected, MonthDay) else None
        intercalary = selected if isinstance(selected, IntercalaryDay) else None
        for day, cell in self._day_cells.items():
            _mark_selected(
                cell,
                month_day is not None
                and month_day.year == self._year
                and month_day.month == self._month
                and month_day.day == day,
            )
        for index, chip in self._chips.items():
            _mark_selected(
                chip,
                intercalary is not None
                and intercalary.year == self._year
                and intercalary.index == index,
            )

    def _clear_grid(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _paint(self) -> None:
        """Repaint the (year, month) page of the active calendar."""
        self._clear_grid()
        self._day_cells = {}
        self._chips = {}
        week_length = len(self._week_names)
        for column, name in enumerate(self._week_names):
            self._grid.addWidget(GameCalendarDayName(name), 0, column)

        year, month = self._year, self._month
        length = self._calendar.month_length(year, month)
        first_column = self._calendar.weekday(MonthDay(year, month, 1))
        last_week_row = 1 + (first_column + length - 1) // week_length
        occupied: set[tuple[int, int]] = set()
        for day in range(1, length + 1):
            position = first_column + day - 1
            slot = (1 + position // week_length, position % week_length)
            occupied.add(slot)
            cell = GameCalendarCell(str(day))
            # Non-clickable in the wizard's preview mode; empty week holes
            # below stay disabled regardless (spec «Минимализм оформления»).
            cell.setEnabled(self._interactive)
            cell.clicked.connect(partial(self._select_coord, MonthDay(year, month, day)))
            self._grid.addWidget(cell, *slot)
            self._day_cells[day] = cell
        for row in range(1, last_week_row + 1):
            for column in range(week_length):
                if (row, column) not in occupied:
                    hole = GameCalendarCell("")
                    hole.setEnabled(False)
                    self._grid.addWidget(hole, row, column)

        rules_on_page = [
            (index, rule)
            for index, rule in enumerate(self._intercalary_rules)
            if rule.after_month == month
        ]
        if rules_on_page:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            for index, rule in rules_on_page:
                chip = GameCalendarIntercalaryChip(rule.name)
                chip.setEnabled(self._interactive)
                chip.clicked.connect(partial(self._select_coord, IntercalaryDay(year, index)))
                row_layout.addWidget(chip)
                self._chips[index] = chip
            row_layout.addStretch()
            # Full-width row under the host month — chips never take a weekday
            # column (spec «Вставные дни строкой-плашкой»).
            self._grid.addWidget(row_widget, last_week_row + 1, 0, 1, week_length)
        # Every repaint recreates the buttons, so the selection state of the
        # shown page is re-applied here — not only via set_selection.
        self._apply_selection()
