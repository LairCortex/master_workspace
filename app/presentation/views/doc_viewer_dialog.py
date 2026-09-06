"""Read-only documentation viewer — QML island (R3 pack 1)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QWidget

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.engine import QML_IMPORT_PATH, island_context, load_island, release_island
from app.presentation.theme import get_default_theme
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.viewmodels.doc_viewer_view_model import DocViewerViewModel

ROOT_QML = str(Path(QML_IMPORT_PATH) / "DocViewerRoot.qml")


class DocViewerDialog(QDialog):
    def __init__(
        self,
        title: str,
        file_path: Path,
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        super().__init__(parent)
        if theme is not None:
            self._theme = theme
        else:
            try:
                self._theme = get_default_theme()
            except Exception:
                from app.infrastructure.ui_prefs.config import UiPrefsManager
                from app.presentation.theme.compiler import tokens_file_path
                from app.presentation.theme.runtime import ThemeRuntime

                self._theme = ThemeRuntime(
                    prefs=UiPrefsManager(Path.home() / ".nri_manager" / "ui.json"),
                    tokens_path=tokens_file_path(),
                )
        self.setWindowTitle(title)
        self.setMinimumSize(640, 480)
        self.resize(720, 560)

        if file_path.exists():
            body = file_path.read_text(encoding="utf-8")
        else:
            body = f"Файл не найден: {file_path}"
        self.vm = DocViewerViewModel(body, parent=self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        engine = setup_qml_shell(QApplication.instance(), self._theme)
        self._engine = engine
        self.quick = QQuickWidget(engine, self)
        self.quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self._palette = QmlPalette(self._theme, parent=self)
        # Dialog-owned context (never the shared engine root): a name written
        # there is nulled for every other island when this dialog dies.
        self._context = island_context(
            engine, self, docViewerVm=self.vm, islandPalette=self._palette
        )
        self._palette.setParent(self._context)
        self._component = load_island(self.quick, self._context, ROOT_QML)
        assert self.quick.status() == QQuickWidget.Status.Ready, self.quick.errors()
        layout.addWidget(self.quick)

    def _release_island(self) -> None:
        release_island(self.quick)

    def done(self, result: int) -> None:
        QTimer.singleShot(0, self, self._release_island)
        super().done(result)
