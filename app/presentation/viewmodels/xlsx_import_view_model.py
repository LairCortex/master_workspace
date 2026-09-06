"""Sync VM for the xlsx-import QML island (R3 pack 1)."""
from __future__ import annotations

from PySide6.QtCore import QObject, Property, Signal, Slot


class XlsxImportViewModel(QObject):
    pathChanged = Signal()
    progressChanged = Signal()
    formatChanged = Signal()
    importRequested = Signal(str)
    browseRequested = Signal()

    def __init__(self, format_text: str = "", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._format = format_text
        self._path = ""
        self._progress = 0
        self._progress_visible = False
        self._import_enabled = True

    def _get_format(self) -> str:
        return self._format

    formatText = Property(str, _get_format, notify=formatChanged)

    def _get_path(self) -> str:
        return self._path

    def _set_path(self, value: str) -> None:
        if self._path != value:
            self._path = value
            self.pathChanged.emit()

    path = Property(str, _get_path, _set_path, notify=pathChanged)

    def _get_progress(self) -> int:
        return self._progress

    progress = Property(int, _get_progress, notify=progressChanged)

    def _get_progress_visible(self) -> bool:
        return self._progress_visible

    progressVisible = Property(bool, _get_progress_visible, notify=progressChanged)

    def _get_import_enabled(self) -> bool:
        return self._import_enabled

    importEnabled = Property(bool, _get_import_enabled, notify=progressChanged)

    @Slot()
    def requestBrowse(self) -> None:
        self.browseRequested.emit()

    @Slot()
    def requestImport(self) -> None:
        self.importRequested.emit(self._path.strip())

    def set_progress(self, current: int, total: int) -> None:
        self._progress = int(100 * current / total) if total > 0 else 0
        self.progressChanged.emit()

    def begin_import(self) -> None:
        self._import_enabled = False
        self._progress_visible = True
        self._progress = 0
        self.progressChanged.emit()
