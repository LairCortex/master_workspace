"""Top-level single-date popup used by QML date fields.

Since piece C3b (design D3) the popup hosts the game-calendar day grid
(:class:`~app.presentation.views.calendar_grid.GameCalendarGrid`) instead of
the Gregorian Qt calendar widget: the bridge currency is a game coordinate in
both directions — pre-filling takes a coordinate (or a bare ``date`` of the
same numbers, coerced by ``split_date_era``/``as_game_coord``) and a click
hands the consumer a ``(GameCoord, is_bc)`` pair.  The old picture-only
pre-fill clamp is gone: the grid paints any valid coordinate of the ACTIVE
calendar itself — an intercalary day included as its chip highlight — and a
coordinate the calendar does not contain (a year outside 1…9999 foremost)
simply leaves the popup un-prefilled.  The era stays the grid's own «до н.э.»
check box — a pure flag that never moves the page.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from app.domain.game_calendar import GameCoord
from app.presentation.utils.date_utils import split_date_era
from app.presentation.views.calendar_grid import GameCalendarGrid


class ThemeDatePopup(QWidget):
    """One reusable game-calendar grid, positioned wholly inside available geometry."""

    #: ``(GameCoord, is_bc)`` — the popup hands its bridge a (coordinate, era)
    #: pair (design D3): the clicked cell or chip carries its pure game
    #: coordinate, the era is read off the grid's own era flag at emit time.
    date_selected = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("themeDatePopup")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self.calendar = GameCalendarGrid(self)
        layout.addWidget(self.calendar)
        self.calendar.day_selected.connect(self._on_day_selected)

    def open_at(
        self,
        anchor_global: QRect,
        current: GameCoord
        | date
        | tuple[GameCoord | date | None, bool]
        | None = None,
    ) -> None:
        """Refresh, prefill and open below a global QML anchor rectangle.

        ``current`` is the bridge's (coordinate, era) pair — the month names
        and the whole page set are re-read from the ACTIVE calendar on every
        open (spec «Имена перечитываются при показе»).  Prefilling paints the
        coordinate's real cell or intercalary chip without substituting any
        number for the picture; a coordinate outside the calendar's validity
        (or no coordinate at all) leaves the grid un-prefilled, and the check
        box takes the era without moving the page (spec «Переключатель эры —
        чистый флаг»).
        """
        # refresh() reads the active calendar first (its page-month clamp runs
        # before the pre-fill can navigate anywhere).
        self.calendar.refresh()
        coord, is_bc = split_date_era(current)
        self.calendar.set_selection(coord, bool(is_bc))

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

    def _on_day_selected(self, coord: GameCoord) -> None:
        self.date_selected.emit((coord, self.calendar.is_bc()))
        self.close()
