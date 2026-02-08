"""Global search bar with live results dropdown."""
from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtCore import QTimer, Signal, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)

_TYPE_LABELS = {
    "events": "События",
    "organizations": "Организации",
    "characters": "Персонажи",
    "items": "Предметы",
    "locations": "Локации",
}

_TYPE_TO_ENTITY = {
    "events": "event",
    "organizations": "organization",
    "characters": "character",
    "items": "item",
    "locations": "location",
}


class SearchBar(QWidget):
    search_requested = Signal(str)
    result_selected = Signal(str, int)  # (entity_type, entity_id)

    def __init__(self, search_vm, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = search_vm
        self._debounce_timer = QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)
        self._debounce_timer.timeout.connect(self._fire_search)
        self._init_ui()
        self._vm.results_changed.connect(self._show_results)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 0)
        layout.setSpacing(0)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск по всем сущностям (от 2 символов)...")
        self.search_input.textChanged.connect(self._on_text_changed)
        self.search_input.returnPressed.connect(self._fire_search)

        self.search_button = QPushButton("Найти")
        self.search_button.clicked.connect(self._fire_search)

        row.addWidget(self.search_input)
        row.addWidget(self.search_button)
        layout.addLayout(row)

        # Results dropdown list
        self.results_list = QListWidget()
        self.results_list.setVisible(False)
        self.results_list.setMaximumHeight(300)
        self.results_list.setStyleSheet(
            "QListWidget { border: 1px solid palette(mid); }"
            "QListWidget::item { padding: 4px 8px; }"
            "QListWidget::item:hover { background: palette(highlight); color: palette(highlighted-text); }"
        )
        self.results_list.itemClicked.connect(self._on_result_clicked)
        layout.addWidget(self.results_list)

    def _on_text_changed(self, text: str) -> None:
        if len(text.strip()) >= 2:
            self._debounce_timer.start()
        else:
            self._debounce_timer.stop()
            self.results_list.setVisible(False)

    def _fire_search(self) -> None:
        query = self.search_input.text().strip()
        if len(query) >= 2:
            self.search_requested.emit(query)

    def _show_results(self) -> None:
        results: Dict[str, List[Any]] = self._vm.results
        self.results_list.clear()

        total = sum(len(v) for v in results.values())
        if total == 0:
            query = self.search_input.text().strip()
            if len(query) >= 2:
                item = QListWidgetItem("Ничего не найдено")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.results_list.addItem(item)
                self.results_list.setVisible(True)
            else:
                self.results_list.setVisible(False)
            return

        for type_key, entities in results.items():
            if not entities:
                continue
            label = _TYPE_LABELS.get(type_key, type_key)
            entity_type = _TYPE_TO_ENTITY.get(type_key, type_key)

            # Section header
            header = QListWidgetItem(f"— {label} ({len(entities)}) —")
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            header.setBackground(self.palette().mid())
            self.results_list.addItem(header)

            for entity in entities:
                name = getattr(entity, "name", str(entity))
                dates = ""
                if hasattr(entity, "start_date") and entity.start_date:
                    dates = f"  [{entity.start_date}]"
                item = QListWidgetItem(f"  {name}{dates}")
                item.setData(256, {"type": entity_type, "id": getattr(entity, "id", None)})
                self.results_list.addItem(item)

        self.results_list.setVisible(True)

    def _on_result_clicked(self, item: QListWidgetItem) -> None:
        data = item.data(256)
        if data and data.get("id") is not None:
            self.result_selected.emit(data["type"], data["id"])
            self.results_list.setVisible(False)
