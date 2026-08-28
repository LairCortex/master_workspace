"""«Создать из пресета…» dialog (add-character-sheet-c, design D5).

Non-modal child of the sheet list dialog: the bundled presets (Fate Core,
Mörk Borg), the full license text of the selected one, and the template name.
Switching the selection re-substitutes the preset title into the name field
only while the user has not typed their own name (the field is empty or still
holds another preset's title). OK calls ``create_from_preset`` on the shared
session lock; on success it emits ``created(sheet_id)`` and closes, on a name
conflict it warns and stays open, cancel creates nothing.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Coroutine

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.application.services.character_sheet_service import (
    CharacterSheetError,
    CharacterSheetService,
)
from app.presentation.views.character_sheet.presets.catalog import (
    PresetCatalog,
)

log = logging.getLogger(__name__)


async def _run_now(coro: Coroutine) -> Any:
    """Default ``run_locked``: no session lock (unit tests, no shared session)."""
    return await coro


class CharacterSheetPresetDialog(QDialog):
    """Pick a bundled preset, see its license, name the snapshot, create it."""

    created = Signal(int)

    def __init__(
        self,
        service: CharacterSheetService,
        parent: QWidget | None = None,
        run_locked: Callable[[Coroutine], Awaitable] | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._run_locked = run_locked or _run_now
        self._presets = PresetCatalog().list()

        self.setWindowTitle("Создать из пресета")
        self.resize(540, 500)

        self.preset_label = QLabel("Пресет:", self)
        self.preset_list = QListWidget(self)
        for preset in self._presets:
            QListWidgetItem(preset.title, self.preset_list)

        self.license_label = QLabel("Лицензия:", self)
        # The full license text is shown read-only, at the dialog's font size
        # (not smaller than the neighbouring captions — spec).
        self.license_view = QPlainTextEdit(self)
        self.license_view.setReadOnly(True)
        self.license_view.setFixedHeight(140)

        self.name_label = QLabel("Имя:", self)
        self.name_edit = QLineEdit(self)

        self.ok_button = QPushButton("Создать", self)
        self.cancel_button = QPushButton("Отмена", self)

        self.preset_list.currentRowChanged.connect(self._on_preset_changed)
        self.ok_button.clicked.connect(lambda: self._spawn(self._on_ok()))
        self.cancel_button.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.ok_button)
        buttons.addWidget(self.cancel_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.preset_label)
        layout.addWidget(self.preset_list, 1)
        layout.addWidget(self.license_label)
        layout.addWidget(self.license_view)
        layout.addWidget(self.name_label)
        layout.addWidget(self.name_edit)
        layout.addLayout(buttons)

        self.preset_list.setCurrentRow(0)

    @staticmethod
    def _spawn(coro) -> None:
        # Runs on the qasync event loop in the app; tests run the loop too.
        asyncio.ensure_future(coro)

    # -- selection -----------------------------------------------------------

    def _current_preset_index(self) -> int:
        return self.preset_list.currentRow()

    def _on_preset_changed(self, row: int) -> None:
        if row < 0:
            return
        preset = self._presets[row]
        self.license_view.setPlainText(preset.license_text)
        # D5: substitute the title only while the field is empty or still
        # holds another preset's title (the user has not typed their own name).
        # Surrounding whitespace does not make it a user name: a padded title
        # like «Mörk Borg » is still the other preset's title and gets
        # replaced by the clean one (review #9).
        current = self.name_edit.text().strip()
        other_titles = {p.title for p in self._presets if p.id != preset.id}
        if current == "" or current in other_titles:
            self.name_edit.setText(preset.title)

    # -- create ---------------------------------------------------------------

    async def _on_ok(self) -> None:
        row = self._current_preset_index()
        if row < 0:
            return
        preset = self._presets[row]
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Чар-листы", "Имя не может быть пустым")
            return
        try:
            created = await self._run_locked(
                self._service.create_from_preset(preset.id, name)
            )
        except CharacterSheetError as exc:
            self._show_error(exc)
            return
        except Exception as exc:
            log.error("create-from-preset failed: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Ошибка", str(exc))
            return
        self.created.emit(created.id)
        self.accept()

    def _show_error(self, exc: Exception) -> None:
        if isinstance(exc, CharacterSheetError):
            QMessageBox.warning(self, "Чар-листы", str(exc))
        else:
            log.error("create-from-preset failed: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Ошибка", str(exc))
