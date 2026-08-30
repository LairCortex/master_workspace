"""Event creation/edit dialog."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QDate, QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from app.presentation.theme.catalog import attach_theme, title
from app.presentation.views.ai_assist_button import AiAssistButton, EntityGenerateButton
from app.presentation.views.custom_date_edit import CustomDateEdit
from app.presentation.views.mention_text_edit import MentionTextEdit
from app.presentation.views.related_section import RelatedSection

# (public widget attribute, attr key, entity type, tab label)
_TABS: list[tuple[str, str, str, str]] = [
    ("org_tab", "organizations", "organization", "Организации"),
    ("char_tab", "characters", "character", "Персонажи"),
    ("item_tab", "items", "item", "Предметы"),
    ("loc_tab", "locations", "location", "Локации"),
]

# Derived from _TABS so a new tab type cannot silently drop out of
# populate()/get_data().
_REL_ATTRS: tuple[str, ...] = tuple(attr for _, attr, _, _ in _TABS)


class EventDialog(QDialog):
    saved = Signal(dict)
    create_related_requested = Signal(str, str)  # (attr_name, entity_type)
    mention_clicked = Signal(str, int)  # (entity_type, entity_id)

    def __init__(
        self,
        event_dialog_vm,
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        super().__init__(parent)
        self._vm = event_dialog_vm
        self._theme = theme
        self._event_id: int | None = None
        self._ai_buttons: list[AiAssistButton] = []
        self._ai_row_layouts: dict[str, QHBoxLayout] = {}
        self._sections: dict[str, RelatedSection] = {}
        self._entity_row: QHBoxLayout | None = None
        self._entity_button: EntityGenerateButton | None = None
        self._save_locked: bool = False
        self._close_guard: object | None = None
        self.setWindowTitle("Новое событие")
        self.setMinimumSize(700, 620)
        self._init_ui()
        self._apply_theme()
        self._setup_ai_buttons()
        self.characteristics_input.mention_clicked.connect(self.mention_clicked)
        self.backstory_input.mention_clicked.connect(self.mention_clicked)

    def _apply_theme(self) -> None:
        """One attach point: the chrome container carries the whole sheet (D1)."""
        if self._theme is not None:
            attach_theme(self.chrome, self._theme)
            self._theme.apply()

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        # The chrome reaches the dialog edges so no OS-palette band frames it.
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.chrome = QWidget()
        self.chrome.setObjectName("eventDialogChrome")  # identifier, not style
        outer.addWidget(self.chrome)
        layout = QVBoxLayout(self.chrome)
        layout.setContentsMargins(11, 11, 11, 11)

        form = QFormLayout()

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Название события *")
        self.name_input.textChanged.connect(self._update_validity)
        form.addRow("Название *:", self._make_ai_row(self.name_input, "name"))

        self.start_date_input = CustomDateEdit()
        self.start_date_input.setDate(QDate.currentDate())
        self.start_date_input.dateChanged.connect(self._update_validity)
        form.addRow("Дата начала *:", self.start_date_input)

        end_row = QHBoxLayout()
        self.end_date_input = CustomDateEdit()
        self.end_date_input.setDate(QDate.currentDate())
        self.end_date_input.dateChanged.connect(self._update_validity)
        end_row.addWidget(self.end_date_input, 1)
        self.no_end_date_cb = QCheckBox("Бессрочно")
        def _on_no_end_toggled(checked):
            self.end_date_input.setVisible(not checked)
            self._update_validity()
        self.no_end_date_cb.toggled.connect(_on_no_end_toggled)
        end_row.addWidget(self.no_end_date_cb)
        form.addRow("Дата конца:", end_row)

        lbl = title("Описание (обязательные поля)")
        # The old inline style carried 10px of top margin; restored as a
        # layout margin on the label (spacing, not style).
        lbl.setContentsMargins(0, 10, 0, 0)
        form.addRow(lbl)

        self.characteristics_input = MentionTextEdit(theme=self._theme)
        self.characteristics_input.setPlaceholderText("Характеристики *")
        self.characteristics_input.setMinimumHeight(60)
        self.characteristics_input.textChanged.connect(self._update_validity)
        form.addRow("Характеристики *:", self._make_ai_row(self.characteristics_input, "characteristics"))

        self.backstory_input = MentionTextEdit(theme=self._theme)
        self.backstory_input.setPlaceholderText("Предыстория *")
        self.backstory_input.setMinimumHeight(60)
        self.backstory_input.textChanged.connect(self._update_validity)
        form.addRow("Предыстория *:", self._make_ai_row(self.backstory_input, "backstory"))

        # Top-right corner of the form: the entity generate/cancel button.
        self._entity_row = QHBoxLayout()
        self._entity_row.setContentsMargins(0, 0, 0, 0)
        self._entity_row.addStretch(1)
        self._entity_button = EntityGenerateButton(self, theme=self._theme)
        self._entity_row.addWidget(self._entity_button)
        layout.addLayout(self._entity_row)
        layout.addLayout(form)

        # Entity tabs: name list + «Привязать существующего»/«Создать нового»/«Отвязать».
        # No inline creation form — new entities are created in a separate card window.
        self.tabs = QTabWidget()
        for widget_attr, attr, entity_type, label in _TABS:
            section = RelatedSection(attr, entity_type, label)
            section.create_requested.connect(
                lambda a=attr, t=entity_type: self.create_related_requested.emit(a, t)
            )
            setattr(self, widget_attr, section)
            self._sections[attr] = section
            self.tabs.addTab(section, label)
        layout.addWidget(self.tabs, 1)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.save_button = QPushButton("Сохранить")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._on_save)
        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        btn_layout.addWidget(self.save_button)
        btn_layout.addWidget(self.cancel_button)
        layout.addLayout(btn_layout)

    def populate(self, event: Any) -> None:
        """Populate dialog for editing an existing event."""
        self._event_id = getattr(event, "id", None)
        self.setWindowTitle("Редактировать событие")

        self.name_input.setText(getattr(event, "name", ""))
        if hasattr(event, "start_date") and event.start_date:
            self.start_date_input.setDate(
                QDate(event.start_date.year, event.start_date.month, event.start_date.day)
            )
        if hasattr(event, "end_date"):
            if event.end_date:
                self.end_date_input.setDate(
                    QDate(event.end_date.year, event.end_date.month, event.end_date.day)
                )
                self.no_end_date_cb.setChecked(False)
            else:
                self.no_end_date_cb.setChecked(True)

        desc = getattr(event, "description", None)
        if desc:
            self.characteristics_input.setContent(getattr(desc, "characteristics", "") or "")
            self.backstory_input.setContent(getattr(desc, "backstory", "") or "")

        # Pre-fill the related sections with currently linked entities
        for attr in _REL_ATTRS:
            self._sections[attr].set_entities(list(getattr(event, attr, [])))
        self._update_validity()

    @property
    def event_id(self) -> int | None:
        return self._event_id

    # ── Public API for wiring (same shape as EntityCardDialog) ────────────

    def set_available_entities(self, attr: str, entities: list[Any]) -> None:
        section = self._sections.get(attr)
        if section is not None:
            section.set_available(entities)

    def add_related_entity(self, attr: str, entity: Any) -> None:
        section = self._sections.get(attr)
        if section is not None:
            section.add_entity(entity)

    def _update_validity(self) -> None:
        name = self.name_input.text().strip()
        chars = self.characteristics_input.toPlainText().strip()
        back = self.backstory_input.toPlainText().strip()

        valid = bool(name) and bool(chars or back)
        if not self.no_end_date_cb.isChecked():
            start = self.start_date_input.date().toPython()
            end = self.end_date_input.date().toPython()
            valid = valid and end >= start
        self.save_button.setEnabled(valid and not self._save_locked)

    def set_save_locked(self, locked: bool) -> None:
        """"Save" is blocked for the whole time any generation is running."""
        self._save_locked = locked
        self._update_validity()

    def get_data(self) -> dict:
        data = {
            "name": self.name_input.text().strip(),
            "characteristics": self.characteristics_input.getContent().strip(),
            "backstory": self.backstory_input.getContent().strip(),
            "start_date": self.start_date_input.date().toPython(),
            "end_date": None if self.no_end_date_cb.isChecked() else self.end_date_input.date().toPython(),
        }
        if self._event_id is not None:
            data["event_id"] = self._event_id
        for attr in _REL_ATTRS:
            data[attr] = [
                {"_existing_id": eid}
                for eid in self._sections[attr].get_current_ids()
                if eid is not None
            ]
        return data

    def get_mention_edits(self) -> list[MentionTextEdit]:
        """Return all MentionTextEdit instances for wiring search."""
        return [self.characteristics_input, self.backstory_input]

    def _make_ai_row(self, field: QWidget, field_name: str) -> QWidget:
        """Wrap a field in a horizontal row reserving the right slot for the AI button."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(field, 1)
        self._ai_row_layouts[field_name] = row_layout
        return row

    def _setup_ai_buttons(self) -> None:
        fields: list[tuple[QWidget, str, str]] = [
            (self.name_input, "name", "Название"),
            (self.characteristics_input, "characteristics", "Характеристики"),
            (self.backstory_input, "backstory", "Предыстория"),
        ]
        for widget, field_name, field_label in fields:
            btn = AiAssistButton(widget, "event", field_name, field_label, theme=self._theme)
            self._ai_buttons.append(btn)
            # Single-line fields align to the middle; multi-line ones pin to the top edge.
            align = (
                Qt.AlignmentFlag.AlignVCenter
                if isinstance(widget, QLineEdit)
                else Qt.AlignmentFlag.AlignTop
            )
            self._ai_row_layouts[field_name].addWidget(btn, 0, align)

    def get_ai_buttons(self) -> list[AiAssistButton]:
        return list(self._ai_buttons)

    def get_entity_button(self) -> EntityGenerateButton:
        return self._entity_button

    def _is_generation_active(self) -> bool:
        if any(b.is_generating for b in self._ai_buttons):
            return True
        return self._entity_button is not None and self._entity_button.is_cancelling

    def set_close_guard(self, fn) -> None:
        """Wiring-provided callback for the close paths (X / «Отмена»).

        «Отмена» always goes through it; X / close events — only while a
        generation is active. The wiring's guard decides: outside generation
        it simply rejects; in flight it may confirm, then cancel + close.
        """
        self._close_guard = fn

    def closeEvent(self, event) -> None:
        if self._is_generation_active() and self._close_guard is not None:
            event.ignore()
            self._close_guard()
            return
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:
        # ESC must not close the dialog while a generation is in flight.
        if (
            event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
            and self._is_generation_active()
        ):
            event.ignore()
            return
        super().keyPressEvent(event)

    def _on_cancel_clicked(self) -> None:
        # D5: the guard handles both cases — during a generation it may
        # confirm and cancel the wave; outside generation it just rejects.
        if self._close_guard is not None:
            self._close_guard()
        else:
            super().reject()

    def reject(self) -> None:
        # Safety net for direct reject() calls from outside the close paths.
        if self._is_generation_active():
            return
        super().reject()

    def _on_save(self) -> None:
        self.saved.emit(self.get_data())
        super().accept()
