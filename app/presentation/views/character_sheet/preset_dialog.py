"""«Создать из пресета…» dialog (add-character-sheet-c, design D5).

Q3a (change port-sheet-list-preset-dialogs-qml-q3a, task 3.2, designs D1/D3/D5):
the frame and Esc stay native (``QDialog``); the whole content (preset list,
license view, name field, OK/Cancel) is a ``QQuickWidget`` island loading
``app/presentation/qml/SheetPresetRoot.qml`` — the widgets content is gone, no
flag, no second copy. The external contract is unchanged: the non-modal child
of the sheet list dialog and the ``created(sheet_id)`` signal.

Division of labour (design D3):

* the island binds to :class:`SheetPresetViewModel` (``sheetPresetVm``) — the
  catalog rows, the selection, the full license text and ``nameText`` — and
  reads colors from the token bridge (dialog-owned :class:`QmlPalette` pushed
  as ``islandPalette``, the launcher/timeline contract); both names are
  island-scoped because the shared engine's root context is global to all
  islands (see the comment in the constructor); a selection change is
  the one sync slot ``selectPreset(index)``, which applies the D5
  substitution rule Python-side (the field is re-filled with the preset title
  only while the user has not typed their own name — the field is empty or
  ``.strip()`` still holds another preset's title);
* «Создать» emits the root ``createRequested``: this facade validates the
  empty name (native ``QMessageBox.warning``), calls ``create_from_preset``
  under ``run_locked`` on the shared session and, on success, emits
  ``created(sheet_id)`` and closes; on a name conflict it warns and stays
  open; cancel («Отмена» / Esc) creates nothing;
* the island marks «Создать» as the default action (root ``defaultButton``);
  the wrapper answers Enter through the same create path.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Coroutine

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from app.application.services.character_sheet_service import (
    CharacterSheetError,
    CharacterSheetService,
)
from app.presentation.qml import setup_qml_shell
from app.presentation.qml.engine import QML_IMPORT_PATH, island_context, load_island
from app.presentation.theme import get_default_theme
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.viewmodels.sheet_preset_view_model import (
    SheetPresetViewModel,
)

log = logging.getLogger(__name__)

ROOT_QML = str(Path(QML_IMPORT_PATH) / "SheetPresetRoot.qml")


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
        theme=None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._run_locked = run_locked or _run_now
        # The island is skinned by the token bridge only, but the bridge still
        # needs a runtime — the widgets-era ``None`` falls back to the process
        # default, exactly like the other islands (D7 keeps it off-skin there).
        self._theme = theme if theme is not None else get_default_theme()

        self.setWindowTitle("Создать из пресета")
        self.resize(540, 500)

        # VM (the catalog + the D5 rule live there) and palette are dialog
        # children — a context property is a raw pointer, so QML must never
        # outlive them (the launcher's seam).
        self.vm = SheetPresetViewModel(parent=self)

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
        # Dialog-owned context (see list_dialog's identical apply-time note):
        # rootContext() on the shared engine is the ENGINE root, where a name
        # is a single global slot — this dialog is explicitly deleted when it
        # finishes, and a bridge of its own left there would strand the list
        # (and the editor behind it) on the off-skin colors.
        self._palette = QmlPalette(self._theme, parent=self)
        self._context = island_context(
            engine, self, sheetPresetVm=self.vm, islandPalette=self._palette
        )
        self._palette.setParent(self._context)
        self._component = load_island(self.quick, self._context, ROOT_QML)
        assert self.quick.status() == QQuickWidget.Status.Ready, self.quick.errors()
        layout.addWidget(self.quick)

        self._root = self.quick.rootObject()
        self._wire_island()

    # ---- island -> facade wiring ------------------------------------------------

    def _wire_island(self) -> None:
        self._root.createRequested.connect(lambda: self._spawn(self._on_ok()))
        # Queued, NOT direct: the QML «Отмена» click reaches here as a Python
        # slot still running inside the island's onClicked JS frame, and
        # reject() -> done() tears the scene down (setSource(QUrl())) — Qt
        # aborts on destroying items whose signal handler is on the stack.
        # The queued hop runs the same reject once the JS stack has unwound;
        # «cancel creates nothing» is unchanged (it was always just done()).
        self._root.cancelRequested.connect(
            self.reject, Qt.QueuedConnection
        )

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — Qt API
        # Enter clicks the island's ``defaultButton`` marker (design D5) — the
        # migrated dialog's default action was «Создать» and the marker
        # objectName pins that button.
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            marker = (
                self._root.property("defaultButton") if self._root is not None else None
            )
            clicked = getattr(marker, "clicked", None) if marker is not None else None
            if clicked is not None:
                clicked.emit()
                return  # the marker owns Enter only when the island is up
        super().keyPressEvent(event)

    @staticmethod
    def _spawn(coro) -> None:
        # Runs on the qasync event loop in the app; tests run the loop too.
        asyncio.ensure_future(coro)

    # -- selection -----------------------------------------------------------

    def _on_preset_changed(self, row: int) -> None:
        """Compatibility seam: the selection (and the D5 name substitution)
        now lives in the VM — the QML delegate drives the very same slot."""
        self.vm.selectPreset(row)

    # -- create ---------------------------------------------------------------

    async def _on_ok(self) -> None:
        preset_id = self.vm.selected_preset_id
        if preset_id is None:
            return
        name = self.vm.name_text.strip()
        if not name:
            QMessageBox.warning(self, "Чар-листы", "Имя не может быть пустым")
            return
        try:
            created = await self._run_locked(
                self._service.create_from_preset(preset_id, name)
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

    # ---- island teardown — synchronous release (Q3a correction) ------------
    #
    # NOT the Q1 deferred one-shot. The deferred seam exists so a dialog close
    # cannot tear the scene down while a QML ``onClicked`` is still on the
    # stack; it is only safe while the dialog object itself stays alive for
    # that one loop turn. A finished preset dialog is a QDialog already under
    # ``WA_DeleteOnClose``, and qasync's idle hook runs
    # ``sendPostedEvents(None, DeferredDelete)`` on its loop callbacks — the
    # dialog's C++ can therefore die before the timer fires, and the one-shot
    # (a child of the dialog) dies unretrieved with it: the island's scene
    # outlives no context at all then, and the QQuickWidget destructor hits a
    # stale context (use-after-free that lands in whichever test GC runs next —
    # the segfault this seam must not resurrect). Releasing inside ``done()``
    # has no such race: the scene is unwound while ``vm``/``_palette`` are
    # still alive, the dialog lives for the rest of its closeEvent either way,
    # and a QDialog::done() call is never a QML signal stack frame (QML clicks
    # land on the facade's Python handlers first).

    def _release_island(self) -> None:
        self.quick.setSource(QUrl())

    def done(self, result: int) -> None:  # QDialog API: accept/reject/close-event
        """Release the island against its VM/palette before the dialog dies.
        """
        self._release_island()
        super().done(result)
