"""Character-sheet list dialog: create / open / rename / delete (non-modal).

Q3a (change port-sheet-list-preset-dialogs-qml-q3a, task 3.1, designs D1/D2/D5):
the frame and Esc stay native (``QDialog``); the whole content (the two tabs,
both lists, the button row) is a ``QQuickWidget`` island loading
``app/presentation/qml/SheetListRoot.qml``, skinned by the token palette — the
widgets content is gone, no flag, no second copy (precedent Q1/Q2.5a). The
external contract is unchanged: the ``open_requested``/
``open_instance_requested``/``renamed``/``instance_renamed`` signals, the
``set_open_sheet_id``/``set_open_instance_id``/``set_seated_ids`` methods, the
async ``refresh()`` and the ``preset_dialog`` property.

Division of labour (design D2):

* the island binds to :class:`SheetListViewModel` (``sheetListVm``) — the two
  row models, the current tab, per-tab selection and the ``canOpen/canRename/
  canDelete/presetButtonVisible`` flags — and reads colors from the token
  bridge (dialog-owned :class:`QmlPalette` pushed as ``islandPalette``, the
  launcher/timeline contract); both names are island-scoped because the shared
  engine's root context is global to all islands (see the context block in the
  constructor); it only calls the VM's sync slots
  and reports clicks through the argument-free root ``*Requested`` signals
  (the facade reads tab + selection back from the VM, like the retired
  ``_on_instances_tab``/``_selected_id`` helpers did from the widgets);
* every session-touching flow (create/open/rename/delete and the list
  refresh) is still a coroutine on the qasync loop wrapped in ``run_locked``
  — the application's session lock, since the shared AsyncSession must not be
  used by concurrent tasks; the native popups
  (``QInputDialog``/``QMessageBox``) stay Python-side (D5);
* the island marks «Открыть» through its root ``defaultButton``; the wrapper
  answers Enter by clicking that marker (D5).

Refresh lock contract (unchanged, review #12): ``refresh()`` itself does NOT
lock; its caller provides the lock — either explicitly
(``await self._run_locked(self.refresh())``, this dialog's own flows) or
because the calling task already runs under the application's session lock
(the app opens the list through ``_wiring._spawn``, which holds the lock for
the whole task). Never wrap ``refresh()`` in ``run_locked`` from a task that
already holds it: the ``asyncio.Lock`` is not reentrant, the inner task would
wait on the outer one forever (a hang, not an error).
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Coroutine

from PySide6.QtCore import QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QInputDialog,
    QMessageBox,
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
)
from app.presentation.qml import setup_qml_shell
from app.presentation.qml.engine import QML_IMPORT_PATH, island_context, load_island
from app.presentation.theme import get_default_theme
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.viewmodels.sheet_list_view_model import (
    TAB_INSTANCES,
    SheetListViewModel,
)
from app.presentation.views.character_sheet.preset_dialog import (
    CharacterSheetPresetDialog,
)

log = logging.getLogger(__name__)

ROOT_QML = str(Path(QML_IMPORT_PATH) / "SheetListRoot.qml")


async def _run_now(coro: Coroutine) -> Any:
    """Default ``run_locked``: no session lock (unit tests, no shared session)."""
    return await coro


class CharacterSheetListDialog(QDialog):
    """List of the current game's sheet templates (QML island inside QDialog).

    The availability rules (open the sheet open in the editor, delete the
    templates that still have sheets, «Создать из пресета…» only on the
    templates tab) live in :class:`SheetListViewModel` (design D2); QML binds
    them to the buttons' enabled/visible states, so the dialog itself keeps no
    widget flags.
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
        theme=None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._instance_service = instance_service
        # Mirrors of the blockers, kept readable for the wiring/tests the
        # widgets dialog exposed; the VM holds the flags they feed.
        self._open_sheet_id: int | None = None
        self._open_instance_id: int | None = None
        self._seated_ids: set[int] = set()
        self._instance_counts: dict[int, int] = {}
        self._run_locked = run_locked or _run_now
        # The island is skinned by the token bridge only, but the bridge still
        # needs a runtime — the widgets-era ``None`` falls back to the process
        # default, exactly like the other islands; invalid tokens (D7) keep it
        # off-skin there too.
        self._theme = theme if theme is not None else get_default_theme()

        self.setWindowTitle("Чар-листы")
        self.resize(420, 520)

        self._preset_dialog: CharacterSheetPresetDialog | None = None

        # VM + palette live for the dialog's whole life and are its children —
        # a context property is a raw pointer, so QML must never outlive them
        # (the launcher's seam).
        self.vm = SheetListViewModel(parent=self)

        layout = QVBoxLayout(self)
        # The island must reach the dialog edges: a default layout margin
        # would show the OS palette as a frame around the QML surface.
        layout.setContentsMargins(0, 0, 0, 0)

        # The island shares the one process-wide engine (spec qml-shell
        # «Движок один на приложение»); ``setup_qml_shell`` is idempotent, and
        # the reference keeps the engine alive under a live island.
        engine = setup_qml_shell(QApplication.instance(), self._theme)
        self._engine = engine
        self.quick = QQuickWidget(engine, self)
        self.quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        # Q3a apply-time correction, pinned empirically: a QQuickWidget built
        # on the shared engine reports the ENGINE's root context from
        # rootContext(), so a name written there is visible to — and owned by —
        # every island on the process engine. A dialog must not write into it
        # at all: when this one closes, the shared ``islandPalette`` entry it
        # had overwritten dies with the dialog and strands the timeline (and
        # every other live island) on the off-skin fallbacks. Both names go
        # into a dialog-owned child context instead, the seam the detail panel
        # and the newer dialog islands already use; the bridge is parented to
        # that context so the scene (a child created BEFORE it) always dies
        # first, and ``done()`` releases the island earlier anyway.
        self._palette = QmlPalette(self._theme, parent=self)
        self._context = island_context(
            engine, self, sheetListVm=self.vm, islandPalette=self._palette
        )
        self._palette.setParent(self._context)
        self._component = load_island(self.quick, self._context, ROOT_QML)
        assert self.quick.status() == QQuickWidget.Status.Ready, self.quick.errors()
        layout.addWidget(self.quick)

        self._root = self.quick.rootObject()
        self._wire_island()

    # ---- island -> facade wiring ------------------------------------------------

    def _wire_island(self) -> None:
        # Argument-free root signals (contract pinned by group 2): the tab and
        # the per-tab selection are read back from the VM below.
        root = self._root
        root.createRequested.connect(lambda: self._spawn(self._create_current()))
        root.presetRequested.connect(self._open_preset_dialog)
        root.openRequested.connect(lambda: self._spawn(self._open_current()))
        root.renameRequested.connect(lambda: self._spawn(self._rename_current()))
        root.deleteRequested.connect(lambda: self._spawn(self._delete_current()))
        root.closeRequested.connect(self.close)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — Qt API
        # Enter clicks the island's ``defaultButton`` marker (design D5) — the
        # migrated dialog answered Enter through «Открыть» and the marker
        # objectName pins that button. With nothing selected the open flow is
        # the same no-op the disabled widgets button used to be.
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            marker = (
                self._root.property("defaultButton") if self._root is not None else None
            )
            clicked = getattr(marker, "clicked", None) if marker is not None else None
            if clicked is not None:
                clicked.emit()
                return  # the marker owns Enter only when the island is up
        super().keyPressEvent(event)

    # -- wiring helpers -------------------------------------------------------

    @staticmethod
    def _spawn(coro) -> None:
        # Runs on the qasync event loop in the app; tests run the loop too.
        asyncio.ensure_future(coro)

    def set_open_sheet_id(self, sheet_id: int | None) -> None:
        """Mark the sheet that is open in the editor (delete becomes unavailable)."""
        self._open_sheet_id = sheet_id
        self.vm.set_open_sheet_id(sheet_id)

    def set_open_instance_id(self, instance_id: int | None) -> None:
        self._open_instance_id = instance_id
        self.vm.set_open_instance_id(instance_id)

    def set_seated_ids(self, instance_ids: set[int] | None) -> None:
        self._seated_ids = set(instance_ids or ())
        self.vm.set_seated_ids(instance_ids)

    @property
    def preset_dialog(self) -> CharacterSheetPresetDialog | None:
        """The open «Создать из пресета…» dialog (or None)."""
        return self._preset_dialog

    def _on_instances_tab(self) -> bool:
        return self.vm.current_tab == TAB_INSTANCES

    def _selected_id(self) -> int | None:
        return self.vm.selected_template_id

    def _selected_instance_id(self) -> int | None:
        return self.vm.selected_instance_id

    def _selected_name(self) -> str | None:
        return self.vm.selected_template_name

    def _selected_instance_name(self) -> str | None:
        return self.vm.selected_instance_name

    def _refresh_selection(self, sheet_id: int) -> None:
        self.vm.select_template_by_id(sheet_id)

    def _refresh_instance_selection(self, instance_id: int) -> None:
        self.vm.select_instance_by_id(instance_id)

    def _show_error(self, exc: Exception) -> None:
        if isinstance(exc, (CharacterSheetError, CharacterSheetInstanceError)):
            QMessageBox.warning(self, "Чар-листы", str(exc))
        else:
            log.error("character-sheet list action failed: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Ошибка", str(exc))

    # -- async flows ------------------------------------------------------------

    async def refresh(self) -> None:
        """Reload both row models from the DB into the VM (name-sorted, ids kept).

        The «лист — шаблон» labels and the sheets-per-template delete blocker
        are recomputed Python-side (D2); the counts mirror below stays for the
        guards the widgets dialog ran in its own flows (``delete_sheet``).
        """
        templates = list(await self._service.list_sheets())
        instances: list[Any] = []
        if self._instance_service is not None:
            instances = list(await self._instance_service.list_instances())
        self._instance_counts = {}
        for row in instances:
            self._instance_counts[row.template_id] = (
                self._instance_counts.get(row.template_id, 0) + 1
            )
        self.vm.set_rows(templates=templates, instances=instances)

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

    def _open_preset_dialog(self) -> None:
        """Show the non-modal preset picker (a child of this dialog)."""
        if self._preset_dialog is not None and self._preset_dialog.isVisible():
            self._preset_dialog.raise_()
            self._preset_dialog.activateWindow()
            return
        dialog = CharacterSheetPresetDialog(
            self._service, parent=self, run_locked=self._run_locked,
            theme=self._theme,
        )
        dialog.created.connect(self._on_preset_created)
        dialog.finished.connect(
            lambda _result, _d=dialog: self._preset_dialog_finished(_d)
        )
        self._preset_dialog = dialog
        dialog.show()

    def _preset_dialog_finished(self, dialog: CharacterSheetPresetDialog) -> None:
        if self._preset_dialog is dialog:
            self._preset_dialog = None
        # Release the island through the facade's own seam BEFORE deleteLater.
        # The deferred-delete cleanup then destroys a dialog whose QQuickWidget
        # has no live scene: without this, the deferred delete races the
        # dialog's parent-owned children — the QQuickWidget dies AFTER its
        # sibling ``vm`` (both children of the dialog), the still-loaded scene
        # re-evaluates bindings against the dead context objects mid-sweep and
        # Qt aborts («shared QObject was deleted directly»). The widgets-era
        # handler could delete directly because QListWidget held no declarative
        # bindings. ``_release_island`` is idempotent (setSource(QUrl()) twice
        # is a no-op), so dialogs that also went through done() are fine.
        dialog._release_island()
        dialog.deleteLater()

    def _on_preset_created(self, sheet_id: int) -> None:
        self._spawn(self._preset_created_flow(sheet_id))

    async def _preset_created_flow(self, sheet_id: int) -> None:
        # The snapshot is a regular template: refresh, select the new row and
        # let the application open its Design (``open_requested`` carries the
        # usual dirty-confirm rules for an already-open editor).
        await self._run_locked(self.refresh())
        self._refresh_selection(sheet_id)
        self.open_requested.emit(sheet_id)

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
        # The migrated ``tabs.setCurrentIndex(1)``: the VM is the tab's single
        # owner, QML mirrors ``vm.currentTab`` into the TabBar.
        self.vm.setCurrentTab(TAB_INSTANCES)
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
        if instance_id in self._seated_ids:
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

    # ---- island teardown (the Q1-accepted launcher pattern) ---------------

    def _release_island(self) -> None:
        self.quick.setSource(QUrl())

    def done(self, result: int) -> None:  # QDialog API: accept/reject/close-event
        """Release the island against its VM/palette before the dialog dies.

        ``QDialog.closeEvent`` calls ``reject()`` and both accept/reject funnel
        through ``done()``. Clearing the QML source tears the island down while
        ``vm``/``_palette`` (children of the dialog) are still alive, so its
        bindings never observe a half-destroyed context.

        The release is deferred one loop turn: every QML-originated close —
        «Закрыть» click included — lands here while the island's own
        ``onClicked`` handler is still on the stack, and destroying the scene
        synchronously there is fatal («Object destroyed while one of its QML
        signal handlers is in progress»). The one-shot is bound to ``self``:
        it runs when the JS stack has unwound and never after the dialog is
        gone.
        """
        QTimer.singleShot(0, self, self._release_island)
        super().done(result)
