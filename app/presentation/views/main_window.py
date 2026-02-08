"""Main application window."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QDialog, QMainWindow, QMenuBar, QPlainTextEdit,
    QSplitter, QVBoxLayout, QWidget,
)

from app.presentation.views.detail_panel import DetailPanel
from app.presentation.views.search_bar import SearchBar
from app.presentation.views.timeline_widget import TimelineWidget
from app.presentation.views.world_snapshot_widget import WorldSnapshotWidget


def _docs_dir() -> Path:
    """Return path to docs/ directory (works in dev and frozen builds)."""
    if getattr(sys, "frozen", False):
        # PyInstaller 6.x: datas go into _internal/ next to the executable
        base = Path(sys.executable).resolve().parent
        for candidate in [
            base / "_internal" / "docs",
            base / "docs",
        ]:
            if candidate.is_dir():
                return candidate
        return base / "_internal" / "docs"  # fallback
    return Path(__file__).resolve().parent.parent.parent.parent / "docs"


class _DocViewerDialog(QDialog):
    """Read-only dialog that shows a text/markdown file."""

    def __init__(self, title: str, file_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(640, 480)
        self.resize(720, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        text_edit = QPlainTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setFont(QFont("Menlo, Consolas, monospace", 11))
        text_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

        if file_path.exists():
            text_edit.setPlainText(file_path.read_text(encoding="utf-8"))
        else:
            text_edit.setPlainText(f"Файл не найден: {file_path}")

        layout.addWidget(text_edit)


class MainWindow(QMainWindow):
    switch_game_requested = Signal()
    export_requested = Signal()

    def __init__(
        self,
        timeline_vm,
        detail_vm,
        search_vm,
        game_name: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._base_title = "НРИ Сценарий Менеджер"
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

        # О приложении
        about_menu = menu_bar.addMenu("О приложении")
        self.readme_action = QAction("Документация", self)
        self.readme_action.triggered.connect(self._show_readme)
        about_menu.addAction(self.readme_action)

        self.changelog_action = QAction("Changelog", self)
        self.changelog_action.triggered.connect(self._show_changelog)
        about_menu.addAction(self.changelog_action)

        self.setMenuBar(menu_bar)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        self.search_bar = SearchBar(search_vm)
        main_layout.addWidget(self.search_bar)

        splitter = QSplitter()
        self.timeline_widget = TimelineWidget(timeline_vm)
        self.detail_panel = DetailPanel(detail_vm)
        self.world_snapshot = WorldSnapshotWidget()
        splitter.addWidget(self.timeline_widget)
        splitter.addWidget(self.detail_panel)
        splitter.addWidget(self.world_snapshot)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 2)
        main_layout.addWidget(splitter, 1)

    def set_game_name(self, name: str) -> None:
        if name:
            self.setWindowTitle(f"{self._base_title} — {name}")
        else:
            self.setWindowTitle(self._base_title)

    # ------ О приложении ------

    def _show_readme(self) -> None:
        dlg = _DocViewerDialog("Документация", _docs_dir() / "README.md", parent=self)
        dlg.open()

    def _show_changelog(self) -> None:
        dlg = _DocViewerDialog("Changelog", _docs_dir() / "CHANGELOG.md", parent=self)
        dlg.open()
