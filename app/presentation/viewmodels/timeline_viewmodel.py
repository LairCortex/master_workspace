"""Timeline ViewModel — manages the list of events, selection and date filtering."""
from __future__ import annotations

from datetime import date
from typing import Any

from PySide6.QtCore import QObject, Signal


class TimelineViewModel(QObject):
    events_changed = Signal()
    selected_event_changed = Signal()

    def __init__(self, event_service, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._event_service = event_service
        self._all_events: list[Any] = []
        self.events: list[Any] = []
        self.selected_event: Any | None = None
        self._current_filter: tuple[date | None, date | None] = (None, None)

    async def load_events(self) -> None:
        self._all_events = list(await self._event_service.get_all_events())
        self._apply_filter()

    def filter_by_dates(self, start: date | None, end: date | None) -> None:
        """Filter events by date range. None clears the filter."""
        self._current_filter = (start, end)
        self._apply_filter()

    def _apply_filter(self) -> None:
        """Recompute the visible set, then keep the selection consistent with it.

        A selected event that fell out of the visible set is dropped here (and
        ``selected_event_changed`` fires), so the canvas — which prunes the
        same id on ``set_events`` — the ViewModel and the detail panel never
        disagree about what is selected (task 3.3).
        """
        start, end = self._current_filter
        if start is None or end is None:
            self.events = list(self._all_events)
        else:
            self.events = [
                e for e in self._all_events
                if e.start_date >= start and (e.end_date is None or e.end_date <= end)
            ]
        self.events_changed.emit()
        if self.selected_event is not None:
            self.select_event_by_id(self.selected_event.id)

    def select_event_by_id(self, event_id: int | None) -> None:
        """Select by event id (W3 id-contract); a miss clears the selection."""
        self.selected_event = next(
            (e for e in self.events if e.id == event_id), None
        )
        self.selected_event_changed.emit()
