"""Lifecycle owner for the character-sheet windows (audit B2, design D6).

Extracted from ``Application``: the list / editor / fill windows and their
``deleteLater`` bookkeeping. The manager is built per game by the composition
root with exactly the collaborators these flows need; ``Application`` keeps
thin delegates (and the ``_sheet_*`` test-visible properties) so no observable
behaviour changed with the move.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from app.application.services.character_sheet_instance_service import (
    CharacterSheetInstanceError,
)
from app.application.services.character_sheet_service import CharacterSheetError
from app.presentation.dialog_utils import confirm_discard
from app.presentation.theme import ThemeRuntime
from app.presentation.views.character_sheet.editor_dialog import (
    CharacterSheetEditorDialog,
)
from app.presentation.views.character_sheet.fill_dialog import (
    CharacterSheetFillDialog,
)
from app.presentation.views.character_sheet.list_dialog import (
    CharacterSheetListDialog,
)

logger = logging.getLogger("app.presentation.sheet_windows")


class SheetWindowsManager:
    """Owns at most one sheet list + one editor + one fill window per game.

    ``spawn`` is the application's session-lock scheduler (the wiring's public
    ``run_locked``): every session-touching flow started from a Qt signal goes
    through it, exactly as when these handlers lived in ``main.py``.
    """

    def __init__(
        self,
        *,
        sheet_service,
        instance_service,
        character_service,
        image_store,
        theme: ThemeRuntime,
        window,
        table_host,
        spawn,
        uow=None,
        geometries=None,
    ) -> None:
        self._sheet_service = sheet_service
        self._instance_service = instance_service
        self._character_service = character_service
        self._image_store = image_store
        self._theme = theme
        self._window = window
        self._table_host = table_host
        self._spawn = spawn
        # Q14 (nri-0011, design D4): the game's unit of work, threaded into
        # the editor/fill dialogs so their image ingest finishes through the
        # single transaction point. Default None keeps out-of-DB tests bare.
        self._uow = uow
        # NRI-0015 (1.3): the app-wide window geometry memory; roles
        # sheet_list / sheet_editor / sheet_fill. Default None (tests that
        # build the manager bare) skips the restore/remember hooks.
        self._geometries = geometries
        # At most one list + one editor + one fill (D6/D4 single windows).
        self.list_dialog: CharacterSheetListDialog | None = None
        self.editor: CharacterSheetEditorDialog | None = None
        self.fill: CharacterSheetFillDialog | None = None

    # ── closing / single-window helpers ──────────────────────────────────────

    def place_window(self, window, role: str) -> None:
        """Restore & start remembering one window's placement (NRI-0015 1.3).

        A bare (test) manager carries no geometry memory — the role is then
        simply not remembered, and the window opens wherever Qt puts it.
        """
        if self._geometries is not None:
            self._geometries.attach(window, role)

    def place_first_open(self, window, role: str) -> bool:
        """Pre-show half of the B4 roles (editor/Fill, NRI-0015 1.3): a
        remembered placement is applied while hidden, a first opening is at
        most shrunk into the screen. A bare manager behaves as remembered
        (nothing to restore, nothing to center)."""
        if self._geometries is None:
            return True
        return self._geometries.restore(window, role, center_when_absent=True)

    def place_after_show(self, window, role: str, remembered: bool) -> None:
        """Post-show half: a first opening finally moves to the screen center
        (its frame exists only now — a move never relays out the scene), then
        the placement tracker takes over. Resizing shown heavyweight dialogs
        offscreen churns their islands, so centering is move-only."""
        if self._geometries is not None:
            self._geometries.post_show_place(window, role, remembered=remembered)

    def close_windows(self) -> None:
        """Close the list and the editor without prompts (app shutdown / game switch)."""
        if self.list_dialog is not None:
            self.list_dialog.close()
            self.list_dialog = None
        if self.editor is not None:
            self.editor.force_close()
            self.editor = None
        if self.fill is not None:
            self.fill.force_close()
            self.fill = None

    # ── sheet list window ────────────────────────────────────────────────────

    def on_char_sheets(self) -> None:
        """Show (or create) the non-modal sheet list window."""
        if self.list_dialog is None:
            dialog = CharacterSheetListDialog(
                self._sheet_service, parent=self._window,
                run_locked=self._spawn,
                instance_service=self._instance_service,
                theme=self._theme,
            )
            dialog.open_requested.connect(self.on_sheet_open)
            dialog.open_instance_requested.connect(self.on_instance_open)
            dialog.renamed.connect(self.on_sheet_renamed)
            dialog.instance_renamed.connect(self.on_instance_renamed)
            # Closing the dialog releases its QML island (list_dialog.done),
            # so the instance is single-use: the next open builds a fresh one
            # (the editor/fill ``_forget_*`` contract).
            dialog.finished.connect(lambda _r, _d=dialog: self._forget_sheet_list(_d))
            # NRI-0015 (1.3): remember/restore the list window's placement.
            self.place_window(dialog, "sheet_list")
            self.list_dialog = dialog
        self.list_dialog.show()
        self.list_dialog.raise_()
        self.list_dialog.activateWindow()
        # Session-touching: go through the wiring's session lock like all others.
        self._spawn(self.sheet_list_refresh())

    def _forget_sheet_list(self, dialog) -> None:
        """Drop the closed list: its island is gone with ``done()``.

        The delete is queued behind the dialog's own deferred
        ``_release_island`` (same timer queue, FIFO), so the scene is already
        unloaded when the dialog and its VM/palette die.
        """
        if self.list_dialog is dialog:
            self.list_dialog = None
        QTimer.singleShot(0, dialog, dialog.deleteLater)

    async def sheet_list_refresh(self) -> None:
        # Runs inside the task spawned by ``_spawn`` above, which
        # holds the session lock for the whole task — that is how this caller
        # satisfies ``refresh()``'s "its caller provides the lock" contract.
        # Do NOT wrap ``dialog.refresh()`` in ``run_locked`` here: the lock
        # is not reentrant (review #12).
        dialog = self.list_dialog
        if dialog is None:
            return
        try:
            await dialog.refresh()
        except Exception as exc:  # app already shut down under this task
            logger.debug("character-sheet list refresh skipped: %s", exc)
            return
        if self.list_dialog is not dialog:
            return
        sheet_id = None
        if self.editor is not None:
            sheet_id = self.editor.view_model.sheet_id
        dialog.set_open_sheet_id(sheet_id)
        instance_id = None
        if self.fill is not None:
            instance_id = self.fill.view_model.instance_id
        dialog.set_open_instance_id(instance_id)
        self.sync_list_seated()

    def sync_list_seated(self) -> None:
        dialog = self.list_dialog
        host = self._table_host
        if dialog is None:
            return
        if host is not None and host.is_running:
            dialog.set_seated_ids(host.seated_ids)
        else:
            dialog.set_seated_ids(set())

    def on_host_values(self, instance_id: int, field_id: str, value) -> None:
        fill = self.fill
        if fill is None or fill.view_model.instance_id != instance_id:
            return
        fill.view_model.apply_remote_value(field_id, value)

    # ── editor window ────────────────────────────────────────────────────────

    def on_sheet_open(self, sheet_id: int) -> None:
        self._spawn(self.open_sheet(sheet_id))

    async def open_sheet(self, sheet_id: int) -> None:
        """Open one editor (D6): a dirty current editor is closed only after confirm."""
        if self.editor is not None:
            if self.editor.view_model.dirty:
                if not confirm_discard(
                    self._window,
                    "В текущем макете есть несохранённые правки. Закрыть без сохранения "
                    "и открыть новый шаблон?",
                ):
                    return
                # The confirm above already asked the user — close without the
                # editor's own dirty prompt.
                self.editor.force_close()
            else:
                self.editor.close()
            self.editor = None
        editor = CharacterSheetEditorDialog(
            self._sheet_service, sheet_id, parent=self._window,
            run_locked=self._spawn,
            image_store=self._image_store,
            theme=self._theme,
            uow=self._uow,
        )
        self.editor = editor
        # A closed window must not keep its stale reference (D6 single editor).
        editor.finished.connect(lambda _r, _e=editor: self._forget_editor(_e))
        editor.saved.connect(lambda _e=editor: self.on_design_saved(_e))
        # NRI-0015 (1.3, B4): role "sheet_editor" — remembered placement or,
        # on the very first opening, the deterministic safe center.
        remembered_editor = self.place_first_open(editor, "sheet_editor")
        editor.show()
        self.place_after_show(editor, "sheet_editor", remembered_editor)
        try:
            await editor.load()
        except CharacterSheetError as exc:
            # A corrupt template must not be opened (spec): drop the editor and report.
            if self.editor is editor:
                self.editor = None
            editor.force_close()  # template is None -> no dirty prompt
            QMessageBox.critical(self._window, "Чар-листы", str(exc))
            if self.list_dialog is not None:
                self.list_dialog.set_open_sheet_id(None)
            return
        except Exception as exc:  # session gone (app shut down mid-load): just drop
            logger.debug("character-sheet load aborted: %s", exc)
            if self.editor is editor:
                self.editor = None
            editor.force_close()  # template is None -> no dirty prompt
            return
        # Only mark the sheet open if this editor is still the current one:
        # if the window was closed while load was in flight, ``finished``
        # already ran ``_forget_editor`` (clearing the mark), and re-applying
        # it here would leave a stale "open" flag on a closed sheet.
        if self.list_dialog is not None and self.editor is editor:
            self.list_dialog.set_open_sheet_id(editor.view_model.sheet_id)

    def on_sheet_renamed(self, sheet_id: int, name: str) -> None:
        """External rename (D5): update the open editor's title, dirty untouched."""
        if self.editor is not None and self.editor.view_model.sheet_id == sheet_id:
            self.editor.set_name(name)

    def _forget_editor(self, editor) -> None:
        """Drop the reference once the editor window is actually closed.

        Also queue the C++ teardown: the dialog is a child of the main window,
        so without ``deleteLater`` every closed editor would linger as a hidden
        top-level widget until the app shuts down.
        """
        if self.editor is editor:
            self.editor = None
        if self.list_dialog is not None:
            self.list_dialog.set_open_sheet_id(None)
        editor.deleteLater()

    # ── fill window ──────────────────────────────────────────────────────────

    def on_instance_open(self, instance_id: int) -> None:
        self._spawn(self.open_fill(instance_id))

    def on_host_player_selected(self, instance_id: int) -> None:
        self._spawn(self.open_fill(instance_id))

    async def open_fill(self, instance_id: int) -> None:
        """Open one Fill window (D4): dirty current Fill is closed only after confirm."""
        read_only = bool(self._table_host is not None and self._table_host.is_running)
        if self.fill is not None:
            current_id = self.fill.view_model.instance_id
            if current_id is None:
                current_id = self.fill.instance_id
            if current_id == instance_id:
                self.fill.show()
                self.fill.raise_()
                self.fill.activateWindow()
                return
            if read_only:
                try:
                    await self.fill.load_instance(instance_id)
                except (CharacterSheetError, CharacterSheetInstanceError) as exc:
                    QMessageBox.critical(self._window, "Чар-листы", str(exc))
                    return
                if self.list_dialog is not None:
                    self.list_dialog.set_open_instance_id(
                        self.fill.view_model.instance_id
                    )
                return
            if self.fill.view_model.dirty:
                if not confirm_discard(
                    self._window,
                    "В текущем листе есть несохранённые правки. Закрыть без сохранения "
                    "и открыть другой лист?",
                ):
                    return
                self.fill.force_close()
            else:
                self.fill.close()
            self.fill = None
        fill = CharacterSheetFillDialog(
            self._instance_service,
            self._sheet_service,
            instance_id,
            parent=self._window,
            run_locked=self._spawn,
            image_store=self._image_store,
            character_service=self._character_service,
            read_only=read_only,
            theme=self._theme,
            uow=self._uow,
        )
        self.fill = fill
        fill.finished.connect(lambda _r, _f=fill: self._forget_fill(_f))
        fill.binding_changed.connect(
            lambda: self._spawn(self.refresh_character_cards())
        )
        # NRI-0015 (1.3, B4): role "sheet_fill" — same safe-center contract
        # as the editor: a first opening is never born outside the screen.
        remembered_fill = self.place_first_open(fill, "sheet_fill")
        fill.show()
        self.place_after_show(fill, "sheet_fill", remembered_fill)
        try:
            await fill.load()
        except (CharacterSheetError, CharacterSheetInstanceError) as exc:
            if self.fill is fill:
                self.fill = None
            fill.force_close()
            QMessageBox.critical(self._window, "Чар-листы", str(exc))
            if self.list_dialog is not None:
                self.list_dialog.set_open_instance_id(None)
            return
        except Exception as exc:
            logger.debug("character-sheet fill load aborted: %s", exc)
            if self.fill is fill:
                self.fill = None
            fill.force_close()
            return
        if self.list_dialog is not None and self.fill is fill:
            self.list_dialog.set_open_instance_id(fill.view_model.instance_id)

    def on_instance_renamed(self, instance_id: int, name: str) -> None:
        if self.fill is not None and self.fill.view_model.instance_id == instance_id:
            self.fill.set_name(name)

    def _forget_fill(self, fill) -> None:
        if self.fill is fill:
            self.fill = None
        if self.list_dialog is not None:
            self.list_dialog.set_open_instance_id(None)
        fill.deleteLater()

    # ── cross-window coordination ────────────────────────────────────────────

    def on_design_saved(self, editor) -> None:
        fill = self.fill
        if fill is not None and fill.view_model.template_id == editor.view_model.sheet_id:
            self._spawn(self.reload_fill_after_design(editor))
            return
        host = self._table_host
        if host is not None and host.is_running:
            self._spawn(host.broadcast_layout(editor.view_model.sheet_id))

    async def reload_fill_after_design(self, editor) -> None:
        fill = self.fill
        if fill is None or editor is None:
            return
        if fill.view_model.template_id != editor.view_model.sheet_id:
            return
        try:
            await fill.view_model.reload_layout()
        except Exception as exc:
            logger.debug("fill reload_layout after design save skipped: %s", exc)
        host = self._table_host
        if host is not None and host.is_running:
            await host.broadcast_layout(editor.view_model.sheet_id)

    async def refresh_character_cards(self) -> None:
        window = self._window
        svc = self._instance_service
        if window is None or svc is None:
            return
        from app.presentation.views.entity_card_dialog import EntityCardDialog
        for card in window.findChildren(EntityCardDialog):
            if card.entity_type != "character":
                continue
            eid = card.populated_entity_id
            if eid is None:
                continue
            inst = await svc.get_by_character_id(eid)
            card.set_character_sheet_available(inst is not None)
