"""Shared native completion popup for widgets and QML mention editors."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.domain import entity_registry
from app.domain.enums.entity_type import EntityType

# Presentation copy (the glyphs) stays with the view; the keys are registry
# type identities resolved through the entity registry (wave 3, A4).
_ICON_BY_TYPE = {
    EntityType.EVENT: "\U0001f4c5",
    EntityType.ORGANIZATION: "\U0001f465",
    EntityType.CHARACTER: "\U0001f9d1",
    EntityType.ITEM: "\U0001f4e6",
    EntityType.LOCATION: "\U0001f4cd",
}


class MentionPopupListView(QListWidget):
    """Named list class consumed by the shared popup stylesheet."""


class _MentionPopup(QWidget):
    """Top-level native result list shared by both mention editors."""

    item_selected = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMinimumWidth(260)
        self.setMaximumHeight(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._list = MentionPopupListView()
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.itemClicked.connect(self._on_click)
        layout.addWidget(self._list)

    def show_results(self, results: list[dict], global_pos: QPoint) -> None:
        self._list.clear()
        for result in results[:15]:
            icon = _ICON_BY_TYPE.get(entity_registry.resolve(result["type"]), "")
            item = QListWidgetItem(f'{icon}  {result["name"]}')
            item.setData(Qt.ItemDataRole.UserRole, result)
            self._list.addItem(item)
        if self._list.count() == 0:
            self.hide()
            return
        self._list.setCurrentRow(0)
        self.move(global_pos)
        self.show()

    def select_next(self) -> None:
        row = self._list.currentRow()
        if row < self._list.count() - 1:
            self._list.setCurrentRow(row + 1)

    def select_prev(self) -> None:
        row = self._list.currentRow()
        if row > 0:
            self._list.setCurrentRow(row - 1)

    def confirm_selection(self) -> None:
        item = self._list.currentItem()
        if item:
            self._on_click(item)

    def _on_click(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self.item_selected.emit(data)
