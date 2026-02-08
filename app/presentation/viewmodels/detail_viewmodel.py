"""Detail ViewModel — loads related entities for a selected event."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal


class DetailViewModel(QObject):
    details_changed = Signal()

    def __init__(self, event_service, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._event_service = event_service
        self.event: Any | None = None
        self.organizations: list[Any] = []
        self.characters: list[Any] = []
        self.items: list[Any] = []
        self.locations: list[Any] = []

    async def load_details(self, event_id: int) -> None:
        self.event = await self._event_service.get_event(event_id)
        if self.event is not None:
            self.organizations = list(self.event.organizations)
            self.characters = list(self.event.characters)
            self.items = list(self.event.items)
            self.locations = list(self.event.locations)
        else:
            self.organizations = []
            self.characters = []
            self.items = []
            self.locations = []
        self.details_changed.emit()
