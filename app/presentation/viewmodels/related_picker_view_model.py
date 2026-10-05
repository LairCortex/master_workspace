"""RelatedPickerViewModel — the candidate rows of the «Выберите <тип>» sheet.

PR-020: the binding picker left the widgets ``QListWidget`` behind (its virtual
cells never reached the cocoa projection — no name, no press, the AT user could
not link an entity). Its rows are ``RowItem`` delegates now, and this VM is the
state the island binds: the flat candidate rows (roles ``id``/``label``, the
same duck the retired QListWidgetItem carried: name falls back to ``str``, id
to ``None``) and the multi-selection the sheet keeps while it is open.

The selection is the list of selected row indexes, ``selectedIndex`` — the
list widget's MultiSelection toggle semantics moved here verbatim: a single
click flips only its own row, everything else keeps its tick. The press of a
row additionally selects it (a tree press arrives without a prior click), the
commit itself stays facade-side: it walks the candidates in order and adds
exactly the ones whose id the selection carries — the retired dialog's
apply_selection loop, one knowledge kept where the choice is committed.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Property, Signal, Slot


class RelatedPickerViewModel(QObject):
    """Candidate rows + the open sheet's multi-selection."""

    rowsChanged = Signal()
    selectionChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self._selected: set[int] = set()

    # ---- QML surface ----

    def _get_rows(self) -> list[dict[str, Any]]:
        return self._rows

    rows = Property("QVariant", _get_rows, notify=rowsChanged)

    def _get_selected_index(self) -> list[int]:
        return sorted(self._selected)

    selectedIndex = Property("QVariant", _get_selected_index, notify=selectionChanged)

    # ---- QML in-calls (sync slots, spec qml-shell) ----

    @Slot(int)
    def toggleRow(self, index: int) -> None:  # noqa: N802 — Qt slot casing
        """Flip one row's tick, others untouched (MultiSelection's click)."""
        if not 0 <= index < len(self._rows):
            return
        if index in self._selected:
            self._selected.discard(index)
        else:
            self._selected.add(index)
        self.selectionChanged.emit()

    @Slot(int)
    def selectRow(self, index: int) -> None:  # noqa: N802 — Qt slot casing
        """Tick a row for good (the accessibility press selects before it
        activates — a press reaches the row with no click behind it)."""
        if not 0 <= index < len(self._rows) or index in self._selected:
            return
        self._selected.add(index)
        self.selectionChanged.emit()

    # ---- Python (facade) contract ----

    def load(self, entities: list[Any]) -> None:
        """Fill the rows from the candidates, the selection starts empty."""
        self._rows = [
            {
                "id": getattr(entity, "id", None),
                "label": getattr(entity, "name", str(entity)),
            }
            for entity in entities
        ]
        self._selected = set()
        self.rowsChanged.emit()

    def selected_entities(self, candidates: list[Any]) -> list[Any]:
        """The chosen entities in candidate order (the retired picker's
        apply_selection walked the same list, so the section receives the
        same order as before)."""
        chosen_ids = {
            self._rows[index]["id"]
            for index in self._selected
            if 0 <= index < len(self._rows)
        }
        return [
            entity
            for entity in candidates
            if getattr(entity, "id", None) in chosen_ids
        ]
