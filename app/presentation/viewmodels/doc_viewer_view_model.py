"""Sync VM for the doc-viewer QML island (R3 pack 1).

The island shows rendered markup, not the source: the VM keeps the raw
document text (``text`` — the file content, still the continuity pin of the
viewer) and publishes the RichText rendering of it (``html``, produced by
the single Qt-md4c converter in ``presentation.utils.doc_html``). Both faces
travel the same write, so the source and the rendered half can never drift.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Property, Signal

from app.presentation.utils.doc_html import build_doc_html


class DocViewerViewModel(QObject):
    textChanged = Signal()
    htmlChanged = Signal()

    def __init__(self, text: str = "", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._text = text
        self._html = build_doc_html(text)

    def _get_text(self) -> str:
        return self._text

    def _set_text(self, value: str) -> None:
        if self._text != value:
            self._text = value
            self._html = build_doc_html(value)
            self.textChanged.emit()
            self.htmlChanged.emit()

    text = Property(str, _get_text, _set_text, notify=textChanged)

    def _get_html(self) -> str:
        return self._html

    html = Property(str, _get_html, notify=htmlChanged)
