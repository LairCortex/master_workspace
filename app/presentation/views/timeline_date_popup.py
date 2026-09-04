"""The «Выбор даты» window popover on the island's Python side (Q2.5a D5).

Moved verbatim-mechanics from ``timeline_widget.py`` (change
port-event-timeline-qml-island-q2-5a, task 3.2): the two-tap live-apply pick,
the backwards-tap re-arm, «Сбросить», the current-window/gap pre-fill and the
low-screen fallback are untouched. What moved is the ENTRY the popover hangs
on: the day chip is QML now, so the panel's facade opens this popover from a
GLOBAL RECTANGLE (the chip's, reported by the island — design D5
«позиция от прямоугольника чипа») instead of from a native anchor widget.

This stays the ONE documented widgets-popover exception (spec qml-shell
«QML-каркас приложения»): a QML popover would be clipped by the low island's
rectangle, while a top-level ``Qt.Popup`` window is not. It is skinned by the
application-wide popup sheet (W2a D2), whose rules address the named classes
below — ``_DateWindowPopup`` and ``_DateWindowResetButton`` are therefore
STYLE-FACING names (see ``compile_popup_qss``): renaming them silently drops
the popover's theme, so keep them exactly as they are.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, QPoint, QRect, Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from app.presentation.utils.date_utils import format_game_date
from app.presentation.views.custom_date_edit import _CustomCalendar

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
#: The popover stacks its two calendars in one column, so both fit only when
#: the room under the chip covers ``2×`` a calendar's height — below that the
#: low-screen fallback keeps a single calendar and the taps assign the dates.
WINDOW_DOUBLE_HEIGHT_FACTOR = 2


def window_chip_text(start: date | None, end: date | None) -> str:
    """Chip caption for the active window: «Все дни ▾» or game-formatted bounds."""
    if start is None or end is None:
        return WINDOW_CHIP_ALL
    return f"{format_game_date(start)} — {format_game_date(end)} ▾"


class _DateWindowResetButton(QPushButton):
    """Named class so the app-wide popup sheet (W2a D2) can skin the reset:
    the sheet must never carry a generic ``QPushButton`` rule (canvas-proxy
    leak), so every popup-owned widget needs its own selector."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class _DateWindowPopup(QWidget):
    """Top-level two-calendar range popover behind the «Выбор даты» chip
    (W3b D9; entry re-pointed to the QML chip by task 3.2 without touching
    the picking mechanics).

    A ``Qt.Popup`` window — dismiss on click-outside and Esc come from Qt; the
    calendars are the game-skinned ``_CustomCalendar`` reused from
    ``custom_date_edit`` (custom month names included). Being top-level it is
    skinned by the application-wide popup sheet (named classes in
    ``compile_popup_qss``), not by an inline stylesheet, and it is not clipped
    by the island's narrow rectangle.

    Picking (D9): the first click arms the start, the second applies
    ``range_applied(start, end)`` and closes — the window lands LIVE, there is
    no «Применить» button; an earlier second tap re-arms a new start instead of
    emitting a backwards range. «Сбросить» closes with ``range_applied(None,
    None)`` (chip returns to «Все дни» — the window's only reset, spec
    «Живое применение и сброс»). When the room under the chip cannot host
    both calendars only one stays visible and the two taps assign start/finish
    there — the tip label mirrors the assignment.
    """

    range_applied = Signal(object, object)  # (start date | None, end date | None)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("timelineDateWindowPopup")  # identifier, not style
        # A plain QWidget only paints the sheet's background with the flag on.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._pending_start: date | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        self.tip_label = QLabel(WINDOW_PICK_START)
        layout.addWidget(self.tip_label)
        self.start_calendar = _CustomCalendar(self)
        self.end_calendar = _CustomCalendar(self)
        layout.addWidget(self.start_calendar)
        layout.addWidget(self.end_calendar)
        reset_row = QHBoxLayout()
        reset_row.addStretch()
        self.reset_button = _DateWindowResetButton(WINDOW_RESET_TEXT)
        reset_row.addWidget(self.reset_button)
        layout.addLayout(reset_row)

        self.start_calendar.clicked.connect(self._on_day_clicked)
        self.end_calendar.clicked.connect(self._on_day_clicked)
        self.reset_button.clicked.connect(self._on_reset)

    # ── opening ─────────────────────────────────────────────────────────────

    def open_at(self, anchor_global: QRect, current: tuple | None = None) -> None:
        """Arm a fresh pick and drop the popover under a GLOBAL chip rectangle.

        ``anchor_global`` is the chip's rectangle in global coordinates — the
        QML chip reports its scene rect and the island's facade maps it (task
        3.2); the popover lands under its bottom-left, exactly where the old
        native-button anchor put it. ``current`` pre-fills the two calendars
        (the active window on a chip click, the gap bounds on a collapsed-gap
        click — task 7.1), without applying anything: only taps inside the
        popover mutate the window. Month names are re-read on every open
        (``refresh_month_names`` reads the process-global map), so a rename
        while the panel stood idle is visible without any wiring around it.
        """
        self._pending_start = None
        self.tip_label.setText(WINDOW_PICK_START)
        self.start_calendar.refresh_month_names()
        self.end_calendar.refresh_month_names()
        start, end = current or (None, None)
        for cal, day in ((self.start_calendar, start), (self.end_calendar, end)):
            if day is not None:
                qday = QDate(day.year, day.month, day.day)
                cal.setSelectedDate(qday)
                cal.setCurrentPage(qday.year(), qday.month())
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
        """Low-screen fallback (D9 risk note): one calendar, taps assign both."""
        need = WINDOW_DOUBLE_HEIGHT_FACTOR * self.start_calendar.sizeHint().height()
        self.end_calendar.setVisible(available_below >= need)

    # ── tap handling ────────────────────────────────────────────────────────

    def _on_day_clicked(self, qdate: QDate) -> None:
        chosen = qdate.toPython()
        if self._pending_start is None or chosen < self._pending_start:
            # First tap arms the start; a second tap *before* it re-arms a new
            # start rather than emitting a backwards range.
            self._pending_start = chosen
            self.start_calendar.setSelectedDate(qdate)
            self.end_calendar.setSelectedDate(qdate)
            self.tip_label.setText(WINDOW_PICK_END)
            return
        self.range_applied.emit(self._pending_start, chosen)
        self.close()

    def _on_reset(self) -> None:
        self._pending_start = None
        self.range_applied.emit(None, None)
        self.close()
