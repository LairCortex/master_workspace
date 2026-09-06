"""Thin QObject bridge for the QML MentionField component."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, QPoint, QObject, Signal, Slot
from PySide6.QtWidgets import QWidget

from app.domain.mentions import parse, strip_brackets
from app.presentation.views.mention_popup import _MentionPopup


class MentionFieldHost(QObject):
    """Own storage/display mapping and the shared native completion popup."""

    storageChanged = Signal()
    displayChanged = Signal()
    spansChanged = Signal()
    popupVisibleChanged = Signal()
    modifiedChanged = Signal()
    searchRequested = Signal(str)
    mentionClicked = Signal(str, int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._storage = ""
        self._display = ""
        self._spans: list[dict[str, Any]] = []
        self._modified = False
        self._mention_start = -1
        self._cursor = 0
        self._popup_visible = False
        self._results: list[dict[str, Any]] = []
        self._result_index = 0
        self._widget: QWidget | None = None
        self._popup: _MentionPopup | None = None
        self._caret_point = QPoint()
        self._known_displays: dict[str, str] = {"": ""}

    def _get_storage(self) -> str:
        return self._storage

    def _set_storage(self, value: str) -> None:
        value = value or ""
        if value == self._storage and not self._modified:
            return
        self._apply_storage(value, reset_modified=True)

    storage = Property(str, _get_storage, _set_storage, notify=storageChanged)

    def _get_display(self) -> str:
        return self._display

    display = Property(str, _get_display, notify=displayChanged)

    def _get_spans(self):
        return self._spans

    spans = Property("QVariant", _get_spans, notify=spansChanged)

    def _get_popup_visible(self) -> bool:
        return self._popup_visible

    popupVisible = Property(bool, _get_popup_visible, notify=popupVisibleChanged)

    def _get_modified(self) -> bool:
        return self._modified

    modified = Property(bool, _get_modified, notify=modifiedChanged)

    @property
    def caretPoint(self) -> QPoint:
        return QPoint(self._caret_point)

    def attachWidget(self, widget: QWidget) -> None:
        """Attach the native popup to the QQuickWidget test/product island."""
        self._widget = widget
        if self.parent() is None:
            self.setParent(widget)

    def _apply_storage(self, value: str, *, reset_modified: bool) -> None:
        old_storage = self._storage
        old_display = self._display
        old_spans = self._spans
        self._storage = value
        self._display, self._spans = self._to_display(value)
        if old_storage != self._storage:
            self.storageChanged.emit()
        if old_display != self._display:
            self.displayChanged.emit()
        if old_spans != self._spans:
            self.spansChanged.emit()
        if reset_modified and self._modified:
            self._modified = False
            self.modifiedChanged.emit()
        if reset_modified:
            self._known_displays = {self._display: self._storage}

    @staticmethod
    def _to_display(storage: str) -> tuple[str, list[dict[str, Any]]]:
        parts: list[str] = []
        spans: list[dict[str, Any]] = []
        storage_cursor = 0
        display_cursor = 0
        for hit in parse(storage):
            plain = storage[storage_cursor:hit.start]
            parts.append(plain)
            display_cursor += len(plain)
            start = display_cursor
            parts.append(hit.display)
            display_cursor += len(hit.display)
            spans.append({
                "start": start,
                "end": display_cursor,
                "storageStart": hit.start,
                "storageEnd": hit.end,
                "display": hit.display,
                "type": hit.type,
                "id": hit.id,
            })
            storage_cursor = hit.end
        parts.append(storage[storage_cursor:])
        return "".join(parts), spans

    def _display_to_storage(self, position: int) -> int:
        delta = 0
        for span in self._spans:
            start = span["start"]
            end = span["end"]
            if position <= start:
                return position + delta
            if position < end:
                midpoint = start + (end - start) / 2
                return span["storageStart"] if position <= midpoint else span["storageEnd"]
            if position == end:
                return span["storageEnd"]
            delta += (
                span["storageEnd"] - span["storageStart"]
                - (span["end"] - span["start"])
            )
        return position + delta

    @Slot(str, int, bool, result=int)
    def updateDisplay(self, text: str, cursor: int, composing: bool = False) -> int:
        """Commit one plain-layer edit back to storage and return safe caret."""
        self._cursor = max(0, cursor)
        if composing:
            return self._cursor
        if text == self._display:
            self._detect_query(self._cursor)
            return self.snapCursor(self._cursor)
        if text in self._known_displays:
            self._apply_storage(self._known_displays[text], reset_modified=False)
            if not self._modified:
                self._modified = True
                self.modifiedChanged.emit()
            self._cursor = self.snapCursor(self._cursor)
            self._detect_query(self._cursor)
            return self._cursor

        old = self._display
        self._known_displays[old] = self._storage
        prefix = 0
        limit = min(len(old), len(text))
        while prefix < limit and old[prefix] == text[prefix]:
            prefix += 1
        suffix = 0
        while (
            suffix < len(old) - prefix
            and suffix < len(text) - prefix
            and old[len(old) - suffix - 1] == text[len(text) - suffix - 1]
        ):
            suffix += 1
        old_end = len(old) - suffix
        new_end = len(text) - suffix
        replacement = text[prefix:new_end]

        # A direct insertion inside a chip is rejected and the caret snaps.
        if prefix == old_end:
            for span in self._spans:
                if span["start"] < prefix < span["end"]:
                    safe = self.snapCursor(prefix)
                    self.displayChanged.emit()
                    return safe

        expanded_start, expanded_end = prefix, old_end
        for span in self._spans:
            if prefix < span["end"] and old_end > span["start"]:
                expanded_start = min(expanded_start, span["start"])
                expanded_end = max(expanded_end, span["end"])

        storage_start = self._display_to_storage(expanded_start)
        storage_end = self._display_to_storage(expanded_end)
        new_storage = (
            self._storage[:storage_start] + replacement + self._storage[storage_end:]
        )
        replacement_display, _ = self._to_display(replacement)
        safe_cursor = expanded_start + len(replacement_display)
        self._apply_storage(new_storage, reset_modified=False)
        self._known_displays[self._display] = self._storage
        if not self._modified:
            self._modified = True
            self.modifiedChanged.emit()
        self._cursor = self.snapCursor(safe_cursor)
        self._detect_query(self._cursor)
        return self._cursor

    @Slot(int, result=int)
    def snapCursor(self, position: int) -> int:
        for span in self._spans:
            if span["start"] < position < span["end"]:
                if position - span["start"] <= span["end"] - position:
                    return span["start"]
                return span["end"]
        return position

    @Slot(int, int, result="QVariant")
    def expandSelection(self, start: int, end: int):
        """Expand a display selection so every intersected chip is atomic."""
        expanded_start = min(start, end)
        expanded_end = max(start, end)
        for span in self._spans:
            if expanded_start < span["end"] and expanded_end > span["start"]:
                expanded_start = min(expanded_start, span["start"])
                expanded_end = max(expanded_end, span["end"])
        return [expanded_start, expanded_end]

    def _detect_query(self, cursor: int) -> None:
        prefix = self._display[:cursor]
        at = prefix.rfind("@")
        if at < 0:
            self.cancelMention()
            return
        query = prefix[at + 1:]
        if any(ch.isspace() for ch in query):
            self.cancelMention()
            return
        self._mention_start = at
        if len(query) >= 2:
            self.searchRequested.emit(query)
        elif self._popup_visible:
            self._hide_popup()

    @Slot(str, int, str)
    def insertMention(self, entity_type: str, entity_id: int, name: str) -> None:
        if self._mention_start < 0:
            return
        marker = f"@[{strip_brackets(name)}]({entity_type}:{entity_id}) "
        start = self._display_to_storage(self._mention_start)
        end = self._display_to_storage(self._cursor)
        self._apply_storage(
            self._storage[:start] + marker + self._storage[end:],
            reset_modified=False,
        )
        if not self._modified:
            self._modified = True
            self.modifiedChanged.emit()
        self._cursor = self._mention_start + len(strip_brackets(name)) + 1
        self._mention_start = -1
        self._hide_popup()

    @Slot("QVariant")
    def showResults(self, results) -> None:
        self._results = [dict(row) for row in (results or [])]
        self._result_index = 0
        if not self._results or self._mention_start < 0:
            self._hide_popup()
            return
        self._set_popup_visible(True)
        if self._widget is not None:
            popup = self._ensure_popup()
            popup.show_results(
                self._results,
                self._widget.mapToGlobal(self._caret_point),
            )

    def _ensure_popup(self) -> _MentionPopup:
        if self._popup is None:
            self._popup = _MentionPopup(self._widget)
            self._popup.item_selected.connect(self._insert_result)
        return self._popup

    def _insert_result(self, result: dict) -> None:
        self.insertMention(result["type"], int(result["id"]), result["name"])

    @Slot()
    def popupDown(self) -> None:
        if self._popup is not None:
            self._popup.select_next()
        if self._results:
            self._result_index = min(self._result_index + 1, len(self._results) - 1)

    @Slot()
    def popupUp(self) -> None:
        if self._popup is not None:
            self._popup.select_prev()
        self._result_index = max(self._result_index - 1, 0)

    @Slot()
    def confirmPopup(self) -> None:
        if not self._popup_visible or not self._results:
            return
        if self._popup is not None:
            self._popup.confirm_selection()
        else:
            self._insert_result(self._results[self._result_index])

    @Slot()
    def cancelMention(self) -> None:
        self._mention_start = -1
        self._hide_popup()

    def _hide_popup(self) -> None:
        if self._popup is not None:
            self._popup.hide()
        self._set_popup_visible(False)

    def _set_popup_visible(self, visible: bool) -> None:
        if visible == self._popup_visible:
            return
        self._popup_visible = visible
        self.popupVisibleChanged.emit()

    @Slot(str, int)
    def activateMention(self, entity_type: str, entity_id: int) -> None:
        self.mentionClicked.emit(entity_type, entity_id)

    @Slot(float, float, float)
    def setCaretRect(self, x: float, y: float, height: float) -> None:
        self._caret_point = QPoint(round(x), round(y + height + 4))
