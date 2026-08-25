"""Character sheet list dialog (task 7.1): template list with create / open /
delete and JSON project export/import (design D7).

Database work goes through the service with bare ``ensure_future`` tasks — the
same pattern as the editor dialog; the list reloads after each mutation.
"""
from __future__ import annotations

import asyncio

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.application.services.character_sheet_service import (
    CHARSHEET_FORMAT,
    CHARSHEET_FORMAT_VERSION,
    CharacterSheetImportError,
    CharacterSheetNameConflict,
    CharacterSheetService,
)
from app.domain.entities.character_sheet import SheetPage, SheetTemplate
from app.domain.enums.sheet_orientation import SheetOrientation


class CharacterSheetListDialog(QDialog):
    """Dialog listing the game's character sheet templates.

    ``open_requested`` carries the id of the template to open in the editor;
    the host (Application) opens the editor window itself.
    """

    #: id (character_sheets.id) of the template to open in the editor
    open_requested = Signal(int)

    def __init__(self, service: CharacterSheetService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self.setWindowTitle("Чар-листы")
        self._init_ui()
        asyncio.ensure_future(self._refresh())

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Шаблоны чар-листов:"))

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _item: self._open_selected())
        layout.addWidget(self._list)

        buttons = QHBoxLayout()
        self._create_btn = QPushButton("Создать")
        self._create_btn.clicked.connect(self._create)
        buttons.addWidget(self._create_btn)
        self._open_btn = QPushButton("Открыть")
        self._open_btn.clicked.connect(self._open_selected)
        buttons.addWidget(self._open_btn)
        self._delete_btn = QPushButton("Удалить")
        self._delete_btn.clicked.connect(self._delete_selected)
        buttons.addWidget(self._delete_btn)
        buttons.addStretch(1)
        self._export_btn = QPushButton("Экспорт JSON")
        self._export_btn.clicked.connect(lambda: asyncio.ensure_future(self._export_selected()))
        buttons.addWidget(self._export_btn)
        self._import_btn = QPushButton("Импорт JSON")
        self._import_btn.clicked.connect(lambda: asyncio.ensure_future(self._import()))
        buttons.addWidget(self._import_btn)
        layout.addLayout(buttons)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        layout.addLayout(bottom)
        self.resize(420, 340)

    # ── list sync ─────────────────────────────────────────────────────────

    async def _refresh(self) -> None:
        rows = await self._service.get_all()
        self._list.clear()
        for row in rows:
            item = QListWidgetItem(row.name)
            item.setData(Qt.ItemDataRole.UserRole, row.id)
            self._list.addItem(item)

    def _selected_id(self) -> int | None:
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    # ── actions ───────────────────────────────────────────────────────────

    def _create(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Новый шаблон", "Имя шаблона:", text="Новый лист",
        )
        name = name.strip()
        if not ok or not name:
            return
        asyncio.ensure_future(self._create_template(name))

    async def _create_template(self, name: str) -> None:
        template = SheetTemplate(
            name=name,
            orientation=SheetOrientation.LANDSCAPE,
            pages=[SheetPage(name="Стр 1")],
        )
        try:
            row = await self._service.create(template)
        except CharacterSheetNameConflict:
            QMessageBox.warning(self, "Чар-листы", f"Имя «{name}» уже существует")
            return
        await self._refresh()
        self._select_by_id(row.id)

    def _select_by_id(self, sheet_id: int) -> None:
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.ItemDataRole.UserRole) == sheet_id:
                self._list.setCurrentRow(i)
                return

    def _open_selected(self) -> None:
        sheet_id = self._selected_id()
        if sheet_id is None:
            return
        self.open_requested.emit(sheet_id)

    def _delete_selected(self) -> None:
        sheet_id = self._selected_id()
        if sheet_id is None:
            return
        item = self._list.currentItem()
        answer = QMessageBox.question(
            self,
            "Удаление шаблона",
            f"Удалить шаблон «{item.text()}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        asyncio.ensure_future(self._delete(sheet_id))

    async def _delete(self, sheet_id: int) -> None:
        await self._service.delete(sheet_id)
        await self._refresh()

    async def _export_selected(self) -> None:
        sheet_id = self._selected_id()
        if sheet_id is None:
            return
        template = await self._service.load(sheet_id)
        if template is None:
            return  # row disappeared between the list reload and the click
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Экспорт чар-листа",
            f"{template.name}.json",
            "JSON файлы (*.json);;Все файлы (*)",
        )
        if not dest:
            return
        data = CharacterSheetService.export_project([template])
        try:
            with open(dest, "w", encoding="utf-8") as f:
                f.write(data)
        except OSError as exc:
            QMessageBox.critical(self, "Ошибка экспорта", str(exc))
            return
        QMessageBox.information(self, "Экспорт", f"Шаблон «{template.name}» экспортирован.")

    async def _import(self) -> None:
        src, _ = QFileDialog.getOpenFileName(
            self,
            "Импорт чар-листа",
            "",
            "JSON файлы (*.json);;Все файлы (*)",
        )
        if not src:
            return
        try:
            with open(src, "r", encoding="utf-8") as f:
                data = f.read()
        except OSError as exc:
            QMessageBox.critical(self, "Ошибка импорта", str(exc))
            return
        try:
            created = await self._service.import_project(data)
        except CharacterSheetImportError as exc:
            QMessageBox.warning(self, "Ошибка импорта", str(exc))
            return
        await self._refresh()
        QMessageBox.information(
            self, "Импорт",
            f"Импортировано шаблонов: {len(created)} "
            f"(формат {CHARSHEET_FORMAT} v{CHARSHEET_FORMAT_VERSION})",
        )
