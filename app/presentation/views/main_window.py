"""Main application window."""
from __future__ import annotations

import logging
import logging.handlers

from PySide6.QtCore import QEvent, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QMenuBar, QSplitter, QVBoxLayout, QWidget,
)

from app import __version__
from app.infrastructure.paths import NRI_MANAGER_DIR
from app.presentation.theme.catalog import attach_theme, set_role
from app.presentation.views.detail_panel import DetailPanel
from app.presentation.views.entity_preview import EntityPreviewWidget
from app.presentation.views.search_bar import SearchBar
from app.presentation.views.timeline_island import TimelineWidget

log = logging.getLogger(__name__)


# NRI-0019: the splitter's panes share one modest usability floor —
# the tab strip stretches/shrinks with its column now (elided captions in a
# narrow pane), so the all-tabs-whole threshold no longer floors the panes;
# the number only keeps a dragged pane draggable back and clickable.
PANE_MIN_WIDTH = 220

# PR-012 (spec modal-sheets «действия, нацеленные на главный оконный слой,
# SHALL быть неактивны»): while the sheet stack is up, SPONTANEOUS pointer
# input aimed at the window's content layer is swallowed here — the same
# scope the native document-modality block has (it lives in the cocoa event
# delivery and only ever touches OS input), so the Qt-level channels that
# never passed through it (QTest, accessibility actions, ``sendEvent``) keep
# working exactly as they did under the old WindowModal sheet. On cocoa the
# attached sheet already blocks its parent at AppKit level; this gate is what
# holds the contract on every platform (and what the offscreen suite can see
# at all). Menu bar and native chrome stay live — the exceptions of the
# window class must be reachable from under a sheet.
_CONTENT_BLOCKED_INPUTS = frozenset(
    {
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseButtonRelease,
        QEvent.Type.MouseButtonDblClick,
        QEvent.Type.Wheel,
    }
)

_LOG_FILENAME = "nri_manager.log"
# AB5 (NRI-0016): the log lives in the one configuration home (paths.py),
# not next to the checkout/exe; ~2 MB × 3 archives bound its growth.
_LOG_MAX_BYTES = 2_000_000
_LOG_BACKUP_COUNT = 3


class MainWindow(QMainWindow):
    switch_game_requested = Signal()
    export_requested = Signal()
    llm_setup_requested = Signal()
    char_sheets_requested = Signal()
    table_host_requested = Signal()
    calendar_wizard_requested = Signal()
    # NRI-0022 (task 2.2, spec world-snapshot): «Обзор мира…» — the entry of
    # the snapshot's home (sheet since NRI-0024 task 2.4); the connector
    # answers with a fresh sheet (ApplicationWiring._connect_snapshot;
    # NRI-0024 task 1.3 retired the open-window registry, task 2.4 moved the
    # content into the sheet family).
    world_snapshot_requested = Signal()

    def __init__(
        self,
        timeline_vm,
        detail_vm,
        search_vm,
        llm_vm=None,
        game_name: str = "",
        parent: QWidget | None = None,
        theme=None,
        now_date_vm=None,
    ) -> None:
        super().__init__(parent)
        self._base_title = "Master Workspace"
        self.llm_vm = llm_vm
        self._theme = theme
        self.set_game_name(game_name)
        self.setMinimumSize(1024, 680)  # hard system floor (stays NRI-0015's)
        # NRI-0018 (design Д5, spec «Первый запуск шире прежнего минимума»):
        # with no remembered placement the window opens 1280×800 — the frame
        # every full tab caption reads whole at (role "main" in the geometry
        # memory replaces it when one is saved; the snapshot «Дата:» row the
        # number also carried left with the panel to its own window, NRI-0022).
        self.resize(1280, 800)

        # Menu bar
        menu_bar = QMenuBar(self)

        # Файл
        file_menu = menu_bar.addMenu("Файл")
        self.switch_game_action = QAction("Сменить игру…", self)
        self.switch_game_action.triggered.connect(self.switch_game_requested.emit)
        file_menu.addAction(self.switch_game_action)

        self.export_action = QAction("Экспорт игры…", self)
        self.export_action.triggered.connect(self.export_requested.emit)
        file_menu.addAction(self.export_action)

        # NRI-0022 (task 2.2), live-audit fix 2026-09-27 (FU-1): the entry
        # rides the working «Файл» submenu, not the bar itself — the macOS
        # cocoa bridge drops a top-level QAction that carries no submenu
        # (reproduced with a minimal PySide6 probe: the bare item never
        # reaches the NSMenu model, so the snapshot was unreachable from UI
        # on the target platform). Since NRI-0024 task 2.4 the spec calls the
        # entry «Обзор мира открывается листом из строки меню» and the entry
        # sits on the sheet-opening gate; the action text and the
        # world_snapshot_requested contract are unchanged; every other entry
        # of this menu bar reaches the user through a submenu too.
        self.world_snapshot_action = QAction("Обзор мира…", self)
        self.world_snapshot_action.triggered.connect(
            self.world_snapshot_requested.emit
        )
        file_menu.addAction(self.world_snapshot_action)

        # Чар-листы
        char_sheets_menu = menu_bar.addMenu("Чар-листы")
        self.char_sheets_action = QAction("Чар-листы…", self)
        self.char_sheets_action.triggered.connect(self.char_sheets_requested.emit)
        char_sheets_menu.addAction(self.char_sheets_action)
        self.table_host_action = QAction("Стол…", self)
        self.table_host_action.triggered.connect(self.table_host_requested.emit)
        char_sheets_menu.addAction(self.table_host_action)

        # Настройки — from piece C4 on this carries the calendar wizard:
        # «Календарь…» is its single manual entry (since NRI-0024 task 3.1
        # the wiring in ``Application`` opens it as a sheet over the live
        # game session).
        settings_menu = menu_bar.addMenu("Настройки")

        # Theme toggle (design D5): checkable state mirrors the current theme;
        # with invalid tokens the runtime toggle is a no-op and the check
        # snaps back (D7).
        self.theme_toggle_action = QAction("Светлая тема", self)
        self.theme_toggle_action.setCheckable(True)
        self.theme_toggle_action.triggered.connect(self._on_theme_toggle)
        settings_menu.addAction(self.theme_toggle_action)
        settings_menu.addSeparator()
        self._sync_theme_action()

        # Calendar wizard entry (C4, spec calendar-wizard «Точки входа
        # мастера»): available in every game, preset or custom, old or new.
        self.calendar_wizard_action = QAction("Календарь…", self)
        self.calendar_wizard_action.triggered.connect(
            self.calendar_wizard_requested.emit
        )
        settings_menu.addAction(self.calendar_wizard_action)

        # Импорт из .xlsx — один пункт вместо пяти по типам сущностей
        # (rework-xlsx-import: единый файл пяти листов).
        self.import_xlsx_action = QAction("Импорт из .xlsx…", self)
        settings_menu.addAction(self.import_xlsx_action)

        # LLM
        llm_menu = menu_bar.addMenu("LLM")
        self.llm_setup_action = QAction("Настройка LLM…", self)
        self.llm_setup_action.triggered.connect(self.llm_setup_requested.emit)
        llm_menu.addAction(self.llm_setup_action)

        # О приложении — the two doc entries carry no handler here: like
        # «Импорт из .xlsx…» their flow is the connector's sheet show path
        # (ApplicationWiring._connect_docs, NRI-0024 task 2.2), so the sheets
        # ride the stack and the gate below covers them.
        about_menu = menu_bar.addMenu("О приложении")
        self.readme_action = QAction("Документация", self)
        about_menu.addAction(self.readme_action)

        self.changelog_action = QAction("Changelog", self)
        about_menu.addAction(self.changelog_action)

        about_menu.addSeparator()
        self.log_action = QAction("Сохранять логи в файл", self)
        self.log_action.setCheckable(True)
        self.log_action.setChecked(False)
        self.log_action.toggled.connect(self._on_log_toggle)
        about_menu.addAction(self.log_action)

        # AB7 (NRI-0016, design V7): the one live place where the user reads
        # the version — a disabled display line, never Changelog-parsed and
        # never a literal; the number comes from app.__version__, which the
        # consistency test pins to pyproject.
        self.version_action = QAction(f"Версия {__version__}", self)
        self.version_action.setEnabled(False)
        about_menu.addAction(self.version_action)

        # NRI-0024 (task 1.2, design Д2, spec modal-sheets «Открытый лист
        # блокирует главное окно, но не окна-исключения»): the entries whose
        # content lives (or is moving, slice by slice) in a sheet. While the
        # connector's sheet stack is up they are deactivated — a sheet under
        # a sheet is unreachable by design, and this gate is also what keeps
        # sheets single-instance in place of the abolished window registry
        # (Д2). Not in the list on purpose: «Чар-листы…» (a window-class
        # exception, openable from under any sheet), «Экспорт игры…» (a
        # system-path file dialog), the theme/log checks and the version
        # display — none of them opens a sheet.
        self._sheet_opening_actions = (
            self.switch_game_action,
            self.world_snapshot_action,
            self.table_host_action,
            self.calendar_wizard_action,
            self.import_xlsx_action,
            self.llm_setup_action,
            self.readme_action,
            self.changelog_action,
        )

        self._file_handler: logging.handlers.RotatingFileHandler | None = None
        # D1 (NRI-0016): the runtime listener's handle, dropped in closeEvent
        # — a closed window must unsubscribe explicitly, not via the collector.
        self._theme_listener = None
        # PR-012: whether this window's content-input gate currently rides the
        # application queue. One install per rising stack, one removal per its
        # fall — the flag keeps a stray double ``True``/``False`` from
        # stacking or orphaning the filter.
        self._content_gate_installed = False

        menu_bar.setObjectName("themeMenu")  # test identifier, not a style hook (W2a)
        # NRI-0014 live audit (L2): Qt's macOS menu-role heuristic reads the
        # translated role words, and with the Russian QTranslator (L1) the
        # action «Настройка LLM…» matches the Preferences keyword — the role
        # promotes to its whole container menu and the native menu bar drops
        # the «LLM» item from the bar (reproduced: 6 bar items instead of 7,
        # the LLM menu vanished and a ghost «Настройки…» appeared in the app
        # menu). The app never asks for native special-menu items (About/
        # Preferences/Quit come from Qt's own defaults), so every menu action
        # is pinned to NoRole: titles stay verbatim on every platform.
        for top in menu_bar.actions():
            top.setMenuRole(QAction.MenuRole.NoRole)
            submenu = top.menu()
            if submenu is not None:
                for action in submenu.actions():
                    if action.menu() is None:  # plain item (separators have no role anyway)
                        action.setMenuRole(QAction.MenuRole.NoRole)
        self.setMenuBar(menu_bar)

        central = QWidget()
        # W2a: role-marked chrome containers (the QSS addresses [uiRole=...])
        # — QSS goes on the central widget and the menu bar only, never on
        # the QMainWindow itself, so dialogs parented to the window keep the
        # OS palette until their own migration.
        central.setObjectName("themeChrome")  # test identifier, not a style hook
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # NRI-0021 (task 3.2): the game's «now» VM joins the search island's
        # context (design Д4 — no new island, the row lives inside the search
        # panel above the field); a bare window without a game leaves it None
        # and the widget row stays hidden.
        self.search_bar = SearchBar(
            search_vm, theme=self._theme, now_date_vm=now_date_vm
        )
        main_layout.addWidget(self.search_bar)

        splitter = QSplitter()
        splitter.setHandleWidth(4)
        # Handle color = the border token via the catalog splitter rule (W2b);
        # no OS-palette mid inline sheet anymore.
        set_role(splitter, "splitter")
        splitter.setChildrenCollapsible(False)
        self.timeline_widget = TimelineWidget(timeline_vm, theme=self._theme)
        # NRI-0021 (task 4.1): the panel's derived texts (age lines, event
        # time suffix) count against the game's «now»; the VM reference stays
        # Python-side — the detail island's context keeps its one VM.
        self.detail_panel = DetailPanel(
            detail_vm, theme=self._theme, now_date_vm=now_date_vm
        )
        # NRI-0022 (task 2.4): the world-snapshot pane left the columns for
        # its own «Обзор мира…» window. Task 4.1 returns the freed third
        # column as the entity-preview island: readable card of the last
        # entity selected in the middle column (design D1 — the lifecycle
        # rule lives in the wiring, this window only hosts the pane).
        # NRI-0019: the tab strip now shares the panel's width between its
        # tabs (whole captions at the default column, elided ones in a narrow
        # one), so the all-tabs-whole threshold retired as the pane floor —
        # every pane keeps one shared usability minimum instead.
        self.entity_preview = EntityPreviewWidget(
            theme=self._theme, now_date_vm=now_date_vm
        )
        self.timeline_widget.setMinimumWidth(PANE_MIN_WIDTH)
        self.detail_panel.setMinimumWidth(PANE_MIN_WIDTH)
        self.entity_preview.setMinimumWidth(PANE_MIN_WIDTH)
        splitter.addWidget(self.timeline_widget)
        splitter.addWidget(self.detail_panel)
        splitter.addWidget(self.entity_preview)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        # PR-014: the default split must hold the spec scenario «Первый запуск
        # шире прежнего минимума» on the REAL layout, not just on a panel
        # measured in isolation. At the 1280 first-run frame the splitter gets
        # 1272 px (central margins 2×4), so the sum below plus the two 4 px
        # handles lands EXACTLY on it — no stretch surplus smears the nominal
        # split across the panes. The detail column carries the tab strip:
        # (434 − 8) / 4 = 106.5 px per equal share ≥ the longest natural
        # caption «Организации» (101.8 px measured offscreen), so every
        # caption reads whole at first launch (was: 390 → 99 px share →
        # «Организаци…»). The timeline keeps its 330; the preview keeps the
        # 500 inherited from the freed snapshot pane (NRI-0022).
        splitter.setSizes([330, 434, 500])
        main_layout.addWidget(splitter, 1)

        self._apply_theme()

    def _apply_theme(self) -> None:
        """Push the generated QSS onto the two chrome containers (design D4)."""
        if self._theme is not None:
            # W2a: attach_theme stamps the uiRole property + registers (the
            # objectNames stayed as test identifiers only).
            attach_theme(self.centralWidget(), self._theme)
            attach_theme(self.menuBar(), self._theme)
            # The check item mirrors the current theme even when some other
            # window switched it (e.g. the launcher on top of this window).
            self._theme_listener = self._theme.add_listener(self._sync_theme_action)
            self._theme.apply()

    def set_game_name(self, name: str) -> None:
        if name:
            self.setWindowTitle(f"{self._base_title} — {name}")
        else:
            self.setWindowTitle(self._base_title)

    def on_sheet_stack_changed(self, active: bool) -> None:
        """Sheet-stack gate (NRI-0024 task 1.2, design Д2; PR-012 widened it):
        the slot the connector's ``sheet_stack_changed`` feeds. With a sheet
        up, every entry that would open another sheet goes inactive, the
        window watches the application queue to swallow pointer input aimed
        at its content layer, and the main layer stays single-sheet; when the
        stack empties, both come back. Exception entries (char sheets, export,
        theme, docs) stay live by construction — they are NOT in the gated
        list, and with the sheet no longer a Qt-modal window (PR-012) the
        native menu bar keeps answering their enabled states. The window owns
        the entry list (its menu), the connector owns the stack — bound once
        in ApplicationWiring.connect(). The open→empty symmetry of
        ``sheet_stack_changed`` is what balances the filter install here:
        exactly one install per rising stack, one removal per its fall.
        """
        for action in self._sheet_opening_actions:
            action.setEnabled(not active)
        app = QApplication.instance()
        if active and not self._content_gate_installed:
            app.installEventFilter(self)
            self._content_gate_installed = True
        elif not active and self._content_gate_installed:
            app.removeEventFilter(self)
            self._content_gate_installed = False

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 — Qt API
        """PR-012's content block: installed only while the sheet stack is
        up (see :meth:`on_sheet_stack_changed`). SPONTANEOUS pointer input
        (press/release/double-click/wheel — what the real hardware produces)
        whose target lives under the central widget — the main content layer
        — never reaches it while a sheet covers the window; this mirrors the
        reach of the AppKit sheet block it replaces, so synthetic delivery
        (``sendEvent``, QTest-free harness probes) stays untouched. Anything
        else (the sheet's own widgets, native popups, the menu bar) passes
        untouched."""
        if (
            event.type() in _CONTENT_BLOCKED_INPUTS
            and event.spontaneous()
            and isinstance(obj, QWidget)
        ):
            central = self.centralWidget()
            if central is not None and (obj is central or central.isAncestorOf(obj)):
                return True
        return super().eventFilter(obj, event)

    def shutdown(self) -> None:
        """The window's штатный teardown (D1, NRI-0016; idempotent) — the
        game-switch slice (NRI-0024 task 4.2) names it explicitly: the old
        main window releases its islands and subscriptions before its game
        (and the replacement window) is built.

        D1: a game switch closes and replaces this window while the runtime
        outlives it — the theme subscription is released here by handle
        instead of leaning on the collector (spec app-logging «Слушатели
        состояния не переживают окно»). The island panels are child widgets,
        so no closeEvent of their own ever reaches them — the window releases
        them: each island unbinds its scene and drops its theme
        subscriptions (palette, panel view models) synchronously, before
        their C++ sides leave with this window. The world snapshot is not in
        this list anymore (NRI-0022 task 2.4): its sheet releases its own
        island when the connector takes it down.
        """
        if self._theme is not None:
            self._theme.remove_listener(self._theme_listener)
        self._theme_listener = None
        for island in (
            self.search_bar,
            self.timeline_widget,
            self.detail_panel,
            self.entity_preview,
        ):
            island.release_island()

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API
        # The ordinary leaving route runs the very same teardown (the game
        # switch may also call shutdown() explicitly earlier — idempotent on
        # re-close, islands unbind once and the None handle is a no-op).
        self.shutdown()
        super().closeEvent(event)

    # ------ О приложении ------

    def _on_log_toggle(self, enabled: bool) -> None:
        root_logger = logging.getLogger()
        if enabled:
            # AB5: the file lives under the app's config home, created on
            # demand; AB6: no handler.setLevel — the file inherits the
            # root-wide threshold and promises exactly what it will get.
            log_path = NRI_MANAGER_DIR / _LOG_FILENAME
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_handler = logging.handlers.RotatingFileHandler(
                str(log_path),
                maxBytes=_LOG_MAX_BYTES,
                backupCount=_LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
            self._file_handler.setFormatter(
                logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
            )
            root_logger.addHandler(self._file_handler)
            log.info("Логирование в файл включено: %s", log_path)
        else:
            if self._file_handler is not None:
                log.info("Логирование в файл выключено")
                root_logger.removeHandler(self._file_handler)
                self._file_handler.close()
                self._file_handler = None

    def _on_theme_toggle(self) -> None:
        """Settings-menu dark/light switch (design D5, D7 no-op on bad tokens)."""
        if self._theme is not None:
            self._theme.toggle()
        # The checkable item flipped itself on trigger; snap it back to the
        # real theme (a no-op toggle must not leave a lying check mark).
        self._sync_theme_action()

    def _sync_theme_action(self) -> None:
        """Checked state = light theme is active; snaps back when toggle is no-op."""
        light = self._theme is not None and self._theme.theme == "light"
        self.theme_toggle_action.blockSignals(True)
        self.theme_toggle_action.setChecked(light)
        self.theme_toggle_action.blockSignals(False)
