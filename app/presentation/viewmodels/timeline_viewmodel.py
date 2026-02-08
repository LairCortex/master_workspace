"""Timeline ViewModel — manages the list of events, selection and date filtering."""
from __future__ import annotations

from datetime import date
from typing import Any, Sequence

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

    async def load_events(self) -> None:
        self._all_events = list(await self._event_service.get_all_events())
        self.events = list(self._all_events)
        self.events_changed.emit()

    def filter_by_dates(self, start: date | None, end: date | None) -> None:
        """Filter events by date range. None clears the filter."""
        if start is None or end is None:
            self.events = list(self._all_events)
        else:
            self.events = [
                e for e in self._all_events
                if e.start_date >= start and e.end_date <= end
            ]
        self.events_changed.emit()

    def select_event(self, index: int) -> None:
        if 0 <= index < len(self.events):
            self.selected_event = self.events[index]
        else:
            self.selected_event = None
        self.selected_event_changed.emit()
