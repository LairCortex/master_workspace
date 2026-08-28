"""Character-sheet list dialog: create / open / rename / delete (non-modal).

All flows go through :class:`CharacterSheetService` on the shared session;
button handlers are coroutines spawned onto the running loop (qasync). Name
conflicts surface as ``QMessageBox`` warnings and leave the list unchanged.
The sheet currently open in the editor cannot be deleted here
(``set_open_sheet_id``). Rename commits immediately and is never a layout edit.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Coroutine

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.application.services.character_sheet_service import (
    CharacterSheetError,
    CharacterSheetService,
)

log = logging.getLogger(__name__)


async def _run_now(coro: Coroutine) -> Any:
    """Default ``run_locked``: no session lock (unit tests, no shared session)."""
    return await coro


class CharacterSheetListDialog(QDialog):
    """List of the current game's sheet templates.

    Every session-touching step (create/rename/delete and the list refresh) is
    wrapped in ``run_locked`` — the application's session lock, since the
    shared AsyncSession must not be used by concurrent tasks. The dialog's own
    UI (modal pickers, selection) is not session work and stays outside it.
    ``refresh()`` itself does NOT lock; its caller provides the lock.
    """

    open_requested = Signal(int)
    renamed = Signal(int, str)

    def __init__(
        self,
        service: CharacterSheetService,
        parent: QWidget | None = None,
        run_locked: Callable[[Coroutine], Awaitable] | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._open_sheet_id: int | None = None
        self._run_locked = run_locked or _run_now

        self.setWindowTitle("Чар-листы")
        self.resize(420, 520)

        self.list_widget = QListWidget(self)

        self.create_button = QPushButton("Создать", self)
        self.open_button = QPushButton("Открыть", self)
        self.rename_button = QPushButton("Переименовать", self)
        self.delete_button = QPushButton("Удалить", self)
        self.close_button = QPushButton("Закрыть", self)

        self.create_button.clicked.connect(lambda: self._spawn(self.create_sheet()))
        self.open_button.clicked.connect(lambda: self._spawn(self.open_sheet()))
        self.rename_button.clicked.connect(lambda: self._spawn(self.rename_sheet()))
        self.delete_button.clicked.connect(lambda: self._spawn(self.delete_sheet()))
        self.close_button.clicked.connect(self.close)
        self.list_widget.itemSelectionChanged.connect(self._sync_delete_enabled)

        buttons = QHBoxLayout()
        buttons.addWidget(self.create_button)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.rename_button)
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)

        bottom = QHBoxLayout()
        bottom.addLayout(buttons)
        bottom.addWidget(self.close_button)

        info = QLabel("Шаблоны чар-листов текущей игры", self)
        info.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addWidget(self.list_widget, 1)
        layout.addLayout(bottom)

    # -- wiring helpers -------------------------------------------------------

    @staticmethod
    def _spawn(coro) -> None:
        # Runs on the qasync event loop in the app; tests run the loop too.
        asyncio.ensure_future(coro)

    def set_open_sheet_id(self, sheet_id: int | None) -> None:
        """Mark the sheet that is open in the editor (delete becomes unavailable)."""
        self._open_sheet_id = sheet_id
        self._sync_delete_enabled()

    def _selected_id(self) -> int | None:
        row = self.list_widget.currentItem()
        return row.data(Qt.ItemDataRole.UserRole) if row is not None else None

    def _selected_name(self) -> str | None:
        row = self.list_widget.currentItem()
        return row.text() if row is not None else None

    def _sync_delete_enabled(self) -> None:
        sheet_id = self._selected_id()
        self.delete_button.setEnabled(
            sheet_id is not None and sheet_id != self._open_sheet_id
        )

    def _refresh_selection(self, sheet_id: int) -> None:
        for i in range(self.list_widget.count()):
            if self.list_widget.item(i).data(Qt.ItemDataRole.UserRole) == sheet_id:
                self.list_widget.setCurrentRow(i)
                return

    def _show_error(self, exc: Exception) -> None:
        if isinstance(exc, CharacterSheetError):
            QMessageBox.warning(self, "Чар-листы", str(exc))
        else:
            log.error("character-sheet list action failed: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Ошибка", str(exc))

    # -- async flows ------------------------------------------------------------

    async def refresh(self) -> None:
        """Reload the list from the DB (name-sorted, id stored per row)."""
        self.list_widget.blockSignals(True)
        try:
            self.list_widget.clear()
            for row in await self._service.list_sheets():
                item = QListWidgetItem(row.name, self.list_widget)
                item.setData(Qt.ItemDataRole.UserRole, row.id)
        finally:
            self.list_widget.blockSignals(False)
        self._sync_delete_enabled()

    async def create_sheet(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Создать чар-лист", "Имя:"
        )
        if not ok:
            return
        if not name.strip():
            QMessageBox.warning(self, "Чар-листы", "Имя не может быть пустым")
            return
        try:
            row = await self._run_locked(self._service.create(name))
        except Exception as exc:
            self._show_error(exc)
            return
        await self._run_locked(self.refresh())
        self._refresh_selection(row.id)
        self.open_requested.emit(row.id)

    async def open_sheet(self) -> None:
        sheet_id = self._selected_id()
        if sheet_id is None:
            return
        self.open_requested.emit(sheet_id)

    async def rename_sheet(self) -> None:
        sheet_id = self._selected_id()
        if sheet_id is None:
            return
        current = self._selected_name() or ""
        name, ok = QInputDialog.getText(
            self, "Переименовать", "Имя:", text=current
        )
        if not ok:
            return
        if not name.strip():
            return
        try:
            row = await self._run_locked(self._service.rename(sheet_id, name))
        except Exception as exc:
            self._show_error(exc)
            return
        await self._run_locked(self.refresh())
        self._refresh_selection(sheet_id)
        self.renamed.emit(sheet_id, row.name)

    async def delete_sheet(self) -> None:
        sheet_id = self._selected_id()
        if sheet_id is None or sheet_id == self._open_sheet_id:
            return
        name = self._selected_name() or ""
        answer = QMessageBox.question(
            self,
            "Удалить чар-лист",
            f"Удалить шаблон «{name}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            await self._run_locked(self._service.delete(sheet_id))
        except Exception as exc:
            self._show_error(exc)
            return
        await self._run_locked(self.refresh())
