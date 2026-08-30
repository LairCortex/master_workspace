"""Global search bar with live results dropdown."""
from __future__ import annotations

from typing import Any, Dict, List

from app.presentation.theme.catalog import attach_theme, set_role
from app.presentation.utils.date_utils import format_game_date

from PySide6.QtCore import QTimer, Signal, Qt
from PySide6.QtGui import QBrush, QColor
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

#: Item-data marker of a section header (entity items use 256/UserRole).
_HEADER_DATA_ROLE = Qt.ItemDataRole.UserRole + 1


class SearchBar(QWidget):
    search_requested = Signal(str)
    result_selected = Signal(str, int)  # (entity_type, entity_id)

    def __init__(
        self,
        search_vm,
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        super().__init__(parent)
        self._vm = search_vm
        self._theme = theme
        self._debounce_timer = QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)
        self._debounce_timer.timeout.connect(self._fire_search)
        self._init_ui()
        self._apply_theme()
        self._vm.results_changed.connect(self._show_results)

    def _apply_theme(self) -> None:
        """One attach point: the chrome container carries the whole sheet (D1)."""
        if self._theme is not None:
            # Item background brushes are snapshots, not QSS → the headers
            # re-read the border token through the retheme callback (W2b).
            attach_theme(self.chrome, self._theme, on_retheme=self._retheme_headers)
            self._theme.apply()

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.chrome = QWidget()
        self.chrome.setObjectName("searchBarChrome")  # identifier, not style
        outer.addWidget(self.chrome)
        layout = QVBoxLayout(self.chrome)
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
        # Catalog list role (surface/border/item padding/selection from tokens);
        # the old OS-palette mid/highlight hover sheet is gone (W2b) —
        # selection is the accent, hover no longer fakes it.
        set_role(self.results_list, "list")
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

    def _header_brush(self) -> QBrush:
        """Section-header background = the ``color.border`` token of the theme.

        With no (or invalid) runtime the headers stay uncoloured — chrome
        colors only ever come from tokens (W2b; no OS-palette mid fallback).
        An unparsable token value stays uncoloured as well: Qt turns an
        invalid ``QColor`` into black, which is exactly the invented color
        D7 forbids (same ``isValid`` contract as ``rating_to_color``).
        """
        tokens = self._theme.tokens if self._theme is not None else None
        if not tokens:
            return QBrush()
        color = QColor(tokens["color.border"][self._theme.theme])
        if not color.isValid():
            return QBrush()
        return QBrush(color)

    def _retheme_headers(self) -> None:
        """Re-read the border token for section headers after a live switch
        (background brushes are snapshots, not QSS — W2b fix)."""
        brush = self._header_brush()
        for i in range(self.results_list.count()):
            item = self.results_list.item(i)
            if item.data(_HEADER_DATA_ROLE):
                item.setBackground(brush)

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
            header.setData(_HEADER_DATA_ROLE, True)
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            header.setBackground(self._header_brush())
            self.results_list.addItem(header)

            for entity in entities:
                name = getattr(entity, "name", str(entity))
                dates = ""
                if hasattr(entity, "start_date") and entity.start_date:
                    dates = f"  [{format_game_date(entity.start_date)}]"
                item = QListWidgetItem(f"  {name}{dates}")
                item.setData(256, {"type": entity_type, "id": getattr(entity, "id", None)})
                self.results_list.addItem(item)

        self.results_list.setVisible(True)

    def _on_result_clicked(self, item: QListWidgetItem) -> None:
        data = item.data(256)
        if data and data.get("id") is not None:
            self.result_selected.emit(data["type"], data["id"])
            self.results_list.setVisible(False)
