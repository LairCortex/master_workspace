"""Fill ViewModel — mutable value map over a read-only saved template (D3, D7)."""
from __future__ import annotations

from copy import deepcopy
from typing import Any
import json
import math

from PySide6.QtCore import QObject, Property, Signal, Slot

from app.domain.entities.character_sheet import SheetField, SheetTemplate
from app.domain.entities.character_sheet_instance import (
    display_fields,
    resolve_display,
)
from app.domain.enums.field_type import FieldType
from app.presentation.viewmodels.character_sheet_viewmodel import (
    TOOL_POINTER,
    SheetFieldModel,
    pages_layout_of,
)

UNDO_STACK_LIMIT: int = 50


class CharacterSheetFillViewModel(QObject):
    dirty_changed = Signal(bool)
    template_changed = Signal()
    values_changed = Signal()
    field_content_changed = Signal(str)
    field_props_changed = Signal(str)
    field_added = Signal(str)
    field_removed = Signal(str)
    field_geometry_changed = Signal(str)
    field_font_changed = Signal(str)
    selection_changed = Signal(object)
    inline_changed = Signal(object)
    pages_changed = Signal()
    current_page_changed = Signal(int)
    history_changed = Signal()
    snap_changed = Signal(bool)
    # Added by Q3b 1.1 for the field model's disabled-role refresh; existing
    # members keep their contracts (facade already calls set_read_only).
    read_only_changed = Signal(bool)

    def __init__(self, instance_service, sheet_service, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._instance_service = instance_service
        self._sheet_service = sheet_service
        self._template: SheetTemplate | None = None
        self._instance_id: int | None = None
        self._template_id: int | None = None
        self._character_id: int | None = None
        self._name: str = ""
        self._values: dict[str, Any] = {}
        self._saved_values: dict[str, Any] = {}
        self._dirty: bool = False
        self._selected_id: str | None = None
        self._inline_id: str | None = None
        self._inline_before: dict[str, Any] | None = None
        self._current_page: int = 0
        self._undo_stack: list[dict[str, Any]] = []
        self._redo_stack: list[dict[str, Any]] = []
        self._read_only: bool = False
        # The fill canvas feeds from the same projection class as design
        # (fill=True): rows are the live template fields, values resolve
        # through the domain's resolve_display, disabled mirrors read_only
        # (Q3b 1.1 / D4 — one model class, no second value implementation).
        self._field_model = SheetFieldModel(self, fill=True, parent=self)
        self.template_changed.connect(self._field_model.on_template_changed)
        self.pages_changed.connect(self._field_model.on_template_changed)
        self.values_changed.connect(self._field_model.on_values_changed)
        self.field_content_changed.connect(self._field_model.on_content_changed)
        self.field_props_changed.connect(self._field_model.on_props_changed)
        self.field_geometry_changed.connect(self._field_model.on_geometry_changed)
        self.field_font_changed.connect(self._field_model.on_font_changed)
        self.field_added.connect(self._field_model.on_field_added)
        self.field_removed.connect(self._field_model.on_field_removed)
        self.read_only_changed.connect(self._field_model.on_read_only_changed)

    # -- state --------------------------------------------------------------

    @property
    def field_model(self) -> SheetFieldModel:
        """The fill canvas field rows (Q3b 1.1) — same contract as design:
        content/imageKey arrive display-ready for the fill view."""
        return self._field_model

    # QML-side alias of :attr:`field_model` (island binds ``model:
    # vm.fieldModel``); ``"QVariant"`` — the meta-object builder rejects a
    # concrete model-list type, and the identity is CONSTANT either way
    # (timeline VM precedent).
    fieldModel = Property("QVariant", lambda self: self._field_model, constant=True)

    # ── QML canvas reads (change Q3b, task 2.5) ──────────────────────────────
    # The same read-only contract as the design VM: page tape from
    # ``pagesLayout`` (``pagesChanged`` fires on load/reload_layout), the
    # single selection and inline id from the pre-existing signals, the
    # constant pointer tool (fill never places). Read-only interactivity
    # arrives per row through the model's ``disabled`` role (it re-emits on
    # ``read_only_changed``), so the canvas gates input on the row, never on
    # a second copy of the flag.

    @Slot(result="QVariantMap")
    def pages_layout(self) -> dict:
        """Tape geometry of the loaded template (see ``pages_layout_of``);
        ``{}`` while nothing is loaded."""
        return pages_layout_of(self._template)

    pagesLayout = Property("QVariant", lambda self: pages_layout_of(self._template),
                           notify=pages_changed)
    currentTool = Property(str, lambda self: TOOL_POINTER, constant=True)

    # Q3b 3.2: the navigation rail lists the template's pages by name (the
    # names live in the template — QML only displays them), and the value
    # panel needs the dropdown option list (the display value itself rides
    # the field model's content role; the options are not renderable — they
    # are the choice set).
    @Slot(result="QStringList")
    def page_names(self) -> list[str]:
        if self._template is None:
            return []
        return [page.name for page in self._template.pages]

    @Slot(str, result="QVariantMap")
    def field_props(self, field_id: str) -> dict:
        if self._template is None:
            return {}
        field = self._template.get_field(field_id)
        if field is None:
            return {}
        return {"min": field.min_value, "max": field.max_value,
                "options": list(field.options)}
    currentPage = Property(int, lambda self: self._current_page,
                           notify=current_page_changed)
    selectedIds = Property(
        "QStringList",
        lambda self: [] if self._selected_id is None else [self._selected_id],
        notify=selection_changed)
    inlineFieldId = Property("QVariant", lambda self: self._inline_id,
                             notify=inline_changed)
    # Q3b 3.2: the fill window island mirrors the master-view flag onto the
    # value panel / action buttons (the same flag the model's disabled role
    # feeds to the canvas — added projection, the contract above unchanged).
    readOnly = Property(bool, lambda self: self._read_only,
                        notify=read_only_changed)
    # ``snapOn`` is absent on purpose: the fill canvas draws no grid, and the
    # model's ``disabled`` role is the single read-only gate (D4 — one source).

    @property
    def template(self) -> SheetTemplate | None:
        return self._template

    @property
    def instance_id(self) -> int | None:
        return self._instance_id

    @property
    def template_id(self) -> int | None:
        return self._template_id

    @property
    def character_id(self) -> int | None:
        return self._character_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def values(self) -> dict[str, Any]:
        return self._values

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def selection(self) -> str | None:
        return self._selected_id

    @property
    def inline_field_id(self) -> str | None:
        return self._inline_id

    @property
    def current_page_index(self) -> int:
        return self._current_page

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    @property
    def tool(self) -> str:
        return TOOL_POINTER

    @property
    def selected_ids(self) -> list[str]:
        return [] if self._selected_id is None else [self._selected_id]

    @property
    def snap_enabled(self) -> bool:
        return False

    @property
    def read_only(self) -> bool:
        return self._read_only

    def set_read_only(self, value: bool) -> None:
        flag = bool(value)
        if flag == self._read_only:
            return
        self._read_only = flag
        # The designer's menu check toggles without any repaint hooks — the
        # QML canvas re-reads the disabled role through the field model.
        self.read_only_changed.emit(flag)
        if self._read_only and self._inline_id is not None:
            self.cancel_inline()

    def page_of(self, field_id: str) -> int | None:
        if self._template is None:
            return None
        return self._template.page_of(field_id)

    # Q3b 1.2/2.5: the shared inline-editor bridge calls these exact names on
    # both VMs; the delegation below is the fill's existing duck contract, the
    # decorators only expose it to the QML meta-object.
    @Slot(str, str, result=bool)
    def set_content(self, field_id: str, content: str) -> bool:
        return self.set_text(field_id, content)

    @Slot(str, str, result=bool)
    def apply_number(self, field_id: str, text: str) -> bool:
        return self.set_number(field_id, text)

    def display_value(self, field_id: str) -> Any:
        if self._template is None:
            return None
        field = self._template.get_field(field_id)
        if field is None:
            return None
        return resolve_display(field, self._values)

    def displayed_fields(self) -> list[SheetField]:
        if self._template is None:
            return []
        return display_fields(self._template)

    # -- load / save / reload -----------------------------------------------

    async def load(self, instance_id: int) -> None:
        row = await self._instance_service.get(instance_id)
        self._instance_id = row.id
        self._template_id = row.template_id
        self._character_id = row.character_id
        self._name = row.name
        self._values = json.loads(row.values)
        self._saved_values = deepcopy(self._values)
        self._template = await self._sheet_service.load(row.template_id)
        self._selected_id = None
        self._inline_id = None
        self._inline_before = None
        self._current_page = 0
        self._clear_history()
        self._set_dirty(False)
        self.template_changed.emit()
        self.values_changed.emit()
        self.pages_changed.emit()
        self.current_page_changed.emit(0)
        self.selection_changed.emit(None)
        self.inline_changed.emit(None)

    async def save(self) -> None:
        if self._instance_id is None:
            return
        await self._instance_service.update_values(self._instance_id, self._values)
        self._saved_values = deepcopy(self._values)
        self._set_dirty(False)

    async def reload(self) -> None:
        if self._instance_id is None:
            return
        await self.load(self._instance_id)

    async def reload_layout(self) -> None:
        if self._template_id is None:
            return
        if self._inline_id is not None:
            self.commit_inline()
        self._template = await self._sheet_service.load(self._template_id)
        self.template_changed.emit()

    def set_name(self, name: str) -> None:
        self._name = name

    async def bind_character(self, character_id: int) -> None:
        if self._instance_id is None:
            return
        row = await self._instance_service.bind_character(
            self._instance_id, character_id
        )
        self._character_id = row.character_id

    async def unbind_character(self) -> None:
        if self._instance_id is None:
            return
        row = await self._instance_service.unbind_character(self._instance_id)
        self._character_id = row.character_id

    # -- selection / pages / inline -----------------------------------------

    @Slot("QVariant")
    def select(self, field_id: str | None) -> None:
        """QML passes the field id or null (Esc / empty-area click)."""
        if isinstance(field_id, str) and not field_id:
            field_id = None
        if field_id == self._selected_id:
            return
        self._selected_id = field_id
        self.selection_changed.emit(field_id)

    @Slot(int)
    def set_current_page(self, index: int) -> None:
        """Scroll channel (Q3b 1.2): the QML canvas reports its visible page."""
        if self._template is None:
            return
        index = max(0, min(index, len(self._template.pages) - 1))
        if index == self._current_page:
            return
        self._current_page = index
        self.current_page_changed.emit(index)

    @Slot(str)
    def open_inline(self, field_id: str) -> None:
        if self._read_only:
            return
        field = self._field(field_id)
        if field is None or self._inline_id == field_id:
            return
        if field.type not in (FieldType.TEXT, FieldType.TEXTAREA, FieldType.NUMBER):
            return
        self._inline_id = field_id
        self._inline_before = deepcopy(self._values)
        self._selected_id = field_id
        self.inline_changed.emit(field_id)
        self.selection_changed.emit(field_id)

    @Slot()
    def commit_inline(self) -> None:
        if self._inline_id is None:
            return
        field_id = self._inline_id
        if self._inline_before is not None and self._values != self._inline_before:
            self._undo_stack.append(self._inline_before)
            if len(self._undo_stack) > UNDO_STACK_LIMIT:
                self._undo_stack.pop(0)
            self._redo_stack.clear()
            self.history_changed.emit()
        self._inline_id = None
        self._inline_before = None
        self.inline_changed.emit(None)
        self._selected_id = field_id
        self.selection_changed.emit(field_id)

    @Slot()
    def cancel_inline(self) -> None:
        if self._inline_id is None:
            return
        field_id = self._inline_id
        if self._inline_before is not None:
            self._values = deepcopy(self._inline_before)
            self.field_content_changed.emit(field_id)
            self._refresh_dirty()
        self._inline_id = None
        self._inline_before = None
        self.inline_changed.emit(None)
        self._selected_id = field_id
        self.selection_changed.emit(field_id)

    # -- value mutators -----------------------------------------------------

    @Slot(str, str, result=bool)
    def set_text(self, field_id: str, text: str) -> bool:
        if self._read_only:
            return False
        field = self._field(field_id)
        if field is None or field.type not in (FieldType.TEXT, FieldType.TEXTAREA):
            return False
        if self._values.get(field_id, resolve_display(field, self._values)) == text:
            return False
        self._checkpoint()
        self._values[field_id] = text
        self.field_content_changed.emit(field_id)
        self._refresh_dirty()
        return True

    @Slot(str, result=bool)
    def toggle_checkbox(self, field_id: str) -> bool:
        if self._read_only:
            return False
        field = self._field(field_id)
        if field is None or field.type is not FieldType.CHECKBOX:
            return False
        current = resolve_display(field, self._values)
        self._checkpoint()
        self._values[field_id] = not bool(current)
        self.field_props_changed.emit(field_id)
        self._refresh_dirty()
        return True

    @Slot(str, str, result=bool)
    def set_number(self, field_id: str, text: str) -> bool:
        if self._read_only:
            return False
        field = self._field(field_id)
        if field is None or field.type is not FieldType.NUMBER:
            return False
        normalized = (text or "").strip().replace(",", ".")
        if normalized:
            try:
                value = float(normalized)
            except ValueError:
                return False
            if not math.isfinite(value):
                return False
            if field.min_value is not None and value < field.min_value:
                return False
            if field.max_value is not None and value > field.max_value:
                return False
        current = resolve_display(field, self._values)
        if current == normalized:
            return True
        self._checkpoint()
        self._values[field_id] = normalized
        self.field_content_changed.emit(field_id)
        self._refresh_dirty()
        return True

    @Slot(str, str, result=bool)
    def set_dropdown(self, field_id: str, option: str) -> bool:
        if self._read_only:
            return False
        field = self._field(field_id)
        if field is None or field.type is not FieldType.DROPDOWN:
            return False
        if option not in field.options:
            return False
        if resolve_display(field, self._values) == option:
            return False
        self._checkpoint()
        self._values[field_id] = option
        self.field_content_changed.emit(field_id)
        self._refresh_dirty()
        return True

    @Slot(str, "QVariant", result=bool)
    def set_image(self, field_id: str, image_id: int | None) -> bool:
        if self._read_only:
            return False
        if isinstance(image_id, float) and image_id.is_integer():
            image_id = int(image_id)  # QML numbers arrive as doubles
        field = self._field(field_id)
        if field is None or field.type is not FieldType.IMAGE:
            return False
        if resolve_display(field, self._values) == image_id and field_id in self._values:
            return False
        self._checkpoint()
        self._values[field_id] = image_id
        self.field_props_changed.emit(field_id)
        self._refresh_dirty()
        return True

    @Slot(str, result=bool)
    def clear_image(self, field_id: str) -> bool:
        return self.set_image(field_id, None)

    # -- undo / redo --------------------------------------------------------

    def undo(self) -> None:
        if self._inline_id is not None:
            self.cancel_inline()
            return
        if not self._undo_stack:
            return
        self._redo_stack.append(deepcopy(self._values))
        self._values = self._undo_stack.pop()
        self.history_changed.emit()
        self.values_changed.emit()
        self._refresh_dirty()

    def redo(self) -> None:
        if self._inline_id is not None:
            self.cancel_inline()
            return
        if not self._redo_stack:
            return
        self._undo_stack.append(deepcopy(self._values))
        if len(self._undo_stack) > UNDO_STACK_LIMIT:
            self._undo_stack.pop(0)
        self._values = self._redo_stack.pop()
        self.history_changed.emit()
        self.values_changed.emit()
        self._refresh_dirty()

    # -- internals ----------------------------------------------------------

    def apply_remote_value(self, field_id: str, value: Any) -> None:
        self._values[field_id] = value
        self._saved_values[field_id] = value
        self.field_content_changed.emit(field_id)
        self.values_changed.emit()
        self._refresh_dirty()

    def _field(self, field_id: str) -> SheetField | None:
        if self._template is None:
            return None
        return self._template.get_field(field_id)

    def _checkpoint(self) -> None:
        if self._inline_id is not None:
            return
        self._undo_stack.append(deepcopy(self._values))
        if len(self._undo_stack) > UNDO_STACK_LIMIT:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self.history_changed.emit()

    def _clear_history(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.history_changed.emit()

    def _refresh_dirty(self) -> None:
        self._set_dirty(self._values != self._saved_values)

    def _set_dirty(self, dirty: bool) -> None:
        if dirty == self._dirty:
            return
        self._dirty = dirty
        self.dirty_changed.emit(dirty)
