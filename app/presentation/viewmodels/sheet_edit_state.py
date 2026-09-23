"""Plain (no-Qt) carriers of the editor's edit state (audit B4, task 6.5.2).

The history stacks, the current selection and the field clipboard used to be
bare list attributes on :class:`CharacterSheetViewModel`, their semantics only
visible through scattered mutations. They now live here as small classes the
view model delegates to — unit-testable without a ``QApplication``; the view
model keeps sole ownership of signal emission.
"""
from __future__ import annotations

from typing import Any, Iterable

#: A layout checkpoint: ``(pages_json, orientation)`` as produced by
#: ``CharacterSheetViewModel._layout_snapshot``.
Snapshot = tuple[str, str]


class LayoutHistory:
    """Undo/redo stacks with the one trimming rule.

    Only the undo branch is length-limited (pushing past ``limit`` drops the
    oldest checkpoint); pushing onto the undo branch clears the redo branch
    unless the caller is itself unwinding it (:meth:`take_redo` pairs with a
    ``clear_redo=False`` push).
    """

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._undo: list[Snapshot] = []
        self._redo: list[Any] = []

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def push_undo(self, snap: Snapshot, *, clear_redo: bool = True) -> None:
        self._undo.append(snap)
        if len(self._undo) > self._limit:
            self._undo.pop(0)
        if clear_redo:
            self._redo.clear()

    def push_redo(self, snap: Any) -> None:
        """Park the current layout as the redo counterweight (uncapped)."""
        self._redo.append(snap)

    def take_undo(self) -> Snapshot:
        return self._undo.pop()

    def take_redo(self) -> Any:
        return self._redo.pop()

    def drop_top_if_matches(self, current: Any) -> bool:
        """Discard a leading checkpoint a finished gesture left unchanged
        (the gesture reserved a slot that turned out to be a no-op)."""
        if self._undo and self._undo[-1] == current:
            self._undo.pop()
            return True
        return False

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()


class SelectionModel:
    """The ordered field-id selection.

    :attr:`ids` exposes the live list so the view model's in-place
    ``append``/``remove`` transitions keep working; :meth:`set` replaces the
    selection wholesale (the single-field ``select`` and the paste/duplicate
    "select the new ones" writes).
    """

    def __init__(self) -> None:
        self._ids: list[str] = []

    @property
    def ids(self) -> list[str]:
        return self._ids

    def set(self, ids: Iterable[str]) -> None:
        self._ids[:] = ids

    @property
    def primary(self) -> str | None:
        """The canonical id when exactly one field is selected, else ``None``
        (the multi/rubber-band case has no single label)."""
        if len(self._ids) == 1:
            return self._ids[0]
        return None


class FieldClipboard:
    """Copied ``(field, source page)`` pairs awaiting paste."""

    def __init__(self) -> None:
        self._items: list[tuple[Any, int]] = []

    @property
    def items(self) -> list[tuple[Any, int]]:
        return self._items

    def set_items(self, items: Iterable[tuple[Any, int]]) -> None:
        self._items[:] = items
