"""Fill window: read-only layout canvas + value map (design D3/D4)."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Coroutine

from PySide6.QtCore import QEvent, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenuBar,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.application.services.character_sheet_instance_service import (
    CharacterSheetInstanceError,
    CharacterSheetInstanceService,
)
from app.application.services.character_sheet_service import CharacterSheetService
from app.domain.enums.field_type import FieldType
from app.infrastructure.images.store import ImageStore
from app.presentation.theme.catalog import attach_theme
from app.presentation.viewmodels.character_sheet_fill_viewmodel import (
    CharacterSheetFillViewModel,
)
from app.presentation.views.character_sheet.canvas import CharacterSheetCanvas
from app.presentation.views.character_sheet.page_rail import PageRail

log = logging.getLogger(__name__)

_RAIL_WIDTH = 160
_PANEL_WIDTH = 260
_IMAGE_FILTER = "Изображения (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;Все файлы (*)"


def character_choice_labels(chars) -> list[tuple[str, int]]:
    """Labels for the bind picker: duplicate names get `` (#id)``."""
    counts: dict[str, int] = {}
    for char in chars:
        counts[char.name] = counts.get(char.name, 0) + 1
    out: list[tuple[str, int]] = []
    for char in chars:
        label = char.name if counts[char.name] == 1 else f"{char.name} (#{char.id})"
        out.append((label, char.id))
    return out


async def _run_now(coro: Coroutine) -> Any:
    return await coro


class FillPropertiesPanel(QWidget):
    """Value editor of the selected fillable field."""

    image_pick_requested = Signal(str)

    def __init__(self, vm: CharacterSheetFillViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = vm
        self._fid: str | None = None
        self._syncing = False

        self.hint = QLabel("Выберите поле", self)
        self.text_edit = QLineEdit(self)
        self.textarea = QPlainTextEdit(self)
        self.textarea.setFixedHeight(80)
        self.checkbox = QCheckBox("Вкл.", self)
        self.dropdown = QComboBox(self)
        self.image_pick = QPushButton("Выбрать…", self)
        self.image_clear = QPushButton("Убрать", self)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Значение", self))
        layout.addWidget(self.hint)
        layout.addWidget(self.text_edit)
        layout.addWidget(self.textarea)
        layout.addWidget(self.checkbox)
        layout.addWidget(self.dropdown)
        row = QHBoxLayout()
        row.addWidget(self.image_pick)
        row.addWidget(self.image_clear)
        layout.addLayout(row)
        layout.addStretch(1)

        self.text_edit.editingFinished.connect(self._commit_text)
        self.textarea.installEventFilter(self)
        self.checkbox.toggled.connect(self._commit_checkbox)
        self.dropdown.currentTextChanged.connect(self._commit_dropdown)
        self.image_pick.clicked.connect(self._pick)
        self.image_clear.clicked.connect(self._clear_image)

        vm.selection_changed.connect(self._on_selection)
        vm.field_content_changed.connect(self._on_field)
        vm.field_props_changed.connect(self._on_field)
        vm.values_changed.connect(lambda: self._on_selection(self._fid))
        vm.template_changed.connect(lambda: self._on_selection(self._fid))
        self._show_none()

    def _on_selection(self, field_id) -> None:
        self._fid = field_id
        self._refresh()

    def _on_field(self, field_id: str) -> None:
        if field_id == self._fid:
            self._refresh()

    def _field(self):
        if self._fid is None or self._vm.template is None:
            return None
        return self._vm.template.get_field(self._fid)

    def _show_none(self) -> None:
        for w in (
            self.text_edit, self.textarea, self.checkbox, self.dropdown,
            self.image_pick, self.image_clear,
        ):
            w.hide()
        self.hint.show()

    def _refresh(self) -> None:
        field = self._field()
        if field is None or field.type in (FieldType.LABEL, FieldType.RECT, FieldType.LINE):
            self._show_none()
            return
        self.hint.hide()
        self._syncing = True
        try:
            value = self._vm.display_value(field.id)
            self.text_edit.setVisible(field.type in (FieldType.TEXT, FieldType.NUMBER))
            self.textarea.setVisible(field.type is FieldType.TEXTAREA)
            self.checkbox.setVisible(field.type is FieldType.CHECKBOX)
            self.dropdown.setVisible(field.type is FieldType.DROPDOWN)
            self.image_pick.setVisible(field.type is FieldType.IMAGE)
            self.image_clear.setVisible(field.type is FieldType.IMAGE)
            if field.type in (FieldType.TEXT, FieldType.NUMBER):
                self.text_edit.setText("" if value is None else str(value))
            elif field.type is FieldType.TEXTAREA:
                self.textarea.setPlainText("" if value is None else str(value))
            elif field.type is FieldType.CHECKBOX:
                self.checkbox.setChecked(bool(value))
            elif field.type is FieldType.DROPDOWN:
                options = list(field.options)
                if isinstance(value, str) and value and value not in options:
                    options = [value, *options]
                self.dropdown.clear()
                self.dropdown.addItems(options)
                if isinstance(value, str):
                    self.dropdown.setCurrentText(value)
        finally:
            self._syncing = False

    def _commit_text(self) -> None:
        if self._syncing or self._fid is None:
            return
        field = self._field()
        if field is None:
            return
        if field.type is FieldType.NUMBER:
            self._vm.set_number(self._fid, self.text_edit.text())
            self._refresh()
        else:
            self._vm.set_text(self._fid, self.text_edit.text())

    def _commit_textarea(self) -> None:
        if self._syncing or self._fid is None:
            return
        field = self._field()
        if field is None or field.type is not FieldType.TEXTAREA:
            return
        self._vm.set_text(self._fid, self.textarea.toPlainText())

    def eventFilter(self, obj, event) -> bool:
        if obj is self.textarea and event.type() == QEvent.Type.FocusOut:
            self._commit_textarea()
        return super().eventFilter(obj, event)

    def _commit_checkbox(self, checked: bool) -> None:
        if self._syncing or self._fid is None:
            return
        current = bool(self._vm.display_value(self._fid))
        if current != checked:
            self._vm.toggle_checkbox(self._fid)

    def _commit_dropdown(self, text: str) -> None:
        if self._syncing or self._fid is None or not text:
            return
        if not self._vm.set_dropdown(self._fid, text):
            self._refresh()

    def _pick(self) -> None:
        if self._fid is not None:
            self.image_pick_requested.emit(self._fid)

    def _clear_image(self) -> None:
        if self._fid is not None:
            self._vm.clear_image(self._fid)


class CharacterSheetFillDialog(QDialog):
    """Fill of one instance. Load before showing."""

    binding_changed = Signal()

    def __init__(
        self,
        instance_service: CharacterSheetInstanceService,
        sheet_service: CharacterSheetService,
        instance_id: int,
        parent: QWidget | None = None,
        run_locked: Callable[[Coroutine], Awaitable] | None = None,
        image_store: ImageStore | None = None,
        character_service=None,
        read_only: bool = False,
        theme=None,
    ) -> None:
        super().__init__(parent)
        self._instance_id = instance_id
        self._vm = CharacterSheetFillViewModel(instance_service, sheet_service)
        self._vm.set_read_only(read_only)
        self._force_closing = False
        self._closing = False
        self._run_locked = run_locked or _run_now
        self._image_store = image_store
        self._character_service = character_service
        self._theme = theme

        self.setWindowTitle("Лист")
        self.resize(1100, 800)

        self.palette = None
        self.rail = PageRail(self._vm, self, navigation_only=True)
        self.rail.setFixedWidth(_RAIL_WIDTH)
        self.canvas = CharacterSheetCanvas(
            self._vm, self, image_store=image_store, fill_mode=True
        )
        self.properties_panel = FillPropertiesPanel(self._vm, self)
        self.properties_panel.setFixedWidth(_PANEL_WIDTH)
        self.properties_panel.setEnabled(not read_only)

        self.save_button = QPushButton("Сохранить", self)
        self.save_button.clicked.connect(lambda: asyncio.ensure_future(self.save()))
        self.bind_button = QPushButton("Привязать…", self)
        self.bind_button.clicked.connect(lambda: asyncio.ensure_future(self._bind_character()))
        self.unbind_button = QPushButton("Отвязать", self)
        self.unbind_button.clicked.connect(lambda: asyncio.ensure_future(self._unbind_character()))

        self._menu_bar = QMenuBar(self)
        self.edit_menu = self._menu_bar.addMenu("Правка")
        self.undo_action = QAction("Отменить", self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self._vm.undo)
        self.redo_action = QAction("Повторить", self)
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.triggered.connect(self._vm.redo)
        self.edit_menu.addAction(self.undo_action)
        self.edit_menu.addAction(self.redo_action)
        self._sync_edit_actions()

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.rail)
        body.addWidget(self.canvas, 1)
        body.addWidget(self.properties_panel)

        bottom = QHBoxLayout()
        bottom.addWidget(self.bind_button)
        bottom.addWidget(self.unbind_button)
        bottom.addStretch(1)
        bottom.addWidget(self.save_button)

        outer = QVBoxLayout(self)
        # The chrome reaches the dialog edges so no OS-palette band frames it.
        # The canvas (a QGraphicsView) is deliberately not in the chrome rule
        # set: its scene renders untouched (W2b D5 — proxy widgets included).
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.chrome = QWidget()
        self.chrome.setObjectName("sheetFillChrome")  # identifier, not style
        outer.addWidget(self.chrome)
        layout = QVBoxLayout(self.chrome)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setMenuBar(self._menu_bar)
        layout.addLayout(body, 1)
        layout.addLayout(bottom)

        self.rail.page_selected.connect(self.canvas.scroll_to_page)
        self.canvas.visible_page_changed.connect(self._on_visible_page)
        self.canvas.image_field_double_clicked.connect(self._pick_image)
        self.properties_panel.image_pick_requested.connect(self._pick_image)
        self._vm.history_changed.connect(self._sync_edit_actions)
        if read_only:
            self.save_button.hide()
            self.bind_button.hide()
            self.unbind_button.hide()
            self._menu_bar.hide()
        self._apply_theme()

    def _apply_theme(self) -> None:
        """One attach point: the chrome container carries the whole sheet (D1).

        The canvas and its scene (proxy widgets included) stay off-skin (D5).
        """
        if self._theme is not None:
            attach_theme(self.chrome, self._theme)
            attach_theme(self._menu_bar, self._theme)
            self._theme.apply()

    def set_read_only(self, value: bool) -> None:
        self._vm.set_read_only(value)
        self.properties_panel.setEnabled(not value)
        self.save_button.setVisible(not value)
        self.bind_button.setVisible(not value)
        self.unbind_button.setVisible(not value)
        self._menu_bar.setVisible(not value)
        if not value:
            self._sync_bind_buttons()
        self._sync_edit_actions()
        self.canvas.update()

    async def load_instance(self, instance_id: int) -> None:
        self._instance_id = instance_id
        await self.load()

    @property
    def view_model(self) -> CharacterSheetFillViewModel:
        return self._vm

    async def load(self) -> None:
        await self._vm.load(self._instance_id)
        if self._closing:
            return
        self.setWindowTitle(self._vm.name)
        self._sync_bind_buttons()

    def set_name(self, name: str) -> None:
        self._vm.set_name(name)
        self.setWindowTitle(name)

    async def save(self) -> None:
        try:
            await self._run_locked(self._vm.save())
        except CharacterSheetInstanceError as exc:
            QMessageBox.warning(self, "Чар-листы", str(exc))
        except Exception as exc:
            log.error("character-sheet fill save failed: %s", exc, exc_info=True)
            QMessageBox.critical(
                self, "Ошибка", f"Не удалось сохранить лист: {exc}"
            )

    def force_close(self) -> None:
        self._force_closing = True
        self.close()
        self._force_closing = False

    def _teardown_vm_links(self) -> None:
        vm = self._vm
        signals = (
            vm.dirty_changed,
            vm.template_changed,
            vm.values_changed,
            vm.field_content_changed,
            vm.field_props_changed,
            vm.selection_changed,
            vm.inline_changed,
            vm.pages_changed,
            vm.current_page_changed,
            vm.history_changed,
            vm.template_changed,
        )
        for sig in signals:
            try:
                sig.disconnect()
            except (TypeError, RuntimeError):
                pass

    def closeEvent(self, event) -> None:
        if not self._force_closing and self._vm.dirty:
            answer = QMessageBox.question(
                self,
                "Несохранённые изменения",
                "В листе есть несохранённые правки. Закрыть без сохранения?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self._closing = True
        self._teardown_vm_links()
        super().closeEvent(event)

    def _on_visible_page(self, index: int) -> None:
        self._vm.set_current_page(index)

    def _sync_edit_actions(self) -> None:
        self.undo_action.setEnabled(self._vm.can_undo)
        self.redo_action.setEnabled(self._vm.can_redo)

    def _pick_image(self, field_id: str) -> None:
        if self._vm.read_only:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите изображение", "", _IMAGE_FILTER
        )
        if not path:
            return
        asyncio.ensure_future(self._store_and_set_image(field_id, path))

    async def _store_and_set_image(self, field_id: str, path: str) -> None:
        if self._image_store is None:
            QMessageBox.critical(
                self, "Ошибка", "Хранилище изображений этой игры недоступно."
            )
            return
        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            QMessageBox.warning(self, "Изображение", f"Файл не удалось прочитать: {exc}")
            return
        try:
            image_id = await self._run_locked(self._image_store.store(data))
        except ValueError:
            QMessageBox.warning(
                self, "Изображение", "Файл повреждён или не является изображением."
            )
            return
        if self._vm.template is None or self._vm.template.get_field(field_id) is None:
            return
        self._vm.set_image(field_id, image_id)

    def _sync_bind_buttons(self) -> None:
        bound = self._vm.character_id is not None
        self.unbind_button.setEnabled(bound)

    async def _bind_character(self) -> None:
        if self._character_service is None:
            return
        try:
            chars = list(await self._run_locked(self._character_service.get_all()))
        except Exception as exc:
            log.error("character list for bind failed: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Ошибка", str(exc))
            return
        if not chars:
            QMessageBox.warning(self, "Чар-листы", "Нет персонажей")
            return
        choices = character_choice_labels(chars)
        names = [label for label, _cid in choices]
        chosen, ok = QInputDialog.getItem(
            self, "Привязать персонажа", "Персонаж:", names, 0, False
        )
        if not ok or not chosen:
            return
        char_id = next((cid for label, cid in choices if label == chosen), None)
        if char_id is None:
            return
        try:
            await self._run_locked(self._vm.bind_character(char_id))
        except CharacterSheetInstanceError as exc:
            QMessageBox.warning(self, "Чар-листы", str(exc))
            return
        except Exception as exc:
            log.error("character-sheet bind failed: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Ошибка", str(exc))
            return
        self._sync_bind_buttons()
        self.binding_changed.emit()

    async def _unbind_character(self) -> None:
        if self._vm.character_id is None:
            return
        try:
            await self._run_locked(self._vm.unbind_character())
        except CharacterSheetInstanceError as exc:
            QMessageBox.warning(self, "Чар-листы", str(exc))
            return
        except Exception as exc:
            log.error("character-sheet unbind failed: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Ошибка", str(exc))
            return
        self._sync_bind_buttons()
        self.binding_changed.emit()
