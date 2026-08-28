"""Property panel of the sheet editor: geometry, font size and per-type props.

A projection of the selected VM field (design D4): it writes through
``CharacterSheetViewModel`` and re-reads on the VM's signals — the VM is the
only buffer. Geometry edits are clamped by the VM into the (oriented) page;
the panel spins show the effective (clamped) values. No family/weight
pickers — one bundled font, size only.

A-playable per-type sections (design D3):
- label / text / textarea: the content edit (``content_edit``);
- number: a line edit (validates on commit: comma → dot, min/max) + optional
  min/max bounds;
- checkbox: an on/off "default" state;
- dropdown: the ordered options (no empty entries) + the default choice;
- image: pick (the owner dialog ingests through the ImageStore) / clear;
- rect / line: decorative — no data section.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.domain.entities.character_sheet import (
    LINE_MIN_THICKNESS,
    MIN_FIELD_H,
    MIN_FIELD_W,
    PAGE_HEIGHT_PT,
    PAGE_WIDTH_PT,
)
from app.domain.enums.field_type import FieldType
from app.presentation.viewmodels.character_sheet_viewmodel import (
    CharacterSheetViewModel,
)

MAX_FONT_SIZE: float = 72.0
MIN_FONT_SIZE: float = 4.0
_BOUND_RANGE: tuple[float, float] = (-1e9, 1e9)

_TEXTUAL_TYPES = (
    FieldType.LABEL, FieldType.TEXT, FieldType.TEXTAREA,
    FieldType.NUMBER, FieldType.DROPDOWN,
)
_CONTENT_EDIT_TYPES = (FieldType.LABEL, FieldType.TEXT, FieldType.TEXTAREA)


def _geom_spin(min_v: float, max_v: float, parent: QWidget | None) -> QDoubleSpinBox:
    spin = QDoubleSpinBox(parent)
    spin.setDecimals(2)  # A4 constants have 2 decimals (595.28 x 841.89)
    spin.setRange(min_v, max_v)
    spin.setSingleStep(1.0)
    return spin


class SheetPropertiesPanel(QWidget):
    """x/y/w/h, font size and the per-type properties of the selected field."""

    # The selected image field asks the owner (editor dialog) to pick a file;
    # the ingest goes through the game's ImageStore (one pipeline, D6).
    image_pick_requested = Signal(str)

    def __init__(self, vm: CharacterSheetViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = vm
        self._fid: str | None = None
        self._syncing = False

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)

        self.x_spin = _geom_spin(0.0, PAGE_WIDTH_PT, self)
        self.y_spin = _geom_spin(0.0, PAGE_HEIGHT_PT, self)
        self.w_spin = _geom_spin(MIN_FIELD_W, PAGE_WIDTH_PT, self)
        self.h_spin = _geom_spin(MIN_FIELD_H, PAGE_HEIGHT_PT, self)
        self.font_spin = _geom_spin(MIN_FONT_SIZE, MAX_FONT_SIZE, self)

        for row, (label, spin) in enumerate([
            ("X", self.x_spin),
            ("Y", self.y_spin),
            ("W", self.w_spin),
            ("H", self.h_spin),
        ]):
            grid.addWidget(QLabel(label, self), row, 0)
            grid.addWidget(spin, row, 1)
        grid.addWidget(QLabel("Кегль", self), 4, 0)
        grid.addWidget(self.font_spin, 4, 1)

        # -- per-type sections (one is visible at a time) ---------------------

        self.content_edit = QPlainTextEdit(self)
        self.content_edit.setPlaceholderText("Текст поля")

        self.number_edit = QLineEdit(self)
        self.number_edit.setPlaceholderText("Число (запятая допустима)")
        self.min_check = QCheckBox("min", self)
        self.min_spin = QDoubleSpinBox(self)
        self.max_check = QCheckBox("max", self)
        self.max_spin = QDoubleSpinBox(self)
        for spin in (self.min_spin, self.max_spin):
            spin.setDecimals(2)
            spin.setRange(*_BOUND_RANGE)

        self.checkbox_state = QCheckBox("Включение по умолчанию", self)

        self.options_list = QListWidget(self)
        self.option_input = QLineEdit(self)
        self.option_input.setPlaceholderText("Новая опция")
        self.option_add_button = QPushButton("Добавить", self)
        self.option_remove_button = QPushButton("Удалить", self)
        self.option_up_button = QPushButton("↑", self)
        self.option_down_button = QPushButton("↓", self)
        self.default_combo = QComboBox(self)

        self.image_pick_button = QPushButton("Выбрать файл…", self)
        self.image_clear_button = QPushButton("Очистить", self)
        self.image_label = QLabel("Картинка не выбрана", self)

        self.decor_label = QLabel(
            "Декоративное поле: данных персонажа не хранит.", self
        )

        def make_section(*widgets: QWidget) -> QWidget:
            section = QWidget(self)
            layout = QVBoxLayout(section)
            layout.setContentsMargins(0, 0, 0, 0)
            for w in widgets:
                layout.addWidget(w)
            return section

        self._text_section = make_section(self.content_edit)
        number_section = make_section(self.number_edit)
        min_row = QHBoxLayout()
        min_row.addWidget(self.min_check)
        min_row.addWidget(self.min_spin)
        number_section.layout().addLayout(min_row)
        max_row = QHBoxLayout()
        max_row.addWidget(self.max_check)
        max_row.addWidget(self.max_spin)
        number_section.layout().addLayout(max_row)
        dropdown_section = make_section(self.options_list)
        input_row = QHBoxLayout()
        input_row.addWidget(self.option_input)
        input_row.addWidget(self.option_add_button)
        dropdown_section.layout().addLayout(input_row)
        ops_row = QHBoxLayout()
        ops_row.addWidget(self.option_remove_button)
        ops_row.addWidget(self.option_up_button)
        ops_row.addWidget(self.option_down_button)
        ops_row.addStretch(1)
        dropdown_section.layout().addLayout(ops_row)
        combo_row = QHBoxLayout()
        combo_row.addWidget(QLabel("Default:", self))
        combo_row.addWidget(self.default_combo)
        dropdown_section.layout().addLayout(combo_row)
        self._checkbox_section = make_section(self.checkbox_state)
        self._image_section = make_section(
            self.image_pick_button, self.image_clear_button, self.image_label
        )
        self._decor_section = make_section(self.decor_label)

        # every type maps to one section (label/text/textarea share the edit,
        # rect/line share the "no data" note)
        self._sections: dict[FieldType, QWidget] = {
            FieldType.LABEL: self._text_section,
            FieldType.TEXT: self._text_section,
            FieldType.TEXTAREA: self._text_section,
            FieldType.NUMBER: number_section,
            FieldType.DROPDOWN: dropdown_section,
            FieldType.CHECKBOX: self._checkbox_section,
            FieldType.IMAGE: self._image_section,
            FieldType.RECT: self._decor_section,
            FieldType.LINE: self._decor_section,
        }

        self.snap_check = QCheckBox("Привязка к сетке", self)
        self.bring_front_button = QPushButton("На передний план", self)
        self.send_back_button = QPushButton("На задний план", self)

        self._field_box = QWidget(self)
        field_layout = QVBoxLayout(self._field_box)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.addLayout(grid)
        field_layout.addWidget(QLabel("Свойства:", self._field_box))
        self.current_section: QWidget | None = None
        for section in dict.fromkeys(self._sections.values()):
            section.setParent(self._field_box)
            field_layout.addWidget(section)
            section.hide()  # a section shows only while its type is selected

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.addWidget(self.snap_check)
        z_row = QHBoxLayout()
        z_row.addWidget(self.bring_front_button)
        z_row.addWidget(self.send_back_button)
        outer.addLayout(z_row)
        outer.addWidget(self._field_box)

        # -- VM → panel --------------------------------------------------------
        vm.selection_changed.connect(self._on_selection)
        vm.selection_changed.connect(self._sync_z_buttons)
        vm.field_geometry_changed.connect(self._on_geometry)
        vm.field_content_changed.connect(self._on_content_changed)
        vm.field_font_changed.connect(self._on_font_changed)
        vm.field_props_changed.connect(self._on_props_changed)
        vm.field_removed.connect(self._on_removed)
        vm.template_changed.connect(lambda: self._on_selection(self._vm.selection))
        # the page geometry is orientation-dependent: the spin ranges must
        # switch with the template (D4), not stay on the portrait A4 constants
        vm.orientation_changed.connect(self._apply_page_bounds)
        vm.template_changed.connect(self._apply_page_bounds)

        # -- panel → VM ----------------------------------------------------------
        self.x_spin.valueChanged.connect(self._on_x)
        self.y_spin.valueChanged.connect(self._on_y)
        self.w_spin.valueChanged.connect(self._on_w)
        self.h_spin.valueChanged.connect(self._on_h)
        self.font_spin.valueChanged.connect(self._on_font)
        self.content_edit.textChanged.connect(self._on_content)

        self.number_edit.editingFinished.connect(self._on_number_commit)
        self.min_check.toggled.connect(lambda _c: self._on_bound())
        self.min_spin.valueChanged.connect(lambda _v: self._on_bound())
        self.max_check.toggled.connect(lambda _c: self._on_bound())
        self.max_spin.valueChanged.connect(lambda _v: self._on_bound())

        self.checkbox_state.toggled.connect(self._on_checkbox_toggled)

        self.option_add_button.clicked.connect(self._on_option_add)
        self.option_remove_button.clicked.connect(self._on_option_remove)
        self.option_up_button.clicked.connect(lambda: self._on_option_move(-1))
        self.option_down_button.clicked.connect(lambda: self._on_option_move(1))
        self.option_input.returnPressed.connect(self._on_option_add)
        self.default_combo.currentIndexChanged.connect(self._on_default_combo)

        self.image_pick_button.clicked.connect(lambda: self.image_pick_requested.emit(self._fid or ""))
        self.image_clear_button.clicked.connect(
            lambda: self._vm.set_image_id(self._fid, None) if self._fid else None
        )

        self.snap_check.toggled.connect(vm.set_snap_enabled)
        vm.snap_changed.connect(self._sync_snap_check)
        self.bring_front_button.clicked.connect(vm.bring_to_front)
        self.send_back_button.clicked.connect(vm.send_to_back)
        self._sync_z_buttons()

        for spin in (
            self.x_spin, self.y_spin, self.w_spin, self.h_spin, self.font_spin,
            self.min_spin, self.max_spin,
        ):
            spin.editingFinished.connect(self._end_edit)
        self.number_edit.editingFinished.connect(self._end_edit)
        self.content_edit.installEventFilter(self)

        self._show_field(vm.selection)

    def isEnabled(self) -> bool:
        return self._field_box.isEnabled()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.content_edit and event.type() == QEvent.Type.FocusOut:
            self._end_edit()
        return super().eventFilter(obj, event)

    def _begin_edit(self) -> None:
        if not self._syncing:
            self._vm.begin_edit()

    def _end_edit(self) -> None:
        if not self._syncing:
            self._vm.end_edit()

    def _sync_snap_check(self, enabled: bool) -> None:
        self.snap_check.blockSignals(True)
        try:
            self.snap_check.setChecked(enabled)
        finally:
            self.snap_check.blockSignals(False)

    def _sync_z_buttons(self, _fid=None) -> None:
        has_sel = bool(self._vm.selected_ids)
        self.bring_front_button.setEnabled(has_sel)
        self.send_back_button.setEnabled(has_sel)

    # -- data ----------------------------------------------------------------

    def field_id(self) -> str | None:
        return self._fid

    def _field(self):
        if self._fid is None or self._vm.template is None:
            return None
        return self._vm.template.get_field(self._fid)

    @staticmethod
    def _with_signals_blocked(*widgets, fn) -> None:
        for w in widgets:
            w.blockSignals(True)
        try:
            fn()
        finally:
            for w in widgets:
                w.blockSignals(False)

    def _set_syncing(self, flag: bool) -> None:
        self._syncing = flag

    def _page_bounds(self) -> tuple[float, float]:
        """(width, height) of the template's pages in points — portrait A4
        until a template is loaded. The geometry spins are bounded by the
        (oriented) page, so landscape pages allow a wider x/w range."""
        template = self._vm.template
        if template is None:
            return PAGE_WIDTH_PT, PAGE_HEIGHT_PT
        return template.page_size

    def _apply_page_bounds(self, _orientation: str | None = None) -> None:
        """The page geometry changed (orientation switch / template load):
        resync the geometry spin ranges and the shown field."""
        page_w, page_h = self._page_bounds()
        if self._fid is not None and self._field() is not None:
            self._show_field(self._fid)  # ranges (incl. the line min) + values
            return
        self._with_signals_blocked(
            self.x_spin, self.y_spin, self.w_spin, self.h_spin,
            fn=lambda: (
                self.x_spin.setRange(0.0, page_w),
                self.y_spin.setRange(0.0, page_h),
                self.w_spin.setRange(MIN_FIELD_W, page_w),
                self.h_spin.setRange(MIN_FIELD_H, page_h),
            ),
        )

    def _visible_section(self, ftype: FieldType) -> QWidget:
        section = self._sections[ftype]
        if self.current_section is not section:
            if self.current_section is not None:
                self.current_section.hide()
            section.show()
            self.current_section = section
            return section
        return section

    # -- VM → panel ----------------------------------------------------------

    def _show_field(self, fid) -> None:
        self._fid = fid if fid is not None else None
        self._field_box.setEnabled(self._fid is not None)
        field = self._field()
        if field is None:
            if self.current_section is not None:
                self.current_section.hide()
                self.current_section = None
            return
        page_w, page_h = self._page_bounds()
        is_line = field.type is FieldType.LINE
        w_min = LINE_MIN_THICKNESS if is_line else MIN_FIELD_W
        h_min = LINE_MIN_THICKNESS if is_line else MIN_FIELD_H
        self._with_signals_blocked(
            self.x_spin, self.y_spin, self.w_spin, self.h_spin,
            self.font_spin, self.content_edit,
            fn=lambda: (
                self.x_spin.setRange(0.0, page_w),
                self.y_spin.setRange(0.0, page_h),
                self.w_spin.setRange(w_min, page_w),
                self.h_spin.setRange(h_min, page_h),
                self.x_spin.setValue(field.x),
                self.y_spin.setValue(field.y),
                self.w_spin.setValue(field.w),
                self.h_spin.setValue(field.h),
                self.font_spin.setValue(field.font_size),
                self.content_edit.setPlainText(field.content),
            ),
        )
        show_font = field.type in _TEXTUAL_TYPES
        self.font_spin.setVisible(show_font)
        self._visible_section(field.type)
        self._sync_section(field.type)

    def _sync_section(self, ftype: FieldType) -> None:
        field = self._field()
        if field is None:
            return
        self._set_syncing(True)
        try:
            if ftype in _CONTENT_EDIT_TYPES:
                if self.content_edit.toPlainText() != field.content:
                    self.content_edit.setPlainText(field.content)
            elif ftype is FieldType.NUMBER:
                self.number_edit.setText(field.content)
                self.min_check.setChecked(field.min_value is not None)
                self.min_spin.setEnabled(self.min_check.isChecked())
                self.max_check.setChecked(field.max_value is not None)
                self.max_spin.setEnabled(self.max_check.isChecked())
                if field.min_value is not None:
                    self.min_spin.setValue(field.min_value)
                if field.max_value is not None:
                    self.max_spin.setValue(field.max_value)
            elif ftype is FieldType.CHECKBOX:
                self.checkbox_state.setChecked(field.content == "true")
            elif ftype is FieldType.DROPDOWN:
                self.options_list.clear()
                self.options_list.addItems(field.options)
                self.default_combo.clear()
                self.default_combo.addItem("")  # the empty default
                self.default_combo.addItems(field.options)
                default_index = self.default_combo.findText(field.content)
                self.default_combo.setCurrentIndex(default_index if default_index >= 0 else 0)
            elif ftype is FieldType.IMAGE:
                if field.image_id is None:
                    self.image_label.setText("Картинка не выбрана")
                else:
                    self.image_label.setText(f"Изображение: id {field.image_id}")
        finally:
            self._set_syncing(False)

    def _on_selection(self, fid) -> None:
        self._show_field(fid)

    def _on_geometry(self, fid) -> None:
        if fid != self._fid:
            return
        field = self._field()
        if field is None:
            return
        self._with_signals_blocked(
            self.x_spin, self.y_spin, self.w_spin, self.h_spin,
            fn=lambda: (
                self.x_spin.setValue(field.x),
                self.y_spin.setValue(field.y),
                self.w_spin.setValue(field.w),
                self.h_spin.setValue(field.h),
            ),
        )

    def _on_content_changed(self, fid) -> None:
        if fid != self._fid:
            return
        field = self._field()
        if field is None:
            return
        self._sync_section(field.type)

    def _on_font_changed(self, fid) -> None:
        if fid != self._fid:
            return
        field = self._field()
        if field is None:
            return
        self._with_signals_blocked(
            self.font_spin, fn=lambda: self.font_spin.setValue(field.font_size)
        )

    def _on_props_changed(self, fid) -> None:
        if fid != self._fid:
            return
        field = self._field()
        if field is None:
            return
        self._sync_section(field.type)

    def _on_removed(self, fid) -> None:
        if fid == self._fid:
            self._fid = None
            self._field_box.setEnabled(False)

    # -- panel → VM: geometry --------------------------------------------------

    def _on_x(self, value: float) -> None:
        field = self._field()
        if field is not None:
            self._begin_edit()
            self._vm.move(self._fid, value, field.y)

    def _on_y(self, value: float) -> None:
        field = self._field()
        if field is not None:
            self._begin_edit()
            self._vm.move(self._fid, field.x, value)

    def _on_w(self, value: float) -> None:
        field = self._field()
        if field is not None:
            self._begin_edit()
            self._vm.resize(self._fid, field.x, field.y, value, field.h)

    def _on_h(self, value: float) -> None:
        field = self._field()
        if field is not None:
            self._begin_edit()
            self._vm.resize(self._fid, field.x, field.y, field.w, value)

    def _on_font(self, value: float) -> None:
        if self._fid is not None:
            self._begin_edit()
            self._vm.set_font_size(self._fid, value)

    def _on_content(self) -> None:
        if self._fid is not None and not self._syncing:
            field = self._field()
            if field is not None and field.type in _CONTENT_EDIT_TYPES:
                self._begin_edit()
                self._vm.set_content(self._fid, self.content_edit.toPlainText())

    # -- panel → VM: number ------------------------------------------------------

    def _on_number_commit(self) -> None:
        if self._fid is None or self._syncing:
            return
        field = self._field()
        if field is None or field.type is not FieldType.NUMBER:
            return
        if not self._vm.apply_number(self._fid, self.number_edit.text()):
            # rejected (non-number or out of bounds): keep the old value
            self._with_signals_blocked(
                self.number_edit,
                fn=lambda: (
                    self.number_edit.setText(field.content),
                    self.number_edit.selectAll(),
                ),
            )

    def _on_bound(self) -> None:
        if self._fid is None or self._syncing:
            return
        field = self._field()
        if field is None or field.type is not FieldType.NUMBER:
            return
        new_min = self.min_spin.value() if self.min_check.isChecked() else None
        new_max = self.max_spin.value() if self.max_check.isChecked() else None
        old_min, old_max = field.min_value, field.max_value
        if new_min == old_min and new_max == old_max:
            return
        for value, attr, old in (
            (new_min, "min_value", old_min),
            (new_max, "max_value", old_max),
        ):
            if value == old:
                continue
            setter = self._vm.set_min_value if attr == "min_value" else self._vm.set_max_value
            if not setter(self._fid, value):
                # restore this bound and stop (min > max refused)
                restore = self._vm.set_min_value if attr == "min_value" else self._vm.set_max_value
                restore(self._fid, old)
                self._on_props_changed(self._fid)
                return
        self._on_props_changed(self._fid)

    # -- panel → VM: checkbox ----------------------------------------------------

    def _on_checkbox_toggled(self, checked: bool) -> None:
        if self._fid is None or self._syncing:
            return
        field = self._field()
        if field is None or field.type is not FieldType.CHECKBOX:
            return
        if (field.content == "true") == checked:
            return
        self._vm.toggle_checkbox(self._fid)

    # -- panel → VM: dropdown ------------------------------------------------------

    def _current_options(self) -> tuple[str, list[str]]:
        return (
            self._fid,
            [self.options_list.item(i).text() for i in range(self.options_list.count())],
        )

    def _on_option_add(self) -> None:
        fid, options = self._current_options()
        text = self.option_input.text()
        if fid is None:
            return
        self.option_input.clear()
        if not self._vm.set_options(fid, [*options, text]):
            self._on_props_changed(fid)  # refused (empty option): resync the list

    def _on_option_remove(self) -> None:
        fid, options = self._current_options()
        row = self.options_list.currentRow()
        if fid is None or not (0 <= row < len(options)):
            return
        options.pop(row)
        self._vm.set_options(fid, options)

    def _on_option_move(self, delta: int) -> None:
        fid, options = self._current_options()
        row = self.options_list.currentRow()
        target = row + delta
        if fid is None or not (0 <= row < len(options)) or not (0 <= target < len(options)):
            return
        options[row], options[target] = options[target], options[row]
        if self._vm.set_options(fid, options):
            self.options_list.setCurrentRow(target)

    def _on_default_combo(self, _index: int) -> None:
        if self._fid is None or self._syncing:
            return
        field = self._field()
        if field is not None and field.type is FieldType.DROPDOWN:
            self._vm.set_content(self._fid, self.default_combo.currentText())

    # -- panel → VM: image ------------------------------------------------------

    # the pick is owned by the dialog (it holds the ImageStore); clearing is
    # a plain VM write (the GC runs after the next committed save, design D6)
