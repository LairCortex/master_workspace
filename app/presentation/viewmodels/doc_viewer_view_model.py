"""Sync VM for the doc-viewer QML island (R3 pack 1)."""
from __future__ import annotations

from PySide6.QtCore import QObject, Property, Signal


class DocViewerViewModel(QObject):
    textChanged = Signal()

    def __init__(self, text: str = "", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._text = text

    def _get_text(self) -> str:
        return self._text

    def _set_text(self, value: str) -> None:
        if self._text != value:
            self._text = value
            self.textChanged.emit()

    text = Property(str, _get_text, _set_text, notify=textChanged)
