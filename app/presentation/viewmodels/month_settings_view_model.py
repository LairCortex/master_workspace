"""Sync VM for the month-settings QML island (R3 pack 1)."""
from __future__ import annotations

from typing import Dict

from PySide6.QtCore import QObject, Property, Signal, Slot

from app.presentation.utils.date_utils import DEFAULT_MONTHS


class MonthSettingsViewModel(QObject):
    namesChanged = Signal()
    saved = Signal(object)

    def __init__(
        self,
        current_months: Dict[int, str] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        months = current_months or DEFAULT_MONTHS
        self._names: list[str] = []
        for i in range(1, 13):
            default = DEFAULT_MONTHS[i]
            custom = months.get(i, default)
            self._names.append("" if custom == default else custom)

    def _get_names(self) -> list[str]:
        return list(self._names)

    names = Property("QVariant", _get_names, notify=namesChanged)

    @Slot(int, result=str)
    def nameAt(self, index: int) -> str:
        if 0 <= index < 12:
            return self._names[index]
        return ""

    @Slot(int, result=str)
    def placeholderAt(self, index: int) -> str:
        if 0 <= index < 12:
            return DEFAULT_MONTHS[index + 1]
        return ""

    @Slot(int, str)
    def setName(self, index: int, text: str) -> None:
        if 0 <= index < 12 and self._names[index] != text:
            self._names[index] = text
            self.namesChanged.emit()

    @Slot()
    def reset(self) -> None:
        self._names = [""] * 12
        self.namesChanged.emit()

    def collect(self) -> Dict[int, str]:
        result: Dict[int, str] = {}
        for i, text in enumerate(self._names, start=1):
            stripped = text.strip()
            result[i] = stripped if stripped else DEFAULT_MONTHS[i]
        return result

    @Slot()
    def save(self) -> None:
        self.saved.emit(self.collect())
