"""Main application window."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog, QMainWindow, QMenuBar, QPlainTextEdit,
    QSplitter, QVBoxLayout, QWidget,
)

from app.presentation.theme import get_default_theme
from app.presentation.theme.catalog import attach_theme, set_role
from app.presentation.views.detail_panel import DetailPanel
from app.presentation.views.search_bar import SearchBar
from app.presentation.views.timeline_widget import TimelineWidget
from app.presentation.views.world_snapshot_widget import WorldSnapshotWidget

log = logging.getLogger(__name__)


_LOG_FILENAME = "nri_manager.log"


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent.parent


def _docs_dir() -> Path:
    """Return path to docs/ directory (works in dev and frozen builds)."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        # Candidates: next to exe, _internal/ next to exe,
        # macOS .app bundle: Contents/Resources/, Contents/Frameworks/
        candidates = [
            exe.parent / "_internal" / "docs",
            exe.parent / "docs",
            exe.parent.parent / "Resources" / "docs",
            exe.parent.parent / "Frameworks" / "docs",
        ]
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        return exe.parent / "_internal" / "docs"  # fallback
    return Path(__file__).resolve().parent.parent.parent.parent / "docs"


class _DocViewerDialog(QDialog):
    """Read-only dialog that shows a text/markdown file."""

    def __init__(
        self,
        title: str,
        file_path: Path,
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle(title)
        self.setMinimumSize(640, 480)
        self.resize(720, 560)

        outer = QVBoxLayout(self)
        # The chrome reaches the dialog edges so no OS-palette band frames it.
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.chrome = QWidget()
        self.chrome.setObjectName("docViewerChrome")  # identifier, not style
        outer.addWidget(self.chrome)
        layout = QVBoxLayout(self.chrome)
        layout.setContentsMargins(8, 8, 8, 8)

        text_edit = QPlainTextEdit()
        text_edit.setReadOnly(True)
        # The block gets field chrome + the monospace family from the
        # font.family.mono token (W2b). Inside the attached chrome the
        # [field][uiRoleMono] QSS rule carries the family and follows live
        # theme switches — an explicit setFont would override it and freeze
        # the old theme's family (W2b fix). Off-skin there is no sheet at
        # all, so the family is applied as an explicit font fallback (D7).
        set_role(text_edit, "field", mono=True)
        runtime = self._theme
        if runtime is None:
            try:
                runtime = get_default_theme()
            except Exception:  # no usable theme (off-skin test)
                runtime = None
        tokens = runtime.tokens if runtime is not None else None
        chrome_attached = self._theme is not None
        if tokens and not chrome_attached:
            font = text_edit.font()
            font.setFamilies(
                [f.strip() for f in tokens["font.family.mono"][runtime.theme].split(",")]
            )
            text_edit.setFont(font)
        text_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

        if file_path.exists():
            text_edit.setPlainText(file_path.read_text(encoding="utf-8"))
        else:
            text_edit.setPlainText(f"Файл не найден: {file_path}")

        layout.addWidget(text_edit)

        self._apply_theme()

    def _apply_theme(self) -> None:
        """One attach point: the chrome container carries the whole sheet (D1)."""
        if self._theme is not None:
            attach_theme(self.chrome, self._theme)
            self._theme.apply()


class MainWindow(QMainWindow):
    switch_game_requested = Signal()
    export_requested = Signal()
    month_settings_requested = Signal()
    llm_setup_requested = Signal()
    char_sheets_requested = Signal()
    table_host_requested = Signal()

    def __init__(
        self,
        timeline_vm,
        detail_vm,
        search_vm,
        llm_vm=None,
        game_name: str = "",
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        super().__init__(parent)
        self._base_title = "НРИ Сценарий Менеджер"
        self.llm_vm = llm_vm
        self._theme = theme
        self.set_game_name(game_name)
        self.setMinimumSize(1024, 680)

        # Menu bar
        menu_bar = QMenuBar(self)

        # Файл
        file_menu = menu_bar.addMenu("Файл")
        self.switch_game_action = QAction("Сменить игру", self)
        self.switch_game_action.triggered.connect(self.switch_game_requested.emit)
        file_menu.addAction(self.switch_game_action)

        self.export_action = QAction("Экспорт игры…", self)
        self.export_action.triggered.connect(self.export_requested.emit)
        file_menu.addAction(self.export_action)

        # Чар-листы
        char_sheets_menu = menu_bar.addMenu("Чар-листы")
        self.char_sheets_action = QAction("Чар-листы…", self)
        self.char_sheets_action.triggered.connect(self.char_sheets_requested.emit)
        char_sheets_menu.addAction(self.char_sheets_action)
        self.table_host_action = QAction("Стол…", self)
        self.table_host_action.triggered.connect(self.table_host_requested.emit)
        char_sheets_menu.addAction(self.table_host_action)

        # Настройки
        settings_menu = menu_bar.addMenu("Настройки")
        self.month_settings_action = QAction("Названия месяцев…", self)
        self.month_settings_action.triggered.connect(self.month_settings_requested.emit)
        settings_menu.addAction(self.month_settings_action)

        # Theme toggle (design D5): checkable state mirrors the current theme;
        # with invalid tokens the runtime toggle is a no-op and the check
        # snaps back (D7).
        self.theme_toggle_action = QAction("Светлая тема", self)
        self.theme_toggle_action.setCheckable(True)
        self.theme_toggle_action.triggered.connect(self._on_theme_toggle)
        settings_menu.addAction(self.theme_toggle_action)
        settings_menu.addSeparator()
        self._sync_theme_action()

        # Импорт из .xlsx
        self.import_events_action = QAction("Импорт событий из .xlsx…", self)
        settings_menu.addAction(self.import_events_action)
        self.import_characters_action = QAction("Импорт персонажей из .xlsx…", self)
        settings_menu.addAction(self.import_characters_action)
        self.import_locations_action = QAction("Импорт локаций из .xlsx…", self)
        settings_menu.addAction(self.import_locations_action)
        self.import_organizations_action = QAction("Импорт организаций из .xlsx…", self)
        settings_menu.addAction(self.import_organizations_action)
        self.import_items_action = QAction("Импорт предметов из .xlsx…", self)
        settings_menu.addAction(self.import_items_action)

        # LLM
        llm_menu = menu_bar.addMenu("LLM")
        self.llm_setup_action = QAction("Настройка LLM…", self)
        self.llm_setup_action.triggered.connect(self.llm_setup_requested.emit)
        llm_menu.addAction(self.llm_setup_action)

        # О приложении
        about_menu = menu_bar.addMenu("О приложении")
        self.readme_action = QAction("Документация", self)
        self.readme_action.triggered.connect(self._show_readme)
        about_menu.addAction(self.readme_action)

        self.changelog_action = QAction("Changelog", self)
        self.changelog_action.triggered.connect(self._show_changelog)
        about_menu.addAction(self.changelog_action)

        about_menu.addSeparator()
        self.log_action = QAction("Сохранять логи в файл", self)
        self.log_action.setCheckable(True)
        self.log_action.setChecked(False)
        self.log_action.toggled.connect(self._on_log_toggle)
        about_menu.addAction(self.log_action)

        self._file_handler: logging.FileHandler | None = None

        menu_bar.setObjectName("themeMenu")  # test identifier, not a style hook (W2a)
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

        self.search_bar = SearchBar(search_vm, theme=self._theme)
        main_layout.addWidget(self.search_bar)

        splitter = QSplitter()
        splitter.setHandleWidth(4)
        # Handle color = the border token via the catalog splitter rule (W2b);
        # no OS-palette mid inline sheet anymore.
        set_role(splitter, "splitter")
        splitter.setChildrenCollapsible(False)
        self.timeline_widget = TimelineWidget(timeline_vm, theme=self._theme)
        self.detail_panel = DetailPanel(detail_vm, theme=self._theme)
        self.world_snapshot = WorldSnapshotWidget(theme=self._theme)
        self.timeline_widget.setMinimumWidth(220)
        self.detail_panel.setMinimumWidth(280)
        self.world_snapshot.setMinimumWidth(280)
        splitter.addWidget(self.timeline_widget)
        splitter.addWidget(self.detail_panel)
        splitter.addWidget(self.world_snapshot)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
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
            self._theme.add_listener(self._sync_theme_action)
            self._theme.apply()

    def set_game_name(self, name: str) -> None:
        if name:
            self.setWindowTitle(f"{self._base_title} — {name}")
        else:
            self.setWindowTitle(self._base_title)

    # ------ О приложении ------

    def _on_log_toggle(self, enabled: bool) -> None:
        root_logger = logging.getLogger()
        if enabled:
            log_path = _app_root() / _LOG_FILENAME
            self._file_handler = logging.FileHandler(
                str(log_path), encoding="utf-8",
            )
            self._file_handler.setLevel(logging.DEBUG)
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

    def _show_readme(self) -> None:
        dlg = _DocViewerDialog(
            "Документация", _docs_dir() / "README.md", parent=self, theme=self._theme,
        )
        dlg.open()

    def _show_changelog(self) -> None:
        dlg = _DocViewerDialog(
            "Changelog", _docs_dir() / "CHANGELOG.md", parent=self, theme=self._theme,
        )
        dlg.open()
