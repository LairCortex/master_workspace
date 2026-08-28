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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.application.services.character_sheet_instance_service import (
    CharacterSheetInstanceError,
    CharacterSheetInstanceService,
)
from app.application.services.character_sheet_service import (
    CharacterSheetError,
    CharacterSheetService,
    TemplateHasInstancesError,
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
    open_instance_requested = Signal(int)
    renamed = Signal(int, str)
    instance_renamed = Signal(int, str)

    def __init__(
        self,
        service: CharacterSheetService,
        parent: QWidget | None = None,
        run_locked: Callable[[Coroutine], Awaitable] | None = None,
        instance_service: CharacterSheetInstanceService | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._instance_service = instance_service
        self._open_sheet_id: int | None = None
        self._open_instance_id: int | None = None
        self._instance_counts: dict[int, int] = {}
        self._run_locked = run_locked or _run_now

        self.setWindowTitle("Чар-листы")
        self.resize(420, 520)

        self.list_widget = QListWidget(self)
        self.instance_list = QListWidget(self)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self.list_widget, "Шаблоны")
        self.tabs.addTab(self.instance_list, "Листы")

        self.create_button = QPushButton("Создать", self)
        self.open_button = QPushButton("Открыть", self)
        self.rename_button = QPushButton("Переименовать", self)
        self.delete_button = QPushButton("Удалить", self)
        self.close_button = QPushButton("Закрыть", self)

        self.create_button.clicked.connect(lambda: self._spawn(self._create_current()))
        self.open_button.clicked.connect(lambda: self._spawn(self._open_current()))
        self.rename_button.clicked.connect(lambda: self._spawn(self._rename_current()))
        self.delete_button.clicked.connect(lambda: self._spawn(self._delete_current()))
        self.close_button.clicked.connect(self.close)
        self.list_widget.itemSelectionChanged.connect(self._sync_actions_enabled)
        self.instance_list.itemSelectionChanged.connect(self._sync_actions_enabled)
        self.tabs.currentChanged.connect(lambda _i: self._sync_actions_enabled())

        buttons = QHBoxLayout()
        buttons.addWidget(self.create_button)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.rename_button)
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)

        bottom = QHBoxLayout()
        bottom.addLayout(buttons)
        bottom.addWidget(self.close_button)

        info = QLabel("Чар-листы текущей игры", self)
        info.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addWidget(self.tabs, 1)
        layout.addLayout(bottom)

    # -- wiring helpers -------------------------------------------------------

    @staticmethod
    def _spawn(coro) -> None:
        # Runs on the qasync event loop in the app; tests run the loop too.
        asyncio.ensure_future(coro)

    def set_open_sheet_id(self, sheet_id: int | None) -> None:
        """Mark the sheet that is open in the editor (delete becomes unavailable)."""
        self._open_sheet_id = sheet_id
        self._sync_actions_enabled()

    def set_open_instance_id(self, instance_id: int | None) -> None:
        self._open_instance_id = instance_id
        self._sync_actions_enabled()

    def _on_instances_tab(self) -> bool:
        return self.tabs.currentIndex() == 1

    def _selected_id(self) -> int | None:
        row = self.list_widget.currentItem()
        return row.data(Qt.ItemDataRole.UserRole) if row is not None else None

    def _selected_instance_id(self) -> int | None:
        row = self.instance_list.currentItem()
        return row.data(Qt.ItemDataRole.UserRole) if row is not None else None

    def _selected_name(self) -> str | None:
        row = self.list_widget.currentItem()
        return row.text() if row is not None else None

    def _selected_instance_name(self) -> str | None:
        row = self.instance_list.currentItem()
        if row is None:
            return None
        stored = row.data(Qt.ItemDataRole.UserRole + 1)
        return stored if stored else row.text()

    def _sync_delete_enabled(self) -> None:
        self._sync_actions_enabled()

    def _sync_actions_enabled(self) -> None:
        if self._on_instances_tab():
            instance_id = self._selected_instance_id()
            has = instance_id is not None
            self.open_button.setEnabled(has)
            self.rename_button.setEnabled(has)
            self.delete_button.setEnabled(
                has and instance_id != self._open_instance_id
            )
            return
        sheet_id = self._selected_id()
        has = sheet_id is not None
        self.open_button.setEnabled(has)
        self.rename_button.setEnabled(has)
        blocked = (
            not has
            or sheet_id == self._open_sheet_id
            or self._instance_counts.get(sheet_id, 0) > 0
        )
        self.delete_button.setEnabled(not blocked)

    def _refresh_selection(self, sheet_id: int) -> None:
        for i in range(self.list_widget.count()):
            if self.list_widget.item(i).data(Qt.ItemDataRole.UserRole) == sheet_id:
                self.list_widget.setCurrentRow(i)
                return

    def _show_error(self, exc: Exception) -> None:
        if isinstance(exc, (CharacterSheetError, CharacterSheetInstanceError)):
            QMessageBox.warning(self, "Чар-листы", str(exc))
        else:
            log.error("character-sheet list action failed: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Ошибка", str(exc))

    # -- async flows ------------------------------------------------------------

    async def refresh(self) -> None:
        """Reload the list from the DB (name-sorted, id stored per row)."""
        self.list_widget.blockSignals(True)
        template_names: dict[int, str] = {}
        try:
            self.list_widget.clear()
            for row in await self._service.list_sheets():
                item = QListWidgetItem(row.name, self.list_widget)
                item.setData(Qt.ItemDataRole.UserRole, row.id)
                template_names[row.id] = row.name
        finally:
            self.list_widget.blockSignals(False)
        self._instance_counts = {}
        self.instance_list.blockSignals(True)
        try:
            self.instance_list.clear()
            if self._instance_service is not None:
                for row in await self._instance_service.list_instances():
                    tmpl = template_names.get(row.template_id, "")
                    label = f"{row.name} — {tmpl}" if tmpl else row.name
                    item = QListWidgetItem(label, self.instance_list)
                    item.setData(Qt.ItemDataRole.UserRole, row.id)
                    item.setData(Qt.ItemDataRole.UserRole + 1, row.name)
                    self._instance_counts[row.template_id] = (
                        self._instance_counts.get(row.template_id, 0) + 1
                    )
        finally:
            self.instance_list.blockSignals(False)
        self._sync_actions_enabled()

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
        if self._instance_counts.get(sheet_id, 0) > 0:
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

    def _refresh_instance_selection(self, instance_id: int) -> None:
        for i in range(self.instance_list.count()):
            if self.instance_list.item(i).data(Qt.ItemDataRole.UserRole) == instance_id:
                self.instance_list.setCurrentRow(i)
                return

    async def _create_current(self) -> None:
        if self._on_instances_tab():
            await self.create_instance()
        else:
            await self.create_sheet()

    async def _open_current(self) -> None:
        if self._on_instances_tab():
            await self.open_instance()
        else:
            await self.open_sheet()

    async def _rename_current(self) -> None:
        if self._on_instances_tab():
            await self.rename_instance()
        else:
            await self.rename_sheet()

    async def _delete_current(self) -> None:
        if self._on_instances_tab():
            await self.delete_instance()
        else:
            await self.delete_sheet()

    async def create_instance(self) -> None:
        if self._instance_service is None:
            return
        templates = list(await self._service.list_sheets())
        if not templates:
            QMessageBox.warning(self, "Чар-листы", "Сначала создайте шаблон")
            return
        names = [t.name for t in templates]
        chosen, ok = QInputDialog.getItem(
            self, "Создать лист", "Шаблон:", names, 0, False
        )
        if not ok or not chosen:
            return
        template = next((t for t in templates if t.name == chosen), None)
        if template is None:
            return
        name, ok = QInputDialog.getText(self, "Создать лист", "Имя:")
        if not ok:
            return
        if not name.strip():
            QMessageBox.warning(self, "Чар-листы", "Имя не может быть пустым")
            return
        try:
            row = await self._run_locked(
                self._instance_service.create(name, template.id)
            )
        except Exception as exc:
            self._show_error(exc)
            return
        await self._run_locked(self.refresh())
        self.tabs.setCurrentIndex(1)
        self._refresh_instance_selection(row.id)
        self.open_instance_requested.emit(row.id)

    async def open_instance(self) -> None:
        instance_id = self._selected_instance_id()
        if instance_id is None:
            return
        self.open_instance_requested.emit(instance_id)

    async def rename_instance(self) -> None:
        if self._instance_service is None:
            return
        instance_id = self._selected_instance_id()
        if instance_id is None:
            return
        current = self._selected_instance_name() or ""
        name, ok = QInputDialog.getText(
            self, "Переименовать", "Имя:", text=current
        )
        if not ok or not name.strip():
            return
        try:
            row = await self._run_locked(
                self._instance_service.rename(instance_id, name)
            )
        except Exception as exc:
            self._show_error(exc)
            return
        await self._run_locked(self.refresh())
        self._refresh_instance_selection(instance_id)
        self.instance_renamed.emit(instance_id, row.name)

    async def delete_instance(self) -> None:
        if self._instance_service is None:
            return
        instance_id = self._selected_instance_id()
        if instance_id is None or instance_id == self._open_instance_id:
            return
        name = self._selected_instance_name() or ""
        answer = QMessageBox.question(
            self,
            "Удалить лист",
            f"Удалить лист «{name}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            await self._run_locked(self._instance_service.delete(instance_id))
        except Exception as exc:
            self._show_error(exc)
            return
        await self._run_locked(self.refresh())
