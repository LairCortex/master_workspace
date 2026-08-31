"""Timeline ViewModel — manages the list of events, selection and date filtering."""
from __future__ import annotations

from datetime import date
from typing import Any

from PySide6.QtCore import QObject, Signal

from app.presentation.views.timeline_rows import Row, build_rows


class TimelineViewModel(QObject):
    events_changed = Signal()
    selected_event_changed = Signal()

    def __init__(self, event_service, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._event_service = event_service
        self._all_events: list[Any] = []
        self.events: list[Any] = []
        self.rows: list[Row] = []
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
        """Recompute the visible set and its derived rows, then keep the
        selection consistent with it.

        A selected event that fell out of the visible set is dropped here (and
        ``selected_event_changed`` fires), so the panel — which prunes the
        same id while re-modelling the new set — the ViewModel and the detail
        panel never disagree about what is selected (task 3.3).

        ``rows`` is the vertical scale's row projection (W3b task 4.1): the
        filter bounds seed ``build_rows`` when a range is live, otherwise the
        sample derives its own min–max range (spec «Диапазон без фильтра»).
        It is recomputed before ``events_changed`` so any consumer reading it
        from the signal sees data consistent with ``events``.
        """
        start, end = self._current_filter
        if start is None or end is None:
            self.events = list(self._all_events)
        else:
            self.events = [
                e for e in self._all_events
                if e.start_date >= start and (e.end_date is None or e.end_date <= end)
            ]
        self.rows = build_rows(self.events, start, end)
        self.events_changed.emit()
        if self.selected_event is not None:
            self.select_event_by_id(self.selected_event.id)

    def select_event_by_id(self, event_id: int | None) -> None:
        """Select by event id (W3 id-contract); a miss clears the selection."""
        self.selected_event = next(
            (e for e in self.events if e.id == event_id), None
        )
        self.selected_event_changed.emit()
