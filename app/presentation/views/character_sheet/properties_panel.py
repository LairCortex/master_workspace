"""Right properties panel: field label/default/font + type-specific section
(task 6.3), two-way synchronized with the viewmodel."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.domain.entities.character_sheet import SheetField
from app.domain.enums.field_type import FieldType

#: widget → property key for the common rows
_LABEL, _DEFAULT, _FONT = "label", "default_value", "font_size"


class _OptionList(QWidget):
    """Compact options editor: list + add/remove lines.

    ``changed`` fires after add/remove — ``QListWidget::itemChanged`` does
    NOT fire for freshly added items, so add/remove need their own signal.
    """

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.list = QListWidget()
        self.list.setMaximumHeight(120)
        self.new_option = QLineEdit()
        self.new_option.setPlaceholderText("Новая опция…")
        add_btn = QPushButton("Добавить")
        remove_btn = QPushButton("Удалить выбранную")

        def _add() -> None:
            text = self.new_option.text().strip()
            if not text:
                return
            self.list.addItem(text)
            self.new_option.clear()
            self.changed.emit()

        def _remove() -> None:
            item = self.list.currentItem()
            if item is not None:
                self.list.takeItem(self.list.row(item))
                self.changed.emit()

        self.new_option.returnPressed.connect(_add)
        add_btn.clicked.connect(_add)
        remove_btn.clicked.connect(_remove)
        layout.addWidget(self.list)
        layout.addWidget(self.new_option)
        row = QVBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(add_btn)
        row.addWidget(remove_btn)
        add_btn_lay = QVBoxLayout()
        add_btn_lay.setContentsMargins(0, 0, 0, 0)
        add_btn_lay.addLayout(row)
        layout.addLayout(add_btn_lay)

    def set_options(self, options: list[str]) -> None:
        self.list.clear()
        for option in options:
            self.list.addItem(option)

    def options(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]


class PropertiesPanel(QFrame):
    """Type-aware field properties, commits on editing finished (one
    undo snapshot per commit, design D6)."""

    def __init__(self, viewmodel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = viewmodel
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.empty_hint = QLabel("Поле не выбрано")
        layout.addWidget(self.empty_hint)

        self._form = QVBoxLayout()
        layout.addLayout(self._form)

        self.label_input = QLineEdit()
        self.label_input.setPlaceholderText("Подпись")
        self.label_input.editingFinished.connect(self._commit)


        self.default_input = QLineEdit()
        self.default_input.setPlaceholderText("Значение по умолчанию")
        self.default_input.editingFinished.connect(self._commit)

        self.font_spin = QSpinBox()
        self.font_spin.setRange(4, 72)
        self.font_spin.valueChanged.connect(lambda v: self._commit_if_visible())

        self.min_spin = QSpinBox()
        self.min_spin.setRange(-9999, 99999)
        self.min_spin.valueChanged.connect(lambda v: self._commit_if_visible())

        self.max_spin = QSpinBox()
        self.max_spin.setRange(-9999, 99999)
        self.max_spin.valueChanged.connect(lambda v: self._commit_if_visible())

        self.checked_box = QCheckBox("Отмечено по умолчанию")
        self.checked_box.toggled.connect(lambda c: self._commit_if_visible())

        self.options_widget = _OptionList()
        self.options_widget.list.itemChanged.connect(lambda *_: self._commit_if_visible())
        self.options_widget.changed.connect(lambda: self._commit_if_visible())

        for widget_row in (
            self._row("Подпись:", self.label_input),
            self._row("Значение:", self.default_input),
            self._row("Шрифт, pt:", self.font_spin),
            self._row("Минимум:", self.min_spin),
            self._row("Максимум:", self.max_spin),
            self._row2("Чекбокс:", self.checked_box),
            self._row2("Опции:", self.options_widget),
        ):
            self._form.addWidget(widget_row)
        self._rows = {
            "label": 0,
            "default_value": 1,
            "font_size": 2,
            "min_value": 3,
            "max_value": 4,
        }
        layout.addStretch(1)

        viewmodel.state_changed.connect(self._refresh)
        viewmodel.selection_changed.connect(self._refresh)
        self._refresh()

    # ── helpers ───────────────────────────────────────────────────────────

    def _row(self, caption: str, widget: QWidget):
        from PySide6.QtWidgets import QFormLayout

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow(caption, widget)
        wrapper = QWidget()
        wrapper.setLayout(form)
        wrapper._field_widget = widget  # type: ignore[attr-defined]
        return wrapper

    def _row2(self, caption: str, widget: QWidget):
        from PySide6.QtWidgets import QFormLayout

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow(caption, widget)
        wrapper = QWidget()
        wrapper.setLayout(form)
        wrapper._field_widget = widget  # type: ignore[attr-defined]
        return wrapper

    # ── refresh from model ────────────────────────────────────────────────

    def _refresh(self) -> None:
        field = self._vm.selected_field
        if field is None:
            self.empty_hint.setText("Поле не выбрано")
            for row_index in range(self._form.count()):
                widget = self._form.itemAt(row_index).widget()
                if widget is not None:
                    widget.setVisible(False)
            return
        self.empty_hint.setText(str(field.type.value).replace("_", " "))
        self._load_field(field)

    def _load_field(self, field: SheetField) -> None:
        self._loading = True
        try:
            rows = self._form
            row_widgets = []
            for i in range(rows.count()):
                w = rows.itemAt(i).widget()
                row_widgets.append(w)
            self._set(row_widgets[0], _LABEL, field.label)
            self._set(row_widgets[1], _DEFAULT, field.default_value)
            self._set(row_widgets[2], _FONT, str(int(field.font_size)))
            self._set(row_widgets[3], "min_value", str(field.min_value))
            self._set(row_widgets[4], "max_value", str(field.max_value))
            checked_widget = row_widgets[5]._field_widget  # type: ignore[attr-defined]
            checked_widget.blockSignals(True)
            checked_widget.setChecked(field.initial_checked)
            checked_widget.blockSignals(False)
            options_widget: _OptionList = row_widgets[6]._field_widget  # type: ignore[attr-defined]
            options_widget.blockSignals(True)
            options_widget.list.blockSignals(True)
            options_widget.set_options(list(field.options))
            options_widget.list.blockSignals(False)
            options_widget.blockSignals(False)
        finally:
            self._loading = False

        visible = self._visible_for(field.type)
        for i, widget in enumerate(row_widgets):
            if widget is not None:
                widget.setVisible(i in visible)

    @staticmethod
    def _visible_for(field_type: FieldType) -> set:
        """Which row indices are relevant for a field type."""
        visible = {0, 2}  # label + font size
        if field_type in (
            FieldType.NUMBER, FieldType.SHORT_TEXT, FieldType.LONG_TEXT,
            FieldType.DATE, FieldType.DROPDOWN,
        ):
            visible.add(1)  # default value
        if field_type is FieldType.NUMBER:
            visible |= {3, 4}
        if field_type is FieldType.CHECKBOX:
            visible.add(5)
        if field_type is FieldType.DROPDOWN:
            visible.add(6)
        return visible

    def _set(self, row_widget, prop: str, value: str) -> None:
        if row_widget is None:
            return
        inner = getattr(row_widget, "_field_widget", None)
        if inner is None:
            return
        inner.blockSignals(True)
        if isinstance(inner, QSpinBox):
            inner.setValue(int(float(value)))
        elif isinstance(inner, QLineEdit):
            inner.setText(value)
        inner.blockSignals(False)

    # ── commit to model ───────────────────────────────────────────────────

    def _commit_if_visible(self) -> None:
        if not self._loading:
            self._commit()

    def _commit(self) -> None:
        if self._loading:
            return
        field = self._vm.selected_field
        if field is None:
            return
        t = field.type
        changes: dict = {"label": self.label_input.text().strip()}
        if 1 in self._visible_for(t):
            changes["default_value"] = self.default_input.text()
        changes["font_size"] = float(self.font_spin.value())
        if t is FieldType.NUMBER:
            changes["min_value"] = self.min_spin.value()
            changes["max_value"] = self.max_spin.value()
        if t is FieldType.CHECKBOX:
            changes["initial_checked"] = self.checked_box.isChecked()
        if t is FieldType.DROPDOWN:
            changes["options"] = self.options_widget.options()
        try:
            self._vm.update_field(field.id, **changes)
        except ValueError:
            # invalid combination (e.g. min > max) — reload from the model
            self._loading = False
            self._refresh()
