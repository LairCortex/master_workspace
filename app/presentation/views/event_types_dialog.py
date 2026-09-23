"""Event-type management dialog — QML island in the kept QDialog facade.

The game's whole type set is edited here: the list, the rename field, the
eight palette swatches of the selected type and «Добавить» / «Удалить» /
«↑» / «↓» for set membership and order. A color is never free-form — the
only choice is which of the eight ``color.chart.1…8`` tokens a type wears.

Since R3 pack 2 the content is ``EventTypesRoot.qml`` on the shared process
engine (design D1): the island gets exactly ``eventTypesVm`` +
``islandPalette`` in its context and only emits requests. This facade keeps
everything else it always had — ``EventService``, the injected ``run``, the
coroutine writes, the reload rules, ``types_changed``, ``wait_idle()``,
``reload()`` and ``type_names()`` — so the public Python API is unchanged by
the port.

Every edit is written through ``EventService`` **immediately** (the spec's
«применяются к игре сразу»): there is no dialog-level Save and no
confirmation on close, and deleting a type only unbinds it from its events
(the events stay). The ``run`` callable injects the app's session-locked task
runner (``ensure_future`` by default, so tests drive a bare loop).

``type_dot_icon`` (with ``NO_TYPE_TEXT`` and ``SWATCH_SIZE``) stays here as
the shared type-dot painter: the still-widgets event dialog imports it for
its type combo, so the painter outlives this dialog's own widgets layout.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QVBoxLayout, QWidget

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.engine import QML_IMPORT_PATH
from app.presentation.qml.island import IslandDialogMixin
from app.presentation.qml.island_size import fit_dialog_to_island
from app.presentation.theme import get_default_theme
from app.presentation.theme.compiler import CHART_TOKEN_KEYS, token_rgb
from app.presentation.viewmodels.event_types_view_model import EventTypesViewModel

ROOT_QML = str(Path(QML_IMPORT_PATH) / "EventTypesRoot.qml")

#: Diameter (px) of a palette swatch / selector dot.
SWATCH_SIZE = 18
#: Caption of the "no type" entry in the event dialog's selector.
NO_TYPE_TEXT = "Без типа"
#: Name given to a new type while the rename field is empty.
DEFAULT_NEW_TYPE_NAME = "Новый тип"


def _token_color(theme, color_index: int) -> QColor | None:
    """``color.chart.{color_index}`` of the live theme, ``None`` off-skin."""
    if not 1 <= color_index <= len(CHART_TOKEN_KEYS):
        return None
    tokens = getattr(theme, "tokens", None)
    if tokens is None:
        return None
    rgb = token_rgb(tokens, theme.theme, CHART_TOKEN_KEYS[color_index - 1])
    return QColor(*rgb) if rgb is not None else None


def type_dot_icon(theme, color_index: int, size: int = SWATCH_SIZE) -> QIcon:
    """Filled circle of the type's chart token; numbered gray off-skin.

    The dot painter of the event dialog's type combo (W4 D5): skinned it is
    exactly ``color.chart.k`` of the live theme, without a skin a gray
    Qt-global circle carries the number instead («оф-скин — нумерованные
    серые образцы»), and no hex literal is involved.
    """
    color = _token_color(theme, color_index)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color if color is not None else QColor(Qt.GlobalColor.gray))
    painter.drawEllipse(1, 1, size - 2, size - 3)
    if color is None:  # numbered sample: the index is the only identity left
        painter.setPen(QColor(Qt.GlobalColor.black))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, str(color_index))
    painter.end()
    return QIcon(pixmap)


class EventTypesDialog(IslandDialogMixin, QDialog):
    island_context_names = {"eventTypesVm": "vm"}

    def island_source(self) -> str:
        return ROOT_QML
    """Per-game event-type editor with immediate write-through."""

    #: Emitted after any edit landed in the game (the panel re-renders its scale).
    types_changed = Signal()

    def __init__(
        self,
        event_service,
        run: Callable | None = None,
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        super().__init__(parent)
        self._service = event_service
        # The app injects its session-locked runner; bare ensure_future keeps
        # the dialog usable on any running loop (tests).
        self._run = run if run is not None else asyncio.ensure_future
        self._theme = theme if theme is not None else get_default_theme()
        self._types: list[Any] = []
        self._task: asyncio.Future | None = None
        self.setWindowTitle("Типы событий")
        self.setMinimumWidth(420)

        self.vm = EventTypesViewModel(parent=self)

        layout = QVBoxLayout(self)
        # The island reaches the dialog edges so no OS-palette band frames it.
        layout.setContentsMargins(0, 0, 0, 0)

        self._engine = setup_qml_shell(QApplication.instance(), self._theme)
        # Dialog-owned context (IslandDialogMixin): the root view is destroyed
        # before it, avoiding binding evaluation against a null VM in teardown.
        self.setup_island()
        layout.addWidget(self.quick)
        # The island's own width is what its action row needs, and that grows
        # with the system font: opening at the 420 floor instead clipped ↑/↓ on
        # the right edge, where Qt neither paints nor delivers clicks.
        fit_dialog_to_island(self, self._root, floor=(420, 320))

        self.vm.addRequested.connect(self._on_add)
        self.vm.renameRequested.connect(self._on_rename)
        self.vm.recolorRequested.connect(self._on_recolor)
        self.vm.moveRequested.connect(self._on_move)
        self.vm.removeRequested.connect(self._on_remove)
        self.vm.closeRequested.connect(self.accept)

        self._task = self._run(self._reload())

    # ── state helpers ──────────────────────────────────────────────────────

    def _type_by_id(self, type_id: int) -> Any | None:
        return next((t for t in self._types if t.id == type_id), None)

    def _row_of(self, type_id: int) -> int:
        return next(
            (row for row, t in enumerate(self._types) if t.id == type_id), -1
        )

    def _start(self, coro) -> None:
        self._task = self._run(coro)

    async def wait_idle(self) -> None:
        """Await the in-flight write (test/await seam for the fire-and-forget)."""
        while self._task is not None:
            task, self._task = self._task, None
            await task

    async def reload(self) -> None:
        await self._reload()

    async def _reload(self) -> None:
        """Re-read the set and re-render the island (selection kept by id)."""
        self._types = list(await self._service.get_event_types())
        self.vm.set_rows(self._types)

    # ── requests from the island (every write is immediate) ────────────────

    def _on_add(self, name: str) -> None:
        self._start(self._create(name.strip() or DEFAULT_NEW_TYPE_NAME))

    def _on_rename(self, type_id: int, name: str) -> None:
        type_ = self._type_by_id(type_id)
        if type_ is None or not name.strip() or name.strip() == type_.name:
            return
        self._start(self._rename(type_, name.strip()))

    def _on_recolor(self, type_id: int, color_index: int) -> None:
        type_ = self._type_by_id(type_id)
        if type_ is None or type_.color_index == color_index:
            return
        self._start(self._recolor(type_, color_index))

    def _on_remove(self, type_id: int) -> None:
        type_ = self._type_by_id(type_id)
        if type_ is None:
            return
        # The spec drops any confirmation: the delete only unbinds (service).
        self._start(self._remove(type_))

    def _on_move(self, type_id: int, delta: int) -> None:
        row = self._row_of(type_id)
        target = row + delta
        if row < 0 or not 0 <= target < len(self._types):
            return
        self._start(self._move(row, target))

    # ── service operations ─────────────────────────────────────────────────

    async def _rename(self, type_, name: str) -> None:
        await self._service.save_event_type(
            name=name, color_index=type_.color_index, type_id=type_.id,
        )
        await self._reload()
        self.types_changed.emit()

    async def _recolor(self, type_, color_index: int) -> None:
        await self._service.save_event_type(
            name=type_.name, color_index=color_index, type_id=type_.id,
        )
        await self._reload()
        self.types_changed.emit()

    async def _create(self, name: str) -> None:
        created = await self._service.save_event_type(
            name=name, color_index=self._next_color_index(),
        )
        await self._reload()
        self.vm.select_by_id(created.id)
        self.types_changed.emit()

    def _next_color_index(self) -> int:
        """First unused palette index, else rotate past the highest used one."""
        used = {t.color_index for t in self._types}
        for index in range(1, len(CHART_TOKEN_KEYS) + 1):
            if index not in used:
                return index
        return (max(used) % len(CHART_TOKEN_KEYS)) + 1

    async def _remove(self, type_) -> None:
        try:
            await self._service.delete_event_type(type_.id)
        except Exception as exc:
            # The service no longer swallows the failure (audit Q14 scenario 7,
            # task 5.2) — the dialog is the place that can show it.
            QMessageBox.warning(
                self, "Удаление типа", f"Не удалось удалить тип «{type_.name}»: {exc}",
            )
            return
        # The row is gone: the reload drops the selection with it.
        await self._reload()
        self.types_changed.emit()

    async def _move(self, row: int, target: int) -> None:
        types = list(self._types)
        types[row], types[target] = types[target], types[row]
        # Positions are rewritten as 0..n-1 — idempotent normalization that
        # also heals accidental sort_order ties.
        for position, t in enumerate(types):
            if t.sort_order != position:
                await self._service.save_event_type(
                    name=t.name, color_index=t.color_index,
                    sort_order=position, type_id=t.id,
                )
        await self._reload()
        self.types_changed.emit()

    # ── island lifecycle — IslandDialogMixin (context, deferred release) ──

    # ── test-facing conveniences ───────────────────────────────────────────

    def type_names(self) -> list[str]:
        """Names as currently listed (display order)."""
        return [t.name for t in self._types]
