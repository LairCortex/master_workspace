"""EventDialog ViewModel — validates and saves new/edited events."""
from __future__ import annotations

from datetime import date
from typing import Any

from PySide6.QtCore import QObject, Signal

from app.domain.date_era import cmp_era_dates


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
        # Era-free legacy VM (no start_bc/end_bc fields): both operands read
        # as «н.э.», but the check still goes through the single chronological
        # helper so no raw date comparison lives outside app/domain/date_era.py
        # (add-era-aware-dates, design D2).
        if cmp_era_dates((self.end_date, False), (self.start_date, False)) < 0:
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
