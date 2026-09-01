"""Event-type management dialog (W4 D5), modeled on ``MonthSettingsDialog``.

The game's whole type set is edited here: the list on the left, the rename
field + eight palette swatches for the selected type, and «Добавить» /
«Удалить» / «↑» / «↓» buttons for set membership and order. A color is never
free-form — the only choice is which of the eight ``color.chart.1…8`` tokens a
type wears, painted as circles (off-skin they degrade to numbered gray
samples, the same named-Qt-global fallback the scale uses).

Every edit is written through ``EventService`` **immediately** (the spec's
«применяются к игре сразу»): there is no dialog-level Save, and deleting a
type only unbinds it from its events (no confirmation, the events stay). The
``run`` callable injects the app's session-locked task runner (``ensure_future``
by default, so tests drive a bare loop).

Theme: ``attach_theme`` skins the chrome and the ``on_retheme`` subscription
re-derives the swatch icons on every live theme swap — circles follow the new
theme's chart tokens without rebuilding the dialog or losing the selection.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Sequence

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QHBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from app.presentation.theme.catalog import attach_theme, hint, set_role
from app.presentation.theme.compiler import CHART_TOKEN_KEYS, token_rgb

#: Diameter (px) of a palette swatch / selector dot.
SWATCH_SIZE = 18
#: Caption of the "no type" entry in the event dialog's selector.
NO_TYPE_TEXT = "Без типа"
#: Name given to a new type while the rename field is empty.
DEFAULT_NEW_TYPE_NAME = "Новый тип"

#: Sentinel: ``_reload`` keeps the current selection unless told otherwise.
_KEEP = object()


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

    The one dot painter shared by the swatch row here and the event dialog's
    type combo (W4 D5): skinned it is exactly ``color.chart.k`` of the live
    theme, without a skin a gray Qt-global circle carries the number instead
    («оф-скин — нумерованные серые образцы»), and no hex literal is involved.
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


class EventTypesDialog(QDialog):
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
        self._theme = theme
        self._types: list[Any] = []
        self._loading = False
        self._task: asyncio.Future | None = None
        self.setWindowTitle("Типы событий")
        self.setMinimumWidth(420)
        self._init_ui()
        self._apply_theme()
        self._task = self._run(self._reload())

    # ── construction ───────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        """One attach point (MonthSettingsDialog pattern) + swatch re-derive."""
        if self._theme is not None:
            attach_theme(self.chrome, self._theme, on_retheme=self._restyle_swatches)
            self._theme.apply()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        # The chrome reaches the dialog edges so no OS-palette band frames it.
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.chrome = QWidget()
        self.chrome.setObjectName("eventTypesChrome")  # identifier, not style
        layout.addWidget(self.chrome)
        chrome = QVBoxLayout(self.chrome)
        chrome.setContentsMargins(11, 11, 11, 11)
        chrome.setSpacing(6)

        chrome.addWidget(hint(
            "Цвет — готовый образец палитры; удаление лишь отвязывает тип от событий",
            italic=True,
        ))

        body = QHBoxLayout()
        chrome.addLayout(body)

        self.type_list = QListWidget()
        set_role(self.type_list, "list")
        self.type_list.currentItemChanged.connect(self._on_selection)
        body.addWidget(self.type_list, 1)

        side = QVBoxLayout()
        body.addLayout(side, 1)

        self.name_input = QLineEdit()
        set_role(self.name_input, "field")
        self.name_input.setPlaceholderText("Название типа")
        self.name_input.editingFinished.connect(self._on_rename)
        side.addWidget(self.name_input)

        swatch_row = QHBoxLayout()
        self.swatch_group = QButtonGroup(self)
        self.swatch_group.setExclusive(True)
        self.swatch_buttons: list[QToolButton] = []
        for index in range(1, len(CHART_TOKEN_KEYS) + 1):
            button = QToolButton()
            button.setObjectName(f"typeColorSwatch{index}")
            button.setCheckable(True)
            button.setFixedSize(SWATCH_SIZE + 8, SWATCH_SIZE + 8)
            button.setToolTip(f"Цвет {index}")
            button.setIconSize(QSize(SWATCH_SIZE, SWATCH_SIZE))
            button.clicked.connect(
                lambda _checked=False, k=index: self._on_swatch_clicked(k)
            )
            self.swatch_group.addButton(button)
            self.swatch_buttons.append(button)
            swatch_row.addWidget(button)
        swatch_row.addStretch()
        side.addLayout(swatch_row)

        button_row = QHBoxLayout()
        self.add_button = QPushButton("Добавить")
        self.add_button.setObjectName("typeAddButton")
        self.add_button.clicked.connect(self._on_add)
        button_row.addWidget(self.add_button)
        self.remove_button = QPushButton("Удалить")
        self.remove_button.setObjectName("typeRemoveButton")
        self.remove_button.clicked.connect(self._on_remove)
        button_row.addWidget(self.remove_button)
        button_row.addStretch()
        self.up_button = QPushButton("↑")
        self.up_button.setObjectName("typeUpButton")
        self.up_button.clicked.connect(lambda: self._on_move(-1))
        button_row.addWidget(self.up_button)
        self.down_button = QPushButton("↓")
        self.down_button.setObjectName("typeDownButton")
        self.down_button.clicked.connect(lambda: self._on_move(1))
        button_row.addWidget(self.down_button)
        side.addLayout(button_row)
        side.addStretch()

        close_row = QHBoxLayout()
        close_row.addStretch()
        self.close_button = QPushButton("Закрыть")
        self.close_button.clicked.connect(self.accept)
        close_row.addWidget(self.close_button)
        chrome.addLayout(close_row)

        self._restyle_swatches()

    # ── state helpers ──────────────────────────────────────────────────────

    def _selected_id(self) -> int | None:
        item = self.type_list.currentItem()
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    def _selected_type(self) -> Any | None:
        type_id = self._selected_id()
        return next((t for t in self._types if t.id == type_id), None)

    def _selected_row(self) -> int:
        return self.type_list.currentRow()

    def _start(self, coro) -> None:
        self._task = self._run(coro)

    async def wait_idle(self) -> None:
        """Await the in-flight write (test/await seam for the fire-and-forget)."""
        while self._task is not None:
            task, self._task = self._task, None
            await task

    async def reload(self) -> None:
        await self._reload()

    # ── list rendering ─────────────────────────────────────────────────────

    async def _reload(self, select_id: Any = _KEEP) -> None:
        self._types = list(await self._service.get_event_types())
        if select_id is _KEEP:
            select_id = self._selected_id()
        self._populate(select_id)

    def _populate(self, select_id: int | None) -> None:
        self.type_list.blockSignals(True)
        self.type_list.clear()
        rows_by_id: dict[int, int] = {}
        for t in self._types:
            item = QListWidgetItem(t.name)
            item.setData(Qt.ItemDataRole.UserRole, t.id)
            self.type_list.addItem(item)
            rows_by_id[t.id] = self.type_list.count() - 1
        self.type_list.blockSignals(False)
        if select_id in rows_by_id:
            self.type_list.setCurrentRow(rows_by_id[select_id])
        else:
            self._reflect(None)

    def _reflect(self, type_: Any | None) -> None:
        """Mirror the selection into the rename field and the swatch row."""
        self._loading = True
        try:
            self.name_input.setText(type_.name if type_ is not None else "")
            for index, button in enumerate(self.swatch_buttons, start=1):
                button.setChecked(type_ is not None and type_.color_index == index)
                button.setEnabled(type_ is not None)
        finally:
            self._loading = False
        row = self._selected_row()
        self.remove_button.setEnabled(type_ is not None)
        self.up_button.setEnabled(type_ is not None and row > 0)
        self.down_button.setEnabled(
            type_ is not None and 0 <= row < self.type_list.count() - 1
        )

    def _restyle_swatches(self) -> None:
        """Re-derive the eight circle icons from the live theme's chart tokens."""
        skinned = getattr(self._theme, "tokens", None) is not None
        for index, button in enumerate(self.swatch_buttons, start=1):
            button.setIcon(type_dot_icon(self._theme, index))
            # Off-skin the digit inside the gray circle is the whole identity.
            button.setText("" if skinned else str(index))

    # ── user actions (every write is immediate) ────────────────────────────

    def _on_selection(self, item, _previous=None) -> None:
        self._reflect(self._selected_type())

    def _on_rename(self) -> None:
        type_ = self._selected_type()
        if self._loading or type_ is None:
            return
        name = self.name_input.text().strip()
        if not name or name == type_.name:
            return
        self._start(self._rename(type_, name))

    async def _rename(self, type_, name: str) -> None:
        await self._service.save_event_type(
            name=name, color_index=type_.color_index, type_id=type_.id,
        )
        await self._reload()
        self.types_changed.emit()

    def _on_swatch_clicked(self, color_index: int) -> None:
        type_ = self._selected_type()
        if self._loading or type_ is None or type_.color_index == color_index:
            return
        self._start(self._recolor(type_, color_index))

    async def _recolor(self, type_, color_index: int) -> None:
        await self._service.save_event_type(
            name=type_.name, color_index=color_index, type_id=type_.id,
        )
        await self._reload()
        self.types_changed.emit()

    def _on_add(self) -> None:
        name = self.name_input.text().strip() or DEFAULT_NEW_TYPE_NAME
        self._start(self._create(name))

    async def _create(self, name: str) -> None:
        created = await self._service.save_event_type(
            name=name, color_index=self._next_color_index(),
        )
        await self._reload(select_id=created.id)
        self.types_changed.emit()

    def _next_color_index(self) -> int:
        """First unused palette index, else rotate past the highest used one."""
        used = {t.color_index for t in self._types}
        for index in range(1, len(CHART_TOKEN_KEYS) + 1):
            if index not in used:
                return index
        return (max(used) % len(CHART_TOKEN_KEYS)) + 1

    def _on_remove(self) -> None:
        type_ = self._selected_type()
        if type_ is None:
            return
        # The spec drops any confirmation: the delete only unbinds (service).
        self._start(self._remove(type_))

    async def _remove(self, type_) -> None:
        await self._service.delete_event_type(type_.id)
        await self._reload(select_id=None)
        self.types_changed.emit()

    def _on_move(self, delta: int) -> None:
        if self._loading:
            return
        type_ = self._selected_type()
        row = self._selected_row()
        target = row + delta
        if type_ is None or not 0 <= target < len(self._types):
            return
        self._start(self._move(row, target))

    async def _move(self, row: int, target: int) -> None:
        types = list(self._types)
        moved = types[row]
        types[row], types[target] = types[target], types[row]
        # Positions are rewritten as 0..n-1 — idempotent normalization that
        # also heals accidental sort_order ties.
        for position, t in enumerate(types):
            if t.sort_order != position:
                await self._service.save_event_type(
                    name=t.name, color_index=t.color_index,
                    sort_order=position, type_id=t.id,
                )
        await self._reload(select_id=moved.id)
        self.types_changed.emit()

    # ── test-facing conveniences ───────────────────────────────────────────

    def type_names(self) -> list[str]:
        """Names as currently listed (display order)."""
        return [t.name for t in self._types]
