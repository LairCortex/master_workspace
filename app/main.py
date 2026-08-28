"""Application entry point — DI, qasync, startup."""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

from PySide6.QtWidgets import QApplication, QMessageBox
from qasync import QEventLoop

from app.infrastructure.db.database import create_engine, create_session_factory
from app.infrastructure.db.migrations import init_db
from app.infrastructure.db.game_manager import ensure_game_directory, export_game, get_db_url, get_images_dir
from app.infrastructure.db.models import GameSettingsModel
from app.infrastructure.images.store import ImageStore
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.event_repository import EventRepository
from app.infrastructure.repositories.organization_repository import OrganizationRepository
from app.infrastructure.repositories.character_repository import CharacterRepository
from app.infrastructure.repositories.item_repository import ItemRepository
from app.infrastructure.repositories.location_repository import LocationRepository
from app.infrastructure.db.models import DescriptionModel

from app.application.services.event_service import EventService
from app.application.services.search_service import SearchService
from app.application.services.entity_service import EntityService
from app.application.services.llm_service import LlmService
from app.application.services.character_sheet_service import (
    CharacterSheetError,
    CharacterSheetService,
)
from app.application.wiring import ApplicationWiring

from app.presentation.viewmodels.timeline_viewmodel import TimelineViewModel
from app.presentation.viewmodels.detail_viewmodel import DetailViewModel
from app.presentation.viewmodels.search_viewmodel import SearchViewModel
from app.presentation.viewmodels.event_dialog_viewmodel import EventDialogViewModel
from app.presentation.viewmodels.llm_viewmodel import (
    FIELD_PROMPTS_KEY, WORLD_PROMPT_KEY, LlmViewModel,
)

from app.presentation.utils.date_utils import (
    SETTINGS_KEY, get_custom_months, months_from_json, months_to_json, set_custom_months,
)
from app.presentation.utils.image_utils import set_image_dir
from app.infrastructure.http import AppHttpClient
from app.infrastructure.llm.config import LlmConfig, LlmConfigManager
from app.infrastructure.llm.remote_provider import RemoteLlmProvider
from app.presentation.views.main_window import MainWindow
from app.presentation.views.game_launcher_dialog import GameLauncherDialog
from app.presentation.views.month_settings_dialog import MonthSettingsDialog
from app.presentation.views.llm_setup_dialog import LlmSetupDialog
from app.presentation.views.character_sheet.editor_dialog import CharacterSheetEditorDialog
from app.presentation.views.character_sheet.list_dialog import CharacterSheetListDialog
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)

class Application:
    """Wires up DI and manages the application lifecycle."""

    def __init__(self, qapp: QApplication, http: AppHttpClient | None = None) -> None:
        """Wires up DI and manages the application lifecycle.

        ``http`` is the optional application-wide HTTP client (injected by
        tests with an emulated transport). When omitted the application
        creates and closes its own default client per start/shutdown cycle.
        """
        self._qapp = qapp
        self.engine = None
        self.session_factory = None
        self._session = None
        self._window: MainWindow | None = None
        self._db_path: str | None = None
        self._image_store: ImageStore | None = None

        self._config_manager = LlmConfigManager()
        self._http_injected: AppHttpClient | None = http
        self._http: AppHttpClient | None = None
        self._llm_service: LlmService | None = None
        self._llm_vm: LlmViewModel | None = None
        # Entity service catalog — built once per game in start()
        self._entity_services: dict[str, EntityService] = {}
        self._wiring: ApplicationWiring | None = None
        # Character-sheet windows (D6): at most one list + one editor per game
        self._sheet_service: CharacterSheetService | None = None
        self._sheet_list_dialog: CharacterSheetListDialog | None = None
        self._sheet_editor: CharacterSheetEditorDialog | None = None

    async def start(self, db_path: str) -> MainWindow:
        """Initialize DB, create all layers, show main window.

        Startup order (design D1/D7/D8): migrate a legacy flat ``.db`` into
        its catalog directory first (game name = directory name from then
        on) → schema + legacy-image migration → restore the storage
        invariant (``startup_gc``) → build layers → show the window.
        """
        self._close_sheet_windows()
        db_path = str(ensure_game_directory(db_path))
        self._db_path = db_path
        db_url = get_db_url(db_path)
        self.engine = create_engine(db_url)
        self.session_factory = create_session_factory(self.engine)
        image_dir = get_images_dir(db_path)
        await init_db(self.engine, image_dir=image_dir)
        self._session = self.session_factory()
        self._image_store = ImageStore(self._session, image_dir)
        await self._image_store.startup_gc()
        set_image_dir(image_dir)

        game_name = Path(db_path).parent.name

        # Load custom month names
        await self._load_month_settings()

        # Repositories
        desc_repo = BaseRepository(self._session, DescriptionModel)
        event_repo = EventRepository(self._session)
        org_repo = OrganizationRepository(self._session)
        char_repo = CharacterRepository(self._session)
        item_repo = ItemRepository(self._session)
        loc_repo = LocationRepository(self._session)

        # Services
        self._entity_services = self._build_entity_services()
        event_service = EventService(
            event_repo=event_repo,
            description_repo=desc_repo,
            organization_service=self._entity_services["organization"],
            character_service=self._entity_services["character"],
            item_service=self._entity_services["item"],
            location_service=self._entity_services["location"],
        )
        search_service = SearchService(
            event=event_repo,
            organization=org_repo,
            character=char_repo,
            item=item_repo,
            location=loc_repo,
        )

        # ViewModels
        timeline_vm = TimelineViewModel(event_service)
        detail_vm = DetailViewModel(event_service)
        search_vm = SearchViewModel(search_service)
        event_dialog_vm = EventDialogViewModel(event_service)

        # LLM: shared http client (injected in tests) + provider from the global connection config
        self._http = self._http_injected if self._http_injected is not None else AppHttpClient()
        self._llm_service = LlmService(RemoteLlmProvider(LlmConfig(), self._http))
        self._llm_vm = LlmViewModel(self._llm_service, self._config_manager, self._http)

        # Load LLM settings
        await self._load_llm_settings()

        # Main window
        window = MainWindow(
            timeline_vm=timeline_vm,
            detail_vm=detail_vm,
            search_vm=search_vm,
            llm_vm=self._llm_vm,
            game_name=game_name,
        )

        self._search_service = search_service

        # Wire signals
        self._wiring = ApplicationWiring(
            self, window, timeline_vm, detail_vm, search_vm, event_dialog_vm, event_service,
        )
        self._wiring.connect()

        # Switch game menu
        window.switch_game_requested.connect(lambda: asyncio.ensure_future(self._on_switch_game()))

        # Export game menu
        window.export_requested.connect(self._on_export_game)

        # Month settings menu
        window.month_settings_requested.connect(
            lambda: asyncio.ensure_future(self._on_month_settings(window, timeline_vm))
        )

        # LLM setup menu
        window.llm_setup_requested.connect(
            lambda: self._on_llm_setup(window)
        )

        # Character-sheet menu (D6): one service per game, repo→service DI.
        # The ImageStore is required: the service GCs the sheet-page image
        # references (pages JSON) after a save/delete commits (design D6) —
        # without it the files of cleared/deleted sheet images are never
        # removed in the running app.
        self._sheet_service = CharacterSheetService(
            CharacterSheetRepository(self._session),
            image_store=self._image_store,
        )
        window.char_sheets_requested.connect(self._on_char_sheets)

        # Initial load
        await timeline_vm.load_events()
        window.timeline_widget.update_events(timeline_vm.events)

        # Replace old window if switching
        if self._window is not None:
            self._window.close()
        self._window = window
        window.show()
        return window

    def _on_export_game(self) -> None:
        """Export current game as .nri archive."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        if not self._db_path:
            return
        game_name = Path(self._db_path).parent.name
        dest, _ = QFileDialog.getSaveFileName(
            self._window,
            "Экспорт игры",
            f"{game_name}.nri",
            "NRI архив (*.nri);;Все файлы (*)",
        )
        if not dest:
            return
        try:
            export_game(self._db_path, dest)
            QMessageBox.information(
                self._window, "Экспорт", f"Игра «{game_name}» успешно экспортирована.",
            )
        except Exception as e:
            QMessageBox.critical(self._window, "Ошибка экспорта", str(e))

    async def _on_switch_game(self) -> None:
        """Show launcher, switch to selected game."""
        dialog = GameLauncherDialog(parent=self._window)
        dialog.game_selected.connect(lambda p: asyncio.ensure_future(self._on_game_selected(p)))
        dialog.open()

    async def _on_game_selected(self, path: str) -> None:
        """Game switch with the character-sheet windows (D6).

        A dirty editor is closed only after an explicit confirm, and then
        without ``update_pages``; the list closes unconditionally. Declining
        the prompt aborts the switch (the launcher stays open).
        """
        if self._sheet_editor is not None and self._sheet_editor.view_model.dirty:
            answer = QMessageBox.question(
                self._window,
                "Несохранённые изменения",
                "В макете чар-листа есть несохранённые правки. Сменить игру и "
                "закрыть редактор без сохранения?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._close_sheet_windows()
        await self.shutdown()
        await self.start(path)

    # -- character sheets (D6) ------------------------------------------------

    def _close_sheet_windows(self) -> None:
        """Close the list and the editor without prompts (app shutdown / game switch)."""
        if self._sheet_list_dialog is not None:
            self._sheet_list_dialog.close()
            self._sheet_list_dialog = None
        if self._sheet_editor is not None:
            self._sheet_editor.force_close()
            self._sheet_editor = None

    def _on_char_sheets(self) -> None:
        """Show (or create) the non-modal sheet list window."""
        if self._sheet_list_dialog is None:
            dialog = CharacterSheetListDialog(
                self._sheet_service, parent=self._window,
                run_locked=self._wiring.run_locked,
            )
            dialog.open_requested.connect(self._on_sheet_open)
            dialog.renamed.connect(self._on_sheet_renamed)
            self._sheet_list_dialog = dialog
        self._sheet_list_dialog.show()
        self._sheet_list_dialog.raise_()
        self._sheet_list_dialog.activateWindow()
        # Session-touching: go through the wiring's session lock like all others.
        self._wiring._spawn(self._sheet_list_refresh())

    async def _sheet_list_refresh(self) -> None:
        dialog = self._sheet_list_dialog
        if dialog is None:
            return
        try:
            await dialog.refresh()
        except Exception as exc:  # app already shut down under this task
            logging.getLogger("app.main").debug("character-sheet list refresh skipped: %s", exc)
            return
        if self._sheet_list_dialog is not dialog:
            return
        sheet_id = None
        if self._sheet_editor is not None:
            sheet_id = self._sheet_editor.view_model.sheet_id
        dialog.set_open_sheet_id(sheet_id)

    def _on_sheet_open(self, sheet_id: int) -> None:
        self._wiring._spawn(self._open_sheet(sheet_id))

    async def _open_sheet(self, sheet_id: int) -> None:
        """Open one editor (D6): a dirty current editor is closed only after confirm."""
        if self._sheet_editor is not None:
            if self._sheet_editor.view_model.dirty:
                answer = QMessageBox.question(
                    self._window,
                    "Несохранённые изменения",
                    "В текущем макете есть несохранённые правки. Закрыть без сохранения "
                    "и открыть новый шаблон?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
                # The confirm above already asked the user — close without the
                # editor's own dirty prompt.
                self._sheet_editor.force_close()
            else:
                self._sheet_editor.close()
            self._sheet_editor = None
        editor = CharacterSheetEditorDialog(
            self._sheet_service, sheet_id, parent=self._window,
            run_locked=self._wiring.run_locked,
            image_store=self._image_store,
        )
        self._sheet_editor = editor
        # A closed window must not keep its stale reference (D6 single editor).
        editor.finished.connect(lambda _r, _e=editor: self._forget_editor(_e))
        editor.show()
        try:
            await editor.load()
        except CharacterSheetError as exc:
            # A corrupt template must not be opened (spec): drop the editor and report.
            if self._sheet_editor is editor:
                self._sheet_editor = None
            editor.force_close()  # template is None -> no dirty prompt
            QMessageBox.critical(self._window, "Чар-листы", str(exc))
            if self._sheet_list_dialog is not None:
                self._sheet_list_dialog.set_open_sheet_id(None)
            return
        except Exception as exc:  # session gone (app shut down mid-load): just drop
            logging.getLogger("app.main").debug("character-sheet load aborted: %s", exc)
            if self._sheet_editor is editor:
                self._sheet_editor = None
            editor.force_close()  # template is None -> no dirty prompt
            return
        # Only mark the sheet open if this editor is still the current one:
        # if the window was closed while load was in flight, ``finished``
        # already ran ``_forget_editor`` (clearing the mark), and re-applying
        # it here would leave a stale "open" flag on a closed sheet.
        if self._sheet_list_dialog is not None and self._sheet_editor is editor:
            self._sheet_list_dialog.set_open_sheet_id(editor.view_model.sheet_id)

    def _on_sheet_renamed(self, sheet_id: int, name: str) -> None:
        """External rename (D5): update the open editor's title, dirty untouched."""
        if self._sheet_editor is not None and self._sheet_editor.view_model.sheet_id == sheet_id:
            self._sheet_editor.set_name(name)

    def _forget_editor(self, editor) -> None:
        """Drop the reference once the editor window is actually closed.

        Also queue the C++ teardown: the dialog is a child of the main window,
        so without ``deleteLater`` every closed editor would linger as a hidden
        top-level widget (with its QGraphicsScene) until the app shuts down.
        """
        if self._sheet_editor is editor:
            self._sheet_editor = None
        if self._sheet_list_dialog is not None:
            self._sheet_list_dialog.set_open_sheet_id(None)
        editor.deleteLater()

    def _wire_mentions_for_dialog(self, dialog, on_entity_click_fn):
        """Connect mention search and click signals for a dialog's MentionTextEdits.

        Both signals touch the shared ``AsyncSession`` (search / entity load),
        so they must run through ``ApplicationWiring._spawn`` like every other
        session-touching task — a bare ``ensure_future`` here would race the
        session against whatever task the lock is currently serializing.
        """
        for edit in dialog.get_mention_edits():
            async def _do_search(query, _edit=edit):
                try:
                    results = await self._search_service.search_names(query)
                    _edit.show_mention_results(results)
                except Exception as exc:
                    logging.getLogger("app.main").error(
                        "Mention search failed for %r: %s", query, exc, exc_info=True
                    )

            edit.mention_search_requested.connect(
                lambda q, _fn=_do_search: self._wiring._spawn(_fn(q))
            )

        dialog.mention_clicked.connect(
            lambda t, i: self._wiring._spawn(on_entity_click_fn(t, i))
        )

    def _get_entity_service(self, entity_type: str) -> EntityService | None:
        """Thin wrapper over the per-game service catalog."""
        return self._entity_services.get(entity_type)

    def _build_entity_services(self) -> dict[str, EntityService]:
        """Build the per-game catalog once (replaces per-call construction)."""
        desc_repo = BaseRepository(self._session, DescriptionModel)
        repo_map = {
            "organization": OrganizationRepository(self._session),
            "character": CharacterRepository(self._session),
            "item": ItemRepository(self._session),
            "location": LocationRepository(self._session),
        }
        services = {
            t: EntityService(repo=r, description_repo=desc_repo, image_store=self._image_store)
            for t, r in repo_map.items()
        }
        for type_name, svc in services.items():
            svc.set_related_services(
                {t: s for t, s in services.items() if t != type_name},
            )
        return services

    async def _load_month_settings(self) -> None:
        """Load custom month names from game_settings table."""
        from sqlalchemy import select
        try:
            result = await self._session.execute(
                select(GameSettingsModel).where(GameSettingsModel.key == SETTINGS_KEY)
            )
            row = result.scalars().first()
            if row:
                months = months_from_json(row.value)
                set_custom_months(months)
            else:
                set_custom_months(None)
        except Exception as exc:
            logging.getLogger("app.main").warning(
                "Failed to load month settings: %s", exc
            )
            set_custom_months(None)

    async def _save_month_settings(self, months: dict) -> None:
        """Save custom month names to game_settings table."""
        from sqlalchemy import select
        result = await self._session.execute(
            select(GameSettingsModel).where(GameSettingsModel.key == SETTINGS_KEY)
        )
        row = result.scalars().first()
        value = months_to_json(months)
        if row:
            row.value = value
        else:
            self._session.add(GameSettingsModel(key=SETTINGS_KEY, value=value))
        await self._session.commit()

    async def _on_month_settings(self, window, timeline_vm) -> None:
        """Show month settings dialog and apply changes."""
        dialog = MonthSettingsDialog(get_custom_months(), parent=window)

        async def _on_saved(months):
            set_custom_months(months)
            await self._save_month_settings(months)
            # Refresh all views with new month names
            await timeline_vm.load_events()
            window.timeline_widget.update_events(timeline_vm.events)

        dialog.saved.connect(lambda m: asyncio.ensure_future(_on_saved(m)))
        dialog.open()

    def _wire_ai_buttons(self, dialog) -> None:
        """Connect AI buttons in a dialog to the LLM ViewModel.

        Field buttons trigger single-field generation; the entity button
        (top-right of the form) starts a parallel wave over all fields and
        becomes its cancel while the wave runs. At most one wave per
        dialog at a time; "Save" is locked for the whole generation.
        """
        if not hasattr(dialog, "get_ai_buttons"):
            return
        llm_vm = self._llm_vm
        service = self._llm_service
        get_entity_button = getattr(dialog, "get_entity_button", None)
        log = logging.getLogger("llm.wire")

        # Per-dialog wave state shared by the field and entity-button handlers.
        # ``batch`` is None outside a wave, otherwise:
        #   {"fields": {field_id: (button, field_name, field_label)},
        #    "pending": set[field_id], "errors": {field_id: reason}}
        # ``single_field`` — field_id of the in-flight single generation (or None).
        # ``cancelled_fields`` — fields of a stopped wave: ALL late results/
        # errors for them are dropped (cancellation is not an error). The
        # marker stays until a new generation of the same field is started.
        state: dict = {"batch": None, "single_field": None, "cancelled_fields": set()}

        def _entity_button():
            return get_entity_button() if get_entity_button is not None else None

        def _any_generating() -> bool:
            return (
                any(b.is_generating for b in dialog.get_ai_buttons())
                or state["batch"] is not None
                or state["single_field"] is not None
            )

        def _sync_controls() -> None:
            lock = getattr(dialog, "set_save_locked", None)
            if lock is not None:
                lock(_any_generating())
            ebtn = _entity_button()
            if ebtn is not None:
                ebtn.set_wave_running(state["batch"] is not None)
                ebtn.set_single_in_flight(
                    state["batch"] is None and state["single_field"] is not None
                )

        buttons_by_id = {
            f"{b.entity_type}.{b.field_name}": b for b in dialog.get_ai_buttons()
        }

        def _fail_field(field_id: str, err: str) -> None:
            """Terminal failure of a dialog field (provider error or an
            unexpected break of request_generation): the single completion
            path for failures, so the dialog can never be left stuck (no
            leaked single_field / batch pending); D6: visible warning."""
            if field_id in state["cancelled_fields"]:
                return  # late signal for a cancelled field
            btn = buttons_by_id[field_id]
            btn.set_generating(False)
            batch = state["batch"]
            if batch is not None and field_id in batch["fields"]:
                batch["errors"][field_id] = err
                batch["pending"].discard(field_id)
                if not batch["pending"]:
                    _finish_wave()
            else:
                if state["single_field"] == field_id:
                    state["single_field"] = None
                QMessageBox.warning(
                    dialog,
                    "AI-ассистент",
                    f"Не удалось сгенерировать поле «{btn.field_label}»: {err}",
                )
                _sync_controls()

        def _launch(btn, field_id: str, et: str, fn: str, fl: str, ct: str) -> None:
            async def _do():
                try:
                    await llm_vm.request_generation(field_id, et, fn, fl, ct, owner=dialog)
                except Exception as exc:
                    # request_generation converts provider errors into
                    # generation_error; this only catches unexpected breaks —
                    # routed through _fail_field so the dialog never sticks.
                    log.error("Generation failed: %s — %s", field_id, exc)
                    _fail_field(field_id, str(exc))

            asyncio.ensure_future(_do())

        def _show_batch_errors(errors: dict, fields: dict) -> None:
            """One aggregated dialog for the failed fields of a finished wave.

            A shared reason is stated once for the whole list; different
            reasons are listed per field.
            """
            items = [(fields[fid][2], reason) for fid, reason in errors.items()]
            reasons = {reason for _label, reason in items}
            if len(reasons) == 1:
                lines = "\n".join(f"- «{label}»" for label, _reason in items)
                text = f"Не удалось сгенерировать поля:\n{lines}\n\nПричина: {next(iter(reasons))}"
            else:
                lines = "\n".join(f"- «{label}»: {reason}" for label, reason in items)
                text = f"Не удалось сгенерировать поля:\n{lines}"
            QMessageBox.warning(dialog, "AI-ассистент", text)

        def _finish_wave() -> None:
            # Every field resets its own button in the finishing handler
            # before dropping out of ``pending``, so by the time the counter
            # reaches zero the whole wave is already unblocked.
            batch = state["batch"]
            state["batch"] = None
            _sync_controls()
            if batch["errors"]:
                _show_batch_errors(batch["errors"], batch["fields"])

        def _stop_all_no_error() -> None:
            """End the wave/single generation without an error dialog: cancel
            the requests and synchronously reset the buttons; results already
            written into fields stay there."""
            batch = state["batch"]
            stopping: set[str] = set(batch["fields"]) if batch is not None else set()
            if state["single_field"] is not None:
                stopping.add(state["single_field"])
            state["cancelled_fields"] |= stopping
            state["batch"] = None
            state["single_field"] = None
            service.cancel_all(dialog)
            for btn in dialog.get_ai_buttons():
                btn.set_generating(False)
            _sync_controls()

        def _start_wave() -> None:
            # Reaches here only from the entity button, which emits
            # batch_requested only when ready and no generation is running.
            fields: dict[str, tuple] = {}
            for btn in dialog.get_ai_buttons():
                field_id = f"{btn.entity_type}.{btn.field_name}"
                fields[field_id] = (btn, btn.field_name, btn.field_label)
                # A new wave invalidates the cancellation markers of a previous one.
                state["cancelled_fields"].discard(field_id)
                btn.set_generating(True)
            state["batch"] = {"fields": fields, "pending": set(fields), "errors": {}}
            _sync_controls()
            for field_id, (btn, fn, fl) in fields.items():
                # Existing field text is part of the prompt; the result
                # overrides it (safe override per spec).
                _launch(btn, field_id, btn.entity_type, fn, fl, btn.current_text)

        for btn in dialog.get_ai_buttons():
            btn.update_llm_state(llm_vm.status, llm_vm.has_world_prompt)
            llm_vm.model_status_changed.connect(
                lambda _s, _b=btn: _b.update_llm_state(llm_vm.status, llm_vm.has_world_prompt)
            )

            def _on_generate(et, fn, fl, ct, _btn=btn):
                field_id = f"{et}.{fn}"
                if _any_generating():
                    return  # at most one wave per dialog
                log.info("AI button clicked: %s, label=%s, text=%r", field_id, fl, ct[:50] if ct else "")
                # A new run invalidates the cancellation marker of a previous wave.
                state["cancelled_fields"].discard(field_id)
                _btn.set_generating(True)
                state["single_field"] = field_id
                _sync_controls()
                _launch(_btn, field_id, et, fn, fl, ct)

            btn.generate_requested.connect(_on_generate)

            def _on_field_finished(owner, fid, text, _btn=btn, _et=btn.entity_type, _fn=btn.field_name):
                field_id = f"{_et}.{_fn}"
                # owner is not dialog → the signal belongs to another (nested)
                # dialog of the same entity type: its results must not land here.
                if owner is not dialog or fid != field_id:
                    return
                if field_id in state["cancelled_fields"]:
                    return  # late signal for a cancelled field
                _btn.set_result_text(text)
                batch = state["batch"]
                if batch is not None and field_id in batch["fields"]:
                    batch["pending"].discard(field_id)
                    if not batch["pending"]:
                        _finish_wave()
                else:
                    if state["single_field"] == field_id:
                        state["single_field"] = None
                    _sync_controls()

            def _on_field_error(owner, fid, err, _et=btn.entity_type, _fn=btn.field_name):
                field_id = f"{_et}.{_fn}"
                if owner is not dialog or fid != field_id:
                    return
                _fail_field(fid, err)

            llm_vm.generation_finished.connect(_on_field_finished)
            llm_vm.generation_error.connect(_on_field_error)

        def _close_guard() -> None:
            """Close path (X / «Отмена») while a generation may be in flight.

            In-flight requests → confirmation with a warning; requests only
            waiting between retries → silent cancel. Either way the wave is
            cancelled after the decision (cancellation is not an error).
            """
            if not _any_generating():
                dialog.reject()
                return
            in_flight = service.count_in_flight(dialog)
            if in_flight > 0:
                answer = QMessageBox.question(
                    dialog,
                    "Генерация",
                    f"Идёт запрос к LLM ({in_flight} полей). Если закрыть, запрос "
                    f"будет прерван и результат не появится.",
                    buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    defaultButton=QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            _stop_all_no_error()
            dialog.reject()

        set_close_guard = getattr(dialog, "set_close_guard", None)
        if set_close_guard is not None:
            set_close_guard(_close_guard)

        ebtn = _entity_button()
        if ebtn is not None:
            ebtn.update_llm_state(llm_vm.status, llm_vm.has_world_prompt)
            llm_vm.model_status_changed.connect(
                lambda _s, _e=ebtn: _e.update_llm_state(llm_vm.status, llm_vm.has_world_prompt)
            )
            ebtn.batch_requested.connect(_start_wave)
            ebtn.batch_cancel_requested.connect(_stop_all_no_error)

    def _on_llm_setup(self, window) -> None:
        llm_vm = self._llm_vm
        dialog = LlmSetupDialog(
            config=llm_vm.config,
            world_prompt=llm_vm.world_prompt,
            field_prompts=llm_vm.field_prompts,
            http=self._http,
            parent=window,
        )

        async def _on_saved(config, world_prompt, field_prompts):
            ok = True
            try:
                self._config_manager.save(config)
                llm_vm.world_prompt = world_prompt
                llm_vm.field_prompts = field_prompts
                llm_vm.apply_config(config)
                if self._session is not None:
                    await self._save_llm_settings()
                else:
                    # App is shutting down: global config file is saved,
                    # per-game prompts are dropped — nothing to surface.
                    logging.getLogger("llm.setup").info(
                        "LLM session closed before per-game prompts saved"
                    )
            except Exception as exc:
                logging.getLogger("llm.setup").error("Failed to save LLM settings: %s", exc)
                ok = False
            dialog.finish_saving(ok)

        dialog.saved.connect(lambda c, wp, fp: asyncio.ensure_future(_on_saved(c, wp, fp)))
        dialog.open()

    async def _load_llm_settings(self) -> None:
        from sqlalchemy import select
        try:
            result = await self._session.execute(
                select(GameSettingsModel).where(GameSettingsModel.key == WORLD_PROMPT_KEY)
            )
            row = result.scalars().first()
            if row:
                self._llm_vm.world_prompt_from_json(row.value)

            result2 = await self._session.execute(
                select(GameSettingsModel).where(GameSettingsModel.key == FIELD_PROMPTS_KEY)
            )
            row2 = result2.scalars().first()
            if row2:
                self._llm_vm.field_prompts_from_json(row2.value)
        except Exception as exc:
            logging.getLogger("app.main").warning(
                "Failed to load LLM settings: %s", exc
            )

    async def _save_llm_settings(self) -> None:
        from sqlalchemy import select
        for key, value in [
            (WORLD_PROMPT_KEY, self._llm_vm.world_prompt_to_json()),
            (FIELD_PROMPTS_KEY, self._llm_vm.field_prompts_to_json()),
        ]:
            result = await self._session.execute(
                select(GameSettingsModel).where(GameSettingsModel.key == key)
            )
            row = result.scalars().first()
            if row:
                row.value = value
            else:
                self._session.add(GameSettingsModel(key=key, value=value))
        await self._session.commit()

    async def shutdown(self) -> None:
        self._close_sheet_windows()
        if self._session:
            await self._session.close()
            self._session = None
        self._image_store = None
        set_image_dir(None)
        if self.engine:
            await self.engine.dispose()
            self.engine = None
        if self._llm_service is not None:
            await self._llm_service.provider.close()
            self._llm_service = None
            self._llm_vm = None
        if self._http is not None and not self._http.is_closed:
            # An injected client is owned by the caller — the app must not close it.
            if self._http is not self._http_injected:
                await self._http.close()
        self._http = None


def main():  # pragma: no cover — entry point: a second QApplication cannot be
    # instantiated in tests and run_forever() never returns, so it is exercised
    # by the manual smoke instead of the automated suite
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    application = Application(app)

    # Show launcher
    launcher = GameLauncherDialog()
    launcher.exec()
    if not launcher.selected_path:
        sys.exit(0)

    db_path = launcher.selected_path

    with loop:
        loop.run_until_complete(application.start(db_path))
        loop.run_forever()


if __name__ == "__main__":
    main()
