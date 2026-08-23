"""Entity card dialog — view/edit any entity type with related entities."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from app.presentation.utils.image_utils import base64_to_pixmap, load_and_encode
from app.presentation.views.ai_assist_button import AiAssistButton
from app.presentation.views.custom_date_edit import CustomDateEdit
from app.presentation.views.mention_text_edit import MentionTextEdit

# Fields that only appear for certain entity types. The 5th entity type is
# data in this table, not a code branch. kind: "mention" | "image".
@dataclass(frozen=True)
class _FieldSpec:
    name: str   # data key; widget attribute is "<name>_input"
    label: str  # RU label without trailing colon
    kind: str


_FIELD_SPECS: dict[str, list[_FieldSpec]] = {
    "character": [
        _FieldSpec("personality", "Личность", "mention"),
        _FieldSpec("image", "Изображение", "image"),
        _FieldSpec("tasks", "Задачи", "mention"),
    ],
    "organization": [
        _FieldSpec("image", "Изображение", "image"),
        _FieldSpec("tasks", "Задачи", "mention"),
    ],
    "location": [
        _FieldSpec("image", "Изображение", "image"),
        _FieldSpec("tasks", "Задачи", "mention"),
    ],
    "item": [],
    "rating": [],
}

_EXTRA_FIELD_MIN_HEIGHT = 40

# Related entities config: which entity types have which related sub-entities
_RELATED_CONFIG: dict[str, list[dict[str, str]]] = {
    "organization": [
        {"attr": "characters", "label": "Персонажи", "entity_type": "character"},
        {"attr": "items", "label": "Предметы", "entity_type": "item"},
        {"attr": "locations", "label": "Локации", "entity_type": "location"},
    ],
    "character": [
        {"attr": "items", "label": "Предметы", "entity_type": "item"},
        {"attr": "locations", "label": "Локации", "entity_type": "location"},
        {"attr": "organizations", "label": "Организации", "entity_type": "organization"},
    ],
    "item": [
        {"attr": "locations", "label": "Локации", "entity_type": "location"},
        {"attr": "characters", "label": "Персонажи", "entity_type": "character"},
        {"attr": "organizations", "label": "Организации", "entity_type": "organization"},
    ],
    "location": [
        {"attr": "characters", "label": "Персонажи", "entity_type": "character"},
        {"attr": "organizations", "label": "Организации", "entity_type": "organization"},
        {"attr": "items", "label": "Предметы", "entity_type": "item"},
    ],
}

_IMAGE_FILTERS = "Изображения (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;Все файлы (*)"


class _RelatedSection(QWidget):
    """Widget for managing a list of related entities (link existing / create new / unlink)."""

    create_requested = Signal()

    def __init__(self, attr_name: str, entity_type: str, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._attr_name = attr_name
        self._entity_type = entity_type
        self._label = label
        self._entities: list[Any] = []
        self._available: list[Any] = []
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, 1)

        btn_row = QHBoxLayout()
        link_btn = QPushButton("Привязать существующего")
        link_btn.clicked.connect(self._on_link_existing)
        create_btn = QPushButton("Создать нового")
        create_btn.clicked.connect(self.create_requested.emit)
        remove_btn = QPushButton("Отвязать")
        remove_btn.clicked.connect(self._on_remove)
        btn_row.addWidget(link_btn)
        btn_row.addWidget(create_btn)
        btn_row.addWidget(remove_btn)
        layout.addLayout(btn_row)

    def set_entities(self, entities: list[Any]) -> None:
        self._entities = list(entities)
        self._refresh()

    def set_available(self, entities: list[Any]) -> None:
        self._available = list(entities)

    def add_entity(self, entity: Any) -> None:
        self._entities.append(entity)
        self._available.append(entity)
        self._refresh()

    def get_current_ids(self) -> list[int]:
        return [getattr(e, "id", None) for e in self._entities]

    def _refresh(self) -> None:
        self.list_widget.clear()
        for e in self._entities:
            item = QListWidgetItem(getattr(e, "name", str(e)))
            item.setData(256, getattr(e, "id", None))
            self.list_widget.addItem(item)

    def _on_link_existing(self) -> None:
        current_ids = {getattr(e, "id", None) for e in self._entities}
        candidates = [e for e in self._available if getattr(e, "id", None) not in current_ids]
        if not candidates:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Выберите {self._label.lower()}")
        dlg.setMinimumSize(300, 400)
        lay = QVBoxLayout(dlg)

        lst = QListWidget()
        lst.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        for e in candidates:
            item = QListWidgetItem(getattr(e, "name", str(e)))
            item.setData(256, getattr(e, "id", None))
            lst.addItem(item)
        lay.addWidget(lst)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            for sel_item in lst.selectedItems():
                eid = sel_item.data(256)
                for e in self._available:
                    if getattr(e, "id", None) == eid:
                        self._entities.append(e)
                        break
            self._refresh()

    def _on_remove(self) -> None:
        row = self.list_widget.currentRow()
        if 0 <= row < len(self._entities):
            self._entities.pop(row)
            self._refresh()


class EntityCardDialog(QDialog):
    saved = Signal(dict)
    create_related_requested = Signal(str, str)  # (attr_name, entity_type)
    mention_clicked = Signal(str, int)  # (entity_type, entity_id)

    def __init__(self, entity_vm, entity_type: str = "organization", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = entity_vm
        self._entity_type = entity_type
        self._related_sections: dict[str, _RelatedSection] = {}
        self._image_b64: str = ""
        self._extra_specs = _FIELD_SPECS.get(entity_type, [])
        self._has_image_field = any(spec.kind == "image" for spec in self._extra_specs)
        self._extra_widgets: dict[str, MentionTextEdit] = {}
        self._music_url: str = ""
        self._ai_buttons: list[AiAssistButton] = []
        self._ai_row_layouts: dict[str, QHBoxLayout] = {}
        self.setWindowTitle(f"Карточка: {entity_type}")
        self.setMinimumSize(750 if self._has_image_field else 550, 550)
        self._init_ui()
        self._setup_ai_buttons()

    def _init_ui(self) -> None:
        root_layout = QVBoxLayout(self)

        # Top area: image (left) + form (right) for types with image
        top_layout = QHBoxLayout()

        if self._has_image_field:
            img_col = QVBoxLayout()
            img_col.setAlignment(Qt.AlignmentFlag.AlignTop)

            self.image_label = QLabel()
            self.image_label.setFixedSize(280, 280)
            self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.image_label.setStyleSheet(
                "QLabel { border: 1px solid palette(mid); background: palette(base); }"
            )
            self.image_label.setText("Нет изображения")
            img_col.addWidget(self.image_label)

            img_btn_row = QHBoxLayout()
            self.pick_image_btn = QPushButton("Выбрать файл")
            self.pick_image_btn.clicked.connect(self._on_pick_image)
            self.clear_image_btn = QPushButton("Убрать")
            self.clear_image_btn.clicked.connect(self._on_clear_image)
            self.clear_image_btn.setEnabled(False)
            img_btn_row.addWidget(self.pick_image_btn)
            img_btn_row.addWidget(self.clear_image_btn)
            img_col.addLayout(img_btn_row)
            img_col.addStretch()

            top_layout.addLayout(img_col)

        # Form column
        form_widget = QWidget()
        form_layout = QVBoxLayout(form_widget)
        form_layout.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()

        self.name_input = QLineEdit()
        form.addRow("Название:", self._make_ai_row(self.name_input, "name"))

        self.rating_input = QSpinBox()
        self.rating_input.setMinimum(1)
        self.rating_input.setMaximum(20)
        self.rating_input.setValue(1)
        self.rating_input.setToolTip("1 — наименее важно, 20 — наиболее важно")
        form.addRow("Рейтинг (1-20):", self.rating_input)

        self.start_date_input = CustomDateEdit()
        self.start_date_input.setDate(QDate.currentDate())
        form.addRow("Дата начала:", self.start_date_input)

        end_row = QHBoxLayout()
        self.end_date_input = CustomDateEdit()
        self.end_date_input.setDate(QDate.currentDate())
        end_row.addWidget(self.end_date_input, 1)
        self.no_end_date_cb = QCheckBox("Бессрочно")
        self.no_end_date_cb.toggled.connect(lambda checked: self.end_date_input.setVisible(not checked))
        end_row.addWidget(self.no_end_date_cb)
        form.addRow("Дата конца:", end_row)

        self.characteristics_input = MentionTextEdit()
        self.characteristics_input.setMinimumHeight(60)
        self.characteristics_input.mention_clicked.connect(self.mention_clicked)
        form.addRow("Характеристики:", self._make_ai_row(self.characteristics_input, "characteristics"))

        self.backstory_input = MentionTextEdit()
        self.backstory_input.setMinimumHeight(60)
        self.backstory_input.mention_clicked.connect(self.mention_clicked)
        form.addRow("Предыстория:", self._make_ai_row(self.backstory_input, "backstory"))

        # Music link (for all entity types)
        music_row = QHBoxLayout()
        self.music_display = QLabel()
        self.music_display.setTextFormat(Qt.TextFormat.RichText)
        self.music_display.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        self.music_display.setOpenExternalLinks(True)
        self.music_display.hide()

        self.music_input = QLineEdit()
        self.music_input.setPlaceholderText("Ссылка на музыку")

        self.music_edit_btn = QPushButton("✎")
        self.music_edit_btn.setToolTip("Редактировать ссылку на музыку")
        self.music_edit_btn.setFixedWidth(28)
        self.music_edit_btn.clicked.connect(self._on_toggle_music_edit)

        music_row.addWidget(self.music_display, 1)
        music_row.addWidget(self.music_input, 1)
        music_row.addWidget(self.music_edit_btn, 0)
        form.addRow("Музыка:", music_row)

        # Entity-specific fields — built from _FIELD_SPECS (no per-type branches).
        # Public widget attribute names stay stable: <name>_input.
        self.personality_input = None
        self.image_input = None  # kept for compatibility but hidden
        self.tasks_input = None

        for spec in self._extra_specs:
            if spec.kind == "image":
                continue  # image panel is built in the top area
            widget = MentionTextEdit()
            widget.setMinimumHeight(_EXTRA_FIELD_MIN_HEIGHT)
            widget.mention_clicked.connect(self.mention_clicked)
            setattr(self, f"{spec.name}_input", widget)
            self._extra_widgets[spec.name] = widget
            form.addRow(f"{spec.label}:", self._make_ai_row(widget, spec.name))

        form_layout.addLayout(form)
        top_layout.addWidget(form_widget, 1)
        root_layout.addLayout(top_layout)

        # Related entities section
        related_configs = _RELATED_CONFIG.get(self._entity_type, [])
        if related_configs:
            related_tabs = QTabWidget()
            for cfg in related_configs:
                section = _RelatedSection(cfg["attr"], cfg["entity_type"], cfg["label"])
                section.create_requested.connect(
                    lambda a=cfg["attr"], t=cfg["entity_type"]: self.create_related_requested.emit(a, t)
                )
                self._related_sections[cfg["attr"]] = section
                related_tabs.addTab(section, cfg["label"])
            root_layout.addWidget(related_tabs, 1)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.save_button = QPushButton("Сохранить")
        self.save_button.clicked.connect(self._on_save)
        cancel_button = QPushButton("Отмена")
        cancel_button.clicked.connect(self.reject)
        btn_layout.addWidget(self.save_button)
        btn_layout.addWidget(cancel_button)
        root_layout.addLayout(btn_layout)

    def _set_music_url(self, url: str) -> None:
        self._music_url = url.strip()
        if self._music_url:
            safe_url = self._music_url.replace('"', "&quot;")
            self.music_display.setText(f'<a href="{safe_url}">{self._music_url}</a>')
            self.music_display.show()
        else:
            self.music_display.setText("")
            self.music_display.hide()
        # Always keep input in sync but hide when displaying as link
        self.music_input.setText(self._music_url)
        if self._music_url:
            self.music_input.hide()
        else:
            self.music_input.show()

    def _on_toggle_music_edit(self) -> None:
        if self.music_input.isVisible():
            # Switch to link view (if any text)
            self._set_music_url(self.music_input.text())
        else:
            # Switch to edit mode
            self.music_display.hide()
            self.music_input.show()
            self.music_input.setFocus()

    # ── Image handling ─────────────────────────────────────────────────────

    def _on_pick_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Выберите изображение", "", _IMAGE_FILTERS)
        if not path:
            return
        try:
            self._image_b64 = load_and_encode(path, max_size=1000)
        except ValueError:
            return
        self._show_preview()

    def _on_clear_image(self) -> None:
        self._image_b64 = ""
        if self._has_image_field:
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText("Нет изображения")
            self.clear_image_btn.setEnabled(False)

    def _show_preview(self) -> None:
        if not self._has_image_field or not self._image_b64:
            return
        pm = base64_to_pixmap(self._image_b64, max_size=280)
        if not pm.isNull():
            self.image_label.setPixmap(pm)
            self.image_label.setText("")
            self.clear_image_btn.setEnabled(True)

    # ── Public API ─────────────────────────────────────────────────────────

    def populate(self, entity: Any) -> None:
        self.name_input.setText(getattr(entity, "name", ""))
        rating_val = getattr(entity, "rating", 1)
        if isinstance(rating_val, int):
            self.rating_input.setValue(max(1, min(20, rating_val)))
        if hasattr(entity, "start_date") and entity.start_date:
            self.start_date_input.setDate(QDate(entity.start_date.year, entity.start_date.month, entity.start_date.day))
        if hasattr(entity, "end_date"):
            if entity.end_date:
                self.end_date_input.setDate(QDate(entity.end_date.year, entity.end_date.month, entity.end_date.day))
                self.no_end_date_cb.setChecked(False)
            else:
                self.no_end_date_cb.setChecked(True)

        desc = getattr(entity, "description", None)
        if desc:
            self.characteristics_input.setContent(getattr(desc, "characteristics", "") or "")
            self.backstory_input.setContent(getattr(desc, "backstory", "") or "")

        for name, widget in self._extra_widgets.items():
            value = getattr(entity, name, None)
            widget.setContent(value or "")

        # Image from DB (base64)
        img_data = getattr(entity, "image", None)
        if img_data and self._has_image_field:
            self._image_b64 = img_data
            self._show_preview()

        # Music URL
        music_url = getattr(entity, "music_url", None)
        if not isinstance(music_url, str):
            music_url = ""
        self._set_music_url(music_url or "")

        # Populate related entities
        for attr, section in self._related_sections.items():
            entities = getattr(entity, attr, [])
            section.set_entities(list(entities))

    def set_available_entities(self, attr: str, entities: list[Any]) -> None:
        if attr in self._related_sections:
            self._related_sections[attr].set_available(entities)

    def add_related_entity(self, attr: str, entity: Any) -> None:
        if attr in self._related_sections:
            self._related_sections[attr].add_entity(entity)

    def get_data(self) -> dict:
        data = {
            "name": self.name_input.text().strip(),
            "rating": self.rating_input.value(),
            "start_date": self.start_date_input.date().toPython(),
            "end_date": None if self.no_end_date_cb.isChecked() else self.end_date_input.date().toPython(),
            "characteristics": self.characteristics_input.getContent().strip(),
            "backstory": self.backstory_input.getContent().strip(),
            "music_url": self.music_input.text().strip(),
        }
        for name, widget in self._extra_widgets.items():
            data[name] = widget.getContent().strip()
        if self._has_image_field:
            data["image"] = self._image_b64

        # Related entity changes
        if self._related_sections:
            related_changes: dict[str, dict] = {}
            for attr, section in self._related_sections.items():
                related_changes[attr] = {"current_ids": section.get_current_ids()}
            data["related_changes"] = related_changes

        return data

    def get_mention_edits(self) -> list[MentionTextEdit]:
        """Return all MentionTextEdit instances for wiring search."""
        edits = [self.characteristics_input, self.backstory_input]
        edits.extend(self._extra_widgets.values())
        return edits

    def _make_ai_row(self, field: QWidget, field_name: str) -> QWidget:
        """Wrap a field in a horizontal row reserving the right slot for the AI button."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(field, 1)
        self._ai_row_layouts[field_name] = row_layout
        return row

    def _setup_ai_buttons(self) -> None:
        et = self._entity_type
        fields: list[tuple[QWidget, str, str]] = [
            (self.name_input, "name", "Название"),
            (self.characteristics_input, "characteristics", "Характеристики"),
            (self.backstory_input, "backstory", "Предыстория"),
        ]
        for spec in self._extra_specs:
            if spec.kind != "mention":
                continue
            fields.append((self._extra_widgets[spec.name], spec.name, spec.label))

        for widget, field_name, field_label in fields:
            btn = AiAssistButton(widget, et, field_name, field_label)
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

    def reject(self) -> None:
        if any(b.is_generating for b in self._ai_buttons):
            return
        super().reject()

    def _on_save(self) -> None:
        self.saved.emit(self.get_data())
        super().accept()
