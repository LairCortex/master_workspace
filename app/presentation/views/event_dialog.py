"""Event creation/edit dialog."""
from __future__ import annotations

import os
from datetime import date
from typing import Any

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QDateEdit, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QPushButton, QScrollArea, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget,
)

from app.presentation.utils.image_utils import load_and_encode


class _EntityTabWidget(QWidget):
    """Reusable tab for adding entities of a given type inside EventDialog."""

    def __init__(self, entity_label: str, extra_fields: list[str] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entity_label = entity_label
        self._extra_fields = extra_fields or []
        self._items: list[dict] = []
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # List of added entities
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, 1)

        # Inline add form
        form = QFormLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(f"Название {self._entity_label}")
        form.addRow("Название:", self.name_input)

        self.chars_input = QLineEdit()
        self.chars_input.setPlaceholderText("Характеристики")
        form.addRow("Характеристики:", self.chars_input)

        self.backstory_input = QLineEdit()
        self.backstory_input.setPlaceholderText("Предыстория")
        form.addRow("Предыстория:", self.backstory_input)

        self.start_date_input = QDateEdit()
        self.start_date_input.setCalendarPopup(True)
        self.start_date_input.setMinimumDate(QDate(100, 1, 1))
        self.start_date_input.setMaximumDate(QDate(9999, 12, 31))
        self.start_date_input.setDate(QDate.currentDate())
        form.addRow("Дата начала:", self.start_date_input)

        self.end_date_input = QDateEdit()
        self.end_date_input.setCalendarPopup(True)
        self.end_date_input.setMinimumDate(QDate(100, 1, 1))
        self.end_date_input.setMaximumDate(QDate(9999, 12, 31))
        self.end_date_input.setDate(QDate.currentDate())
        form.addRow("Дата конца:", self.end_date_input)

        self._extra_inputs: dict[str, QLineEdit | QTextEdit] = {}
        self._image_b64: str = ""
        field_labels = {
            "personality": "Личность",
            "image": "Изображение",
            "tasks": "Задачи",
        }
        for field in self._extra_fields:
            if field == "image":
                img_row = QHBoxLayout()
                self._image_label = QLabel("не выбрано")
                self._image_label.setStyleSheet("color: #999; font-style: italic;")
                img_btn = QPushButton("Выбрать файл…")
                img_btn.clicked.connect(self._on_pick_image)
                img_row.addWidget(self._image_label, 1)
                img_row.addWidget(img_btn)
                form.addRow(f"{field_labels['image']}:", img_row)
            else:
                inp = QLineEdit()
                inp.setPlaceholderText(field_labels.get(field, field))
                form.addRow(f"{field_labels.get(field, field)}:", inp)
                self._extra_inputs[field] = inp

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.add_button = QPushButton(f"Добавить {self._entity_label}")
        self.add_button.clicked.connect(self._on_add)
        self.remove_button = QPushButton("Удалить выбранное")
        self.remove_button.clicked.connect(self._on_remove)
        btn_row.addWidget(self.add_button)
        btn_row.addWidget(self.remove_button)
        layout.addLayout(btn_row)

    def _on_pick_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбрать изображение", "",
            "Изображения (*.png *.jpg *.jpeg *.bmp *.webp);;Все файлы (*)",
        )
        if path:
            try:
                self._image_b64 = load_and_encode(path)
                self._image_label.setText(os.path.basename(path))
                self._image_label.setStyleSheet("color: #7eb87e; font-style: normal;")
            except Exception:
                self._image_b64 = ""
                self._image_label.setText("ошибка загрузки")
                self._image_label.setStyleSheet("color: #cc5555; font-style: italic;")

    def _on_add(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            return
        item = {
            "name": name,
            "characteristics": self.chars_input.text().strip(),
            "backstory": self.backstory_input.text().strip(),
            "start_date": self.start_date_input.date().toPython(),
            "end_date": self.end_date_input.date().toPython(),
        }
        for field, inp in self._extra_inputs.items():
            item[field] = inp.text().strip() if isinstance(inp, QLineEdit) else ""
        # Image field — store base64
        if "image" in self._extra_fields:
            item["image"] = self._image_b64 if self._image_b64 else None
        self._items.append(item)
        self.list_widget.addItem(name)
        # Clear inputs
        self.name_input.clear()
        self.chars_input.clear()
        self.backstory_input.clear()
        for inp in self._extra_inputs.values():
            if isinstance(inp, QLineEdit):
                inp.clear()
        # Clear image selection
        self._image_b64 = ""
        if hasattr(self, "_image_label"):
            self._image_label.setText("не выбрано")
            self._image_label.setStyleSheet("color: #999; font-style: italic;")

    def _on_remove(self) -> None:
        row = self.list_widget.currentRow()
        if 0 <= row < len(self._items):
            self._items.pop(row)
            self.list_widget.takeItem(row)

    def get_items(self) -> list[dict]:
        return list(self._items)


class EventDialog(QDialog):
    saved = Signal(dict)

    def __init__(self, event_dialog_vm, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = event_dialog_vm
        self._event_id: int | None = None
        self.setWindowTitle("Новое событие")
        self.setMinimumSize(700, 620)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Название события *")
        self.name_input.textChanged.connect(self._update_validity)
        form.addRow("Название *:", self.name_input)

        self.start_date_input = QDateEdit()
        self.start_date_input.setCalendarPopup(True)
        self.start_date_input.setMinimumDate(QDate(100, 1, 1))
        self.start_date_input.setMaximumDate(QDate(9999, 12, 31))
        self.start_date_input.setDate(QDate.currentDate())
        self.start_date_input.dateChanged.connect(self._update_validity)
        form.addRow("Дата начала *:", self.start_date_input)

        self.end_date_input = QDateEdit()
        self.end_date_input.setCalendarPopup(True)
        self.end_date_input.setMinimumDate(QDate(100, 1, 1))
        self.end_date_input.setMaximumDate(QDate(9999, 12, 31))
        self.end_date_input.setDate(QDate.currentDate())
        self.end_date_input.dateChanged.connect(self._update_validity)
        form.addRow("Дата конца *:", self.end_date_input)

        lbl = QLabel("Описание (обязательные поля)")
        lbl.setStyleSheet("font-weight: bold; margin-top: 10px;")
        form.addRow(lbl)

        self.characteristics_input = QTextEdit()
        self.characteristics_input.setPlaceholderText("Характеристики *")
        self.characteristics_input.setMinimumHeight(60)
        self.characteristics_input.textChanged.connect(self._update_validity)
        form.addRow("Характеристики *:", self.characteristics_input)

        self.backstory_input = QTextEdit()
        self.backstory_input.setPlaceholderText("Предыстория *")
        self.backstory_input.setMinimumHeight(60)
        self.backstory_input.textChanged.connect(self._update_validity)
        form.addRow("Предыстория *:", self.backstory_input)

        layout.addLayout(form)

        # Entity tabs with inline add forms
        self.tabs = QTabWidget()
        self.org_tab = _EntityTabWidget("организацию", extra_fields=["tasks"])
        self.char_tab = _EntityTabWidget("персонажа", extra_fields=["personality", "image", "tasks"])
        self.item_tab = _EntityTabWidget("предмет")
        self.loc_tab = _EntityTabWidget("локацию", extra_fields=["image", "tasks"])
        self.tabs.addTab(self.org_tab, "Организации")
        self.tabs.addTab(self.char_tab, "Персонажи")
        self.tabs.addTab(self.item_tab, "Предметы")
        self.tabs.addTab(self.loc_tab, "Локации")
        layout.addWidget(self.tabs, 1)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.save_button = QPushButton("Сохранить")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._on_save)
        cancel_button = QPushButton("Отмена")
        cancel_button.clicked.connect(self.reject)
        btn_layout.addWidget(self.save_button)
        btn_layout.addWidget(cancel_button)
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
        if hasattr(event, "end_date") and event.end_date:
            self.end_date_input.setDate(
                QDate(event.end_date.year, event.end_date.month, event.end_date.day)
            )

        desc = getattr(event, "description", None)
        if desc:
            self.characteristics_input.setPlainText(getattr(desc, "characteristics", "") or "")
            self.backstory_input.setPlainText(getattr(desc, "backstory", "") or "")

        # Hide entity tabs in edit mode (entities managed via detail panel)
        self.tabs.setVisible(False)
        self._update_validity()

    @property
    def event_id(self) -> int | None:
        return self._event_id

    def _update_validity(self) -> None:
        name = self.name_input.text().strip()
        chars = self.characteristics_input.toPlainText().strip()
        back = self.backstory_input.toPlainText().strip()
        start = self.start_date_input.date().toPython()
        end = self.end_date_input.date().toPython()

        valid = bool(name) and bool(chars or back) and end >= start
        self.save_button.setEnabled(valid)

    def get_data(self) -> dict:
        data = {
            "name": self.name_input.text().strip(),
            "characteristics": self.characteristics_input.toPlainText().strip(),
            "backstory": self.backstory_input.toPlainText().strip(),
            "start_date": self.start_date_input.date().toPython(),
            "end_date": self.end_date_input.date().toPython(),
        }
        if self._event_id is not None:
            data["event_id"] = self._event_id
        else:
            data["organizations"] = self.org_tab.get_items()
            data["characters"] = self.char_tab.get_items()
            data["items"] = self.item_tab.get_items()
            data["locations"] = self.loc_tab.get_items()
        return data

    def _on_save(self) -> None:
        self.saved.emit(self.get_data())
        self.accept()
