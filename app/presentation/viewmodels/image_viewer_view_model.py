"""Sync VM for the image-viewer QML island (R3 pack 1)."""
from __future__ import annotations

from PySide6.QtCore import QObject, Property, Signal


class ImageViewerViewModel(QObject):
    sourceChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._source = ""
        self._used_preview = False
        self._unavailable = True

    def _get_source(self) -> str:
        return self._source

    source = Property(str, _get_source, notify=sourceChanged)

    def _get_used_preview(self) -> bool:
        return self._used_preview

    usedPreview = Property(bool, _get_used_preview, notify=sourceChanged)

    def _get_unavailable(self) -> bool:
        return self._unavailable

    unavailable = Property(bool, _get_unavailable, notify=sourceChanged)

    def set_source(self, source: str, *, used_preview: bool, unavailable: bool) -> None:
        self._source = source
        self._used_preview = used_preview
        self._unavailable = unavailable
        self.sourceChanged.emit()
