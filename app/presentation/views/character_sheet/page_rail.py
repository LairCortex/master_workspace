"""The character-sheet page rail (A-playable, design D7).

A separate widget left of the canvas (not a second canvas): the template's
pages as a named list with add / delete / reorder / rename.

- Clicking an item emits ``page_selected(index)`` — the owner scrolls the
  canvas to that sheet and the item becomes current.
- Double-click an item to rename it; the edit commits on Enter through
  ``itemChanged`` (Esc reverts to the stored name). An empty name is refused
  and the list stays on the stored name.
- Deleting a page that has fields asks for confirmation (``QMessageBox``);
  the last remaining page cannot be deleted (button unavailable).
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.presentation.viewmodels.character_sheet_viewmodel import (
    CharacterSheetViewModel,
)


class PageRail(QWidget):
    """The page list of the editor: names + add / delete / reorder / rename."""

    page_selected = Signal(int)

    def __init__(self, vm: CharacterSheetViewModel,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = vm
        self._renaming = False

        self.pages_list = QListWidget(self)
        self.pages_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.pages_list.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
        )
        self.pages_list.itemClicked.connect(self._on_item_clicked)
        self.pages_list.itemChanged.connect(self._on_item_changed)

        self.up_button = QToolButton(self)
        self.up_button.setText("↑")
        self.up_button.setToolTip("Вверх")
        self.down_button = QToolButton(self)
        self.down_button.setText("↓")
        self.down_button.setToolTip("Вниз")
        self.delete_button = QToolButton(self)
        self.delete_button.setText("−")
        self.delete_button.setToolTip("Удалить страницу")
        self.add_button = QToolButton(self)
        self.add_button.setText("+")
        self.add_button.setToolTip("Добавить страницу после текущей")

        self.up_button.clicked.connect(self._move_up)
        self.down_button.clicked.connect(self._move_down)
        self.delete_button.clicked.connect(self._delete_page)
        self.add_button.clicked.connect(self._add_page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.addWidget(self.pages_list, 1)
        row = QHBoxLayout()
        buttons = [self.up_button, self.down_button, self.delete_button, self.add_button]
        for b in buttons:
            b.setMinimumHeight(26)
            row.addWidget(b)
        layout.addLayout(row)

        vm.pages_changed.connect(self._rebuild)
        vm.template_changed.connect(self._rebuild)
        vm.current_page_changed.connect(self._set_current)

        if vm.template is not None:
            self._rebuild()

    # -- VM → rail ------------------------------------------------------------

    def _rebuild(self) -> None:
        template = self._vm.template
        self._renaming = False
        current = self._vm.current_page_index
        self.pages_list.blockSignals(True)
        try:
            self.pages_list.clear()
            if template is not None:
                for page in template.pages:
                    self.pages_list.addItem(QListWidgetItem(page.name))
        finally:
            self.pages_list.blockSignals(False)
        self._set_current(current, scroll=False)
        self._sync_controls()

    def _set_current(self, index: int, scroll: bool = True) -> None:
        if not (0 <= index < self.pages_list.count()):
            return
        self.pages_list.blockSignals(True)
        try:
            self.pages_list.setCurrentRow(index)
        finally:
            self.pages_list.blockSignals(False)
        if scroll:
            self.pages_list.scrollToItem(self.pages_list.item(index))

    def _sync_controls(self) -> None:
        n = self.pages_list.count()
        has = self.pages_list.currentRow() >= 0
        self.up_button.setEnabled(n > 1 and has)
        self.down_button.setEnabled(n > 1 and has)
        self.delete_button.setEnabled(n > 1 and has)
        self.add_button.setEnabled(n > 0)

    # -- rail → VM --------------------------------------------------------------

    def _on_item_clicked(self, item) -> None:
        if self._renaming:
            return
        index = self.pages_list.row(item)
        self._vm.set_current_page(index)
        self._sync_controls()
        self.page_selected.emit(index)

    def _on_item_changed(self, item) -> None:
        """Inline-edit commit: apply the new name, or restore the stored one."""
        index = self.pages_list.row(item)
        template = self._vm.template
        if template is None or not 0 <= index < len(template.pages):
            return
        new_name = item.text()
        if new_name == template.pages[index].name:
            return
        self._renaming = True
        try:
            if self._vm.rename_page(index, new_name):
                return
        finally:
            self._renaming = False
        # refused (empty name): keep the stored name
        self.pages_list.blockSignals(True)
        try:
            item.setText(template.pages[index].name)
        finally:
            self.pages_list.blockSignals(False)

    def _add_page(self) -> None:
        self._vm.add_page()

    def _delete_page(self) -> None:
        index = self.pages_list.currentRow()
        if index < 0:
            return
        template = self._vm.template
        if template is None or not 0 <= index < len(template.pages):
            return
        if len(template.pages) <= 1:
            return  # the last remaining page cannot be deleted
        if template.pages[index].fields:
            answer = QMessageBox.question(
                self,
                "Удалить страницу",
                "На странице есть поля. Удалить её вместе с ними?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._vm.remove_page(index, confirmed=True)

    def _move_up(self) -> None:
        index = self.pages_list.currentRow()
        if index > 0:
            self._vm.move_page(index, index - 1)

    def _move_down(self) -> None:
        index = self.pages_list.currentRow()
        if index >= 0 and index < self.pages_list.count() - 1:
            self._vm.move_page(index, index + 1)
