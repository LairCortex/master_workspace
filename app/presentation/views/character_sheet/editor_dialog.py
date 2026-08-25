"""Character sheet editor window: toolbar + palette | canvas | properties
(tasks 6.1–6.4, 6.6). Save/export are coroutines run through the qasync
event loop (the app-wide pattern)."""
from __future__ import annotations

import asyncio
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.application.services.character_sheet_service import CharacterSheetService
from app.domain.enums.sheet_orientation import SheetOrientation, a4_size
from app.presentation.viewmodels.character_sheet_viewmodel import (
    CharacterSheetViewModel,
    DEFAULT_SNAP_STEP,
    _DEFAULT_SIZES,
)
from app.presentation.views.character_sheet.canvas_view import SheetCanvas, SheetCanvasView
from app.presentation.views.character_sheet.items_palette import ItemsPalette
from app.presentation.views.character_sheet.properties_panel import PropertiesPanel

from app.presentation.views.character_sheet import pages_dialog as _pages


def make_pages_dialog(viewmodel, parent=None):
    """Factory (kept separate so tests can patch QMessageBox freely)."""
    return _pages.PagesDialog(viewmodel, parent)


class CharacterSheetEditorDialog(QDialog):
    def __init__(
        self,
        service: CharacterSheetService,
        sheet_id: int | None = None,
        name: str = "Новый лист",
        orientation: SheetOrientation = SheetOrientation.LANDSCAPE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._sheet_id = sheet_id
        self._new_name = name
        self._new_orientation = orientation
        self._vm = CharacterSheetViewModel(service, self)
        self._closing = False
        self._close_pending = False

        self.setWindowTitle("Редактор чар-листа")
        self.setMinimumSize(1100, 720)
        self._init_ui()
        if self._sheet_id is None:
            self._vm.create_new(self._new_name, self._new_orientation)
            self._refresh_canvas()
        else:
            asyncio.ensure_future(self._open())

    @property
    def vm(self) -> CharacterSheetViewModel:
        return self._vm

    # ── construction ──────────────────────────────────────────────────────

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.addLayout(self._build_toolbar())

        body = QHBoxLayout()
        self._palette = ItemsPalette()
        body.addWidget(self._palette)

        self._canvas = SheetCanvas(self._vm)
        self._canvas_view = SheetCanvasView(self._canvas)
        body.addWidget(self._canvas_view, 1)

        self._properties = PropertiesPanel(self._vm)
        self._properties.setFixedWidth(230)
        body.addWidget(self._properties)
        root.addLayout(body, 1)
        self._status = QLabel("")
        root.addWidget(self._status)

        # wiring
        self._vm.state_changed.connect(self._on_state_changed)
        self._vm.dirty_changed.connect(lambda _d: self._update_title())
        self._vm.can_undo_changed.connect(lambda can: self._undo_btn.setEnabled(can))
        self._vm.can_redo_changed.connect(lambda can: self._redo_btn.setEnabled(can))
        self._vm.status_message.connect(self._status.setText)
        self._palette.field_type_clicked.connect(self._on_palette_clicked)

        self._refresh_canvas()

    def _build_toolbar(self):
        bar = QHBoxLayout()

        def add_button(caption, slot, shortcut: str | None = None) -> QPushButton:
            button = QPushButton(caption)
            button.clicked.connect(slot)
            if shortcut:
                button.setShortcut(QKeySequence(shortcut))
            bar.addWidget(button)
            return button

        self.save_btn = add_button("Сохранить", self._on_save, "Ctrl+S")
        self.export_btn = add_button("Экспорт PDF", self._on_export)
        self._undo_btn = add_button("Отменить", self._vm.undo, "Ctrl+Z")
        self._redo_btn = add_button("Повторить", self._vm.redo, "Ctrl+Shift+Z")
        self._undo_btn.setEnabled(False)
        self._redo_btn.setEnabled(False)

        bar.addSpacing(12)
        bar.addWidget(QLabel("Сетка:"))
        self._grid_cb = QCheckBox()
        self._grid_cb.stateChanged.connect(self._on_grid_toggled)
        bar.addWidget(self._grid_cb)
        self._grid_spin = QSpinBox()
        self._grid_spin.setRange(5, 100)
        self._grid_spin.setValue(int(DEFAULT_SNAP_STEP))
        self._grid_spin.valueChanged.connect(self._on_grid_toggled)
        bar.addWidget(self._grid_spin)

        bar.addSpacing(12)
        bar.addWidget(QLabel("Ориентация:"))
        self._orientation_combo = QComboBox()
        self._orientation_combo.addItem("Альбомная", SheetOrientation.LANDSCAPE)
        self._orientation_combo.addItem("Книжная", SheetOrientation.PORTRAIT)
        self._orientation_combo.currentIndexChanged.connect(self._on_orientation_changed)
        bar.addWidget(self._orientation_combo)

        bar.addSpacing(12)
        self.add_page_btn = QPushButton("+ Страница")
        self.add_page_btn.clicked.connect(lambda: self._vm.add_page())
        bar.addWidget(self.add_page_btn)
        self.pages_btn = QPushButton("Страницы…")
        self.pages_btn.clicked.connect(self._on_pages_dialog)
        bar.addWidget(self.pages_btn)

        bar.addStretch(1)
        # zoom buttons (task 6.4)
        # the view is built after the toolbar — resolve lazily
        self.zoom_out_btn = QPushButton("−")
        self.zoom_out_btn.setFixedWidth(32)
        self.zoom_out_btn.clicked.connect(lambda: self._canvas_view.zoom_by(1 / 1.25))
        bar.addWidget(self.zoom_out_btn)
        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.setFixedWidth(32)
        self.zoom_in_btn.clicked.connect(lambda: self._canvas_view.zoom_by(1.25))
        bar.addWidget(self.zoom_in_btn)
        self.fit_btn = QPushButton("Вписать")
        self.fit_btn.clicked.connect(lambda: self._canvas_view.fit_to_window())
        bar.addWidget(self.fit_btn)
        return bar

    def _on_pages_dialog(self) -> None:
        make_pages_dialog(self._vm, self).exec()

    # ── loading ───────────────────────────────────────────────────────────

    async def _open(self) -> None:
        if not await self._vm.open(self._sheet_id):
            QMessageBox.critical(self, "Ошибка", "Шаблон не найден")
            self.reject()
            return
        self._sync_orientation_combo()
        self._update_title()
        self._refresh_canvas()

    # ── toolbar handlers ──────────────────────────────────────────────────

    def _on_palette_clicked(self, field_type) -> None:
        """Palette: field at the center of the page nearest the view center (D5)."""
        page_index = self._canvas.page_index_at_view_center(self._canvas_view)
        page_w, page_h = a4_size(self._vm.template.orientation)
        size_w, size_h = _DEFAULT_SIZES[field_type]
        x = max(0.0, (page_w - size_w) / 2)
        y = max(0.0, (page_h - size_h) / 2)
        self._vm.add_field(field_type, page_index, x, y)

    def _on_grid_toggled(self, *_args) -> None:
        self._vm.set_snap(self._grid_cb.isChecked(), float(self._grid_spin.value()))
        self._canvas.set_grid(self._grid_cb.isChecked(), float(self._grid_spin.value()))

    def _on_orientation_changed(self, index: int) -> None:
        orientation = self._orientation_combo.itemData(index)
        self._vm.set_orientation(orientation)

    def _sync_orientation_combo(self) -> None:
        mapping = {SheetOrientation.LANDSCAPE: 0, SheetOrientation.PORTRAIT: 1}
        index = mapping.get(self._vm.template.orientation, 0)
        self._orientation_combo.blockSignals(True)
        self._orientation_combo.setCurrentIndex(index)
        self._orientation_combo.blockSignals(False)

    def _on_save(self) -> None:
        asyncio.ensure_future(self._save())

    async def _save(self) -> None:
        if await self._vm.save():
            self._status.setText("")

    def _on_export(self) -> None:
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Экспорт PDF",
            f"{self._vm.template.name}.pdf",
            "PDF файлы (*.pdf)",
        )
        if not dest:
            return
        asyncio.ensure_future(self._export(dest))

    async def _export(self, dest: str) -> None:
        if await self._vm.export_pdf(Path(dest)):
            self._status.setText(f"PDF сохранён: {dest}")

    # ── keyboard ──────────────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:
        modifiers = event.modifiers()
        ctrl = modifiers & Qt.KeyboardModifier.ControlModifier
        shift = modifiers & Qt.KeyboardModifier.ShiftModifier
        if event.key() == Qt.Key.Key_Delete:
            self._delete_selected()
            event.accept()
            return
        if ctrl and event.key() == Qt.Key.Key_D:
            self._duplicate_selected()
            event.accept()
            return
        if ctrl and not shift and event.key() == Qt.Key.Key_Z:
            if self._vm.undo():
                event.accept()
                return
        if ctrl and shift and event.key() == Qt.Key.Key_Z:
            if self._vm.redo():
                event.accept()
                return
        if ctrl and event.key() == Qt.Key.Key_S:
            self._on_save()
            event.accept()
            return
        super().keyPressEvent(event)

    def _delete_selected(self) -> None:
        field_id = self._vm.selected_field_id
        if field_id:
            self._vm.remove_field(field_id)

    def _duplicate_selected(self) -> None:
        field_id = self._vm.selected_field_id
        if field_id:
            self._vm.duplicate_field(field_id)

    # ── refresh helpers ───────────────────────────────────────────────────

    def _on_state_changed(self) -> None:
        self._refresh_canvas()

    def _refresh_canvas(self) -> None:
        if not self._vm.is_ready:
            return  # an opened sheet is still loading asynchronously
        self._canvas.refresh()
        self._canvas.set_grid(self._grid_cb.isChecked(), float(self._grid_spin.value()))
        self._sync_orientation_combo()
        self._update_title()

    def _update_title(self) -> None:
        base = self._vm.template.name if self._vm.template is not None else "Лист"
        self.setWindowTitle(f"{base}{'*' if self._vm.dirty else ''} — редактор чар-листа")

    # ── close guard (6.6) ─────────────────────────────────────────────────

    def force_close(self) -> None:
        """Programmatic close that skips the unsaved-changes prompt (game
        switch / shutdown — the caller has already handled the question)."""
        self._closing = True
        self.close()

    def reject(self) -> None:
        if self._confirm_close():
            super().reject()

    def closeEvent(self, event) -> None:
        if self._confirm_close():
            self._canvas.clear()
            event.accept()
        else:
            event.ignore()

    def _confirm_close(self) -> bool:
        if self._closing or self._close_pending or not self._vm.dirty:
            return True
        self._close_pending = True
        answer = QMessageBox.question(
            self,
            "Несохранённые изменения",
            "Сохранить изменения перед закрытием?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            asyncio.ensure_future(self._save_and_close())
            return False  # close only after the async save finishes
        self._close_pending = False
        return answer == QMessageBox.StandardButton.No

    async def _save_and_close(self) -> None:
        if await self._vm.save():
            self._closing = True
            self._close_pending = False
            self.close()
        else:
            self._close_pending = False
