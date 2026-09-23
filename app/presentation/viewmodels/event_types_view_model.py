"""Sync VM for the event-types QML island (R3 pack 2, design D2/D6).

The thin state half of ``EventTypesDialog``: the row model (roles
``id``/``name``/``colorIndex``), the current selection, the rename field's
text and the availability flags of the four set actions — mirroring the rules
the retired widgets ``_reflect`` carried (remove needs a selection, ↑/↓ need
a neighbour in that direction).

Every user action leaves here as a *synchronous request signal*; the facade
owns ``EventService``, the injected ``_run``, the coroutines and the reload,
so this object never sees a service, a coroutine or a QML type (spec
qml-shell «Контракт биндингов», «VM не знает про QML»). Write-through: there
is no Save, no dirty state and no revert to model.
"""
from __future__ import annotations

from typing import Any, Sequence

from PySide6.QtCore import QObject, Property, Signal, Slot

from app.presentation.theme.compiler import CHART_TOKEN_KEYS

#: Size of the closed type palette — ``color.chart.1…8``. The island's swatch
#: ``Repeater`` reads it from here, so the palette set is declared once.
PALETTE_SIZE = len(CHART_TOKEN_KEYS)


class EventTypesViewModel(QObject):
    """Rows + selection + name text + action availability, requests out."""

    rowsChanged = Signal()
    selectionChanged = Signal()
    nameTextChanged = Signal()
    flagsChanged = Signal()

    #: Requests the facade answers with the existing service operations.
    addRequested = Signal(str)
    renameRequested = Signal(int, str)
    recolorRequested = Signal(int, int)
    moveRequested = Signal(int, int)
    removeRequested = Signal(int)
    closeRequested = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: list[dict] = []
        self._index = -1
        self._name_text = ""
        self._flag_state = self._compute_flags()

    # ---- QML surface ----

    def _get_rows(self) -> list[dict]:
        return self._rows

    rows = Property("QVariant", _get_rows, notify=rowsChanged)

    def _get_selected_id(self) -> Any:
        # QVariant: "no selection" reaches QML as null, not 0/-1.
        return self.selected_id

    selectedId = Property("QVariant", _get_selected_id, notify=selectionChanged)

    def _get_selected_color_index(self) -> int:
        row = self._selected_row_data()
        return 0 if row is None else row["colorIndex"]

    selectedColorIndex = Property(
        int, _get_selected_color_index, notify=selectionChanged
    )

    def _get_name_text(self) -> str:
        return self._name_text

    nameText = Property(str, _get_name_text, notify=nameTextChanged)

    def _get_has_selection(self) -> bool:
        return self._selected_row_data() is not None

    hasSelection = Property(bool, _get_has_selection, notify=flagsChanged)

    canRemove = Property(bool, _get_has_selection, notify=flagsChanged)

    def _get_can_move_up(self) -> bool:
        return self._get_has_selection() and self._index > 0

    canMoveUp = Property(bool, _get_can_move_up, notify=flagsChanged)

    def _get_can_move_down(self) -> bool:
        return self._get_has_selection() and self._index < len(self._rows) - 1

    canMoveDown = Property(bool, _get_can_move_down, notify=flagsChanged)

    def _get_palette_size(self) -> int:
        return PALETTE_SIZE

    paletteSize = Property(int, _get_palette_size, constant=True)

    # ---- QML entrances (sync slots only) ----

    @Slot(int)
    def select(self, index: int) -> None:
        """Select a row; anything outside the list means "no selection"."""
        if not 0 <= index < len(self._rows):
            index = -1
        self._set_index(index)

    @Slot(str)
    def setNameText(self, text: str) -> None:  # noqa: N802 (QML naming)
        if text == self._name_text:
            return
        self._name_text = text
        self.nameTextChanged.emit()

    @Slot()
    def requestAdd(self) -> None:  # noqa: N802
        """Add the type named in the field (the facade names an empty one)."""
        self.addRequested.emit(self._name_text.strip())

    @Slot()
    def requestRename(self) -> None:  # noqa: N802
        row = self._selected_row_data()
        name = self._name_text.strip()
        if row is None or not name or name == row["name"]:
            return
        self.renameRequested.emit(row["id"], name)

    @Slot(int)
    def requestRecolor(self, color_index: int) -> None:  # noqa: N802
        row = self._selected_row_data()
        if row is None or not 1 <= color_index <= PALETTE_SIZE:
            return
        if row["colorIndex"] == color_index:
            return
        self.recolorRequested.emit(row["id"], color_index)

    @Slot(int)
    def requestMove(self, delta: int) -> None:  # noqa: N802
        row = self._selected_row_data()
        if row is None or not 0 <= self._index + delta < len(self._rows):
            return
        self.moveRequested.emit(row["id"], delta)

    @Slot()
    def requestRemove(self) -> None:  # noqa: N802
        row = self._selected_row_data()
        if row is None:
            return
        self.removeRequested.emit(row["id"])

    @Slot()
    def requestClose(self) -> None:  # noqa: N802
        self.closeRequested.emit()

    # ---- Python (facade / tests) contract ----

    @property
    def selected_id(self) -> int | None:
        row = self._selected_row_data()
        return None if row is None else row["id"]

    @property
    def selected_row(self) -> int:
        return self._index

    @property
    def selected_name(self) -> str | None:
        row = self._selected_row_data()
        return None if row is None else row["name"]

    def set_rows(self, types: Sequence[Any]) -> None:
        """Rebuild the model from the service rows, keeping selection by id."""
        selected = self.selected_id
        self._rows = [
            {"id": t.id, "name": t.name, "colorIndex": t.color_index} for t in types
        ]
        self._index = self._index_of_id(selected)
        self.rowsChanged.emit()
        self.selectionChanged.emit()
        self._reflect_name()
        self._recompute_flags()

    def select_by_id(self, type_id: int) -> None:
        """Move the selection onto ``type_id``; an unknown id is a no-op."""
        index = self._index_of_id(type_id)
        if index == -1:
            return
        self._set_index(index)

    # ---- internals ----

    def _selected_row_data(self) -> dict | None:
        if 0 <= self._index < len(self._rows):
            return self._rows[self._index]
        return None

    def _index_of_id(self, type_id: int | None) -> int:
        if type_id is None:
            return -1
        for index, row in enumerate(self._rows):
            if row["id"] == type_id:
                return index
        return -1

    def _set_index(self, index: int) -> None:
        if index == self._index:
            return
        self._index = index
        self.selectionChanged.emit()
        self._reflect_name()
        self._recompute_flags()

    def _reflect_name(self) -> None:
        """Mirror the selection into the rename field (the old ``_reflect``)."""
        self.setNameText(self.selected_name or "")

    def _compute_flags(self) -> tuple[bool, bool, bool]:
        return (
            self._get_has_selection(),
            self._get_can_move_up(),
            self._get_can_move_down(),
        )

    def _recompute_flags(self) -> None:
        # Qt notify semantics: flagsChanged only when a flag value moves.
        state = self._compute_flags()
        if state != self._flag_state:
            self._flag_state = state
            self.flagsChanged.emit()
