"""«Страницы…» dialog: rename, reorder, delete with confirmation (6.5).

Actions apply to the viewmodel immediately (hence undoable); the dialog
just re-lists the pages after each action.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid


class PagesDialog(QDialog):
    def __init__(self, viewmodel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = viewmodel
        self._reloading = False
        self.setWindowTitle("Страницы")
        self._init_ui()
        # pages may be added/removed outside the dialog (the viewmodel is the
        # single source of truth) — follow it
        self._vm.state_changed.connect(self._reload)
        self._reload()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Страницы шаблона:"))

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _item: self._rename())
        self._list.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._list)

        buttons = QHBoxLayout()
        for caption, slot in (
            ("Переименовать", self._rename),
            ("Удалить", self._remove),
            ("Выше", lambda: self._move(-1)),
            ("Ниже", lambda: self._move(+1)),
        ):
            button = QPushButton(caption)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.resize(360, 320)

    # ── list sync ─────────────────────────────────────────────────────────

    def _reload(self) -> None:
        current = self._list.currentRow()
        self._reloading = True
        try:
            self._list.clear()
            for page in self._vm.template.pages:
                item = QListWidgetItem(page.name)
                if page.fields:
                    item.setToolTip(f"{len(page.fields)} полей")
                self._list.addItem(item)
        finally:
            self._reloading = False
        self._list.setCurrentRow(min(max(current, 0), self._list.count() - 1) if current >= 0 else 0)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        if self._reloading:
            return
        if not isValid(item):
            return  # item already rebuilt by a prior _reload (defensive)
        row = self._list.row(item)
        if row < 0:
            return
        # inline rename committed (double-click edit): push to the model
        new_name = item.text().strip()
        if self._vm.template.pages[row].name == new_name:
            return  # flag change / already applied — idempotent, no reload
        if new_name and self._vm.rename_page(row, new_name):
            pass  # state_changed → _reload
        else:
            self._reload()  # empty rejected: restore displayed names

    def _selected_index(self) -> int:
        row = self._list.currentRow()
        return row if row >= 0 else -1

    # ── actions ───────────────────────────────────────────────────────────

    def _rename(self) -> None:
        index = self._selected_index()
        if index < 0:
            return
        item = self._list.item(index)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self._list.editItem(item)

    def _remove(self) -> None:
        index = self._selected_index()
        if index < 0:
            return
        page = self._vm.template.pages[index]
        if page.fields:
            answer = QMessageBox.question(
                self,
                "Удаление страницы",
                f"На странице «{page.name}» есть поля — удалить вместе со страницей?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        if self._vm.remove_page(index):
            self._reload()

    def _move(self, delta: int) -> None:
        index = self._selected_index()
        if index < 0:
            return
        moved = self._vm.move_page_up(index) if delta < 0 else self._vm.move_page_down(index)
        if moved:
            self._reload()
            self._list.setCurrentRow(index + delta)
