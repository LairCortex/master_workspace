"""Character-sheet editor ViewModel — in-memory template, design D4.

The VM is the single source of truth for the layout: the QGraphics scene,
the page rail and the property panel are all projections of it (panel and
canvas read the same field, there is no second text buffer). ``save()`` /
``reload()`` are coroutines through :class:`CharacterSheetService` (qasync
runs them on the Qt loop, like the other VMs).

State owned here:
- ``template`` — the :class:`SheetTemplate` in memory; field ids (uuid4 hex,
  assigned at placement) never change on move/resize/edit, survive save/reload.
- ``tool`` — ``pointer`` or a place_* tool; a successful ``place`` resets it
  to pointer, selects the new field and does NOT open inline editing.
- ``selected_ids`` — zero or more field ids (order of addition).
- ``selection`` — the sole selected id, or None when the set is empty or larger.
- ``inline_field_id`` — the field currently edited on the canvas; while set,
  the canvas must not move/resize it.
- ``current_page_index`` — the rail/canvas current page (A-playable: pages
  are unlimited, the canvas lays them out as a vertical tape).
- ``dirty`` — any layout edit sets it; ``save()`` clears it.

Signals: ``dirty_changed(bool)``, ``template_changed()`` (full reload —
rebuild projections), granular
``field_added/removed/geometry/content/font/props`` (str field id),
``selection_changed(object)`` (id or None), ``tool_changed`` (str),
``inline_changed(object)`` (id or None); A-playable adds
``pages_changed()`` (page structure: add/remove/reorder/rename/relocate/
orientation — rail and canvas rebuild from the template),
``current_page_changed(int)``, ``orientation_changed(str)`` and
``field_props_changed(str)`` (per-type extras: checkbox state, number
min/max, dropdown options, image reference — the panel and canvas repaint).

Cross-page drag (design D5): ``drag_move`` is the live feedback (the field
follows the cursor while it stays within the field's own page, otherwise the
field holds its last in-page position); ``apply_drag`` on release resolves the
drop: over another page the field is relocated there (topmost, clamped), over
a gutter / the same page it is clamped back into its own page.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

from PySide6.QtCore import (
    QObject,
    Property,
    Signal,
    Slot,
)

from app.domain.entities.character_sheet import (
    GUTTER_PT,
    ORIENTATION_LANDSCAPE,
    ORIENTATION_PORTRAIT,
    SheetField,
    SheetTemplate,
    clamp_rect,
    page_origin,
    scene_to_page,
    tape_height,
)
from app.domain.enums.field_type import FieldType
from app.presentation.viewmodels.sheet_edit_state import (
    FieldClipboard,
    LayoutHistory,
    SelectionModel,
)
from app.presentation.viewmodels.sheet_field_model import SheetFieldModel

UNDO_STACK_LIMIT: int = 50
SNAP_PT: float = 4.0
DUPLICATE_OFFSET_PT: float = 8.0


def snap_coord(value: float) -> float:
    return round(value / SNAP_PT) * SNAP_PT

TOOL_POINTER: str = "pointer"
TOOL_PLACE_LABEL: str = "place_label"
TOOL_PLACE_TEXT: str = "place_text"
TOOL_PLACE_TEXTAREA: str = "place_textarea"
# A-playable palette (the full closed catalog; design D7):
TOOL_PLACE_CHECKBOX: str = "place_checkbox"
TOOL_PLACE_NUMBER: str = "place_number"
TOOL_PLACE_DROPDOWN: str = "place_dropdown"
TOOL_PLACE_IMAGE: str = "place_image"
TOOL_PLACE_RECT: str = "place_rect"
TOOL_PLACE_LINE: str = "place_line"

_TOOL_TO_TYPE: dict[str, FieldType] = {
    TOOL_PLACE_LABEL: FieldType.LABEL,
    TOOL_PLACE_TEXT: FieldType.TEXT,
    TOOL_PLACE_TEXTAREA: FieldType.TEXTAREA,
    TOOL_PLACE_CHECKBOX: FieldType.CHECKBOX,
    TOOL_PLACE_NUMBER: FieldType.NUMBER,
    TOOL_PLACE_DROPDOWN: FieldType.DROPDOWN,
    TOOL_PLACE_IMAGE: FieldType.IMAGE,
    TOOL_PLACE_RECT: FieldType.RECT,
    TOOL_PLACE_LINE: FieldType.LINE,
}


def field_type_for_tool(tool: str) -> FieldType | None:
    """Map a palette tool to the field type it places (or None for pointer)."""
    return _TOOL_TO_TYPE.get(tool)


def pages_layout_of(template: SheetTemplate | None) -> dict:
    """The tape geometry the QML canvas lays its pages out from (Q3b 2.1:
    «Repeater страниц page_origin/размер из домена, выводимые VM»).

    Every number is the domain's own (``page_size`` / ``page_origin`` /
    ``tape_height`` / gutter, plus the editor's grid step) — QML only indexes
    the ``origins`` list, it never re-derives page positions. An empty map
    before ``load`` (the canvas stays a clickable empty viewport, the same
    tolerance the widgets canvas had).
    """
    if template is None:
        return {}
    page_w, page_h = template.page_size
    n = len(template.pages)
    return {
        "width": page_w,
        "height": page_h,
        "count": n,
        "gutter": GUTTER_PT,
        "gridStep": SNAP_PT,
        "tapeHeight": tape_height(n, page_h),
        "origins": [list(page_origin(i, page_h)) for i in range(n)],
        "orientation": template.orientation,
    }


def _field_type_for_value(type_value: str) -> FieldType | None:
    """Map a raw type value (QML passes strings) to FieldType, unknown → None."""
    try:
        return FieldType(type_value)
    except ValueError:
        return None


class CharacterSheetViewModel(QObject):
    dirty_changed = Signal(bool)
    template_changed = Signal()
    field_added = Signal(str)
    field_removed = Signal(str)
    field_geometry_changed = Signal(str)
    field_content_changed = Signal(str)
    field_font_changed = Signal(str)
    field_props_changed = Signal(str)      # per-type extras (min/max/options/..)
    selection_changed = Signal(object)   # field id or None
    tool_changed = Signal(str)
    inline_changed = Signal(object)      # inline-edited field id or None
    # A-playable:
    pages_changed = Signal()             # page structure changed (rebuild)
    current_page_changed = Signal(int)
    orientation_changed = Signal(str)
    history_changed = Signal()
    snap_changed = Signal(bool)
    clipboard_changed = Signal()

    def __init__(self, service, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._template: SheetTemplate | None = None
        self._sheet_id: int | None = None
        self._dirty: bool = False
        # Serialized pages as of the last load/save — the dirty state is
        # derived from it (a cancelled edit restores the saved buffer and the
        # flag drops by itself instead of sticking).
        self._saved_pages_json: str | None = None
        self._tool: str = TOOL_POINTER
        # Edit-state carriers (task 6.5.2, audit B4): plain non-Qt holders for
        # the selection, the undo/redo stacks and the clipboard. The view
        # model delegates through the ``_selected_ids``/``_clipboard``
        # properties below and owns every signal emission itself.
        self._selection = SelectionModel()
        self._history = LayoutHistory(UNDO_STACK_LIMIT)
        self._clipboard_carrier = FieldClipboard()
        self._inline_id: str | None = None
        self._inline_snapshot: str = ""
        self._inline_before: tuple[str, str] | None = None
        self._current_page: int = 0
        self._in_gesture: bool = False
        self._suppress_checkpoint: bool = False
        self._snap_enabled: bool = False
        self._snap_override: bool | None = None
        # The QML canvas feeds from this projection of the same template:
        # rows are the live domain fields, updated through the VM's existing
        # granular signals only (Q3b D4 — no second set anywhere).
        self._field_model = SheetFieldModel(self, parent=self)
        self.field_added.connect(self._field_model.on_field_added)
        self.field_removed.connect(self._field_model.on_field_removed)
        self.field_geometry_changed.connect(self._field_model.on_geometry_changed)
        self.field_content_changed.connect(self._field_model.on_content_changed)
        self.field_font_changed.connect(self._field_model.on_font_changed)
        self.field_props_changed.connect(self._field_model.on_props_changed)
        self.template_changed.connect(self._field_model.on_template_changed)
        self.pages_changed.connect(self._field_model.on_template_changed)
        self.orientation_changed.connect(self._field_model.on_template_changed)

    # -- state ------------------------------------------------------------

    @property
    def template(self) -> SheetTemplate | None:
        return self._template

    @property
    def sheet_id(self) -> int | None:
        return self._sheet_id

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def tool(self) -> str:
        return self._tool

    # Carrier-facing aliases: the whole module keeps addressing the selection
    # and clipboard through these names (task 6.5.2); the getters hand out the
    # carriers' live lists, the setters replace their content.
    @property
    def _selected_ids(self) -> list[str]:
        return self._selection.ids

    @_selected_ids.setter
    def _selected_ids(self, ids: list[str]) -> None:
        self._selection.set(ids)

    @property
    def _clipboard(self) -> list[tuple[SheetField, int]]:
        return self._clipboard_carrier.items

    @_clipboard.setter
    def _clipboard(self, items: list[tuple[SheetField, int]]) -> None:
        self._clipboard_carrier.set_items(items)

    @property
    def selection(self) -> str | None:
        return self._selection.primary

    @property
    def selected_ids(self) -> list[str]:
        return list(self._selected_ids)

    @property
    def can_undo(self) -> bool:
        return self._history.can_undo

    @property
    def can_redo(self) -> bool:
        return self._history.can_redo

    @property
    def snap_enabled(self) -> bool:
        return self._snap_enabled

    @property
    def inline_field_id(self) -> str | None:
        return self._inline_id

    @property
    def page_count(self) -> int:
        return len(self._template.pages) if self._template is not None else 0

    @property
    def current_page_index(self) -> int:
        if self._template is None:
            return 0
        return max(0, min(self._current_page, len(self._template.pages) - 1))

    @property
    def field_model(self) -> SheetFieldModel:
        """The canvas field rows as a QML list model (Q3b 1.1 / D4).

        The reference is constant for the VM's lifetime (the model outlives
        templates — a reload only resets its rows), so no notify signal is
        needed; ``QAbstractListModel`` is exactly what QML delegates bind to.
        """
        return self._field_model

    # QML-side alias of :attr:`field_model` (the island binds ``model:
    # vm.fieldModel``); ``"QVariant"`` because the meta-object builder rejects
    # a concrete model-list type — and the identity is CONSTANT either way.
    fieldModel = Property("QVariant", lambda self: self._field_model, constant=True)

    # ── QML canvas reads (change Q3b, task 2.x) ──────────────────────────────
    # The canvas binds view state only through these read-only Qt properties
    # and the sync Slots below — never a Python ``@property`` (invisible to
    # QML, pinned by tests/presentation/test_sheet_vm_invokables.py). Every
    # notify signal already fired on EVERY transition of its value
    # (pre-existing contract, unchanged), so the bindings below are live by
    # construction: tool (set_tool/place/load), selection (select*/place/
    # undo…), inline id (open/apply/cancel/_close_inline_session), current
    # page (rail/scroll channel), snap flag (set_snap_enabled). The page tape
    # is re-read from ``pages_layout()`` on ``pagesChanged`` (fires on every
    # structural moment, load/reload/reorder/orientation/undo included).

    @Slot(result="QVariantMap")
    def pages_layout(self) -> dict:
        """Tape geometry of the template (domain functions, see
        :func:`pages_layout_of`); ``{}`` before the first ``load``."""
        return pages_layout_of(self._template)

    @Slot(float, float, result="QVariantMap")
    def page_at(self, x: float, y: float) -> dict:
        """Page under a tape point in page units: ``{page, x, y}`` page-local,
        ``{}`` for a gutter/outside point (domain ``scene_to_page`` rule, D1 —
        the canvas never re-derives it)."""
        if self._template is None:
            return {}
        page_w, page_h = self._template.page_size
        hit = scene_to_page(x, y, page_w, page_h, len(self._template.pages))
        if hit is None:
            return {}
        return {"page": hit[0], "x": hit[1], "y": hit[2]}

    @Slot(result="QStringList")
    def page_names(self) -> list[str]:
        """Page names in rail order (Q3b 3.1/3.2: the page rail is QML, the
        names stay in the template — QML only displays them)."""
        if self._template is None:
            return []
        return [page.name for page in self._template.pages]

    @Slot(str, result="QVariantMap")
    def field_props(self, field_id: str) -> dict:
        """The per-type extras the property panel edits (Q3b 3.1): the number
        bounds and the dropdown options (the list itself, not just its size)
        are not field-model roles because they are edited, not rendered.
        Geometry/content/font come from ``fieldModel.get()`` — one source."""
        field = self._field(field_id)
        if field is None:
            return {}
        return {
            "min": field.min_value,
            "max": field.max_value,
            "options": list(field.options),
            "page": self.page_of(field_id),
        }

    currentTool = Property(str, lambda self: self._tool, notify=tool_changed)
    currentPage = Property(int, lambda self: self.current_page_index,
                           notify=current_page_changed)
    pagesLayout = Property("QVariant", lambda self: pages_layout_of(self._template),
                           notify=pages_changed)
    selectedIds = Property("QStringList", lambda self: list(self._selected_ids),
                           notify=selection_changed)
    inlineFieldId = Property("QVariant", lambda self: self._inline_id,
                             notify=inline_changed)
    snapOn = Property(bool, lambda self: self._snap_enabled, notify=snap_changed)

    @Slot(int)
    def set_current_page(self, index: int) -> None:
        """Set the rail/current page (clamped). No-op when already current.

        The canvas scroll channel (Q3b task 1.2): QML emits it on every
        visible-page change; the visible page is read back through
        ``current_page_index`` / ``current_page_changed``.
        """
        if self._template is None:
            return
        clamped = max(0, min(index, len(self._template.pages) - 1))
        if clamped == self._current_page:
            return
        self._current_page = clamped
        self.current_page_changed.emit(clamped)

    # -- loading (coroutines via the service) ------------------------------

    async def load(self, sheet_id: int) -> None:
        """Load the template from the DB and reset all transient state."""
        self._template = await self._service.load(sheet_id)
        self._sheet_id = sheet_id
        self._saved_pages_json = self._template.to_pages_json()
        self._selected_ids = []
        self._inline_id = None
        self._inline_before = None
        self._tool = TOOL_POINTER
        self._current_page = 0
        self._clear_history()
        self._set_dirty(False)
        self.selection_changed.emit(None)
        self.tool_changed.emit(TOOL_POINTER)
        self.template_changed.emit()
        self.pages_changed.emit()
        self.current_page_changed.emit(0)

    async def save(self) -> None:
        """Persist the in-memory layout and clear the dirty flag.

        A no-op before ``load`` completed (the canvas/button can fire while
        the template is still on its way).
        """
        if self._sheet_id is None or self._template is None:
            return
        await self._service.update_pages(self._sheet_id, self._template)
        self._saved_pages_json = self._template.to_pages_json()
        self._set_dirty(False)

    async def reload(self) -> None:
        """Drop in-memory (possibly unsaved) edits, re-read from the DB."""
        self._template = await self._service.load(self._sheet_id)
        self._saved_pages_json = self._template.to_pages_json()
        self._selected_ids = []
        self._inline_id = None
        self._inline_before = None
        self._current_page = 0
        self._clear_history()
        if self._tool != TOOL_POINTER:
            self._tool = TOOL_POINTER
            self.tool_changed.emit(TOOL_POINTER)
        self.selection_changed.emit(None)
        self.inline_changed.emit(None)
        self._set_dirty(False)
        self.template_changed.emit()
        self.pages_changed.emit()
        self.current_page_changed.emit(0)

    # -- tool & selection ---------------------------------------------------

    @Slot(str)
    def set_tool(self, tool: str) -> None:
        if tool == self._tool:
            return
        self._tool = tool
        self.tool_changed.emit(tool)

    @Slot(result=str)
    def tool_field_type(self) -> str:
        """Catalog value of the field type the active tool places ("" for
        pointer / unknown — the QML press handler asks instead of
        re-deriving the tool table, task 2.3)."""
        field_type = field_type_for_tool(self._tool)
        return "" if field_type is None else field_type.value

    @Slot("QVariant")
    def select(self, field_id: str | None) -> None:
        """QML passes the field id or null (Esc / empty-area click)."""
        if isinstance(field_id, str) and not field_id:
            field_id = None
        new = [] if field_id is None else [field_id]
        if new == self._selected_ids:
            return
        self._selected_ids = new
        self.selection_changed.emit(self.selection)

    @Slot(str)
    def toggle_select(self, field_id: str) -> None:
        if field_id in self._selected_ids:
            self._selected_ids = [i for i in self._selected_ids if i != field_id]
        else:
            self._selected_ids.append(field_id)
        self.selection_changed.emit(self.selection)

    @Slot("QStringList")
    @Slot("QStringList", bool)
    def select_ids(self, ids: list[str], additive: bool = False) -> None:
        if additive:
            for field_id in ids:
                if field_id not in self._selected_ids:
                    self._selected_ids.append(field_id)
        else:
            self._selected_ids = list(ids)
        self.selection_changed.emit(self.selection)

    @Slot("QVariant")
    def set_snap_override(self, enabled: bool | None) -> None:
        self._snap_override = enabled

    @Slot(bool)
    def set_snap_enabled(self, enabled: bool) -> None:
        flag = bool(enabled)
        if flag == self._snap_enabled:
            return
        self._snap_enabled = flag
        self.snap_changed.emit(flag)

    @property
    def has_clipboard(self) -> bool:
        return bool(self._clipboard)

    @property
    def _snap_active(self) -> bool:
        if self._snap_override is False:
            return False
        if self._snap_override is True:
            return True
        return self._snap_enabled

    # -- layout mutations (all clamped into the field's page, D4) -----------

    def _field(self, field_id: str) -> SheetField | None:
        if self._template is None:
            return None
        return self._template.get_field(field_id)

    def page_of(self, field_id: str) -> int | None:
        """The index of the page holding the field, or None."""
        if self._template is None:
            return None
        return self._template.page_of(field_id)

    # QML invokables: the type arrives as its catalog string (QML passes no
    # Python enums); the page defaults to the current one, so the canvas can
    # call place with the exact argument list it has. An unknown string places
    # nothing (same "" as "no template loaded yet").
    @Slot(str, float, float, result=str)
    @Slot(str, float, float, int, result=str)
    def place(self, field_type: FieldType | str, x: float, y: float,
              page_index: int | None = None,
              snap_override: bool | None = None) -> str:
        """Place one field (top-left at the click point, clamped) and select it.

        ``page_index`` defaults to the current page (the canvas resolves the
        clicked sheet under the cursor). ``snap_override`` suppresses the grid
        for this placement only (Shift held on the click, design D3). Returns
        the new field id, or ``""`` when nothing was placed (no template loaded
        yet — the canvas can be clickable during ``load``).
        """
        resolved = field_type if isinstance(field_type, FieldType) else _field_type_for_value(field_type)
        if resolved is None or self._template is None:
            return ""
        field_type = resolved
        if page_index is None:
            page_index = self.current_page_index
        page_index = max(0, min(page_index, len(self._template.pages) - 1))
        self._checkpoint()
        field = self._template.add_field(field_type, (x, y), page_index=page_index)
        previous_override = self._snap_override
        if snap_override is not None:
            self._snap_override = snap_override
        try:
            self._snap_field_geometry(field, snap_size=False)
        finally:
            self._snap_override = previous_override
        self._selected_ids = [field.id]
        if self._tool != TOOL_POINTER:
            self._tool = TOOL_POINTER
            self.tool_changed.emit(TOOL_POINTER)
        self.field_added.emit(field.id)
        self.selection_changed.emit(field.id)
        self._refresh_dirty()
        return field.id

    @Slot(str, float, float, result=bool)
    def move(self, field_id: str, x: float, y: float) -> bool:
        field = self._field(field_id)
        if field is None:
            return False
        page_w, page_h = self._template.page_size
        nx, ny, nw, nh = clamp_rect(
            x, y, field.w, field.h, page_w=page_w, page_h=page_h, field_type=field.type
        )
        nx, ny, nw, nh = self._maybe_snap_rect(
            nx, ny, nw, nh, field.type, snap_size=False
        )
        if nx == field.x and ny == field.y:
            return False
        self._checkpoint()
        field.x = nx
        field.y = ny
        self.field_geometry_changed.emit(field_id)
        self._refresh_dirty()
        return True

    @Slot(str, float, float, float, float, result=bool)
    def resize(self, field_id: str, x: float, y: float, w: float, h: float) -> bool:
        if len(self._selected_ids) != 1:
            return False
        field = self._field(field_id)
        if field is None:
            return False
        page_w, page_h = self._template.page_size
        nx, ny, nw, nh = clamp_rect(
            x, y, w, h, page_w=page_w, page_h=page_h, field_type=field.type
        )
        nx, ny, nw, nh = self._maybe_snap_rect(nx, ny, nw, nh, field.type)
        if (nx, ny, nw, nh) == (field.x, field.y, field.w, field.h):
            return False
        self._checkpoint()
        field.x, field.y, field.w, field.h = nx, ny, nw, nh
        self.field_geometry_changed.emit(field_id)
        self._refresh_dirty()
        return True

    @Slot(str, result=bool)
    def remove(self, field_id: str) -> bool:
        if self._template is None or self._template.get_field(field_id) is None:
            return False
        self._checkpoint()
        if not self._template.remove_field(field_id):
            return False
        if field_id in self._selected_ids:
            self._selected_ids = [i for i in self._selected_ids if i != field_id]
            self.selection_changed.emit(self.selection)
        if self._inline_id == field_id:
            self._inline_id = None
            self._inline_before = None
            self.inline_changed.emit(None)
        self.field_removed.emit(field_id)
        self._refresh_dirty()
        return True

    @Slot(str, str, result=bool)
    def set_content(self, field_id: str, content: str) -> bool:
        field = self._field(field_id)
        if field is None or field.content == content:
            return False
        if self._inline_id != field_id:
            self._checkpoint()
        field.content = content
        self.field_content_changed.emit(field_id)
        self._refresh_dirty()
        return True

    @Slot(str, float, result=bool)
    def set_font_size(self, field_id: str, size: float) -> bool:
        field = self._field(field_id)
        if field is None or field.font_size == size:
            return False
        self._checkpoint()
        field.font_size = size
        self.field_font_changed.emit(field_id)
        self._refresh_dirty()
        return True

    # -- per-type extras (A-playable, design D3) ------------------------------

    @Slot(str, result=bool)
    def toggle_checkbox(self, field_id: str) -> bool:
        """Flip the checkbox default (double-click on the canvas or the panel).

        The default is off: a freshly placed checkbox has content "false".
        """
        field = self._field(field_id)
        if field is None or field.type is not FieldType.CHECKBOX:
            return False
        self._checkpoint()
        field.content = "false" if field.content == "true" else "true"
        self.field_props_changed.emit(field_id)
        self._refresh_dirty()
        return True

    @Slot(str, str, result=bool)
    def apply_number(self, field_id: str, text: str) -> bool:
        """Validate and store a number-field value (comma → dot, design D3).

        Refused (False, nothing written): non-numeric text and values outside
        the optional min/max bounds. Empty text is a valid (empty) value.
        A valid but unchanged value still returns True (the caller closes the
        inline editor); it emits no signal.
        """
        field = self._field(field_id)
        if field is None or field.type is not FieldType.NUMBER:
            return False
        normalized = (text or "").strip().replace(",", ".")
        if normalized:
            try:
                value = float(normalized)
            except ValueError:
                return False
            if field.min_value is not None and value < field.min_value:
                return False
            if field.max_value is not None and value > field.max_value:
                return False
        if field.content != normalized:
            # the stored value is the normalized string ('.' form; design D3)
            if self._inline_id != field_id:
                self._checkpoint()
            field.content = normalized
            self.field_content_changed.emit(field_id)
            self._refresh_dirty()
        return True

    @Slot(str, "QVariant", result=bool)
    def set_min_value(self, field_id: str, value: float | None) -> bool:
        """Optional lower bound of a number field (None = unbounded)."""
        return self._set_number_bound(field_id, "min_value", value)

    @Slot(str, "QVariant", result=bool)
    def set_max_value(self, field_id: str, value: float | None) -> bool:
        """Optional upper bound of a number field (None = unbounded)."""
        return self._set_number_bound(field_id, "max_value", value)

    def _set_number_bound(self, field_id: str, attr: str,
                          value: float | None) -> bool:
        field = self._field(field_id)
        if field is None or field.type is not FieldType.NUMBER:
            return False
        if value is None:
            if getattr(field, attr) is None:
                return False
            self._checkpoint()
            setattr(field, attr, None)
            self.field_props_changed.emit(field_id)
            self._refresh_dirty()
            return True
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        value = float(value)
        other = getattr(field, "max_value" if attr == "min_value" else "min_value")
        if other is not None:
            if (attr == "min_value" and value > other) or (
                attr == "max_value" and value < other
            ):
                return False  # min must not exceed max (and vice versa)
        if getattr(field, attr) == value:
            return False
        self._checkpoint()
        setattr(field, attr, value)
        self.field_props_changed.emit(field_id)
        self._refresh_dirty()
        return True

    @Slot(str, "QStringList", result=bool)
    def set_options(self, field_id: str, options: list[str]) -> bool:
        """Replace the dropdown's ordered options.

        Refused: a non-dropdown target and any empty/whitespace-only option
        (the spec stores options without empty strings). When the stored
        default is no longer one of the options, it is reset to empty.
        """
        field = self._field(field_id)
        if field is None or field.type is not FieldType.DROPDOWN:
            return False
        if not isinstance(options, list):
            return False
        for option in options:
            if not isinstance(option, str) or not option.strip():
                return False
        if list(field.options) == list(options):
            return False
        self._checkpoint()
        field.options = list(options)
        if field.content and field.content not in field.options:
            field.content = ""
        self.field_props_changed.emit(field_id)
        self.field_content_changed.emit(field_id)
        self._refresh_dirty()
        return True

    @Slot(str, "QVariant", result=bool)
    def set_image_id(self, field_id: str, image_id: int | None) -> bool:
        """Point an image field at an ``images`` row (or clear it).

        The ingest of a chosen file happens in the caller (the dialog owns the
        ImageStore); this only records the reference — the GC of a cleared
        file runs after the next write is persisted (design D6).
        """
        field = self._field(field_id)
        if field is None or field.type is not FieldType.IMAGE:
            return False
        if field.image_id == image_id:
            return False
        self._checkpoint()
        field.image_id = image_id
        self.field_props_changed.emit(field_id)
        self._refresh_dirty()
        return True

    # -- pages (A-playable: unlimited, named, ordered) ----------------------

    def _close_inline_session(self) -> None:
        """End an open inline session before any canvas-rebuilding operation.

        The canvas destroys every field item on a rebuild (pages_changed /
        template_changed), and the inline editor widget is a child of its
        field item. Closing the session first keeps the widget teardown on a
        live item (no access to a deleted C++ widget) and keeps the canvas
        responsive — its key handling must not stay stuck in the inline
        branch on a widget that no longer exists. Text values are already in
        the VM (the inline widget is the live buffer); a number value not
        yet applied on Enter loses its pending text, the same as a
        rejected Enter.
        """
        if self._inline_id is None:
            return
        field_id = self._inline_id
        self._inline_id = None
        self._inline_before = None
        self.inline_changed.emit(None)
        self._selected_ids = [field_id]
        self.selection_changed.emit(field_id)

    @Slot(result="QVariant")
    @Slot(int, result="QVariant")
    def add_page(self, after_index: int | None = None) -> int | None:
        """Insert a page after ``after_index`` (default: the current one).

        The new page is «Страница N» (N = new total count) and becomes current.
        """
        if self._template is None:
            return None
        self._close_inline_session()
        self._checkpoint()
        if after_index is None:
            after_index = self.current_page_index
        after_index = max(0, min(after_index, len(self._template.pages) - 1))
        page = self._template.add_page(after_index=after_index)
        pos = self._template.pages.index(page)
        self._current_page = pos
        self.pages_changed.emit()
        self.current_page_changed.emit(pos)
        self._refresh_dirty()
        return pos

    @Slot(int, result=bool)
    @Slot(int, bool, result=bool)
    def remove_page(self, index: int, confirmed: bool = False) -> bool:
        """Remove page ``index`` along with its fields.

        Refused (False, no-op): the last remaining page, the template not
        loaded, a non-empty page without ``confirmed``.
        """
        if self._template is None or len(self._template.pages) <= 1:
            return False
        if not 0 <= index < len(self._template.pages):
            return False
        page = self._template.pages[index]
        if page.fields and not confirmed:
            return False
        # Close the inline session BEFORE the fields leave the scene: the
        # canvas widget is a child of the field item and must be torn down
        # while that item is still alive (design D4 projection order).
        self._close_inline_session()
        self._checkpoint()
        removed_ids = [f.id for f in page.fields]
        self._template.remove_page(index)
        for field_id in removed_ids:
            self.field_removed.emit(field_id)
        if any(i in set(removed_ids) for i in self._selected_ids):
            self._selected_ids = [i for i in self._selected_ids if i not in set(removed_ids)]
            self.selection_changed.emit(self.selection)
        # the current page keeps referring to the same visible sheet: a page
        # removed before it shifts it down; removing it lands on the sheet
        # that now occupies the slot (or the previous one if it was last)
        if index < self._current_page:
            self._current_page -= 1
        else:
            self._current_page = min(index, len(self._template.pages) - 1)
        self.pages_changed.emit()
        self.current_page_changed.emit(self._current_page)
        self._refresh_dirty()
        return True

    @Slot(int, int, result=bool)
    def move_page(self, from_index: int, to_index: int) -> bool:
        """Reorder pages; the current page follows the moved one."""
        if self._template is None or len(self._template.pages) <= 1:
            return False
        self._close_inline_session()
        self._checkpoint()
        self._template.move_page(from_index, to_index)
        if self._current_page == from_index:
            self._current_page = max(0, min(to_index, len(self._template.pages) - 1))
        self.pages_changed.emit()
        self.current_page_changed.emit(self._current_page)
        self._refresh_dirty()
        return True

    @Slot(int, str, result=bool)
    def rename_page(self, index: int, new_name: str) -> bool:
        if self._template is None or not 0 <= index < len(self._template.pages):
            return False
        if not new_name.strip():
            return False
        if self._template.pages[index].name == new_name.strip():
            return False
        self._close_inline_session()
        self._checkpoint()
        try:
            self._template.rename_page(index, new_name)
        except ValueError:
            return False
        self.pages_changed.emit()
        self._refresh_dirty()
        return True

    # -- orientation (one per template; clamp, never scale, D4) -------------

    @Slot(str, result=bool)
    def set_orientation(self, orientation: str) -> bool:
        """Switch the whole template; out-of-fit fields are clamped in place.

        No proportional scaling (the field frame keeps its size wherever it
        still fits); the layout is marked dirty and rebuilt.
        """
        if (
            self._template is None
            or orientation not in (ORIENTATION_PORTRAIT, ORIENTATION_LANDSCAPE)
            or orientation == self._template.orientation
        ):
            return False
        self._close_inline_session()
        self._checkpoint()
        self._template.set_orientation(orientation)
        self.pages_changed.emit()
        self.orientation_changed.emit(orientation)
        self._refresh_dirty()
        return True

    # -- cross-page drag (design D5) ----------------------------------------
    # Single-field and selection drags share one live-move and one release
    # core (audit B4, task 6.5.3): the single path is the one-element case of
    # the list, distinguished by ``multi`` only where the two originally
    # opened the gesture at different moments. The @Slot wrappers below are
    # the QML contract and keep their exact signatures.

    def _drag_live(
        self,
        ids: list[str],
        ref_id: str | None,
        scene_x: float,
        scene_y: float,
        grab_dx: float,
        grab_dy: float,
        *,
        multi: bool,
    ) -> None:
        if self._template is None or not ids:
            return
        ref = ref_id if ref_id in ids else ids[0]
        field = self._field(ref)
        src = self.page_of(ref)
        if field is None or src is None:
            if not multi:
                return  # single drag on an unknown field: no state touched
            # The selection path had already opened the gesture (original
            # timing preserved): it stays open with nothing moved.
            if not self._in_gesture:
                self.begin_gesture()
            return
        page_w, page_h = self._template.page_size
        hit = scene_to_page(scene_x, scene_y, page_w, page_h, len(self._template.pages))
        if hit is None or hit[0] != src:
            if multi and not self._in_gesture:
                self.begin_gesture()  # selection opened it before the hit test
            return                    # hold the last in-page position
        if not self._in_gesture:
            self.begin_gesture()
        _, origin_y = page_origin(src, page_h)
        dx = (scene_x - grab_dx) - field.x
        dy = (scene_y - grab_dy - origin_y) - field.y
        self._suppress_checkpoint = True
        try:
            for field_id in list(ids):
                f = self._field(field_id)
                if f is None:
                    continue
                self.move(field_id, f.x + dx, f.y + dy)
        finally:
            self._suppress_checkpoint = False

    def _drag_release(
        self,
        ids: list[str],
        ref_id: str | None,
        drop_scene_x: float,
        drop_scene_y: float,
        grab_dx: float,
        grab_dy: float,
        *,
        multi: bool,
    ) -> int | None:
        if self._template is None or not ids:
            return None
        ref = ref_id if ref_id in ids else ids[0]
        if not multi and self._template.page_of(ref) is None:
            return None  # single path: unknown field returns before the gesture
        if not self._in_gesture:
            self.begin_gesture()
        try:
            origins: dict[str, tuple[int, float, float]] = {}
            for field_id in ids:
                field = self._field(field_id)
                page = self.page_of(field_id)
                if field is None or page is None:
                    continue
                origins[field_id] = (page, field.x, field.y)
            if not origins:
                return None
            ref = ref if ref in origins else next(i for i in ids if i in origins)
            ref_page, ref_x, ref_y = origins[ref]
            page_w, page_h = self._template.page_size
            hit = scene_to_page(
                drop_scene_x, drop_scene_y, page_w, page_h,
                len(self._template.pages),
            )
            if hit is not None and hit[0] != ref_page:
                dst, local_x, local_y = hit
                dx = (local_x - grab_dx) - ref_x
                dy = (local_y - grab_dy) - ref_y
                self._suppress_checkpoint = True
                try:
                    for field_id, (_page, ox, oy) in origins.items():
                        self.relocate_field(field_id, dst, ox + dx, oy + dy)
                finally:
                    self._suppress_checkpoint = False
                return dst
            _, origin_y = page_origin(ref_page, page_h)
            dx = (drop_scene_x - grab_dx) - ref_x
            dy = (drop_scene_y - grab_dy - origin_y) - ref_y
            self._suppress_checkpoint = True
            try:
                for field_id, (_page, ox, oy) in origins.items():
                    self.move(field_id, ox + dx, oy + dy)
            finally:
                self._suppress_checkpoint = False
            return ref_page
        finally:
            self.end_gesture()

    @Slot(str, float, float, float, float)
    def drag_move(self, field_id: str, scene_x: float, scene_y: float,
                  grab_dx: float, grab_dy: float) -> None:
        """Live drag feedback: the field follows the cursor while the cursor
        stays within the field's own page; over the gutter or another sheet
        the field holds its last in-page (clamped) position until release.
        Positions here are scene coordinates of the tape (D1)."""
        self._drag_live(
            [field_id], field_id, scene_x, scene_y, grab_dx, grab_dy, multi=False
        )

    @Slot(str, int, float, float, result=bool)
    def relocate_field(self, field_id: str, to_page_index: int,
                       x: float, y: float) -> bool:
        """Move the field to page ``to_page_index`` (top-left at the page-local
        point, clamped into that page) at the top of its z-order (D5)."""
        if self._template is None:
            return False
        src = self._template.page_of(field_id)
        if src is None or not 0 <= to_page_index < len(self._template.pages):
            return False
        field = self._template.get_field(field_id)
        page_w, page_h = self._template.page_size
        nx, ny, nw, nh = clamp_rect(
            x, y, field.w, field.h, page_w=page_w, page_h=page_h, field_type=field.type
        )
        nx, ny, nw, nh = self._maybe_snap_rect(
            nx, ny, nw, nh, field.type, snap_size=False
        )
        self._checkpoint()
        self._template.pages[src].fields.remove(field)
        field.x, field.y = nx, ny
        self._template.pages[to_page_index].fields.append(field)
        self.field_geometry_changed.emit(field_id)
        if to_page_index != src:
            self.pages_changed.emit()
        self._refresh_dirty()
        return True

    @Slot(str, float, float, float, float, result="QVariant")
    def apply_drag(self, field_id: str, drop_scene_x: float, drop_scene_y: float,
                    grab_dx: float, grab_dy: float) -> int | None:
        """Resolve a drag on release (D5). The cursor drop point is in scene
        coordinates of the tape; the field's top-left goes to ``drop - grab``.

        Over another page — the field is relocated there (topmost, clamped);
        over a gutter or its own page — it is clamped back into its own page.
        Returns the page index the field ended on, or None when unknown.
        """
        return self._drag_release(
            [field_id], field_id, drop_scene_x, drop_scene_y,
            grab_dx, grab_dy, multi=False,
        )

    # -- inline editing (state; the widget itself lives on the canvas) ------

    @Slot(str)
    def open_inline(self, field_id: str) -> None:
        field = self._field(field_id)
        if field is None or self._inline_id == field_id:
            return
        if len(self._selected_ids) != 1:
            return
        self._inline_id = field_id
        self._inline_snapshot = field.content
        self._inline_before = self._layout_snapshot()
        self._selected_ids = [field_id]
        self.inline_changed.emit(field_id)

    @Slot()
    def apply_inline(self) -> None:
        """Close inline editing keeping the current content (already written
        into the single buffer through ``set_content``)."""
        if self._inline_id is None:
            return
        field_id = self._inline_id
        if (
            self._inline_before is not None
            and self._layout_snapshot() != self._inline_before
        ):
            self._push_undo(self._inline_before)
        self._inline_id = None
        self._inline_before = None
        self.inline_changed.emit(None)
        self._selected_ids = [field_id]
        self.selection_changed.emit(field_id)

    @Slot()
    def cancel_inline(self) -> None:
        """Close inline editing restoring the pre-double-click content; the
        field stays selected.

        The restore is not a new layout change: the buffer returns to its
        pre-double-click state, so the dirty flag is simply re-derived (a sheet
        that was clean before the double-click stays clean — no spurious
        unsaved-changes prompt).
        """
        if self._inline_id is None:
            return
        field_id = self._inline_id
        field = self._field(field_id)
        if field is not None and field.content != self._inline_snapshot:
            field.content = self._inline_snapshot
            self.field_content_changed.emit(field_id)
        self._inline_id = None
        self._inline_before = None
        self.inline_changed.emit(None)
        self._selected_ids = [field_id]
        self.selection_changed.emit(field_id)
        self._refresh_dirty()

    # -- undo / redo (D1) ---------------------------------------------------

    @Slot()
    def undo(self) -> None:
        if not self._history.can_undo or self._template is None:
            return
        self._history.push_redo(self._layout_snapshot())
        self._restore_layout(self._history.take_undo())
        self.history_changed.emit()

    @Slot()
    def redo(self) -> None:
        if not self._history.can_redo or self._template is None:
            return
        self._push_undo(self._layout_snapshot(), clear_redo=False)
        self._restore_layout(self._history.take_redo())

    def _push_undo(
        self, snap: tuple[str, str], *, clear_redo: bool = True
    ) -> None:
        """The one sink into the undo stack (audit B4, task 6.5.1 replaces
        four copies); the trimming rules live in :class:`LayoutHistory`."""
        self._history.push_undo(snap, clear_redo=clear_redo)
        self.history_changed.emit()

    _UNSET = object()

    @Slot()
    @Slot(bool)
    def begin_gesture(self, snap_override: object = _UNSET) -> None:
        if self._template is None:
            return
        if not self._in_gesture:
            self._push_undo(self._layout_snapshot())
        self._in_gesture = True
        if snap_override is not self._UNSET:
            self._snap_override = snap_override  # type: ignore[assignment]

    @Slot()
    def begin_edit(self) -> None:
        self.begin_gesture()

    @Slot()
    def end_edit(self) -> None:
        self.end_gesture()

    @Slot()
    def end_gesture(self) -> None:
        if self._history.drop_top_if_matches(self._layout_snapshot()):
            self.history_changed.emit()
        self._in_gesture = False
        self._snap_override = None

    # -- selection operations (D2) ------------------------------------------

    @Slot(float, float, result=bool)
    def move_selection(self, dx: float, dy: float) -> bool:
        ids = list(self._selected_ids)
        if not ids:
            return False
        self._checkpoint()
        self._suppress_checkpoint = True
        changed = False
        try:
            for field_id in ids:
                field = self._field(field_id)
                if field is None:
                    continue
                if self.move(field_id, field.x + dx, field.y + dy):
                    changed = True
        finally:
            self._suppress_checkpoint = False
        return changed

    @Slot(result=bool)
    def remove_selection(self) -> bool:
        ids = list(self._selected_ids)
        if not ids:
            return False
        self._checkpoint()
        self._suppress_checkpoint = True
        try:
            for field_id in ids:
                self.remove(field_id)
        finally:
            self._suppress_checkpoint = False
        return True

    @Slot(float, float, float, float)
    @Slot(float, float, float, float, "QVariant")
    def apply_drag_selection(
        self,
        drop_scene_x: float,
        drop_scene_y: float,
        grab_dx: float,
        grab_dy: float,
        ref_id: str | None = None,
    ) -> None:
        # The multi-member case of the one release core (task 6.5.3); the
        # landing page is not surfaced to the selection flow (void slot).
        self._drag_release(
            list(self._selected_ids), ref_id, drop_scene_x, drop_scene_y,
            grab_dx, grab_dy, multi=True,
        )

    @Slot(float, float, float, float)
    @Slot(float, float, float, float, "QVariant")
    def drag_move_selection(
        self,
        scene_x: float,
        scene_y: float,
        grab_dx: float,
        grab_dy: float,
        ref_id: str | None = None,
    ) -> None:
        # The multi-member case of the one live-move core (task 6.5.3).
        self._drag_live(
            list(self._selected_ids), ref_id, scene_x, scene_y,
            grab_dx, grab_dy, multi=True,
        )

    # -- z-order (D4) -------------------------------------------------------

    @Slot(result=bool)
    def bring_to_front(self) -> bool:
        return self._reorder_selected(to_front=True)

    @Slot(result=bool)
    def send_to_back(self) -> bool:
        return self._reorder_selected(to_front=False)

    def _reorder_selected(self, to_front: bool) -> bool:
        if self._template is None or not self._selected_ids:
            return False
        selected = set(self._selected_ids)
        planned: list[tuple[int, list[SheetField]]] = []
        changed = False
        for i, page in enumerate(self._template.pages):
            chosen = [f for f in page.fields if f.id in selected]
            rest = [f for f in page.fields if f.id not in selected]
            if not chosen:
                continue
            new_order = rest + chosen if to_front else chosen + rest
            if [f.id for f in new_order] != [f.id for f in page.fields]:
                changed = True
            planned.append((i, new_order))
        if not changed:
            return False
        self._checkpoint()
        for i, new_order in planned:
            self._template.pages[i].fields[:] = new_order
        self.pages_changed.emit()
        self._refresh_dirty()
        return True

    # -- clipboard (D5) -----------------------------------------------------

    def copy(self) -> None:
        self._clipboard = []
        if self._template is None:
            return
        for field_id in self._selected_ids:
            field = self._field(field_id)
            page = self.page_of(field_id)
            if field is None or page is None:
                continue
            self._clipboard.append((deepcopy(field), page))
        self.clipboard_changed.emit()

    def duplicate(self) -> list[str]:
        if self._template is None or not self._selected_ids:
            return []
        self._checkpoint()
        self._suppress_checkpoint = True
        new_ids: list[str] = []
        try:
            for field_id in list(self._selected_ids):
                field = self._field(field_id)
                page = self.page_of(field_id)
                if field is None or page is None:
                    continue
                copy = self._clone_field(
                    field, page, field.x + DUPLICATE_OFFSET_PT, field.y + DUPLICATE_OFFSET_PT
                )
                new_ids.append(copy.id)
        finally:
            self._suppress_checkpoint = False
        self._selected_ids = new_ids
        self.selection_changed.emit(self.selection)
        self._refresh_dirty()
        return new_ids

    def paste(self, visible_center: tuple[float, float] | None = None) -> list[str]:
        if self._template is None or not self._clipboard:
            return []
        self._checkpoint()
        self._suppress_checkpoint = True
        new_ids: list[str] = []
        current = self.current_page_index
        page_w, page_h = self._template.page_size
        first_field, first_page = self._clipboard[0]
        try:
            if first_page == current:
                for field, _page in self._clipboard:
                    copy = self._clone_field(
                        field, current,
                        field.x + DUPLICATE_OFFSET_PT,
                        field.y + DUPLICATE_OFFSET_PT,
                    )
                    new_ids.append(copy.id)
            else:
                if visible_center is not None:
                    cx = visible_center[0] - first_field.w / 2
                    cy = visible_center[1] - first_field.h / 2
                else:
                    cx = (page_w - first_field.w) / 2
                    cy = (page_h - first_field.h) / 2
                ox, oy = first_field.x, first_field.y
                for field, _page in self._clipboard:
                    copy = self._clone_field(
                        field, current,
                        cx + (field.x - ox),
                        cy + (field.y - oy),
                    )
                    new_ids.append(copy.id)
        finally:
            self._suppress_checkpoint = False
        self._selected_ids = new_ids
        self.selection_changed.emit(self.selection)
        self._refresh_dirty()
        return new_ids

    def _clone_field(
        self, src: SheetField, page_index: int, x: float, y: float
    ) -> SheetField:
        new = replace(src, id=uuid4().hex, x=x, y=y, options=list(src.options))
        page_w, page_h = self._template.page_size
        new.x, new.y, new.w, new.h = clamp_rect(
            new.x, new.y, new.w, new.h,
            page_w=page_w, page_h=page_h, field_type=new.type,
        )
        new.x, new.y, new.w, new.h = self._maybe_snap_rect(
            new.x, new.y, new.w, new.h, new.type, snap_size=False
        )
        self._template.pages[page_index].fields.append(new)
        self.field_added.emit(new.id)
        return new

    # -- helpers ------------------------------------------------------------

    def _layout_snapshot(self) -> tuple[str, str] | None:
        if self._template is None:
            return None
        return (self._template.to_pages_json(), self._template.orientation)

    def _restore_layout(self, snap: tuple[str, str]) -> None:
        pages_json, orientation = snap
        restored = SheetTemplate.parse_template(
            pages_json,
            name=self._template.name,
            orientation=orientation,
            id=self._template.id,
        )
        self._template.pages = restored.pages
        self._template.orientation = orientation
        valid = {f.id for page in self._template.pages for f in page.fields}
        self._selected_ids = [i for i in self._selected_ids if i in valid]
        self._inline_id = None
        self._inline_before = None
        self.pages_changed.emit()
        self.orientation_changed.emit(orientation)
        self.selection_changed.emit(self.selection)
        self.inline_changed.emit(None)
        self._refresh_dirty()

    def _clear_history(self) -> None:
        self._history.clear()
        self._in_gesture = False
        self._snap_override = None
        self.history_changed.emit()

    def _checkpoint(self) -> None:
        if (
            self._template is None
            or self._in_gesture
            or self._suppress_checkpoint
        ):
            return
        self._push_undo(self._layout_snapshot())

    def _maybe_snap_rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        field_type: FieldType,
        snap_size: bool = True,
    ) -> tuple[float, float, float, float]:
        if not self._snap_active or self._template is None:
            return x, y, w, h
        page_w, page_h = self._template.page_size
        sw = snap_coord(w) if snap_size else w
        sh = snap_coord(h) if snap_size else h
        return clamp_rect(
            snap_coord(x), snap_coord(y), sw, sh,
            page_w=page_w, page_h=page_h, field_type=field_type,
        )

    def _snap_field_geometry(self, field: SheetField, snap_size: bool = True) -> None:
        nx, ny, nw, nh = self._maybe_snap_rect(
            field.x, field.y, field.w, field.h, field.type, snap_size=snap_size
        )
        field.x, field.y, field.w, field.h = nx, ny, nw, nh

    def _refresh_dirty(self) -> None:
        """Re-derive the dirty flag: layout differs from the last load/save.

        Kept cheap for A1: one JSON serialize of the (single-page) layout per
        mutation. A1 sheets are small; if this ever gets hot, compare field
        lists instead.
        """
        if self._template is None or self._saved_pages_json is None:
            return
        self._set_dirty(self._template.to_pages_json() != self._saved_pages_json)

    def _set_dirty(self, dirty: bool) -> None:
        if dirty == self._dirty:
            return
        self._dirty = dirty
        self.dirty_changed.emit(dirty)
