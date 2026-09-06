"""Character-sheet editor window: DESIGN content as a QML island under the
native «Правка» menu.

Q3b (change port-character-sheet-canvas-qml-q3b, task 3.3, designs D1/D6/D9):
the frame, Esc and the menu stay native (``QDialog`` + ``QMenuBar``); the
whole content (palette, page rail, canvas, property panel, action row) is a
``QQuickWidget`` island loading ``app/presentation/qml/SheetEditorRoot.qml``.
The widgets content (palette.py / page_rail.py / properties_panel.py /
canvas.py) is gone — no flag, no second copy (precedent Q1/Q2.5a/Q3a). The
external contract is unchanged: ``saved``, ``view_model``, ``load``,
``set_name``, ``save``, ``export_pdf``, ``force_close``, the dirty
``closeEvent`` — ``app/main.py`` imports this module verbatim.

Division of labour (D1):

* the island talks to the design ViewModel through its declared ``vm``
  property only (setInitialProperties — the shared engine's root context is
  global, the Q3a lesson); geometry, snapping, undo land on the VM's sync
  entrances exactly as the widgets did;
* every session/popup flow stays on this facade: save under ``run_locked``
  with ``QMessageBox`` error surfaces, the PDF picker (``QFileDialog``), the
  image ingest (ImageStore), the delete-page confirm (``QMessageBox``), the
  paste position (the island's canvas answers its ``visibleCenter`` through
  the ``pasteRequested`` bridge);
* Enter clicks the island's ``defaultButton`` marker («Сохранить») — but only
  when the island did not consume Enter itself (inline field editing owns the
  key while focused; keys the Quick scene does not accept propagate here).
"""
from __future__ import annotations

import asyncio
import logging
import warnings
from pathlib import Path
from typing import Any, Awaitable, Callable, Coroutine

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QAction, QKeyEvent, QKeySequence
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QMenuBar,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from app.application.services.character_sheet_service import (
    CharacterSheetError,
    CharacterSheetService,
)
from app.domain.character_sheet_pdf import write_sheet_pdf
from app.domain.entities.character_sheet import SheetTemplate
from app.domain.enums.field_type import FieldType
from app.infrastructure.images.store import ImageStore
from app.presentation.qml import setup_qml_shell
from app.presentation.qml.engine import QML_IMPORT_PATH, island_context, load_island, release_island
from app.presentation.qml.sheet_image_provider import bind_sheet_image_store
from app.presentation.qml.tooltip_shim import install_island_tooltips
from app.presentation.theme import get_default_theme
from app.presentation.theme.catalog import attach_theme
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.viewmodels.character_sheet_viewmodel import (
    CharacterSheetViewModel,
)

log = logging.getLogger(__name__)

ROOT_QML = str(Path(QML_IMPORT_PATH) / "SheetEditorRoot.qml")

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
        theme=None,
    ) -> None:
        super().__init__(parent)
        self._sheet_id = sheet_id
        self._vm = CharacterSheetViewModel(service)  # kept alive by this dialog
        self._force_closing = False
        self._closing = False
        self._run_locked = run_locked or _run_now
        self._image_store = image_store
        # The island is skinned by the token bridge only; the widgets-era
        # ``None`` falls back to the process default (the Q3a seam).
        self._theme = theme if theme is not None else get_default_theme()

        self.setWindowTitle("Чар-лист")
        self.resize(1280, 800)

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

        outer = QVBoxLayout(self)
        # The island reaches the dialog edges so no OS-palette band frames it
        # (its surface comes from the token palette). Only the menu is chrome.
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.setMenuBar(self._menu_bar)
        outer.addWidget(self._build_island())
        # the current game ImageStore feeds ``image://sheet`` (D7): bound for
        # the live engine's provider and remembered for later registrations
        bind_sheet_image_store(self._image_store)

    # ── island seam (the Q3a dialog pattern) ─────────────────────────────────

    def _build_island(self) -> QQuickWidget:
        # The one process-wide engine (spec «Движок один на приложение»);
        # ``setup_qml_shell`` is idempotent and the reference keeps it alive.
        self._engine = setup_qml_shell(QApplication.instance(), self._theme)
        self.quick = QQuickWidget(self._engine, self)
        self.quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        # The VM goes in as the root's DECLARED property; the token bridge —
        # which nested library components look up by name — into the dialog's
        # own context. Neither reaches the shared engine root context, whose
        # names are one global slot per island: the facade that writes last
        # owns it and nulls it for everyone when it dies (the Q3a lesson,
        # pinned in list_dialog.py).
        self._palette = QmlPalette(self._theme, parent=self)
        self._context = island_context(
            self._engine, self, islandPalette=self._palette
        )
        self._palette.setParent(self._context)
        # Native tooltip display for the island chrome (Q2.5a D9): the bridge
        # is parented to the island (raw-pointer context property).
        self._tooltip_bridge = install_island_tooltips(self.quick, self._context)
        self._component = load_island(
            self.quick, self._context, ROOT_QML, {"vm": self._vm}
        )
        assert self.quick.status() == QQuickWidget.Status.Ready, self.quick.errors()
        self._root = self.quick.rootObject()
        self._wire_island()
        if self._theme is not None:
            attach_theme(self._menu_bar, self._theme)
            self._theme.apply()
        return self.quick

    def _wire_island(self) -> None:
        root = self._root
        root.saveRequested.connect(
            lambda: asyncio.ensure_future(self.save())
        )
        root.exportPdfRequested.connect(
            lambda: asyncio.ensure_future(self.export_pdf())
        )
        root.imagePickRequested.connect(self._pick_image)
        # the delete-page confirm is a native QMessageBox (D1)
        root.pageRemoveRequested.connect(self._confirm_page_remove)
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

    def set_name(self, name: str) -> None:
        """External rename from the list window: title only, dirty untouched."""
        if self._vm.template is None:
            return
        self._vm.template.name = name
        self.setWindowTitle(name)

    # -- island bridges ---------------------------------------------------------

    def _on_paste(self) -> None:
        # The migrated canvas.visible_page_center seam: ask the island, read
        # the canvas' answer straight back (the emit runs QML synchronously).
        page = self._vm.current_page_index
        self._root.pasteRequested.emit(page)
        center = self._root.property("pasteCenterOut")
        point = None
        if center is not None:
            x = center.x() if hasattr(center, "x") else center["x"]
            y = center.y() if hasattr(center, "y") else center["y"]
            if x >= 0 and y >= 0:
                point = (float(x), float(y))
        self._vm.paste(visible_center=point)

    def _confirm_page_remove(self, index: int) -> None:
        """The rail's «−» (the retired page_rail._delete_page, verbatim rules)."""
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

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — Qt API
        # Enter clicks the island's «Сохранить» marker — unless the island
        # consumed the key first: a focused inline editor accepts Enter and
        # the event never gets here (design D1, the Q3a marker pattern).
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            marker = (
                self._root.property("defaultButton") if self._root is not None else None
            )
            clicked = getattr(marker, "clicked", None) if marker is not None else None
            if clicked is not None:
                clicked.emit()
                return
        super().keyPressEvent(event)

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
        window closes (e.g. closed mid-load). The island's Connections objects
        hold receivers bound to scene items; ``deleteLater`` defers the C++
        destruction past the next emit, so an emit landing on an already-deleted
        item raises ``RuntimeError`` in the event loop. The views live exactly
        as long as this dialog, so disconnecting the (one-per-window) VM's
        signals on close is safe and makes in-flight mutations no-ops.
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
        # QML Connections receivers are C++-side: a blanket Python disconnect
        # attempts more than it can reach (shiboken's RuntimeWarning); the
        # declarative links die with the released scene instead.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
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

    # ── island teardown (the Q1-accepted launcher pattern, as in list_dialog) ──

    def _release_island(self) -> None:
        release_island(self.quick)

    def done(self, result: int) -> None:  # QDialog API: accept/reject/close-event
        """Release the island against its VM/palette before the dialog dies.

        The release is deferred one loop turn: a QML-originated close lands
        here while the island's own handler is still on the stack, and
        destroying the scene synchronously there is fatal. One-shot bound to
        ``self`` — it runs when the JS stack unwound and never after the
        dialog is gone (the list_dialog Q3a precedent, word for word).
        """
        QTimer.singleShot(0, self, self._release_island)
        super().done(result)

    def _sync_edit_actions(self) -> None:
        self.undo_action.setEnabled(self._vm.can_undo)
        self.redo_action.setEnabled(self._vm.can_redo)
        has_sel = bool(self._vm.selected_ids)
        self.copy_action.setEnabled(has_sel)
        self.duplicate_action.setEnabled(has_sel)
        self.paste_action.setEnabled(self._vm.has_clipboard)

    # -- image field: the file bridge (D6, the same pipeline as entity cards) ---

    def _pick_image(self, field_id: str) -> None:
        """File dialog first (sync UI), then the ingest on the loop."""
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
