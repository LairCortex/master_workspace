"""Application state — shared state across ViewModels and Views."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal


class AppState(QObject):
    """Singleton-like shared state object."""

    current_event_changed = Signal(object)
    events_updated = Signal()
    search_results_changed = Signal(dict)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._current_event: Any | None = None

    @property
    def current_event(self):
        return self._current_event

    @current_event.setter
    def current_event(self, value):
        self._current_event = value
        self.current_event_changed.emit(value)
