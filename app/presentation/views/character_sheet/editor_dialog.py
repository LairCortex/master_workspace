"""The character-sheet editor window: palette | rail | canvas | properties.

One non-modal QDialog per sheet. The ViewModel (one per window) is the only
layout buffer; the window adds the explicit «Сохранить» action and a
close-with-unsaved-changes confirmation. A rename in the list window reaches
this one through :meth:`set_name` — it changes the title and never touches
the dirty flag (a rename is not a layout edit).

A-playable additions (design D1–D7): the page rail (its clicks scroll the
canvas, the visible page becomes the current one), the template-wide orientation
switch (clamps, never scales), and the image-field file pick — the file goes
through the game's ``ImageStore`` like the entity cards (one pipeline).
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Coroutine

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.application.services.character_sheet_service import (
    CharacterSheetError,
    CharacterSheetService,
)
from app.domain.character_sheet_pdf import write_sheet_pdf
from app.domain.entities.character_sheet import (
    ORIENTATION_LANDSCAPE,
    ORIENTATION_PORTRAIT,
    SheetTemplate,
)
from app.domain.enums.field_type import FieldType
from app.infrastructure.images.store import ImageStore

log = logging.getLogger(__name__)
from app.presentation.viewmodels.character_sheet_viewmodel import (
    CharacterSheetViewModel,
)
from app.presentation.views.character_sheet.canvas import CharacterSheetCanvas
from app.presentation.views.character_sheet.page_rail import PageRail
from app.presentation.views.character_sheet.palette import SheetPalette
from app.presentation.views.character_sheet.properties_panel import (
    SheetPropertiesPanel,
)

_PALETTE_WIDTH = 120
_RAIL_WIDTH = 160
_PANEL_WIDTH = 260

_IMAGE_FILTER = "Изображения (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;Все файлы (*)"


def _safe_disconnect(sig) -> None:
    try:
        sig.disconnect()
    except (TypeError, RuntimeError):
        pass


async def _run_now(coro: Coroutine) -> Any:
    """Default ``run_locked``: no session lock (unit tests, no shared session)."""
    return await coro


class CharacterSheetEditorDialog(QDialog):
    """Editor of one sheet template. Load the sheet before showing it.

    ``run_locked`` wraps the session-touching part of ``save()`` and the
    image ingest in the application's session lock (the shared AsyncSession
    is not safe for concurrent tasks). Unit tests pass nothing and the
    coroutines run bare.
    """

    saved = Signal()

    def __init__(
        self,
        service: CharacterSheetService,
        sheet_id: int,
        parent: QWidget | None = None,
        run_locked: Callable[[Coroutine], Awaitable] | None = None,
        image_store: ImageStore | None = None,
    ) -> None:
        super().__init__(parent)
        self._sheet_id = sheet_id
        self._vm = CharacterSheetViewModel(service)
        self._force_closing = False
        self._closing = False
        self._run_locked = run_locked or _run_now
        self._image_store = image_store

        self.setWindowTitle("Чар-лист")
        self.resize(1280, 800)

        self.palette = SheetPalette(self)
        self.palette.setFixedWidth(_PALETTE_WIDTH)
        self.rail = PageRail(self._vm, self)
        self.rail.setFixedWidth(_RAIL_WIDTH)
        self.canvas = CharacterSheetCanvas(self._vm, self, image_store=image_store)
        self.properties_panel = SheetPropertiesPanel(self._vm, self)
        self.properties_panel.setFixedWidth(_PANEL_WIDTH)

        self.orientation_combo = QComboBox(self)
        self.orientation_combo.addItem("Книжная", ORIENTATION_PORTRAIT)
        self.orientation_combo.addItem("Альбомная", ORIENTATION_LANDSCAPE)

        self.save_button = QPushButton("Сохранить", self)
        self.save_button.clicked.connect(lambda: asyncio.ensure_future(self.save()))
        self.export_pdf_button = QPushButton("Экспорт в PDF…", self)
        self.export_pdf_button.clicked.connect(
            lambda: asyncio.ensure_future(self.export_pdf())
        )

        self.snap_check = self.properties_panel.snap_check
        self.bring_front_button = self.properties_panel.bring_front_button
        self.send_back_button = self.properties_panel.send_back_button

        self._menu_bar = QMenuBar(self)
        self.edit_menu = self._menu_bar.addMenu("Правка")
        self.undo_action = QAction("Отменить", self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self._vm.undo)
        self.redo_action = QAction("Повторить", self)
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.triggered.connect(self._vm.redo)
        self.copy_action = QAction("Копировать", self)
        self.copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        self.copy_action.triggered.connect(self._vm.copy)
        self.paste_action = QAction("Вставить", self)
        self.paste_action.setShortcut(QKeySequence.StandardKey.Paste)
        self.paste_action.triggered.connect(self._on_paste)
        self.duplicate_action = QAction("Дублировать", self)
        self.duplicate_action.setShortcut(QKeySequence("Ctrl+D"))
        self.duplicate_action.triggered.connect(self._vm.duplicate)
        for action in (
            self.undo_action, self.redo_action, self.copy_action,
            self.paste_action, self.duplicate_action,
        ):
            self.edit_menu.addAction(action)
        self._sync_edit_actions()

        top = QHBoxLayout()
        top.addWidget(QLabel("Ориентация:", self))
        top.addWidget(self.orientation_combo)
        top.addStretch(1)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.palette)
        body.addWidget(self.rail)
        body.addWidget(self.canvas, 1)
        body.addWidget(self.properties_panel)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(self.export_pdf_button)
        bottom.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setMenuBar(self._menu_bar)
        layout.addLayout(top)
        layout.addLayout(body, 1)
        layout.addLayout(bottom)

        self.palette.tool_requested.connect(self._vm.set_tool)
        # one-shot placement resets the tool to the pointer in the VM; the
        # palette buttons must follow that (D7), not stay on the place tool
        self._vm.tool_changed.connect(self.palette.set_active_tool)
        # rail click → the canvas scrolls to that sheet (D1)
        self.rail.page_selected.connect(self.canvas.scroll_to_page)
        # the sheet with the largest visible area becomes the current page
        self.canvas.visible_page_changed.connect(self._on_visible_page)
        # orientation: one per template, clamps without scaling (D4)
        self.orientation_combo.currentIndexChanged.connect(self._on_orientation)
        self._vm.orientation_changed.connect(self._sync_orientation)
        # image field: double-click on the canvas or the panel button
        self.canvas.image_field_double_clicked.connect(self._pick_image)
        self.properties_panel.image_pick_requested.connect(self._pick_image)
        self._vm.history_changed.connect(self._sync_edit_actions)
        self._vm.selection_changed.connect(lambda _fid: self._sync_edit_actions())
        self._vm.clipboard_changed.connect(self._sync_edit_actions)

    # -- data -----------------------------------------------------------------

    @property
    def view_model(self) -> CharacterSheetViewModel:
        return self._vm

    async def load(self) -> None:
        """Load the sheet into the VM and set the window title from its name.

        If ``closeEvent`` ran while the load was in flight (the user closed the
        window early), the C++ widget may already be queued for
        ``deleteLater`` — the title is then not touched.
        """
        await self._vm.load(self._sheet_id)
        if self._closing:
            return
        template = self._vm.template
        self.setWindowTitle(template.name)
        self._sync_orientation()

    def set_name(self, name: str) -> None:
        """External rename from the list window: title only, dirty untouched."""
        if self._vm.template is None:
            return
        self._vm.template.name = name
        self.setWindowTitle(name)

    # -- actions ---------------------------------------------------------------

    async def save(self) -> None:
        """Explicit save: write the layout, clear the dirty flag.

        Failures are surfaced (RU message, dirty flag kept) instead of being
        dropped into an unawaited future.
        """
        try:
            await self._run_locked(self._vm.save())
        except CharacterSheetError as exc:
            QMessageBox.warning(self, "Чар-листы", str(exc))
            return
        except Exception as exc:
            log.error("character-sheet save failed: %s", exc, exc_info=True)
            QMessageBox.critical(
                self, "Ошибка", f"Не удалось сохранить шаблон: {exc}"
            )
            return
        self.saved.emit()

    async def export_pdf(self) -> None:
        """Picker + write of the current canvas (including unsaved edits)."""
        template = self._vm.template
        if template is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт в PDF", f"{template.name}.pdf", "PDF (*.pdf)"
        )
        if not path:
            return
        images = await self._run_locked(self._collect_image_bytes(template))
        try:
            write_sheet_pdf(template, Path(path), images)
        except OSError as exc:
            QMessageBox.critical(self, "Ошибка", f"Не удалось записать PDF: {exc}")

    async def _collect_image_bytes(self, template: SheetTemplate) -> dict[int, bytes]:
        store = self._image_store
        out: dict[int, bytes] = {}
        if store is None:
            return out
        ids = {
            field.image_id
            for page in template.pages
            for field in page.fields
            if field.type is FieldType.IMAGE and field.image_id is not None
        }
        for image_id in ids:
            path = await store.original_file_path(image_id)
            if path is None:
                path = await store.preview_file_path(image_id)
            if path is None:
                continue
            try:
                out[image_id] = Path(path).read_bytes()
            except OSError:
                continue
        return out

    def force_close(self) -> None:
        """Close without the dirty prompt (application shutdown / game switch)."""
        self._force_closing = True
        self.close()
        self._force_closing = False

    def _teardown_vm_links(self) -> None:
        """Sever every ViewModel → view signal connection.

        ``load`` / ``save`` are coroutines that can still be in flight when the
        window closes (e.g. closed mid-load). Their ``deleteLater`` defers the
        C++ destruction of the canvas / rail / panel past the next emit, so an
        emit landing on an already-deleted widget raises ``RuntimeError`` in the
        event loop. The views live exactly as long as this dialog, so
        disconnecting the (one-per-window) VM's signals on close is safe and
        makes the in-flight mutations no-ops instead of crashes.
        """
        vm = self._vm
        signals = (
            vm.dirty_changed,
            vm.template_changed,
            vm.field_added,
            vm.field_removed,
            vm.field_geometry_changed,
            vm.field_content_changed,
            vm.field_font_changed,
            vm.field_props_changed,
            vm.selection_changed,
            vm.tool_changed,
            vm.inline_changed,
            vm.pages_changed,
            vm.current_page_changed,
            vm.orientation_changed,
            vm.history_changed,
            vm.snap_changed,
            vm.clipboard_changed,
        )
        for sig in signals:
            _safe_disconnect(sig)

    def closeEvent(self, event) -> None:
        if (
            not self._force_closing
            and self._vm.template is not None
            and self._vm.dirty
        ):
            answer = QMessageBox.question(
                self,
                "Несохранённые изменения",
                "В макете есть несохранённые правки. Закрыть без сохранения?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self._closing = True  # the window is going away (a close in flight marks this)
        self._teardown_vm_links()
        super().closeEvent(event)

    # -- A-playable: orientation / visible page / image pick --------------------

    def _sync_orientation(self, orientation: str | None = None) -> None:
        if orientation is None:
            template = self._vm.template
            if template is None:
                return
            orientation = template.orientation
        index = self.orientation_combo.findData(orientation)
        if index < 0:
            index = 0
        self.orientation_combo.blockSignals(True)
        try:
            self.orientation_combo.setCurrentIndex(index)
        finally:
            self.orientation_combo.blockSignals(False)

    def _on_orientation(self, _index: int) -> None:
        self._vm.set_orientation(self.orientation_combo.currentData())

    def _on_visible_page(self, index: int) -> None:
        self._vm.set_current_page(index)

    def _on_paste(self) -> None:
        center = self.canvas.visible_page_center(self._vm.current_page_index)
        self._vm.paste(visible_center=center)

    def _sync_edit_actions(self) -> None:
        self.undo_action.setEnabled(self._vm.can_undo)
        self.redo_action.setEnabled(self._vm.can_redo)
        has_sel = bool(self._vm.selected_ids)
        self.copy_action.setEnabled(has_sel)
        self.duplicate_action.setEnabled(has_sel)
        self.paste_action.setEnabled(self._vm.has_clipboard)
        self.bring_front_button.setEnabled(has_sel)
        self.send_back_button.setEnabled(has_sel)

    def _pick_image(self, field_id: str) -> None:
        """File dialog first (sync UI), then the ingest on the loop (D6/D3:
        the same ImageStore pipeline as the entity cards)."""
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
            # undecodable file: the field stays empty, the error is visible
            QMessageBox.warning(
                self, "Изображение", "Файл повреждён или не является изображением."
            )
            return
        if self._vm.template is None or self._vm.template.get_field(field_id) is None:
            return  # the field (or the page) vanished behind the dialog
        self._vm.set_image_id(field_id, image_id)
