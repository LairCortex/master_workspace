"""Shared section widget for managing related entities.

Used by ``EventDialog`` (one tab per entity type) and ``EntityCardDialog``
(one section per related type): a list of names plus the three actions
«Привязать существующего» / «Создать нового» / «Отвязать». No inline
creation form — new entities are created in a separate card window.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)


class RelatedSection(QWidget):
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
        self.link_button = QPushButton("Привязать существующего")
        self.link_button.clicked.connect(self._on_link_existing)
        self.create_button = QPushButton("Создать нового")
        self.create_button.clicked.connect(self.create_requested.emit)
        self.remove_button = QPushButton("Отвязать")
        self.remove_button.clicked.connect(self._on_remove)
        btn_row.addWidget(self.link_button)
        btn_row.addWidget(self.create_button)
        btn_row.addWidget(self.remove_button)
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
