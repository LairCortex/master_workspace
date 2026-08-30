"""Entity card dialog — view/edit any entity type with related entities."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, QEvent, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from app.presentation.theme.catalog import attach_theme, set_role
from app.presentation.utils.image_utils import load_entity_original, load_entity_preview
from app.presentation.views.ai_assist_button import AiAssistButton, EntityGenerateButton
from app.presentation.views.clickable_label import ClickableLabel
from app.presentation.views.custom_date_edit import CustomDateEdit
from app.presentation.views.image_viewer_dialog import ImageViewerDialog
from app.presentation.views.mention_text_edit import MentionTextEdit
from app.presentation.views.related_section import RelatedSection

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


class EntityCardDialog(QDialog):
    saved = Signal(dict)
    create_related_requested = Signal(str, str)  # (attr_name, entity_type)
    mention_clicked = Signal(str, int)  # (entity_type, entity_id)
    # Raw bytes of a freshly picked file — the owner (wiring) persists it via
    # ImageStore.store() and reports the result back via set_stored_image_id
    # (design D4: ImageStore is the single ingest pipeline, not the dialog).
    image_picked = Signal(bytes)
    open_character_sheet_requested = Signal()

    def __init__(
        self,
        entity_vm,
        entity_type: str = "organization",
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        super().__init__(parent)
        self._vm = entity_vm
        self._theme = theme
        self._entity_type = entity_type
        self._populated_entity_id: int | None = None
        self._related_sections: dict[str, RelatedSection] = {}
        self._image_id: int | None = None
        # Full-size viewer inputs (design D10/task 5.3) — kept in step with
        # whatever is currently shown in the preview slot, so the viewer
        # works both for a saved entity and for a freshly picked, not yet
        # persisted file (no entity row to resolve a path from).
        self._viewer_original: QPixmap = QPixmap()
        self._viewer_preview: QPixmap = QPixmap()
        self._extra_specs = _FIELD_SPECS.get(entity_type, [])
        self._has_image_field = any(spec.kind == "image" for spec in self._extra_specs)
        self._extra_widgets: dict[str, MentionTextEdit] = {}
        self._music_url: str = ""
        self._ai_buttons: list[AiAssistButton] = []
        self._ai_row_layouts: dict[str, QHBoxLayout] = {}
        self._entity_row: QHBoxLayout | None = None
        self._entity_button: EntityGenerateButton | None = None
        self._form_layout: QVBoxLayout | None = None
        self._save_locked: bool = False
        self._close_guard: object | None = None
        self.setWindowTitle(f"Карточка: {entity_type}")
        self.setMinimumSize(750 if self._has_image_field else 550, 550)
        self._init_ui()
        self._apply_theme()
        self._setup_ai_buttons()

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
        self.chrome.setObjectName("entityCardChrome")  # identifier, not style
        outer.addWidget(self.chrome)
        root_layout = QVBoxLayout(self.chrome)
        root_layout.setContentsMargins(11, 11, 11, 11)

        # Top area: image (left) + form (right) for types with image
        top_layout = QHBoxLayout()

        if self._has_image_field:
            img_col = QVBoxLayout()
            img_col.setAlignment(Qt.AlignmentFlag.AlignTop)

            self.image_label = ClickableLabel()
            self.image_label.setFixedSize(280, 280)
            self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # Placeholder chrome comes from the card role (surface/border from
            # tokens) — no OS-palette mid/base literals anymore (W2b).
            set_role(self.image_label, "card")
            self.image_label.setText("Нет изображения")
            self.image_label.clicked.connect(self._open_image_viewer)
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
        self._form_layout = form_layout

        # Top-right corner of the form: the entity generate/cancel button.
        self._entity_row = QHBoxLayout()
        self._entity_row.setContentsMargins(0, 0, 0, 0)
        self._entity_row.addStretch(1)
        self._entity_button = EntityGenerateButton(form_widget, theme=self._theme)
        self._entity_row.addWidget(self._entity_button)
        form_layout.addLayout(self._entity_row)

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

        self.characteristics_input = MentionTextEdit(theme=self._theme)
        self.characteristics_input.setMinimumHeight(60)
        self.characteristics_input.mention_clicked.connect(self.mention_clicked)
        form.addRow("Характеристики:", self._make_ai_row(self.characteristics_input, "characteristics"))

        self.backstory_input = MentionTextEdit(theme=self._theme)
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
            widget = MentionTextEdit(theme=self._theme)
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
                section = RelatedSection(cfg["attr"], cfg["entity_type"], cfg["label"])
                section.create_requested.connect(
                    lambda a=cfg["attr"], t=cfg["entity_type"]: self.create_related_requested.emit(a, t)
                )
                self._related_sections[cfg["attr"]] = section
                related_tabs.addTab(section, cfg["label"])
            root_layout.addWidget(related_tabs, 1)

        # Buttons
        btn_layout = QHBoxLayout()
        self.open_sheet_button = QPushButton("Открыть чар-лист")
        self.open_sheet_button.hide()
        self.open_sheet_button.clicked.connect(self.open_character_sheet_requested.emit)
        btn_layout.addWidget(self.open_sheet_button)
        btn_layout.addStretch()
        self.save_button = QPushButton("Сохранить")
        self.save_button.clicked.connect(self._on_save)
        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        btn_layout.addWidget(self.save_button)
        btn_layout.addWidget(self.cancel_button)
        root_layout.addLayout(btn_layout)

    def set_character_sheet_available(self, available: bool) -> None:
        self.open_sheet_button.setVisible(
            self._entity_type == "character" and available
        )

    @property
    def entity_type(self) -> str:
        return self._entity_type

    @property
    def populated_entity_id(self) -> int | None:
        return self._populated_entity_id

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
            data = Path(path).read_bytes()
        except OSError:
            QMessageBox.warning(self, "Изображение", f"Не удалось прочитать файл: {path}")
            return
        pm = QPixmap()
        if not pm.loadFromData(data) or pm.isNull():
            QMessageBox.warning(self, "Изображение", "Файл повреждён или не является изображением.")
            return
        # Not yet a durable image_id — resolved once the owner's ImageStore.store()
        # completes (image_picked below) and calls set_stored_image_id().
        self._image_id = None
        self._viewer_original = pm  # the picked file itself IS the "original"
        self._viewer_preview = QPixmap()
        self._display_pixmap(pm.scaled(
            280, 280, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
        ))
        self.image_picked.emit(data)

    def set_stored_image_id(self, image_id: int) -> None:
        """Called by the owner once ``image_picked``'s bytes are persisted."""
        self._image_id = image_id

    def _on_clear_image(self) -> None:
        self._image_id = None
        self._viewer_original = QPixmap()
        self._viewer_preview = QPixmap()
        self._clear_preview()

    def _open_image_viewer(self) -> None:
        if not self._has_image_field:
            return
        ImageViewerDialog(
            self._viewer_original, self._viewer_preview, parent=self, theme=self._theme,
        ).exec()

    def _display_pixmap(self, pm: QPixmap) -> None:
        if not self._has_image_field:
            return
        if pm.isNull():
            self._clear_preview()
            return
        self.image_label.setPixmap(pm)
        self.image_label.setText("")
        self.clear_image_btn.setEnabled(True)

    def _clear_preview(self) -> None:
        if not self._has_image_field:
            return
        self.image_label.setPixmap(QPixmap())
        self.image_label.setText("Нет изображения")
        self.clear_image_btn.setEnabled(False)

    # ── Public API ─────────────────────────────────────────────────────────

    def populate(self, entity: Any) -> None:
        self._populated_entity_id = getattr(entity, "id", None)
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

        # Image from file storage (design D10) — entity.image_ref is
        # eager-loaded (lazy="selectin"), so this resolves synchronously.
        if self._has_image_field:
            self._image_id = getattr(entity, "image_id", None)
            self._viewer_original = load_entity_original(entity)
            # Only needed as the viewer's fallback when the original is
            # missing/corrupt — loaded at native preview size (≤512px, no
            # further downscale), not the 280px slot shown in the card.
            self._viewer_preview = load_entity_preview(entity, slot_size=4096)
            self._display_pixmap(load_entity_preview(entity, slot_size=280))

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
            data["image_id"] = self._image_id

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
            btn = AiAssistButton(widget, et, field_name, field_label, theme=self._theme)
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

    def set_save_locked(self, locked: bool) -> None:
        """"Save" is blocked for the whole time any generation is running."""
        self._save_locked = locked
        self.save_button.setEnabled(not locked)

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
