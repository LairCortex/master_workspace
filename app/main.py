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
from app.application.services.current_date_service import CurrentDateService
from app.application.services.preview_pins_service import PreviewPinsService
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
from app.presentation.geometry_memory import WindowGeometryMemory
from app.presentation.wiring import ApplicationWiring

from app.presentation.viewmodels.timeline_viewmodel import TimelineViewModel
from app.presentation.viewmodels.detail_viewmodel import DetailViewModel
from app.presentation.viewmodels.now_date_view_model import NowDateViewModel
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
from app.presentation.views.game_launcher_dialog import (
    GameLauncherDialog,
    GameSwitchSheet,
)
from app.presentation.theme import ThemeRuntime, get_default_theme
from app.presentation.qml import setup_qml_shell
from app.presentation.views.llm_setup_dialog import LlmSetupDialog
from app.presentation.sheet_windows import SheetWindowsManager
from app.presentation.views.table_host.cluster import TableCluster
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
        # NRI-0021 (design Д2): the game's «now» — a game-bound holder built
        # and loaded per start() after the calendar became active, so a game
        # switch can never carry the previous game's value over.
        self._current_date_service: CurrentDateService | None = None
        # NRI-0025 (task 1.2, design Д3): the preview column's pins — a thin
        # game-bound storage service built per start() on the same unit; the
        # connector reads it at game open and writes on every pin/unpin.
        self._preview_pins_service: PreviewPinsService | None = None
        # Calendar wizard (C4, task 7.1): the one dialog at a time. Since
        # NRI-0024 (task 3.1) it is a sheet of the connector's stack, opened
        # through the very menu path; the first-entry one (NRI-0015 task 2.4)
        # rides the same builder, deferred after start() instead of an
        # exec() nested inside it (W3/FI-6); its close step is the finish
        # task below.
        self._calendar_wizard: CalendarWizardDialog | None = None
        # PR-010: the one corruption warning per game open, raised deferred
        # (after the window shows) through a modeless show() on the shared
        # loop — the live ref keeps it out of Qt's garbage between
        # scheduling and show.
        self._calendar_warning: QMessageBox | None = None
        self._first_run_finish: asyncio.Future | None = None
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
        # NRI-0024 (task 5.2, re-docked by the owner ruling 2026-10-05): the
        # live table cluster docked into THIS game's window, as a child row
        # between the search bar and the columns.
        self._table_cluster: TableCluster | None = None
        # NRI-0015 (design T3): the geometry memory of the named windows
        # (main, sheet list/editor/fill) rides the one ui.json manager the
        # theme already owns; the memory lives for the process, so a
        # reopened role returns to its remembered placement. Retired roles
        # (NRI-0024 task 6.1) are never attached; stale keys they left in
        # ui.json are silently ignored.
        self._geometries = WindowGeometryMemory(self._theme.prefs)

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
        """Open ``db_path`` and show its main window (the process startup and
        every game opening run through here; the switch confirmation calls
        the same builder under its own name, task 4.2)."""
        return await self._build_main_window(db_path)

    async def _build_main_window(self, db_path: str) -> MainWindow:
        """Build the whole per-game composition and show its main window.

        Startup order (design D1/D7/D8): migrate a legacy flat ``.db`` into
        its catalog directory first (game name = directory name from then
        on) → schema + legacy-image migration → restore the storage
        invariant (``startup_gc``) → build layers → show the window.

        NRI-0024 (task 4.2, design Д4): this is the one factory of the
        composition — extracted verbatim out of ``start`` so the game-switch
        flow rebuilds the NEXT game through the very same chain (same
        factories, same order, role "main" placement memory) after the old
        window's ``shutdown()`` and :meth:`shutdown` ran. No process restart:
        the window object is replaced inside the live loop.
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
        # PR-010: the reasons are collected here but the window is NOT shown
        # here — a static ``QMessageBox.warning`` on this contour nested a
        # modal loop inside the still-pending start task and killed qasync
        # («Event loop stopped before Future completed») before the window
        # ever painted.  The fact rides to the deferred show below, the same
        # ``call_soon`` channel the first-run wizard already uses (W3/FI-6).
        corruption_body = (
            calendar_corruption_body(outcome.reasons) if outcome.reasons else None
        )

        # C3a (design D8): the game-open sweep of the six dated tables —
        # repair corrupted coordinate texts, shift coordinates invalid in
        # the just-activated calendar (every move logged), then re-align the
        # stored era keys — all before any repository or view model reads
        # dates.  Idempotent; a no-op on a standard game.
        await self._calendar_service.sweep_dated_records(self._session)

        # NRI-0021 (design Д2): the game's «now» loads right after the
        # calendar became active — its stored coordinate is read against the
        # calendar the game actually lives on (an out-of-range value from a
        # calendar switch reads as absent, Д1).  Absence seeds the real
        # today in memory; no key is written before the master's first edit.
        self._current_date_service = CurrentDateService(self._uow)
        await self._current_date_service.load()

        # NRI-0025 (task 1.2, design Д3): the preview-pins storage face on the
        # SAME unit every write shares.  Nothing is read or written here —
        # the connector loads the saved list at game open (group 5); the
        # composition root only names the concrete class (design D7).
        self._preview_pins_service = PreviewPinsService(self._uow)

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
        # NRI-0021 (task 3.1, design Д2): the widget VM mirrors the value the
        # service loaded above — the composition root is the one place that
        # pairs them; the island sees the VM as ``nowDateVm``, the connector
        # runs the popup/write flow against it (groups 4–6 subscribe to its
        # ``nowChanged`` through this wiring too).
        now_date_vm = NowDateViewModel(
            self._current_date_service.value.coord,
            self._current_date_service.value.is_bc,
            self._current_date_service.value.hour,
        )
        # NRI-0021 (tasks 5.1–5.2, design Д6): the timeline reads the same VM
        # for the today-outline flag, the «➜ Сейчас» availability/target and
        # the popover's game-«now» page.
        timeline_vm = TimelineViewModel(event_service, now_vm=now_date_vm)
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
            now_date_vm=now_date_vm,
        )

        self._search_service = search_service

        # Wire signals
        self._wiring = ApplicationWiring(
            self, window, timeline_vm, detail_vm, search_vm, event_dialog_vm, event_service,
            uow=self._uow,
            # NRI-0021 (task 2.3): the loaded «now» reaches the presentation
            # through the connector — the date widget's VM (group 3) and the
            # derived surfaces read and edit it via this wiring.
            current_date_service=self._current_date_service,
            # NRI-0021 (task 3.3): the same VM the island shows — the
            # connector wires its popup request and the applied-value slot.
            now_date_vm=now_date_vm,
            # NRI-0025 (task 5.2, design Д3): the pin-list storage face —
            # the connector reads it at open below and writes every pin/unpin.
            preview_pins_service=self._preview_pins_service,
        )
        self._wiring.connect()
        # NRI-0025 (task 5.2, design Д3): the saved pins load right after the
        # connector is live and before the window shows — unavailable pairs
        # are silently dropped there, storage stays untouched (no background
        # rewrite), the restored column paints with the window's first frame.
        await self._wiring.restore_preview_pins()

        # Switch game menu (NRI-0024 task 4.1: the entry opens a sheet, a
        # synchronous show path — no task until a game is actually chosen).
        window.switch_game_requested.connect(self._on_switch_game)

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
            # NRI-0015 (1.3): the list/editor/fill windows restore and
            # remember their placements through the same app-wide memory.
            geometries=self._geometries,
        )
        window.char_sheets_requested.connect(self._on_char_sheets)
        window.table_host_requested.connect(self._on_table_host)
        # The live desk controls docked into this window (NRI-0024 task 5.2's
        # Tool band, re-docked by the owner ruling 2026-10-05; the spec
        # «Управление столом живо в шапке главного окна» is retouched by the
        # next change): a child row between the search bar and the columns,
        # hugging the search row's right edge, visible only while the table
        # is up. Deliberate trade of the re-dock: under an open sheet the
        # panel is visible but unclickable — the sheet's block covers the
        # whole window content layer, this panel included. The desk caption
        # re-enters the same «Стол…» path (the connector's open_sheet raises
        # the live desk), the stop button rides the very stop the desk
        # button uses. The panel hides itself on every occupancy push (start
        # alone never pushes — the sync in _start_table covers that
        # transition) and dies with this window as its child.
        self._table_cluster = TableCluster(
            self._table_host, window, theme=self._theme,
        )
        window.attach_table_cluster(self._table_cluster)
        self._table_cluster.desk_requested.connect(self._on_table_host)
        self._table_cluster.stop_requested.connect(
            lambda: self._wiring.run_locked(self._stop_table())
        )

        # Calendar wizard (C4, task 7.1): the «Настройки → Календарь…» menu
        # entry, built over the live session by _wire_calendar_menu below.
        self._wire_calendar_menu(window)

        # First entry of a new game (C4, design D8; W3/NRI-0015 task 2.4):
        # start() only READS the decision through the live session.  The old
        # contour ran the wizard itself here (``await begin()`` + ``exec()``):
        # on the qasync loop the nested modal loop re-entered this very start
        # task («Cannot enter into task», FI-6) and the window never painted.
        # The wizard now opens deferred, right below ``window.show()``,
        # through the very builder the menu entry uses.
        first_run_wizard = await self._calendar_service.wizard_should_open_on_start(
            self._session
        )

        # Initial load
        await timeline_vm.load_events()
        window.timeline_widget.update_events(timeline_vm.events)

        # Replace old window if switching (PR-002: the replacement retires
        # the old one for good — a hidden live window is the ghost cocoa
        # re-raises over the new one, see ``_retire_window``).
        if self._window is not None:
            self._retire_window()
        self._window = window
        # NRI-0015 (1.3): role "main" — remembered placement returns the
        # window where the user left it, clamped into a connected screen.
        # NRI-0019: the all-tabs-whole width provider retired — the tab strip
        # shrinks its captions with the column now, so a narrow saved frame
        # comes back exactly as saved.
        self._geometries.attach(window, "main")
        window.show()
        if corruption_body is not None:
            # PR-010: raised on the next loop pass over the SHOWN window —
            # exactly the wizard's first-run channel, never a nested loop.
            asyncio.get_running_loop().call_soon(
                self._show_calendar_corruption_warning, corruption_body
            )
        if first_run_wizard:
            # Deferred right after the window is on screen (task 2.4): the
            # next loop pass raises the wizard as a SHEET over the shown
            # window (task 3.2) — no nested event loop ever wraps start().
            asyncio.get_running_loop().call_soon(self._open_calendar_wizard, True)
        return window

    def _show_calendar_corruption_warning(self, body: str) -> None:
        """PR-010: the one warning per open about a damaged ``game_calendar``
        (spec «Окно не глотает молчание»), raised after the window is on
        screen through the same deferred channel as the first-run wizard.

        The box rides ``show()`` on the application's shared loop — the
        project's non-nesting show mechanism (AGENTS: no application dialog
        enters a nested event loop; the modeless show also keeps the main
        window workable while the reason stays on screen, unlike the former
        static ``QMessageBox.warning`` whose nested loop inside start()
        killed qasync).
        """
        box = QMessageBox(self._window)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(MONTH_WARNING_TITLE)
        box.setText(body)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        self._calendar_warning = box
        box.finished.connect(self._calendar_warning_finished)
        box.show()

    def _calendar_warning_finished(self, _result: int) -> None:
        """Drop the live ref of the closed corruption warning (the box dies
        with its parent window otherwise only until the next game open)."""
        self._calendar_warning = None

    def _on_export_game(self) -> None:
        """Export current game as .nri archive.

        Only the Qt shell (task 6.3): picking the destination and reporting
        the outcome. Naming and packing live in :class:`ExportService`.
        """
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        if not self._db_path:
            return
        service = ExportService(self._db_path)
        # A4 (NRI-0016): the panel opens in the CURRENT game's database
        # directory (``games/<name>/`` through the session, never a literal)
        # with the usual suggested name — the archive lands next to its
        # source without any manual navigation.
        start_path = Path(self._db_path).parent / service.suggested_file_name()
        dest, _ = QFileDialog.getSaveFileName(
            self._window,
            "Экспорт игры",
            str(start_path),
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

    def _on_switch_game(self) -> None:
        """«Сменить игру…» — the launcher as a SHEET of the connector's
        stack (NRI-0024 task 4.1, design Д1/Д2/Д4; spec game-launcher «Смена
        игры открывается лаунчером-листом»).

        The same launcher content the first screen shows (game list, «Новая
        игра», import, theme switches), wrapped in the sheet contract:
        header «Сменить игру…» with the cancel-equal «Закрыть» — closing
        without a choice lands back in the very same game, nothing touched.
        The show goes through the connector's one ``open_sheet`` path
        (attached native sheet over the main window, NonModal at Qt level —
        PR-012; stack-owned, released on
        ``finished``), so the stack gate keeps a second copy unreachable —
        the property the abolished registry and the old fresh-window factory
        each provided in their turn (Д2). The first-run chooser in ``main()``
        is untouched and stays modal («Первый экран остаётся модальным»).
        The chosen game re-enters the application through the same
        ``game_selected`` contract the first screen carries; :meth:`_on_game_selected`
        owns the guard + rebuild (task 4.2).
        """
        sheet = GameSwitchSheet(parent=self._window, theme=self._theme)
        sheet.game_selected.connect(
            lambda p: asyncio.ensure_future(self._on_game_selected(p))
        )
        self._wiring.open_sheet(sheet)

    async def _on_game_selected(self, path: str) -> None:
        """Confirm the chosen game (NRI-0024 task 4.2, design Д4): switch the
        application over to ``path`` WITHOUT a process restart, in the order
        the contract names:

        1. the unchanged unsaved-changes guard (a dirty character-sheet
           editor/fill asks through ``confirm_discard``; declining aborts —
           the sheet stays open and the game is untouched);
        2. the whole sheet stack comes down (``close_all_sheets`` — the
           switch sheet itself and any sheet that could sit over it);
        3. the table stops and the character-sheet windows close silently
           (the existing programmatic-close policy, NRI-0016 TB1);
        4. the old ``MainWindow`` runs its штатный ``shutdown()`` (islands
           released, theme subscription dropped by handle) and closes;
        5. :meth:`shutdown` closes the session/engine of the old game;
        6. ``_build_main_window`` — the same factories as the startup —
           builds the new ``MainWindow`` over the chosen base, role "main"
           (the remembered placement returns the replacement to the frame
           the user left).
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
        # Stack down first (task 4.2): the switch sheet was confirmed, so its
        # close is a result, not a cancel — and it leaves through the sheet's
        # own ``finished`` channel like any user close.
        # The switch is the one flow that intentionally empties the screen:
        # the stack comes down and the old window closes BEFORE the
        # replacement shows. Qt's quit-on-last-window-closed rule reads the
        # live window count when the hide lands, so on the running qasync
        # loop it fired ``lastWindowClosed`` → ``quit()`` → ``run_forever()``
        # returned mid-rebuild (the switch task never resumed: no new
        # window, no wizard — the 2026-10-02 hang of the sheet switch).
        # The rule is suspended for the windowless stretch and restored the
        # moment the replacement is on screen; every other exit path keeps
        # the normal rule (closing the main window still quits the app).
        self._qapp.setQuitOnLastWindowClosed(False)
        try:
            if self._wiring is not None:
                self._wiring.close_all_sheets()
            if self._table_host is not None and self._table_host.is_running:
                await self._table_host.stop()
            self._close_sheet_windows()
            # The old window's штатный teardown runs while its game is still
            # alive: islands unbind and the theme subscription leaves by handle
            # before the session under them closes (the leak the two-switch test
            # pins — the runtime outlives every window of every game).
            if self._window is not None:
                self._window.shutdown()
                self._retire_window()
            await self.shutdown()
            await self._build_main_window(path)
        finally:
            self._qapp.setQuitOnLastWindowClosed(True)

    def _retire_window(self) -> None:
        """Take the live ``MainWindow`` out of service for good (PR-002).

        A game switch replaces the window under role «main»; a bare
        ``close()`` only hid the old one and left it a live top-level — on
        cocoa the first native sheet opened afterwards re-raised that
        island-less husk as a black rectangle over the working window (the
        blocking defect of the 2026-10-03 full run). The window-class norm
        names no survivor: ``close()`` runs the штатный closeEvent teardown
        (idempotent with the earlier explicit ``shutdown()``) and
        ``WA_DeleteOnClose`` takes the native window — and with it every
        lingering child sheet of the old game — down with the deferred
        delete, so nothing can ever come back.
        """
        window = self._window
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        window.close()
        self._window = None

    # ── Calendar wizard (C4, tasks 7.1–7.3) ──────────────────────────────────

    def _wire_calendar_menu(self, window: MainWindow) -> None:
        """Connect the single «Настройки → Календарь…» wizard entry (task 7.1)."""
        window.calendar_wizard_requested.connect(self._on_calendar_wizard)

    def _on_calendar_wizard(self) -> None:
        """The «Настройки → Календарь…» menu entry: the wizard over the
        CURRENT session, preselecting nothing extra — the «seen» flag is
        never touched from here, only a first-entry close marks it (design D6).
        """
        self._open_calendar_wizard()

    def _open_calendar_wizard(self, first_entry: bool = False) -> None:
        """Open THE wizard (menu entry and the deferred first-run opening are
        one builder — W3, task 2.4) as a sheet of the connector's stack.

        The view model preselects the kind of the current calendar key
        (spec «Вход из меню доступен всегда»); with ``first_entry`` a freshly
        seeded game lives on the preset, and its close still runs the service
        close step (:meth:`_wizard_finished`). The flow keeps its draft
        through the dialog by contract of the spec «Черновик мастера», so
        closing needs no extra handling.

        NRI-0024 (tasks 3.1/3.2, design Д6/Д7): the wizard lives on the
        application's sheet contract now — an attached native sheet over the
        main window (Qt.Sheet, NonModal at Qt level — PR-012)
        through the connector's one ``open_sheet`` path, the same way as the
        event dialogs and every translated sheet. Neither the menu entry nor
        the deferred first-run opening ever enters a nested event loop, and
        the stack gate (task 1.2) makes a second copy unreachable — the
        old raise-the-live-wizard branch retired together with that gate.
        """
        if (
            self._calendar_service is None
            or self._session is None
            or self._wiring is None
        ):
            return
        wizard_vm = CalendarWizardViewModel(
            self._uow, self._calendar_service, first_entry=first_entry,
        )
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
            lambda _r, _d=dialog, _f=first_entry: self._wizard_finished(_d, _f)
        )
        self._calendar_wizard = dialog
        # NRI-0024 task 3.1: the one sheet show path (open(), stack-owned,
        # released on ``finished``) — no nested event loop, no application-
        # modal top-level; the stack dim and the menu gate come with it.
        self._wiring.open_sheet(dialog)
        # Draft continuation (spec «Черновик мастера») reads the session —
        # a locked spawn; its state_changed repaints the already-visible
        # dialog onto the saved stage. On the first run this is the moment
        # the wizard sheet rises over the ALREADY SHOWN window (task 3.2).
        self._wiring.run_locked(dialog.begin())

    def _wizard_finished(self, dialog: CalendarWizardDialog, first_entry: bool) -> None:
        """Drop the closed wizard; a FIRST-ENTRY close carries the C4 close
        step (draft-left / already-applied / close-as-preset — all in the
        service).  Since W3 the step runs as a locked, tracked task instead
        of an awaited call behind a nested exec(): on the boot contour the
        session is still live, and :meth:`shutdown` awaits this future before
        the session closes (FI-6 «флаг не дописывается» must not return)."""
        self._forget_calendar_wizard(dialog)
        if not first_entry:
            return
        if self._calendar_service is None or self._session is None:
            return
        self._first_run_finish = self._wiring.run_locked(
            self._calendar_service.finish_first_run_flow(self._session)
        )

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

    # -- character sheets (D6) ------------------------------------------------
    # The window lifecycle itself — creation, single-window dirty confirms,
    # the ``deleteLater`` ownership — moved into :class:`SheetWindowsManager`
    # (audit B2, task 6.1). What stays below are thin delegates for the menu
    # wiring and the suite's e2e observers.

    def _close_sheet_windows(self) -> None:
        """Close the sheet windows and the table-host desk, without prompts."""
        if self._sheets is not None:
            self._sheets.close_windows()
        if self._table_host_panel is not None:
            # NRI-0024 (task 5.1, spec «Крест при работающем столе»): closing
            # the desk never asked since the sheet contract — the table stops
            # unconditionally on this path (the caller stops the service), and
            # the close here only hides the panel with the game.
            self._table_host_panel.close()
            self._table_host_panel = None

    def _on_char_sheets(self) -> None:
        """Show (or create) the non-modal sheet list window."""
        if self._sheets is not None:
            self._sheets.on_char_sheets()

    def _on_table_host(self) -> None:
        """«Стол…» — the desk as a sheet of the connector's stack (NRI-0024
        task 5.1, design Д5/Д6; spec character-sheet-host «пульт стола SHALL
        жить листом внутри главного окна с шапкой «Стол»»).

        The table session belongs to the service, not to the dialog: closing
        the sheet hides the desk and stops nothing, so the panel instance
        lives for the game — it is also the single subscriber of the
        service's occupancy pushes. A re-entry re-opens the very same desk
        through ``open_sheet`` (the reopen contour of the connector) and the
        refresh below paints the LIVE requisites: port, PIN, URLs, players.
        Sheets keep no placement, so the old ``table_host`` geometry role is
        not attached any more.
        """
        if (
            self._table_host is None
            or self._window is None
            or self._wiring is None
        ):
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
        self._wiring.open_sheet(self._table_host_panel)
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
        if self._table_cluster is not None:
            # The one start-side sync: start() clears the occupancy without a
            # push, so the cluster raises from this explicit call (task 5.2).
            self._table_cluster.sync_running()
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
        """Open the LLM setup as a sheet (NRI-0024 task 2.3, design Д1/Д2).

        The three-class contract moves «Настройка LLM…» from the non-modal
        window family into the sheet one: the dialog is a SheetFrame sheet
        shown through the connector's one ``open_sheet`` path — an attached
        native sheet over the main window (Qt.Sheet, NonModal at Qt level —
        PR-012),
        owned by the sheet stack, released on
        ``finished``. While the stack is up this entry itself is gated, so a
        second copy is unreachable by construction — the property the
        abolished registry used to provide (Д2). The wizard content, its
        footer «Закрыть», the «N из M» counter and the running-save close
        guard are untouched by the container move.
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
            return dialog

        self._wiring.open_sheet(make_setup())

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
        # NRI-0022 (task 2.1) + NRI-0024 (tasks 1.3, 2.4): the «Обзор мира»
        # sheet is session-bound (its date query and entity activation run on
        # THIS game's wiring), so it leaves with the game exactly the way the
        # retired panel used to leave with the old main window. Since the
        # open-window registry was abolished the connector owns the live
        # sheet; closing it fires the wrapper's done(): the island unbinds
        # one turn later — a stale sheet can never be raised over the next
        # game.
        if self._wiring is not None:
            self._wiring.close_snapshot_sheet()
        # A wizard left open on a closing game must not outlive its session:
        # its view model is bound to exactly this AsyncSession.  Closing it
        # here fires the first-run close step (task 2.4) — the future it
        # produced is awaited right below, through the STILL-LIVE session.
        if self._calendar_wizard is not None:
            self._calendar_wizard.close()
            self._calendar_wizard = None
        if self._first_run_finish is not None:
            await self._first_run_finish
            self._first_run_finish = None
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


def _run_game_session(application: Application, loop: QEventLoop, db_path: str) -> None:
    """The ordinary game-session sequence of ``main``: start, run, leave.

    PR-007: everything ``start`` opened leaves through ``shutdown``. The
    exit used to stop at ``run_forever`` — the game's single shared
    ``AsyncSession`` was still holding its pooled connection when the loop
    closed, so the interpreter's collector terminated it through the pool
    (the «The garbage collector is trying to clean up non-checked-in
    connection» error + SAWarning in the journal on every штатный Cmd+Q).
    ``shutdown`` runs on the still-open loop after the last window's quit,
    its awaits real: the session closes, the engine pool is disposed
    (awaited — aiosqlite's worker threads are joined through it), the HTTP
    client shuts down; nothing SQLAlchemy survives for the collector.
    """
    loop.run_until_complete(application.start(db_path))
    loop.run_forever()
    loop.run_until_complete(application.shutdown())


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
    # Product name everywhere Qt falls back to the application name. It does
    # NOT rename the macOS Dock/menu label of a source checkout: without a
    # bundle, LaunchServices attributes the process to the interpreter's own
    # bundle (Homebrew's Python.app), and no runtime call can override that —
    # the label there is carried by a bundle plist: the release .app of
    # nri_manager.spec or the dev wrapper of dev_run.py.
    app.setApplicationName("Master Workspace")
    # Desktop identity: the freedesktop desktop-entry name (icon matching on
    # Linux) and — explicitly on Windows, where Qt may otherwise group the
    # taskbar button under python.exe — the AppUserModelID of this process.
    app.setDesktopFileName("com.nri.scenario-manager")
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "com.nri.scenario-manager"
        )
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
        _run_game_session(application, loop, db_path)


if __name__ == "__main__":
    main()
