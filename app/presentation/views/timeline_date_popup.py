"""The «Выбор даты» window popover on the island's Python side (Q2.5a D5).

Moved verbatim-mechanics from ``timeline_widget.py`` (change
port-event-timeline-qml-island-q2-5a, task 3.2): the two-tap live-apply pick,
the backwards-tap re-arm, «Сбросить», the current-window pre-fill and the
low-screen fallback are untouched. What moved is the ENTRY the popover hangs
on: the day chip is QML now, so the panel's facade opens this popover from a
GLOBAL RECTANGLE (the chip's, reported by the island — design D5
«позиция от прямоугольника чипа») instead of from a native anchor widget.
With the flat list (simplify-event-timeline-flat-list, task 3.4) the chip is
the popover's ONLY opener: the collapsed-gap pre-fill entry died with the
gaps, the picking mechanics did not.

Since piece C3b (design D3) the two calendars are game-calendar grids
(:class:`~app.presentation.views.calendar_grid.GameCalendarGrid`): the page
shows the ACTIVE calendar's months/week/intercalary chips and the bounds ride
as game coordinates — the two-tap mechanics kept word-for-word, only the
carrier changed (``QDate`` → ``GameCoord``).  The pre-fill paints the active
bounds' real pages and chips (no picture-only clamp any more); a bound the
calendar does not contain simply leaves its grid un-prefilled while the era
check box still mirrors it.

This stays the ONE documented widgets-popover exception (spec qml-shell
«QML-каркас приложения»): a QML popover would be clipped by the low island's
rectangle, while a top-level ``Qt.Popup`` window is not. It is skinned by the
application-wide popup sheet (W2a D2), whose rules address the named classes
below — ``_DateWindowPopup`` and ``_DateWindowResetButton`` are therefore
STYLE-FACING names (see ``compile_popup_qss``): renaming them silently drops
the popover's theme, so keep them exactly as they are.

NRI-0015 (spec event-timeline «Панель выбора даты имеет читаемые состояния»)
made its open states readable: P1 — a bound the window does not carry opens
its grid on the current game date's page (``_today_page``), not at «январь,
год 1»; P2 — both grids answer to a permanent «Начало окна»/«Конец окна»
caption from the first open frame; P3 — the popover is created without a
widget parent, so no chrome-attached ancestor's generic QPushButton rule can
leak through the stylesheet parent chain and accent-fill every cell (the
popover stays parent-less and popup-sheet-skinned).
"""
from __future__ import annotations

from datetime import date
from functools import partial

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from app.domain.date_era import cmp_era_dates
from app.domain.game_calendar import (
    MIN_YEAR,
    GameCoord,
    as_game_coord,
    current_calendar,
)
from app.presentation.utils.date_utils import (
    format_game_date,
    split_date_era,
)
from app.presentation.views.calendar_grid import GameCalendarGrid

# ── «Выбор даты» chip + popover captions (W3b D9; migrated with the popover) ─
#: Chip caption while no window is applied; the caret marks it as a dropdown
#: (spec «Выбор даты»: без окна кнопка отображает «Все дни»). The island's QML
#: chip renders this text, which the facade pushes onto the root as
#: ``windowText`` — Python stays the caption's single writer.
WINDOW_CHIP_ALL = "Все дни ▾"
#: Popover hint line guiding the two taps that pick the range (D9).
WINDOW_PICK_START = "Кликните дату начала"
WINDOW_PICK_END = "Кликните дату окончания"
WINDOW_RESET_TEXT = "Сбросить"
#: P2 (NRI-0015, spec «Панель выбора даты имеет читаемые состояния»): every
#: grid carries its own orienting caption from the first frame of the open —
#: the second grid used to carry no caption until the start had been picked.
#: The captions are constant; the only dynamic hint stays the tip label.
WINDOW_GRID_CAPTION_START = "Начало окна"
WINDOW_GRID_CAPTION_END = "Конец окна"
#: The popover stacks its two grids in one column, so both fit only when the
#: room under the chip covers ``2×`` a grid's height — below that the
#: low-screen fallback keeps a single grid and the taps assign the dates.
WINDOW_DOUBLE_HEIGHT_FACTOR = 2


def window_chip_text(start, end) -> str:
    """Chip caption for the active window: «Все дни ▾» or game-formatted bounds.

    Bounds ride as the popover applies them — a bare coordinate (== «н.э.»,
    since piece C3a a plain ``date`` of the same numbers) or a
    ``(coordinate, is_bc)`` pair (add-era-aware-dates, task 4.2): a BC bound
    prints with the «N г. до н.э.» suffix, an intercalary bound with its rule
    name (spec «Границы окна через эпохи» / «Отображение эры»)."""
    start_date, start_bc = split_date_era(start)
    end_date, end_bc = split_date_era(end)
    if start_date is None or end_date is None:
        return WINDOW_CHIP_ALL
    return (
        f"{format_game_date(start_date, is_bc=bool(start_bc))} — "
        f"{format_game_date(end_date, is_bc=bool(end_bc))} ▾"
    )


def _today_page() -> tuple[int, int]:
    """The page of the CURRENT game date in the ACTIVE calendar.

    P1 (NRI-0015, spec «Панель выбора даты имеет читаемые состояния»): an
    empty window opens its grids on the page containing today's numbers,
    not at the head of calendar history. The placement follows the wizard
    preview's documented convention «текущая игровая дата, иначе год 1» —
    an assembled calendar with no room for today's coordinate pages to
    year 1 instead (no second rule of its own).
    """
    today = as_game_coord(date.today())
    if current_calendar().is_valid(today):
        return today.year, today.month
    return MIN_YEAR, 1


class _DateWindowResetButton(QPushButton):
    """Named class so the app-wide popup sheet (W2a D2) can skin the reset:
    the sheet must never carry a generic ``QPushButton`` rule (canvas-proxy
    leak), so every popup-owned widget needs its own selector."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class _DateWindowPopup(QWidget):
    """Top-level two-grid range popover behind the «Выбор даты» chip
    (W3b D9; grids swapped from the Gregorian widget to the game calendar in
    piece C3b without touching the picking mechanics).

    A ``Qt.Popup`` window — dismiss on click-outside and Esc come from Qt; the
    grids are the shared ``GameCalendarGrid`` of the ACTIVE game calendar
    (its month names, week length, week names and intercalary chips included).
    Being top-level it is skinned by the application-wide popup sheet (named
    classes in ``compile_popup_qss``), not by an inline stylesheet, and it is
    not clipped by the island's narrow rectangle.

    Picking (D9): the first click arms the start, the second applies
    ``range_applied(start_pair, end_pair)`` and closes — the window lands
    LIVE, there is no «Применить» button; each bound is a ``(GameCoord,
    is_bc)`` pair carrying its own grid's independent «до н.э.» check box (Q9),
    and the backwards-check is chronological across the eras (design D2).
    An earlier second tap re-arms a new start instead of emitting a
    backwards range. «Сбросить» closes with ``range_applied(None,
    None)`` (chip returns to «Все дни» — the window's only reset, spec
    «Живое применение и сброс»). When the room under the chip cannot host
    both grids only one stays visible and the two taps assign start/finish
    there — the tip label mirrors the assignment.
    """

    range_applied = Signal(object, object)  # (start pair | None, end pair | None)

    def __init__(self) -> None:
        # P3 (NRI-0015, spec «Панель выбора даты имеет читаемые состояния»):
        # deliberately PARENT-LESS. A widget-parented top level still inherits
        # its parent's stylesheet chain, and the panel hosting the chip lives
        # under the chrome-attached central widget, whose generic
        # ``QWidget[uiRole="chrome"] QPushButton`` accent rule used to fill
        # EVERY day cell — the live audit P3 («в режиме «Все дни» всё залито
        # акцентным, выбранное и доступное сливаются»). Only the app-wide
        # popup sheet may skin this popover; the opener keeps the object alive
        # through its own attribute, exactly like the tooltip does.
        super().__init__(None, Qt.WindowType.Popup)
        self.setObjectName("timelineDateWindowPopup")  # identifier, not style
        # A plain QWidget only paints the sheet's background with the flag on.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._pending_start: tuple[GameCoord, bool] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        self.tip_label = QLabel(WINDOW_PICK_START)
        layout.addWidget(self.tip_label)
        # P2: a permanent caption over each grid, visible from the first open
        # frame — the second grid used to stay unlabelled until the start tap.
        self.start_hint_label = QLabel(WINDOW_GRID_CAPTION_START)
        self.end_hint_label = QLabel(WINDOW_GRID_CAPTION_END)
        self.start_calendar = GameCalendarGrid(self)
        self.end_calendar = GameCalendarGrid(self)
        layout.addWidget(self.start_hint_label)
        layout.addWidget(self.start_calendar)
        layout.addWidget(self.end_hint_label)
        layout.addWidget(self.end_calendar)
        reset_row = QHBoxLayout()
        reset_row.addStretch()
        self.reset_button = _DateWindowResetButton(WINDOW_RESET_TEXT)
        reset_row.addWidget(self.reset_button)
        layout.addLayout(reset_row)

        self.start_calendar.day_selected.connect(
            partial(self._on_day_clicked, self.start_calendar)
        )
        self.end_calendar.day_selected.connect(
            partial(self._on_day_clicked, self.end_calendar)
        )
        self.reset_button.clicked.connect(self._on_reset)

    # ── opening ─────────────────────────────────────────────────────────────

    def open_at(self, anchor_global: QRect, current: tuple | None = None) -> None:
        """Arm a fresh pick and drop the popover under a GLOBAL chip rectangle.

        ``anchor_global`` is the chip's rectangle in global coordinates — the
        QML chip reports its scene rect and the island's facade maps it (task
        3.2); the popover lands under its bottom-left, exactly where the old
        native-button anchor put it. ``current`` pre-fills the two grids with
        the ACTIVE window (the chip is the popover's only opener; the flat
        list deleted the collapsed-gap pre-fill along with the gaps), without
        applying anything: only taps inside the popover mutate the window.
        The grids re-read the ACTIVE game calendar on every open
        (``refresh`` covers month names and the week page set), so a rename
        while the panel stood idle is visible without any wiring around it.
        Each seeded bound paints its page and marks its real cell or
        intercalary chip with NO number substituted for the picture (spec
        event-timeline «Предзаполнение панелей»); an unrepresentable bound
        leaves its grid un-prefilled while the era check box of that very
        grid still mirrors the bound (the eras stay independent, Q9).
        """
        self._pending_start = None
        self.tip_label.setText(WINDOW_PICK_START)
        self.start_calendar.refresh()
        self.end_calendar.refresh()
        start, end = current or (None, None)
        for grid, value in ((self.start_calendar, start), (self.end_calendar, end)):
            day, is_bc = split_date_era(value)
            # ``set_selection`` navigates to and marks the bound's real page;
            # a coordinate the active calendar rejects simply leaves the grid
            # un-prefilled — never a rewritten number (piece C3b, design D3).
            grid.set_selection(day, bool(is_bc))
            if day is None:
                # P1: an absent bound opens its grid on the CURRENT game
                # date's page, never at «январь, год 1» — only a page walk
                # (no selection), so P3's no-fill empty window is preserved.
                grid.set_page(*_today_page())
        pos = QPoint(anchor_global.x(), anchor_global.y() + anchor_global.height() + 2)
        screen = QApplication.screenAt(pos)
        room = (
            screen.availableGeometry().bottom() - pos.y()
            if screen is not None else 0
        )
        self._fit_low_screen(room)
        self.adjustSize()
        if screen is not None:
            geo = screen.availableGeometry()
            pos.setX(max(geo.left(), min(pos.x(), geo.right() - self.width() + 1)))
        self.move(pos)
        self.show()

    def _fit_low_screen(self, available_below: int) -> None:
        """Low-screen fallback (D9 risk note): one grid, taps assign both.
        The end caption belongs to its grid and follows it off the screen."""
        need = WINDOW_DOUBLE_HEIGHT_FACTOR * self.start_calendar.sizeHint().height()
        both = available_below >= need
        self.end_hint_label.setVisible(both)
        self.end_calendar.setVisible(both)

    # ── tap handling ────────────────────────────────────────────────────────

    def _on_day_clicked(self, grid: GameCalendarGrid, coord: GameCoord) -> None:
        # Each bound carries its own grid's independent era flag (Q9); since
        # piece C3b the tapped cell or chip already IS the game coordinate
        # (design D3), so the backwards-check below compares coordinate pairs.
        chosen: tuple[GameCoord, bool] = (coord, grid.is_bc())
        if self._pending_start is None or cmp_era_dates(chosen, self._pending_start) < 0:
            # First tap arms the start; a second tap *chronologically before*
            # it (across the eras, design D2) re-arms a new start rather than
            # emitting a backwards range.  Both grids mirror the armed
            # coordinate on their pages; each keeps its own era flag (Q9).
            self._pending_start = chosen
            self.start_calendar.set_selection(coord)
            self.end_calendar.set_selection(coord)
            self.tip_label.setText(WINDOW_PICK_END)
            return
        self.range_applied.emit(self._pending_start, chosen)
        self.close()

    def _on_reset(self) -> None:
        self._pending_start = None
        self.range_applied.emit(None, None)
        self.close()
