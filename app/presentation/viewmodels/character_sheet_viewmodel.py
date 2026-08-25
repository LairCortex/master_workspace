"""Character sheet editor viewmodel (design D6/D7).

Holds the in-memory ``SheetTemplate``; every significant mutation takes a
snapshot first (undo = deep copies, limit 100, redo cleared by a new
operation). ``save()`` / ``export_pdf()`` are coroutines that go through
the service / PDF generator; Qt signals drive the editor UI.
"""
from __future__ import annotations

import uuid
from typing import Any

from PySide6.QtCore import QObject, Signal

from app.application.services.character_sheet_service import (
    CharacterSheetNameConflict,
    CharacterSheetService,
)
from app.domain.entities.character_sheet import (
    SheetField,
    SheetPage,
    SheetTemplate,
    scale_for_orientation,
)
from app.domain.enums.field_type import FieldType
from app.domain.enums.sheet_orientation import SheetOrientation
from app.infrastructure.pdf.sheet_pdf import generate_sheet_pdf

UNDO_LIMIT = 100
MIN_FIELD_WIDTH = 20.0
MIN_FIELD_HEIGHT = 10.0
DEFAULT_FONT_SIZE = 12.0
DEFAULT_SNAP_STEP = 20.0
DUPLICATE_OFFSET = 20.0

#: default box size (w, h) per field type placed from the palette
_DEFAULT_SIZES: dict[FieldType, tuple[float, float]] = {
    FieldType.HEADING: (250.0, 24.0),
    FieldType.STATIC_TEXT: (200.0, 20.0),
    FieldType.SHORT_TEXT: (180.0, 24.0),
    FieldType.LONG_TEXT: (220.0, 100.0),
    FieldType.NUMBER: (90.0, 24.0),
    FieldType.DATE: (120.0, 24.0),
    FieldType.CHECKBOX: (20.0, 20.0),
    FieldType.DROPDOWN: (160.0, 24.0),
    FieldType.PORTRAIT: (120.0, 150.0),
}

#: property names accepted by update_field()
_FIELD_PROPERTIES = (
    "label", "default_value", "font_size",
    "min_value", "max_value", "options", "initial_checked",
)


def _new_uuid() -> str:
    return uuid.uuid4().hex


class CharacterSheetViewModel(QObject):
    state_changed = Signal()            # template contents changed (redraw)
    selection_changed = Signal()        # selected field changed
    dirty_changed = Signal(bool)
    can_undo_changed = Signal(bool)
    can_redo_changed = Signal(bool)
    status_message = Signal(str)        # transient user message, "" clears

    def __init__(self, service: CharacterSheetService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._sheet_id: int | None = None
        self._template: SheetTemplate | None = None
        self._dirty = False
        self._undo: list[SheetTemplate] = []
        self._redo: list[SheetTemplate] = []
        self._selected_field_id: str | None = None
        self._clipboard: tuple[int, SheetField] | None = None  # (page index, clone)
        self._snap_enabled = True
        self._snap_step = DEFAULT_SNAP_STEP

    # ── opening / creating ────────────────────────────────────────────────

    def create_new(self, name: str, orientation: SheetOrientation = SheetOrientation.LANDSCAPE) -> None:
        self._sheet_id = None
        self._template = SheetTemplate(
            name=name, orientation=orientation, pages=[SheetPage(name="Стр 1")],
        )
        self._reset_state()

    async def open(self, sheet_id: int) -> bool:
        template = await self._service.load(sheet_id)
        if template is None:
            return False
        self._sheet_id = sheet_id
        self._template = template
        self._reset_state()
        return True

    def _reset_state(self) -> None:
        self._dirty = False
        self._undo.clear()
        self._redo.clear()
        self._selected_field_id = None
        self._clipboard = None
        self._emit_state()
        self.selection_changed.emit()
        self.dirty_changed.emit(False)
        self.can_undo_changed.emit(False)
        self.can_redo_changed.emit(False)

    # ── accessors ─────────────────────────────────────────────────────────

    @property
    def template(self) -> SheetTemplate:
        assert self._template is not None
        return self._template

    @property
    def is_ready(self) -> bool:
        return self._template is not None

    @property
    def sheet_id(self) -> int | None:
        return self._sheet_id

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def snap_enabled(self) -> bool:
        return self._snap_enabled

    @property
    def snap_step(self) -> float:
        return self._snap_step

    @property
    def selected_field_id(self) -> str | None:
        return self._selected_field_id

    @property
    def selected_page_index(self) -> int | None:
        if not self._selected_field_id:
            return None
        found = self.template.find_field(self._selected_field_id)
        return found[0] if found else None

    @property
    def selected_field(self) -> SheetField | None:
        if not self._selected_field_id:
            return None
        found = self.template.find_field(self._selected_field_id)
        return found[1] if found else None

    # ── history / dirty ───────────────────────────────────────────────────

    def _snapshot(self) -> None:
        self._undo.append(self.template.clone())
        if len(self._undo) > UNDO_LIMIT:
            self._undo.pop(0)
        self._redo.clear()
        self._emit_state()

    def _commit(self) -> None:
        self._dirty = True
        self._emit_state()
        self.dirty_changed.emit(True)

    def _emit_state(self) -> None:
        self.state_changed.emit()
        self.can_undo_changed.emit(self.can_undo)
        self.can_redo_changed.emit(self.can_redo)

    def _locate(self, field_id: str) -> tuple[SheetPage, SheetField] | None:
        found = self.template.find_field(field_id)
        if found is None:
            return None
        return self.template.pages[found[0]], found[1]

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self.template.clone())
        self._template = self._undo.pop()
        self._drop_stale_selection()
        self._commit()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self.template.clone())
        self._template = self._redo.pop()
        self._drop_stale_selection()
        self._commit()
        return True

    def _drop_stale_selection(self) -> None:
        if self._selected_field_id and self.template.find_field(self._selected_field_id) is None:
            self._selected_field_id = None
            self.selection_changed.emit()

    # ── selection ─────────────────────────────────────────────────────────

    def select(self, field_id: str | None) -> None:
        if field_id is not None and self.template.find_field(field_id) is None:
            return
        self._selected_field_id = field_id
        self.selection_changed.emit()

    # ── snap (task 5.3) ───────────────────────────────────────────────────

    def set_snap(self, enabled: bool, step: float = DEFAULT_SNAP_STEP) -> None:
        self._snap_enabled = bool(enabled)
        self._snap_step = max(float(step), 0.0)

    def _snap(self, value: float) -> float:
        if self._snap_enabled and self._snap_step > 0:
            return round(round(value / self._snap_step) * self._snap_step, 2)
        return round(value, 2)

    # ── field operations (task 5.1) ───────────────────────────────────────

    def add_field(
        self,
        field_type: FieldType,
        page_index: int,
        x: float,
        y: float,
        w: float | None = None,
        h: float | None = None,
        **properties: Any,
    ) -> SheetField:
        size_w, size_h = _DEFAULT_SIZES[field_type]
        # palette defaults keep their design size; snap applies to user-driven
        # movement/resizing (set_field_rect), not to the stock defaults
        width = round(w if w is not None else size_w, 2)
        height = round(h if h is not None else size_h, 2)
        if width < MIN_FIELD_WIDTH or height < MIN_FIELD_HEIGHT:
            width = max(width, MIN_FIELD_WIDTH)
            height = max(height, MIN_FIELD_HEIGHT)
        font_size = 16.0 if field_type is FieldType.HEADING else DEFAULT_FONT_SIZE
        field = SheetField(
            id=_new_uuid(),
            type=field_type,
            x=self._snap(x),
            y=self._snap(y),
            w=width,
            h=height,
            font_size=font_size,
        )
        self._validate_field_changes(field, properties)
        for key, value in properties.items():
            setattr(field, key, value)
        self._snapshot()
        self.template.pages[page_index].fields.append(field)
        self._selected_field_id = field.id
        self.selection_changed.emit()
        self._commit()
        return field

    def remove_field(self, field_id: str) -> bool:
        located = self._locate(field_id)
        if located is None:
            return False
        page, _ = located
        self._snapshot()
        page.fields = [f for f in page.fields if f.id != field_id]
        self._drop_stale_selection()
        self._commit()
        return True

    def set_field_rect(self, field_id: str, x: float, y: float, w: float, h: float) -> bool:
        located = self._locate(field_id)
        if located is None:
            return False
        _, field = located
        self._snapshot()
        field.x = self._snap(x)
        field.y = self._snap(y)
        field.w = max(self._snap(w), MIN_FIELD_WIDTH)
        field.h = max(self._snap(h), MIN_FIELD_HEIGHT)
        self._commit()
        return True

    def update_field(self, field_id: str, **changes: Any) -> bool:
        """Apply one or more ``_FIELD_PROPERTIES`` (property panel commits)."""
        located = self._locate(field_id)
        if located is None:
            return False
        _, field = located
        self._validate_field_changes(field, changes)
        self._snapshot()
        for key, value in changes.items():
            setattr(field, key, value)
        self._commit()
        return True

    @staticmethod
    def _validate_field_changes(field: SheetField, changes: dict[str, Any]) -> None:
        """Validate ``_FIELD_PROPERTIES`` (raises ValueError, no mutation).

        Shared by ``add_field`` (initial values) and ``update_field`` (panel
        commits) so both paths reject the same combinations — e.g. min > max.
        """
        for key in changes:
            if key not in _FIELD_PROPERTIES:
                raise ValueError(f"unknown field property: {key!r}")
        if "font_size" in changes:
            size = float(changes["font_size"])
            if size <= 0:
                raise ValueError("font_size must be positive")
        min_value = changes["min_value"] if "min_value" in changes else field.min_value
        max_value = changes["max_value"] if "max_value" in changes else field.max_value
        if min_value > max_value:
            raise ValueError("min_value must be <= max_value")

    def duplicate_field(self, field_id: str) -> SheetField | None:
        located = self._locate(field_id)
        if located is None:
            return None
        page, source = located
        self._snapshot()
        clone = source.clone()
        clone.id = _new_uuid()
        clone.x = self._snap(source.x + DUPLICATE_OFFSET)
        clone.y = self._snap(source.y + DUPLICATE_OFFSET)
        page.fields.insert(page.fields.index(source) + 1, clone)
        self._selected_field_id = clone.id
        self.selection_changed.emit()
        self._commit()
        return clone

    # copy/paste — internal buffer, not the system clipboard (design D5)
    def copy_selected(self) -> bool:
        field = self.selected_field
        if field is None:
            return False
        page_index = self.selected_page_index
        self._clipboard = (page_index, field.clone())
        return True

    def paste(self, dx: float = 0.0, dy: float = 0.0) -> SheetField | None:
        if self._clipboard is None:
            return None
        source_index, source = self._clipboard
        page_index = min(source_index, len(self.template.pages) - 1)
        self._snapshot()
        clone = source.clone()
        clone.id = _new_uuid()
        clone.x = self._snap(source.x + dx)
        clone.y = self._snap(source.y + dy)
        self.template.pages[page_index].fields.append(clone)
        self._selected_field_id = clone.id
        self.selection_changed.emit()
        self._commit()
        return clone

    # z-order = order in the page field list (design D5)
    def bring_forward(self, field_id: str) -> bool:
        return self._swap_z(field_id, +1)

    def send_backward(self, field_id: str) -> bool:
        return self._swap_z(field_id, -1)

    def _swap_z(self, field_id: str, delta: int) -> bool:
        located = self._locate(field_id)
        if located is None:
            return False
        page, _ = located
        index = page.fields.index(located[1])
        swap_with = index + delta
        if not 0 <= swap_with < len(page.fields):
            return False
        self._snapshot()
        page.fields[index], page.fields[swap_with] = page.fields[swap_with], page.fields[index]
        self._commit()
        return True

    # ── page operations (task 5.2) ────────────────────────────────────────

    def add_page(self, name: str | None = None) -> int:
        if name is None:
            name = f"Стр {len(self.template.pages) + 1}"
        self._snapshot()
        self.template.pages.append(SheetPage(name=name))
        self._commit()
        return len(self.template.pages) - 1

    def rename_page(self, page_index: int, name: str) -> bool:
        if not name or not 0 <= page_index < len(self.template.pages):
            return False
        self._snapshot()
        self.template.pages[page_index].name = name
        self._commit()
        return True

    def remove_page(self, page_index: int) -> bool:
        if len(self.template.pages) <= 1:
            return False  # a template always keeps at least one page
        if not 0 <= page_index < len(self.template.pages):
            return False
        self._snapshot()
        self.template.pages.pop(page_index)
        if self._clipboard is not None and self._clipboard[0] > page_index:
            self._clipboard = (self._clipboard[0] - 1, self._clipboard[1])
        self._drop_stale_selection()
        self._commit()
        return True

    def move_page_up(self, page_index: int) -> bool:
        return self._move_page(page_index, -1)

    def move_page_down(self, page_index: int) -> bool:
        return self._move_page(page_index, +1)

    def _move_page(self, page_index: int, delta: int) -> bool:
        target = page_index + delta
        if not 0 <= target < len(self.template.pages):
            return False
        self._snapshot()
        pages = self.template.pages
        pages[page_index], pages[target] = pages[target], pages[page_index]
        self._commit()
        return True

    def set_orientation(self, new_orientation: SheetOrientation) -> bool:
        if new_orientation is self.template.orientation:
            return False
        self._snapshot()
        self._template = scale_for_orientation(self.template, new_orientation)
        self._drop_stale_selection()  # ids survive scaling, keep selection
        self._commit()
        return True

    # ── save / export (task 5.4) ──────────────────────────────────────────

    async def save(self) -> bool:
        if self._sheet_id is None:
            try:
                row = await self._service.create(self.template)
            except CharacterSheetNameConflict as exc:
                self.status_message.emit(f"Имя «{exc.args[0]}» уже существует")
                return False
            self._sheet_id = row.id
        else:
            try:
                row = await self._service.update(self._sheet_id, self.template)
            except CharacterSheetNameConflict as exc:
                self.status_message.emit(f"Имя «{exc.args[0]}» уже существует")
                return False
            if row is None:
                self.status_message.emit("Шаблон не найден")
                return False
        self._dirty = False
        self._emit_state()
        self.dirty_changed.emit(False)
        return True

    async def export_pdf(self, path) -> bool:
        try:
            generate_sheet_pdf(self.template, path)
        except OSError as exc:
            self.status_message.emit(f"Не удалось сохранить PDF: {exc}")
            return False
        return True
