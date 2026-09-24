"""Application entry point — DI, qasync, startup."""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlEngine
from PySide6.QtWidgets import QApplication, QMessageBox
from qasync import QEventLoop

from app.infrastructure.db.database import create_engine, create_session_factory
from app.infrastructure.db.migrations import init_db
from app.infrastructure.db.game_manager import ensure_game_directory, get_db_url, get_images_dir
from app.infrastructure.db.uow import GameSessionUoW
from app.infrastructure.db.models import (
    CharacterModel,
    ItemModel,
    LocationModel,
    OrganizationModel,
)
from app.infrastructure.images.store import ImageStore
from app.infrastructure.localization import install_russian_localization
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.event_repository import EventRepository
from app.infrastructure.repositories.event_type_repository import EventTypeRepository
from app.infrastructure.repositories.dated_repository import dated_repository
from app.infrastructure.db.models import DescriptionModel

from app.application.services.event_service import EventService
from app.application.services.calendar_settings_service import (
    CalendarSettingsService,
)
from app.application.services.search_service import SearchService
from app.application.services.entity_service import EntityService
from app.application.services.export_service import ExportService
from app.application.services.llm_service import LlmService
from app.application.services.character_sheet_service import (
    CharacterSheetService,
)
from app.application.services.character_sheet_instance_service import (
    CharacterSheetInstanceService,
)
from app.application.services.table_host_service import (
    EmptySeatingError,
    PortBusyError,
    TableHostService,
)
from app.presentation.dialog_utils import confirm_discard
from app.presentation.ai_generation_controller import AiGenerationController
from app.presentation.wiring import ApplicationWiring

from app.presentation.viewmodels.timeline_viewmodel import TimelineViewModel
from app.presentation.viewmodels.detail_viewmodel import DetailViewModel
from app.presentation.viewmodels.search_viewmodel import SearchViewModel
from app.presentation.viewmodels.event_dialog_viewmodel import EventDialogViewModel
from app.presentation.viewmodels.llm_viewmodel import LlmViewModel

from app.domain.enums.entity_type import EntityType
from app.domain.game_calendar import (
    reset_current_calendar,
)
from app.presentation.utils.calendar_warnings import (
    MONTH_WARNING_TITLE,
    calendar_corruption_body,
)
from app.presentation.utils.image_utils import set_image_dir
from app.infrastructure.http import AppHttpClient
from app.infrastructure.llm.base_provider import BaseLlmProvider
from app.infrastructure.llm.config import LlmConfig, LlmConfigManager
from app.infrastructure.llm.remote_provider import RemoteLlmProvider
from app.presentation.views.main_window import MainWindow
from app.presentation.viewmodels.calendar_wizard_viewmodel import (
    CalendarWizardViewModel,
)
from app.presentation.views.calendar_wizard import CalendarWizardDialog
from app.presentation.views.game_launcher_dialog import GameLauncherDialog
from app.presentation.theme import ThemeRuntime, get_default_theme
from app.presentation.qml import setup_qml_shell
from app.presentation.views.llm_setup_dialog import LlmSetupDialog
from app.presentation.sheet_windows import SheetWindowsManager
from app.presentation.window_registry import (
    LAUNCHER_SWITCH_KEY,
    LLM_SETUP_KEY,
    MenuWindowRegistry,
)
from app.presentation.views.table_host.panel import TableHostPanel
from app.infrastructure.table_host.http import TableHostHttp, create_table_host_app
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)
from app.infrastructure.repositories.character_sheet_instance_repository import (
    CharacterSheetInstanceRepository,
)
from app.infrastructure.repositories.llm_settings_repository import (
    LlmSettingsRepository,
)

class Application:
    """Wires up DI and manages the application lifecycle."""

    def __init__(
        self,
        qapp: QApplication,
        http: AppHttpClient | None = None,
        theme: ThemeRuntime | None = None,
    ) -> None:
        """Wires up DI and manages the application lifecycle.

        ``http`` is the optional application-wide HTTP client (injected by
        tests with an emulated transport). When omitted the application
        creates and closes its own default client per start/shutdown cycle.
        ``theme`` injects a ThemeRuntime (tests redirect the preference
        file); when omitted the process-wide default is used.
        """
        self._qapp = qapp
        self.engine = None
        self.session_factory = None
        self._session = None
        self._window: MainWindow | None = None
        self._db_path: str | None = None
        self._image_store: ImageStore | None = None
        # QML shell (design D2): the one process engine, built in start(),
        # survives game switches; islands are handed it like the theme.
        self._qml_engine: QQmlEngine | None = None

        self._config_manager = LlmConfigManager()
        # Design tokens theme (W1): one runtime for Qt chrome and table CSS.
        self._theme: ThemeRuntime = theme or get_default_theme()
        # W2a D2: the runtime owns the popup sheet (tooltips, menus, combo
        # lists, calendar, mentions) app-wide; it is (re)pushed from apply()/
        # set_theme() whenever the compiled text changes.
        self._theme.attach_app(qapp)
        self._http_injected: AppHttpClient | None = http
        self._http: AppHttpClient | None = None
        self._llm_service: LlmService | None = None
        self._llm_vm: LlmViewModel | None = None
        # AI generation orchestration (audit B1, design D6): built per game
        # with the ViewModel it drives; dialogs are wired through it.
        self._ai_controller: AiGenerationController | None = None
        # Entity service catalog — built once per game in start()
        self._entity_services: dict[str, EntityService] = {}
        # Game-calendar settings (C2, design D2): one stateless service per
        # process; start() loads the calendar and sweeps the dated records
        # with it (C3a, design D8 — repair, shift, key reconcile).
        self._calendar_service: CalendarSettingsService | None = None
        # Calendar wizard (C4, task 7.1): the one menu dialog at a time;
        # the first-entry modal (task 7.2) is transient and never stored
        # here — it dies inside start().
        self._calendar_wizard: CalendarWizardDialog | None = None
        self._wiring: ApplicationWiring | None = None
        # Character sheets (D6/D4): one service pair per game; the window
        # lifecycle (list + editor + fill, audit B2) lives in SheetWindowsManager,
        # built in start() once the wiring exists. The ``_sheet_*`` attributes
        # below stay as properties delegating to it (retained test-visible API).
        self._sheet_service: CharacterSheetService | None = None
        self._instance_service: CharacterSheetInstanceService | None = None
        self._sheets: SheetWindowsManager | None = None
        self._table_host: TableHostService | None = None
        self._table_host_panel: TableHostPanel | None = None
        # NRI-0014 (design D1): the one registry of single-instance menu
        # windows, built once and surviving game switches; start() hands it
        # to MainWindow, so the docs entries and the launcher switch entry
        # share the mechanism instead of re-inventing dedup per usage site.
        self._window_registry = MenuWindowRegistry()

    # The three window refs stay readable/writable under their historical
    # private names: the suite's e2e tests observe the open windows through
    # them, and the table-host flows reassign them (task 6.1, design D6).
    @property
    def _sheet_list_dialog(self):
        return self._sheets.list_dialog if self._sheets is not None else None

    @_sheet_list_dialog.setter
    def _sheet_list_dialog(self, dialog) -> None:
        if self._sheets is not None:
            self._sheets.list_dialog = dialog

    @property
    def _sheet_editor(self):
        return self._sheets.editor if self._sheets is not None else None

    @_sheet_editor.setter
    def _sheet_editor(self, editor) -> None:
        if self._sheets is not None:
            self._sheets.editor = editor

    @property
    def _sheet_fill(self):
        return self._sheets.fill if self._sheets is not None else None

    @_sheet_fill.setter
    def _sheet_fill(self, fill) -> None:
        if self._sheets is not None:
            self._sheets.fill = fill

    @property
    def qml_engine(self) -> QQmlEngine | None:
        """The shared QML engine, set once start() ran (design D2)."""
        return self._qml_engine

    async def start(self, db_path: str) -> MainWindow:
        """Initialize DB, create all layers, show main window.

        Startup order (design D1/D7/D8): migrate a legacy flat ``.db`` into
        its catalog directory first (game name = directory name from then
        on) → schema + legacy-image migration → restore the storage
        invariant (``startup_gc``) → build layers → show the window.
        """
        self._close_sheet_windows()
        # QML shell (design D2): the single process-wide engine, up before
        # any island can load — idempotent across game switches.
        self._qml_engine = setup_qml_shell(self._qapp, self._theme)
        db_path = str(ensure_game_directory(db_path))
        self._db_path = db_path
        db_url = get_db_url(db_path)
        self.engine = create_engine(db_url)
        self.session_factory = create_session_factory(self.engine)
        image_dir = get_images_dir(db_path)
        await init_db(self.engine, image_dir=image_dir)
        self._session = self.session_factory()
        # Wave 5 (design D4): one unit of work per game over the shared
        # session; it also owns the lock every session task serializes on.
        # Services and the connector receive this same unit, so every write
        # path finishes through one point with one non-reentrancy guard.
        self._uow = GameSessionUoW(self._session)
        self._image_store = ImageStore(self._session, image_dir)
        # The boot storage scan is a write like any other: it finishes through
        # the same unit of work as every user operation (task 5.11 — the store
        # itself no longer commits; its two former commit points live here
        # and in the services' post-write hooks).
        async with self._uow.transaction():
            await self._image_store.startup_gc()
        set_image_dir(image_dir)

        game_name = Path(db_path).parent.name

        # C2 (designs D2/D3): read the game's calendar setting, migrate the
        # legacy ``custom_months`` key once, and make the decoded calendar
        # active — before any view model or ``load_events`` touches month
        # captions or chronological keys.  A damaged value leaves its row
        # byte-identical and returns reasons (design D4); the caller shows
        # exactly one warning per open, so the service stays free of Qt.
        self._calendar_service = CalendarSettingsService()
        outcome = await self._calendar_service.load_and_apply(self._session)
        if outcome.reasons:
            QMessageBox.warning(
                None,
                MONTH_WARNING_TITLE,
                calendar_corruption_body(outcome.reasons),
            )

        # C3a (design D8): the game-open sweep of the six dated tables —
        # repair corrupted coordinate texts, shift coordinates invalid in
        # the just-activated calendar (every move logged), then re-align the
        # stored era keys — all before any repository or view model reads
        # dates.  Idempotent; a no-op on a standard game.
        await self._calendar_service.sweep_dated_records(self._session)

        # Repositories
        desc_repo = BaseRepository(self._session, DescriptionModel)
        event_repo = EventRepository(self._session)
        # The dated tables share one implementation (C4); the composition
        # root is the only place naming a model per repository.
        org_repo = dated_repository(OrganizationModel)(self._session)
        char_repo = dated_repository(CharacterModel)(self._session)
        item_repo = dated_repository(ItemModel)(self._session)
        loc_repo = dated_repository(LocationModel)(self._session)
        event_type_repo = EventTypeRepository(self._session)

        # Services
        self._entity_services = self._build_entity_services()
        event_service = EventService(
            event_repo=event_repo,
            description_repo=desc_repo,
            organization_service=self._entity_services["organization"],
            character_service=self._entity_services["character"],
            item_service=self._entity_services["item"],
            location_service=self._entity_services["location"],
            event_type_repo=event_type_repo,
            # Task 5.9: the SAME unit the entity services and the connector
            # share — one finish point, one non-reentrancy guard (design D4).
            uow=self._uow,
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

        # LLM: shared http client (injected in tests) + the ONE provider
        # factory (nri-0011, design D2): a closure over the client, handed to
        # both the service and the view model — presentation never names the
        # concrete provider class.
        self._http = self._http_injected if self._http_injected is not None else AppHttpClient()
        http_client = self._http

        def make_provider(config: LlmConfig) -> BaseLlmProvider:
            return RemoteLlmProvider(config, http_client)

        self._llm_service = LlmService(make_provider(LlmConfig()))
        self._llm_vm = LlmViewModel(self._llm_service, self._config_manager, make_provider)
        self._ai_controller = AiGenerationController(self._llm_vm, self._llm_service)

        # Load LLM settings
        await self._load_llm_settings()

        # Main window
        window = MainWindow(
            timeline_vm=timeline_vm,
            detail_vm=detail_vm,
            search_vm=search_vm,
            llm_vm=self._llm_vm,
            game_name=game_name,
            theme=self._theme,
            # NRI-0014 1.2: the window's docs entries and this application's
            # launcher entry share ONE open-window registry (design D1).
            window_registry=self._window_registry,
        )

        self._search_service = search_service

        # Wire signals
        self._wiring = ApplicationWiring(
            self, window, timeline_vm, detail_vm, search_vm, event_dialog_vm, event_service,
            uow=self._uow,
        )
        self._wiring.connect()

        # Switch game menu
        window.switch_game_requested.connect(lambda: asyncio.ensure_future(self._on_switch_game()))

        # Export game menu
        window.export_requested.connect(self._on_export_game)

        # LLM setup menu
        window.llm_setup_requested.connect(
            lambda: self._on_llm_setup(window)
        )

        # Character-sheet menu (D6): one service per game, repo→service DI.
        # The ImageStore is required: the service GCs the sheet-page image
        # references through the unit's post-write hooks after the save has
        # committed (design D6, task 5.11) — without it the files of
        # cleared/deleted sheet images are never removed in the running app.
        inst_repo = CharacterSheetInstanceRepository(self._session)
        self._sheet_service = CharacterSheetService(
            CharacterSheetRepository(self._session),
            image_store=self._image_store,
            instance_repo=inst_repo,
            uow=self._uow,
        )
        self._instance_service = CharacterSheetInstanceService(
            inst_repo, self._sheet_service, image_store=self._image_store,
            uow=self._uow,
        )
        self._table_host = TableHostService(
            self._instance_service,
            self._sheet_service,
            image_store=self._image_store,
        )
        self._table_host.set_http(
            TableHostHttp(create_table_host_app(self._table_host, theme=self._theme))
        )
        self._instance_service.set_seating_guard(self._table_host.is_seated)
        self._table_host.subscribe_values(self._on_host_values)
        self._table_host.subscribe_occupancy(self._sync_list_seated)
        # The sheet-window lifecycle (B2, task 6.1) is built once per game with
        # exactly the collaborators its flows touch; the wiring above already
        # exists, so the manager gets the real session-lock scheduler.
        self._sheets = SheetWindowsManager(
            sheet_service=self._sheet_service,
            instance_service=self._instance_service,
            character_service=self._entity_services["character"],
            image_store=self._image_store,
            theme=self._theme,
            window=window,
            table_host=self._table_host,
            spawn=self._wiring.run_locked,
            # Q14 (nri-0011, design D4): the editor/fill dialogs receive the
            # SAME unit — their image ingest commits through the single point.
            uow=self._uow,
        )
        window.char_sheets_requested.connect(self._on_char_sheets)
        window.table_host_requested.connect(self._on_table_host)

        # Calendar wizard (C4, task 7.1): the «Настройки → Календарь…» menu
        # entry, built over the live session by _wire_calendar_menu below.
        self._wire_calendar_menu(window)

        # First entry of a new game (C4, design D8): the seeded
        # «calendar_wizard_seen == "0"» runs the wizard modally after the
        # startup sweep and BEFORE the window is shown, so every surface's
        # first paint already speaks the calendar the open settled on.
        await self._maybe_show_calendar_wizard()

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
        """Export current game as .nri archive.

        Only the Qt shell (task 6.3): picking the destination and reporting
        the outcome. Naming and packing live in :class:`ExportService`.
        """
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        if not self._db_path:
            return
        service = ExportService(self._db_path)
        dest, _ = QFileDialog.getSaveFileName(
            self._window,
            "Экспорт игры",
            service.suggested_file_name(),
            "NRI архив (*.nri);;Все файлы (*)",
            # L1 (NRI-0014): the native panel is untranslatable and differs
            # between dev and the .app — always the Russian Qt panel.
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not dest:
            return
        try:
            service.run_export(dest)
            QMessageBox.information(
                self._window, "Экспорт", f"Игра «{service.game_name}» успешно экспортирована.",
            )
        except Exception as e:
            QMessageBox.critical(self._window, "Ошибка экспорта", str(e))

    async def _on_switch_game(self) -> None:
        """Show the launcher as a non-modal window, switch to the selected game.

        NRI-0014 3.1 (A1/A2, spec game-launcher «Формат лаунчера зависит от
        точки входа»): from «Сменить игру…» the launcher opens as a REAL
        non-modal window — titled, closable, the rest of the menu stays
        alive. (``QDialog.open()`` under a parent is a WindowModal sheet:
        no title bar, the menu silently greyed out — it contradicted this
        method's old "non-modal" comment, defect A1.) The first-run chooser
        in ``main()`` is untouched and stays modal. Presentation goes
        through the registry (key ``launcher_switch``, AB4): a repeated
        entry raises the live window instead of stacking, closing releases
        the key and returns to the same game. The switch mechanics are
        unchanged: the accepted dialog emits ``game_selected`` and the
        shutdown→start flow runs as before.
        """
        def make_launcher() -> GameLauncherDialog:
            dialog = GameLauncherDialog(parent=self._window, theme=self._theme)
            dialog.game_selected.connect(
                lambda p: asyncio.ensure_future(self._on_game_selected(p))
            )
            # Parent stays (taskbar/cohesion) but NOT window-modal: the
            # sheet format was the defect. show()+raise_() foreground the
            # fresh window on first open (the registry raises on reuse;
            # its own show() here is then a no-op).
            dialog.setWindowModality(Qt.WindowModality.NonModal)
            dialog.show()
            dialog.raise_()
            return dialog

        self._window_registry.open(LAUNCHER_SWITCH_KEY, make_launcher)

    async def _on_game_selected(self, path: str) -> None:
        """Game switch with the character-sheet windows (D6).

        A dirty editor is closed only after an explicit confirm, and then
        without ``update_pages``; the list closes unconditionally. Declining
        the prompt aborts the switch (the launcher stays open).
        """
        if self._sheet_editor is not None and self._sheet_editor.view_model.dirty:
            if not confirm_discard(
                self._window,
                "В макете чар-листа есть несохранённые правки. Сменить игру и "
                "закрыть редактор без сохранения?",
            ):
                return
        if self._sheet_fill is not None and self._sheet_fill.view_model.dirty:
            if not confirm_discard(
                self._window,
                "В заполненном листе есть несохранённые правки. Сменить игру и "
                "закрыть лист без сохранения?",
            ):
                return
        if self._table_host is not None and self._table_host.is_running:
            await self._table_host.stop()
        self._close_sheet_windows()
        await self.shutdown()
        await self.start(path)

    # ── Calendar wizard (C4, tasks 7.1–7.3) ──────────────────────────────────

    def _wire_calendar_menu(self, window: MainWindow) -> None:
        """Connect the single «Настройки → Календарь…» wizard entry (task 7.1)."""
        window.calendar_wizard_requested.connect(self._on_calendar_wizard)

    def _on_calendar_wizard(self) -> None:
        """Open the wizard modally over the CURRENT session.

        The view model preselects the kind of the current calendar key
        (spec «Вход из меню доступен всегда»), and the «seen» flag is never
        touched from here — only a first-entry application marks it (design
        D6). The flow keeps its draft through the dialog by contract of the
        spec «Черновик мастера», so closing needs no extra handling.
        """
        if self._calendar_service is None or self._session is None:
            return
        if self._calendar_wizard is not None:
            self._calendar_wizard.raise_()
            self._calendar_wizard.activateWindow()
            return
        wizard_vm = CalendarWizardViewModel(self._uow, self._calendar_service)
        dialog = CalendarWizardDialog(
            wizard_vm,
            parent=self._window,
            theme=self._theme,
            # Intents touch the shared session — serialize them on the wiring
            # lock exactly like every other signal-spawned task.
            run=self._wiring.run_locked,
        )
        # Propagation (design D11): a successful application repaints the
        # surfaces that are showing dates right now.
        wizard_vm.apply_succeeded.connect(
            lambda: self._wiring.run_locked(self._reload_after_calendar_change())
        )
        dialog.finished.connect(
            lambda _r, _d=dialog: self._forget_calendar_wizard(_d)
        )
        self._calendar_wizard = dialog
        # NRI-0014 D5/D6 (live audit D6): an own application-modal top-level,
        # not the parent-attached sheet `open()` gave (WindowModal; macOS drew
        # it sheet-style over the window, and the wizard being wider than the
        # window moved the main window on open). The parent stays for the
        # task bar; no nested event loop is entered here.
        dialog.setWindowModality(Qt.ApplicationModal)
        dialog.show()
        # Draft continuation (spec «Черновик мастера») reads the session —
        # a locked spawn; its state_changed repaints the already-visible
        # dialog onto the saved stage.
        self._wiring.run_locked(dialog.begin())

    def _forget_calendar_wizard(self, dialog: CalendarWizardDialog) -> None:
        """Drop the closed wizard and queue its C++ teardown."""
        if self._calendar_wizard is dialog:
            self._calendar_wizard = None
        dialog.deleteLater()

    async def _reload_after_calendar_change(self) -> None:
        """Design D11: repaint everything that shows dates, no restart.

        A freshly applied calendar is already active (promote_draft installed
        it after its commit) — here the timeline feed and the «Выбор даты»
        chip re-model through the ViewModel's load, the detail panel (which
        hosts the dated record's own header) rebuilds when one is open, and
        the table host panel refreshes when it is on screen. Popups and the
        dialogs' date captions read the calendar again at their next opening
        (the grids refresh on open_at), so they need nothing here.
        """
        window = self._window
        wiring = self._wiring
        if window is None or wiring is None:
            return
        timeline_vm = wiring.timeline_vm
        detail_vm = wiring.detail_vm
        await timeline_vm.load_events()
        window.timeline_widget.update_events(timeline_vm.events)
        if detail_vm.event is not None:
            await detail_vm.load_details(detail_vm.event.id)
            window.detail_panel.show_event(detail_vm.event)
        if self._table_host_panel is not None:
            await self._refresh_table_host_panel()

    async def _maybe_show_calendar_wizard(self) -> None:
        """First entry of a new game (task 7.2, design D8; task 6.3 thinned
        it — the status decision and the close step are service calls now,
        see :meth:`CalendarSettingsService.wizard_should_open_on_start`).

        The modal still runs before ``MainWindow.show()``; its prefilled kind
        is «Стандартный» because a freshly seeded game lives on the preset.
        """
        if not await self._calendar_service.wizard_should_open_on_start(
            self._session
        ):
            return
        wizard_vm = CalendarWizardViewModel(
            self._uow, self._calendar_service, first_entry=True,
        )
        dialog = CalendarWizardDialog(
            wizard_vm, theme=self._theme, run=self._wiring.run_locked,
        )
        # The draft decides the opening position, so it is read out before
        # the modal loop starts; no other session user exists yet — the
        # window is unshown and the startup coroutine still owns the session.
        await dialog.begin()
        dialog.exec()
        dialog.deleteLater()
        # Draft-left / already-applied / close-as-preset: all in the service.
        await self._calendar_service.finish_first_run_flow(self._session)

    # -- character sheets (D6) ------------------------------------------------
    # The window lifecycle itself — creation, single-window dirty confirms,
    # the ``deleteLater`` ownership — moved into :class:`SheetWindowsManager`
    # (audit B2, task 6.1). What stays below are thin delegates for the menu
    # wiring and the suite's e2e observers.

    def _close_sheet_windows(self) -> None:
        """Close the sheet windows and the table-host panel, without prompts."""
        if self._sheets is not None:
            self._sheets.close_windows()
        if self._table_host_panel is not None:
            self._table_host_panel.close()
            self._table_host_panel = None

    def _on_char_sheets(self) -> None:
        """Show (or create) the non-modal sheet list window."""
        if self._sheets is not None:
            self._sheets.on_char_sheets()

    def _on_table_host(self) -> None:
        if self._table_host is None or self._window is None:
            return
        if self._table_host_panel is None:
            panel = TableHostPanel(
                self._table_host, parent=self._window, theme=self._theme,
            )
            panel.start_requested.connect(
                lambda: self._wiring.run_locked(self._start_table())
            )
            panel.stop_requested.connect(
                lambda: self._wiring.run_locked(self._stop_table())
            )
            panel.player_selected.connect(self._on_host_player_selected)
            self._table_host_panel = panel
        self._table_host_panel.show()
        self._table_host_panel.raise_()
        self._table_host_panel.activateWindow()
        self._wiring.run_locked(self._refresh_table_host_panel())

    async def _refresh_table_host_panel(self) -> None:
        panel = self._table_host_panel
        host = self._table_host
        inst = self._instance_service
        if panel is None or host is None or inst is None:
            return
        rows = [(row.id, row.name) for row in await inst.list_instances()]
        panel.set_instances(rows)
        panel.sync_running()

    async def _start_table(self) -> None:
        host = self._table_host
        panel = self._table_host_panel
        if host is None or panel is None:
            return
        if self._sheet_fill is not None and self._sheet_fill.view_model.dirty:
            if not confirm_discard(
                self._window,
                "В заполненном листе есть несохранённые правки. Открыть стол и "
                "закрыть лист без сохранения?",
            ):
                return
            self._sheet_fill.force_close()
            self._sheet_fill = None
        elif self._sheet_fill is not None and not self._sheet_fill.view_model.read_only:
            self._sheet_fill.force_close()
            self._sheet_fill = None
        host.set_seating(panel.checked_seat_ids())
        try:
            await host.start(panel.selected_port())
        except (EmptySeatingError, PortBusyError, OSError) as exc:
            panel.show_start_error(exc)
            return
        panel.sync_running()
        self._sync_list_seated()
        if self._sheet_fill is not None:
            self._sheet_fill.set_read_only(True)

    async def _stop_table(self) -> None:
        host = self._table_host
        if host is None:
            return
        await host.stop()
        if self._table_host_panel is not None:
            self._table_host_panel.sync_running()
        if self._sheet_fill is not None:
            self._sheet_fill.set_read_only(False)
        self._sync_list_seated()

    def _sync_list_seated(self) -> None:
        if self._sheets is not None:
            self._sheets.sync_list_seated()

    def _on_host_player_selected(self, instance_id: int) -> None:
        if self._sheets is not None:
            self._sheets.on_host_player_selected(instance_id)

    def _on_host_values(self, instance_id: int, field_id: str, value) -> None:
        if self._sheets is not None:
            self._sheets.on_host_values(instance_id, field_id, value)

    async def _sheet_list_refresh(self) -> None:
        if self._sheets is not None:
            await self._sheets.sheet_list_refresh()

    def _on_instance_open(self, instance_id: int) -> None:
        if self._sheets is not None:
            self._sheets.on_instance_open(instance_id)

    async def _open_fill(self, instance_id: int) -> None:
        if self._sheets is not None:
            await self._sheets.open_fill(instance_id)

    def _on_instance_renamed(self, instance_id: int, name: str) -> None:
        if self._sheets is not None:
            self._sheets.on_instance_renamed(instance_id, name)

    def _on_design_saved(self, editor) -> None:
        if self._sheets is not None:
            self._sheets.on_design_saved(editor)

    async def _reload_fill_after_design(self, editor) -> None:
        if self._sheets is not None:
            await self._sheets.reload_fill_after_design(editor)

    async def _refresh_character_cards(self) -> None:
        if self._sheets is not None:
            await self._sheets.refresh_character_cards()

    def _wire_mentions_for_dialog(self, dialog, on_entity_click_fn):
        """Connect mention search and click signals for a dialog's mention proxies.

        Both signals touch the shared ``AsyncSession`` (search / entity load),
        so they must run through the connector's public ``run_locked`` like
        every other session-touching task — a bare ``ensure_future`` here
        would race the session against whatever task the lock is currently
        serializing.
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
                lambda q, _fn=_do_search: self._wiring.run_locked(_fn(q))
            )

        async def _on_mention_clicked(entity_type, entity_id):
            window = self._wiring.window
            if entity_type == "event":
                event = await self._wiring.event_service.get_event(entity_id)
                if event:
                    await self._wiring.open_event_editor(entity_id)
                    return
                QMessageBox.warning(window, "Упоминание", "Упоминание не найдено.")
                return
            svc = self._get_entity_service(entity_type)
            if svc is None:
                QMessageBox.warning(window, "Упоминание", "Упоминание не найдено.")
                return
            entity = await svc.get_entity(entity_id)
            if entity is None:
                QMessageBox.warning(window, "Упоминание", "Упоминание не найдено.")
                return
            await on_entity_click_fn(entity_type, entity_id)

        dialog.mention_clicked.connect(
            lambda t, i: self._wiring.run_locked(_on_mention_clicked(t, i))
        )

    def _get_entity_service(self, entity_type: str) -> EntityService | None:
        """Thin wrapper over the per-game service catalog."""
        return self._entity_services.get(entity_type)

    def _build_entity_services(self) -> dict[str, EntityService]:
        """Build the per-game catalog once (replaces per-call construction)."""
        desc_repo = BaseRepository(self._session, DescriptionModel)
        # type↔repository stays in the composition root (design D2); the keys
        # are EntityType members, not parallel string literals
        repo_map = {
            EntityType.ORGANIZATION: dated_repository(OrganizationModel)(self._session),
            EntityType.CHARACTER: dated_repository(CharacterModel)(self._session),
            EntityType.ITEM: dated_repository(ItemModel)(self._session),
            EntityType.LOCATION: dated_repository(LocationModel)(self._session),
        }
        services = {
            t.value: EntityService(
                repo=r, description_repo=desc_repo,
                image_store=self._image_store, uow=self._uow,
            )
            for t, r in repo_map.items()
        }
        for type_name, svc in services.items():
            svc.set_related_services(
                {t: s for t, s in services.items() if t != type_name},
            )
        return services

    def _wire_ai_buttons(self, dialog) -> None:
        """Route a dialog's AI-assist buttons through the generation controller.

        The whole orchestration moved to :class:`AiGenerationController`
        (audit finding B1, design D6); the composition root wires it in.
        """
        self._ai_controller.wire(dialog)

    def _on_llm_setup(self, window) -> None:
        """Show the LLM setup as a non-modal, single-instance window.

        NRI-0014 (spec qml-shell «Формат диалогов задан точкой входа», design
        D1): «Настройка LLM…» is one of the contract's non-modal windows —
        its windowTitle becomes a visible title bar, the native close
        button stays available and the rest of the menu stays alive while
        the config is read or edited (the old ``open()`` under the parent
        drew a sheet and greyed the menu — the AB3-class pattern). The
        registry holds the single instance (key ``llm_setup``): a repeated
        entry raises the open window instead of stacking a second one (AB4).
        """
        llm_vm = self._llm_vm

        def make_setup() -> LlmSetupDialog:
            dialog = LlmSetupDialog(
                config=llm_vm.config,
                world_prompt=llm_vm.world_prompt,
                field_prompts=llm_vm.field_prompts,
                llm_vm=llm_vm,
                parent=window,
                theme=self._theme,
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

            # The save touches the shared session (per-game prompts): schedule
            # it through the wiring's lock like every other session-touching
            # task — a raw ensure_future here raced that session with
            # concurrent dialog flows (audit Q14 scenario 6).
            dialog.saved.connect(lambda c, wp, fp: self._wiring.run_locked(_on_saved(c, wp, fp)))
            # Explicit NonModal pins the contract (the registry shows with
            # show(); open()-under-parent WindowModal was the defect); the
            # titled window already carries «Настройка AI-ассистента (LLM)».
            dialog.setWindowModality(Qt.WindowModality.NonModal)
            return dialog

        self._window_registry.open(LLM_SETUP_KEY, make_setup)

    async def _load_llm_settings(self) -> None:
        # Per-game prompts read through the infrastructure repository
        # (task 6.2): ``main`` no longer hand-rolls ``game_settings`` queries.
        try:
            repo = LlmSettingsRepository(self._session)
            world = await repo.load_world_prompt()
            if world is not None:
                self._llm_vm.world_prompt_from_json(world)
            fields = await repo.load_field_prompts()
            if fields is not None:
                self._llm_vm.field_prompts_from_json(fields)
        except Exception as exc:
            logging.getLogger("app.main").warning(
                "Failed to load LLM settings: %s", exc
            )

    async def _save_llm_settings(self) -> None:
        # Wave 5 (task 5.11): the per-game prompts upsert finishes through the
        # game's unit of work — commit on clean exit, rollback + re-raise on
        # any failure. The caller already holds the session lock (5.1), so the
        # transaction has the session to itself.
        async with self._uow.transaction():
            repo = LlmSettingsRepository(self._session)
            await repo.save_world_prompt(self._llm_vm.world_prompt_to_json())
            await repo.save_field_prompts(self._llm_vm.field_prompts_to_json())

    async def shutdown(self) -> None:
        # C2 (spec «Активный календарь в жизненном цикле игры»): closing the
        # game restores the «Стандартный» preset, so the next game can never
        # inherit this one's calendar.
        reset_current_calendar()
        if self._table_host is not None and self._table_host.is_running:
            await self._table_host.stop()
        self._close_sheet_windows()
        # A wizard left open on a closing game must not outlive its session:
        # its view model is bound to exactly this AsyncSession.
        if self._calendar_wizard is not None:
            self._calendar_wizard.close()
            self._calendar_wizard = None
        self._table_host = None
        # The sheet manager is game-bound too (its dialogs parent to this
        # game's window); ``_close_sheet_windows`` above already tore them down.
        self._sheets = None
        if self._session:
            await self._session.close()
            self._session = None
        self._uow = None
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
    # L1 (NRI-0014, spec interface-language): Russian standard elements from
    # the first window on — the one QTranslator(qtbase_ru) is installed right
    # here, before the launcher opens and before Application.__init__ builds
    # any chrome. The test suite mirrors this state via the session fixture in
    # tests/conftest.py.
    install_russian_localization(app)
    # Product name: the macOS app menu (a source checkout has no bundle plist,
    # so Qt reads this), plus any place Qt falls back to the application name.
    app.setApplicationName("Master Workspace")
    # Window/taskbar icon. The macOS .app gets its Dock icon from the bundle's
    # .icns; every other platform (and a source checkout) reads this PNG.
    app_icon = Path(__file__).resolve().parent / "resources" / "app_icon.png"
    if app_icon.exists():
        app.setWindowIcon(QIcon(str(app_icon)))
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    # One theme runtime for the whole process: launcher chrome, main window
    # chrome and the table host CSS all read from it (design D6).
    theme = get_default_theme()
    application = Application(app, theme=theme)

    # Push the app-wide popup sheet before the launcher opens. The launcher's
    # QML content is skinned by the palette (Q1), but its native popups —
    # QInputDialog / QMessageBox / QFileDialog — are widgets fed by this sheet;
    # the old widgets launcher used to trigger the push through its chrome.
    theme.apply()

    # Show launcher. Its content is a QML island (the constructor raises the
    # shared engine, idempotent with Application.start below — the launcher is
    # shown before start(), so it must set the shell up itself).
    launcher = GameLauncherDialog(theme=theme)
    launcher.exec()
    if not launcher.selected_path:
        sys.exit(0)

    db_path = launcher.selected_path

    with loop:
        loop.run_until_complete(application.start(db_path))
        loop.run_forever()


if __name__ == "__main__":
    main()
