"""Fill window: read-only layout canvas + value map as a QML island under the
native «Правка» menu (design D3/D4).

Q3b (change port-character-sheet-canvas-qml-q3b, task 3.3): the frame, Esc
and the menu stay native; the whole content (navigation rail, canvas in fill
mode, value panel, action row) is a ``QQuickWidget`` island loading
``app/presentation/qml/SheetFillRoot.qml`` — the widgets rail and
FillPropertiesPanel are gone (no flag, no second copy). External contract
unchanged: ``binding_changed``, ``view_model``, ``load``/``load_instance``,
``set_name``, ``save``, ``force_close``, ``set_read_only``, dirty
``closeEvent``; ``main.py`` imports this module verbatim.

Popup/menu rules (spec qml-shell): character binding stays a native
``QInputDialog``; image pick a ``QFileDialog``; the canvas dropdown bridge is
answered by a native ``QMenu`` in the field's global coordinates here (the
island only reports fieldId + scene position, design D9).
"""
from __future__ import annotations

import asyncio
import logging
import warnings
from pathlib import Path
from typing import Any, Awaitable, Callable, Coroutine

from PySide6.QtCore import QPoint, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QKeyEvent, QKeySequence
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QMenu,
    QMenuBar,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from app.application.services.character_sheet_instance_service import (
    CharacterSheetInstanceError,
    CharacterSheetInstanceService,
)
from app.application.services.character_sheet_service import CharacterSheetService
from app.infrastructure.images.store import ImageStore
from app.presentation.qml import setup_qml_shell
from app.presentation.qml.engine import QML_IMPORT_PATH, island_context, load_island
from app.presentation.qml.sheet_image_provider import bind_sheet_image_store
from app.presentation.qml.tooltip_shim import install_island_tooltips
from app.presentation.theme import get_default_theme
from app.presentation.theme.catalog import attach_theme
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.viewmodels.character_sheet_fill_viewmodel import (
    CharacterSheetFillViewModel,
)

log = logging.getLogger(__name__)

ROOT_QML = str(Path(QML_IMPORT_PATH) / "SheetFillRoot.qml")

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
        self._theme = theme if theme is not None else get_default_theme()
        # the native option-choice menu of a fill dropdown field (the retired
        # canvas._dropdown_menu seam, same attribute name)
        self.dropdown_menu: QMenu | None = None

        self.setWindowTitle("Лист")
        self.resize(1100, 800)

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
        if read_only:
            self._menu_bar.hide()

        outer = QVBoxLayout(self)
        # The island reaches the dialog edges (its surface comes from the
        # token palette); only the menu is chrome.
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.setMenuBar(self._menu_bar)
        outer.addWidget(self._build_island())
        # the current game ImageStore feeds ``image://sheet`` (D7): bound for
        # the live engine's provider and remembered for later registrations
        bind_sheet_image_store(self._image_store)

    # ── island seam (the Q3a dialog pattern) ─────────────────────────────────

    def _build_island(self) -> QQuickWidget:
        self._engine = setup_qml_shell(QApplication.instance(), self._theme)
        self.quick = QQuickWidget(self._engine, self)
        self.quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        # the VM as the island's DECLARED property, the bridge in a
        # dialog-owned context (never an engine-wide name for one dialog —
        # the Q3a lesson)
        self._palette = QmlPalette(self._theme, parent=self)
        self._context = island_context(
            self._engine, self, islandPalette=self._palette
        )
        self._palette.setParent(self._context)
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
        root.saveRequested.connect(lambda: asyncio.ensure_future(self.save()))
        root.bindRequested.connect(
            lambda: asyncio.ensure_future(self._bind_character())
        )
        root.unbindRequested.connect(
            lambda: asyncio.ensure_future(self._unbind_character())
        )
        root.imagePickRequested.connect(self._pick_image)
        # the native-QMenu bridge (spec: island menus are native popups)
        root.dropdownRequested.connect(self._popup_dropdown)
        self._vm.history_changed.connect(self._sync_edit_actions)
        self._sync_bind_buttons()

    # ── public API (unchanged) ───────────────────────────────────────────────

    def set_read_only(self, value: bool) -> None:
        """The master-view switch: the VM flag drives the island (panel
        enabled, action buttons) through its bindings; the native menu is the
        facade's own widget."""
        self._vm.set_read_only(value)
        self._menu_bar.setVisible(not value)
        if not value:
            self._sync_bind_buttons()
        self._sync_edit_actions()

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
            vm.read_only_changed,
        )
        # QML Connections receivers are C++-side: a blanket disconnect attempts
        # more than Python can reach (shiboken's RuntimeWarning) and removes
        # exactly what the old widgets teardown removed — its Python lambdas;
        # the declarative links die with the released scene instead.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
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

    # ── island teardown (the launcher/list-dialog pattern) ──────────────────

    def _release_island(self) -> None:
        import shiboken6

        if shiboken6.isValid(self.quick):
            self.quick.setSource(QUrl())

    def done(self, result: int) -> None:  # QDialog API: accept/reject/close-event
        # Deferred scene release before the dialog's children go away (the
        # Q3a list-dialog comment applies verbatim).
        QTimer.singleShot(0, self, self._release_island)
        super().done(result)

    # -- native bridges --------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — Qt API
        # Enter clicks the island's «Сохранить» marker when the island did not
        # consume the key (a focused inline editor accepts Enter first). In
        # read-only there is no marker click to make (the button is hidden).
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not self._vm.read_only:
            marker = (
                self._root.property("defaultButton") if self._root is not None else None
            )
            clicked = getattr(marker, "clicked", None) if marker is not None else None
            if clicked is not None:
                clicked.emit()
                return
        super().keyPressEvent(event)

    def _popup_dropdown(self, field_id: str, x: float, y: float) -> None:
        """The native option menu in the field's coordinates (the retired
        canvas._popup_dropdown, branch-for-branch: orphan current disabled at
        top, options trigger ``vm.set_dropdown``)."""
        if self.dropdown_menu is not None:
            self.dropdown_menu.close()
            self.dropdown_menu.deleteLater()
            self.dropdown_menu = None
        template = self._vm.template
        field = template.get_field(field_id) if template is not None else None
        if field is None:
            return
        menu = QMenu(self)
        current = self._vm.display_value(field_id)
        options = list(field.options)
        if isinstance(current, str) and current and current not in options:
            orphan = menu.addAction(current)
            orphan.setEnabled(False)
            menu.addSeparator()
        for opt in options:
            action = menu.addAction(opt)
            action.triggered.connect(
                lambda _c=False, o=opt, fid=field_id: self._vm.set_dropdown(fid, o)
            )
        self.dropdown_menu = menu
        menu.popup(self.quick.mapToGlobal(QPoint(int(x), int(y))))

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
        # the migrated unbind-button enable rule, pushed over the island's
        # declared bridge (the VM fires no bind signal)
        bound = self._vm.character_id is not None
        if self._root is not None:
            self._root.setProperty("characterBound", bool(bound))

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
