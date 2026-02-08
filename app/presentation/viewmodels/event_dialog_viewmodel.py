"""EventDialog ViewModel — validates and saves new/edited events."""
from __future__ import annotations

from datetime import date
from typing import Any

from PySide6.QtCore import QObject, Signal


class EventDialogViewModel(QObject):
    validity_changed = Signal(bool)

    def __init__(self, event_service, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._event_service = event_service
        self.name: str = ""
        self.characteristics: str = ""
        self.backstory: str = ""
        self.start_date: date | None = None
        self.end_date: date | None = None

    @property
    def is_valid(self) -> bool:
        if not self.name:
            return False
        if self.start_date is None or self.end_date is None:
            return False
        if self.end_date < self.start_date:
            return False
        if not self.characteristics and not self.backstory:
            return False
        return True

    async def save(self) -> Any | None:
        if not self.is_valid:
            return None
        return await self._event_service.create_event(
            name=self.name,
            characteristics=self.characteristics,
            backstory=self.backstory,
            start_date=self.start_date,
            end_date=self.end_date,
        )
