"""Read-only documentation viewer — QML island (R3 pack 1)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QWidget

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.island import QML_IMPORT_PATH, IslandDialogMixin
from app.presentation.theme import get_default_theme
from app.presentation.viewmodels.doc_viewer_view_model import DocViewerViewModel

ROOT_QML = str(Path(QML_IMPORT_PATH) / "DocViewerRoot.qml")


class DocViewerDialog(IslandDialogMixin, QDialog):
    island_context_names = {"docViewerVm": "vm"}

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
                # Fallback theme: the global ui_prefs file resolved by its own
                # settings family (no duplicated ~/.nri_manager spelling here).
                from app.infrastructure.ui_prefs.config import (
                    UiPrefsManager,
                    default_config_file,
                )
                from app.presentation.theme.compiler import tokens_file_path
                from app.presentation.theme.runtime import ThemeRuntime

                self._theme = ThemeRuntime(
                    prefs=UiPrefsManager(default_config_file()),
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

        self._engine = setup_qml_shell(QApplication.instance(), self._theme)
        self.setup_island()
        layout.addWidget(self.quick)

    # Island lifecycle (widget, context, deferred release) — IslandDialogMixin.

    def island_source(self) -> str:
        return ROOT_QML
