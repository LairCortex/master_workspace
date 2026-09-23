"""The canvas field projection as its own module (audit B4, task 6.5.4).

``SheetFieldModel`` used to sit next to the designer view model it serves,
reaching into it through duck-typed ``getattr``; the two view models it
projects for (design and fill) now meet it through explicit ``Protocol``
contracts, and the class itself has no import path through the view models.
"""
from __future__ import annotations

from typing import Any, Protocol

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    Qt,
    Slot,
)

from app.domain.entities.character_sheet import SheetField, SheetTemplate
from app.domain.entities.character_sheet_instance import resolve_display
from app.domain.enums.field_type import FieldType


class SheetDesignSource(Protocol):
    """The read surface the field model takes from the design view model."""

    @property
    def template(self) -> SheetTemplate | None:
        """The live template whose pages/fields are the model rows."""
        ...


class SheetFillSource(SheetDesignSource, Protocol):
    """Additional read surface of the fill view model.

    Required, not probed: task 6.5.4 replaced ``getattr(self._vm, ...)``
    with this contract — a fill-mode model holds its source under this
    protocol (the view model's ``values``/``read_only`` are properties it
    declares unconditionally).
    """

    @property
    def values(self) -> dict[str, Any]:
        """The instance value map behind ``resolve_display``."""
        ...

    @property
    def read_only(self) -> bool:
        """When true the fill rows announce ``disabled`` to the canvas."""
        ...


class SheetFieldModel(QAbstractListModel):
    """Canvas fields as a QML-ready list model (Q3b D4 / spec «Питание QML-списков
    списочной моделью», scenario «Поля канваса идут из модели»).

    The rows are the live ``SheetField`` objects of the VM ``template`` in
    flat order (page order, then the page's field order). The model never
    copies the set: a mutation through the VM mutates the same row object in
    place (identity preserved — verified by tests), and the role reads return
    fresh values because they delegate to the field itself. Geometry,
    per-type extras and the current-page rules are not re-derived here.

    Feeding is incremental through the VM's existing signals (the contract is
    unchanged): add/remove → ``beginInsertRows``/``beginRemoveRows``,
    geometry/content/font/props → per-row ``dataChanged`` with the moved role
    set, page structure / orientation / a full reload → model reset.

    ``fill=True`` serves the fill view over the fill VM: the content/imageKey
    for fillable fields resolve through the domain rule
    :func:`resolve_display` (the instance value map first, the template
    default otherwise — there is no second value-resolution implementation);
    image fields render empty text (the image goes through ``imageKey``);
    checkbox values reach the canvas as "true"/"false" strings, matching the
    template-side storage form; ``disabled`` reflects the fill VM's
    ``read_only``. Design rows never disable.
    """

    ID_ROLE = Qt.ItemDataRole.UserRole + 1
    TYPE_ROLE = Qt.ItemDataRole.UserRole + 2
    PAGE_ROLE = Qt.ItemDataRole.UserRole + 3
    X_ROLE = Qt.ItemDataRole.UserRole + 4
    Y_ROLE = Qt.ItemDataRole.UserRole + 5
    W_ROLE = Qt.ItemDataRole.UserRole + 6
    H_ROLE = Qt.ItemDataRole.UserRole + 7
    FONT_SIZE_ROLE = Qt.ItemDataRole.UserRole + 8
    CONTENT_ROLE = Qt.ItemDataRole.UserRole + 9
    IMAGE_KEY_ROLE = Qt.ItemDataRole.UserRole + 10
    OPTIONS_COUNT_ROLE = Qt.ItemDataRole.UserRole + 11
    DISABLED_ROLE = Qt.ItemDataRole.UserRole + 12

    GEOMETRY_ROLES = [PAGE_ROLE, X_ROLE, Y_ROLE, W_ROLE, H_ROLE]

    def __init__(
        self,
        view_model: SheetDesignSource,
        fill: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._vm: SheetDesignSource = view_model
        self._fill = bool(fill)
        # D5 (task 6.5.4): the fill-side reads go through this bound
        # protocol member instead of probing the VM with ``getattr``.
        self._fill_vm: SheetFillSource | None = view_model if fill else None
        self._rows: list[SheetField] = []
        self._page_of_row: list[int] = []
        self._rebuild_rows()

    # -- projection helpers ---------------------------------------------------

    @property
    def _template(self) -> SheetTemplate | None:
        return self._vm.template

    def _rebuild_rows(self) -> None:
        rows: list[SheetField] = []
        page_of_row: list[int] = []
        template = self._template
        if template is not None:
            for i, page in enumerate(template.pages):
                for field in page.fields:
                    rows.append(field)
                    page_of_row.append(i)
        self._rows = rows
        self._page_of_row = page_of_row

    @property
    def rows(self) -> tuple[SheetField, ...]:
        """The delivered live field objects (introspection/test seam; the tuple
        snapshot does not imply a copy of the set: entries are the template's
        own fields — identity preserved by every transition)."""
        return tuple(self._rows)

    # -- incremental feeding (connected to the VM's existing signals) ---------

    def on_field_added(self, field_id: str) -> None:
        if self._row_in_projection(field_id) is not None:
            # the id is already a row — something structural happened outside
            # a clean add/remove pair; resync honestly.
            self.on_template_changed()
            return
        row = self._flat_index_of(self._template, field_id)
        if row > len(self._rows):
            # structural surprise (id present but beyond the projection) —
            # fall back to a reset: the QML view re-syncs correctly either
            # way, the reset only costs delegate re-materialization.
            self.on_template_changed()
            return
        field = self._template.get_field(field_id)
        if field is None:  # raced with a removal — the remove path rebuilds
            return
        page_index = self._flat_index_page(self._template, row)
        self.beginInsertRows(QModelIndex(), row, row)
        self._rows.insert(row, field)
        self._page_of_row.insert(row, page_index)
        self.endInsertRows()

    def on_field_removed(self, field_id: str) -> None:
        row = self._row_in_projection(field_id)
        if row is None:  # unknown id — nothing incremental to remove
            self.on_template_changed()
            return
        self.beginRemoveRows(QModelIndex(), row, row)
        del self._rows[row]
        del self._page_of_row[row]
        self.endRemoveRows()

    def on_geometry_changed(self, field_id: str) -> None:
        self._notify(field_id, list(self.GEOMETRY_ROLES))

    def on_content_changed(self, field_id: str) -> None:
        self._notify(field_id, [self.CONTENT_ROLE])

    def on_font_changed(self, field_id: str) -> None:
        self._notify(field_id, [self.FONT_SIZE_ROLE])

    def on_props_changed(self, field_id: str) -> None:
        self._notify(
            field_id,
            [self.CONTENT_ROLE, self.IMAGE_KEY_ROLE, self.OPTIONS_COUNT_ROLE],
        )

    def on_values_changed(self) -> None:
        # the whole value map moved (undo/redo): every displayed value re-reads
        self._notify_all([self.CONTENT_ROLE, self.IMAGE_KEY_ROLE])

    def on_read_only_changed(self, _enabled: bool) -> None:
        self._notify_all([self.DISABLED_ROLE])

    def on_template_changed(self) -> None:
        self.beginResetModel()
        self._rebuild_rows()
        self.endResetModel()

    # -- QAbstractListModel contract -------------------------------------------

    def _notify(self, field_id: str, roles: list[int]) -> None:
        row = self._row_in_projection(field_id)
        if row is None:
            # the id lives outside the current projection (page removed — the
            # following pages_changed resets the view anyway)
            return
        if self._flat_index_of(self._template, field_id) != row:
            # the flat order (the tape's z-order) moved under this field
            # (relocate-to-top within the page): dataChanged cannot reorder
            # rows — the view honestly needs the structure reset
            self.on_template_changed()
            return
        index = self.index(row)
        self.dataChanged.emit(index, index, roles)

    def _notify_all(self, roles: list[int]) -> None:
        if not self._rows:
            return
        self.dataChanged.emit(self.index(0), self.index(len(self._rows) - 1), roles)

    # -- row-position maths (template order is the single truth) ---------------

    def _row_in_projection(self, field_id: str) -> int | None:
        for i, field in enumerate(self._rows):
            if field.id == field_id:
                return i
        return None

    @staticmethod
    def _flat_index_of(template: SheetTemplate | None, field_id: str) -> int:
        """Row of ``field_id`` in the current template order, -1 when absent."""
        if template is None:
            return -1
        row = 0
        for page in template.pages:
            for field in page.fields:
                if field.id == field_id:
                    return row
                row += 1
        return -1

    @staticmethod
    def _flat_index_page(template: SheetTemplate, index: int) -> int:
        """Page of a flat row in the template order (the index space
        insertRows announces to the view)."""
        row = index
        for page_index, page in enumerate(template.pages):
            if row < len(page.fields):
                return page_index
            row -= len(page.fields)
        raise IndexError(index)

    # -- QAbstractListModel contract -------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # Qt API name
        return 0 if parent.isValid() else len(self._rows)

    def data(
        self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ):  # Qt API name
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        field = self._rows[index.row()]
        if role == self.ID_ROLE:
            return field.id
        if role == self.TYPE_ROLE:
            return field.type.value
        if role == self.PAGE_ROLE:
            return self._page_of_row[index.row()]
        if role == self.X_ROLE:
            return field.x
        if role == self.Y_ROLE:
            return field.y
        if role == self.W_ROLE:
            return field.w
        if role == self.H_ROLE:
            return field.h
        if role == self.FONT_SIZE_ROLE:
            return field.font_size
        if role == self.CONTENT_ROLE:
            return self._content_for(field)
        if role == self.IMAGE_KEY_ROLE:
            return self._image_key_for(field)
        if role == self.OPTIONS_COUNT_ROLE:
            return len(field.options)
        if role == self.DISABLED_ROLE:
            return bool(
                self._fill_vm is not None and self._fill_vm.read_only
            )
        return None

    # -- fill/design value rules: both delegate, never re-implement ------------

    def _content_for(self, field: SheetField) -> str:
        if not self._fill:
            return field.content
        if field.type is FieldType.IMAGE:
            return ""
        return self._display_text(field)

    def _image_key_for(self, field: SheetField) -> str:
        if not self._fill:
            return "" if field.image_id is None else str(field.image_id)
        if field.type is not FieldType.IMAGE:
            return ""
        return self._display_text(field)

    def _display_text(self, field: SheetField) -> str:
        # The domain's single value-resolution rule (instance map first,
        # template default otherwise) — no second implementation (D4).
        assert self._fill_vm is not None  # fill-only row resolution path
        value = resolve_display(field, self._fill_vm.values)
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def roleNames(self) -> dict:  # Qt API name
        return {
            self.ID_ROLE: b"id",
            self.TYPE_ROLE: b"type",
            self.PAGE_ROLE: b"page",
            self.X_ROLE: b"x",
            self.Y_ROLE: b"y",
            self.W_ROLE: b"w",
            self.H_ROLE: b"h",
            self.FONT_SIZE_ROLE: b"fontSize",
            self.CONTENT_ROLE: b"content",
            self.IMAGE_KEY_ROLE: b"imageKey",
            self.OPTIONS_COUNT_ROLE: b"optionsCount",
            self.DISABLED_ROLE: b"disabled",
        }

    # Q3b 2.1: the canvas hit-test/gesture maths run in the QML view layer and
    # need row reads from plain JS, where the list-protocol (``.count`` /
    # ``delegate.model``) is only available inside views. This is the same
    # seam the timeline island's ``TimelineRowModel.get`` established (Q2.5a):
    # a pure role projection through ``data()`` — no second geometry source,
    # the values are the very ones ``data()`` returns to the delegates.
    @Slot(int, result="QVariantMap")
    def get(self, index: int) -> dict:
        i = int(index)
        if i < 0 or i >= len(self._rows):
            return {}
        model_index = self.index(i)
        return {
            name.decode("ascii"): self.data(model_index, role)
            for role, name in self.roleNames().items()
        }

