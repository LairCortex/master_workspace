"""Read-only documentation viewer — a sheet on SheetFrame (nri-0024 task 2.2).

The three-class contract moves the last non-modal window family into the
sheet family: «Документация» and «Changelog» open as sheets over the main
window (design Д1: the content stays the documentation island, the widget-
side SheetFrame carries the shared sheet chrome). The header names the open
document (spec document-viewer «Документ опознаваем по оболочке») — one
windowTitle-threaded value — and its «Закрыть» performs exactly the Esc
cancel. The show contract (WindowModal over the parent, the connector's
sheet stack, the single release on ``finished``) is the connector's
``open_sheet`` — like every other sheet, the entry is gated while a sheet is
up, so a second copy of one document is unreachable by construction (Д2).
The island itself is untouched by the move: the same read-only mono text in
its ScrollView, so the whole document stays reachable by scroll (NRI-0014
task 2.1, defect AB1).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QWidget

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.island import QML_IMPORT_PATH, IslandDialogMixin
from app.presentation.theme import get_default_theme
from app.presentation.viewmodels.doc_viewer_view_model import DocViewerViewModel
from app.presentation.views.sheet_frame import SheetFrame

ROOT_QML = str(Path(QML_IMPORT_PATH) / "DocViewerRoot.qml")


class DocViewerDialog(IslandDialogMixin, SheetFrame):
    island_context_names = {"docViewerVm": "vm"}

    def __init__(
        self,
        title: str,
        file_path: Path,
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        if theme is None:
            try:
                theme = get_default_theme()
            except Exception:
                # Fallback theme: the global ui_prefs file resolved by its own
                # settings family (no duplicated ~/.nri_manager spelling here).
                from app.infrastructure.ui_prefs.config import (
                    UiPrefsManager,
                    default_config_file,
                )
                from app.presentation.theme.compiler import tokens_file_path
                from app.presentation.theme.runtime import ThemeRuntime

                theme = ThemeRuntime(
                    prefs=UiPrefsManager(default_config_file()),
                    tokens_path=tokens_file_path(),
                )
        # The frame threads the document name into windowTitle AND the header
        # label, and seats its scrim duck for the connector's stack dim.
        super().__init__(title, parent, theme)
        # NRI-0024 (design Д6): documents open as 720×620 sheets; a sheet
        # never remembers its placement, the minimum keeps the scroll area
        # usable when the main window is small.
        self.setMinimumSize(720, 480)
        self.resize(720, 620)

        if file_path.exists():
            body = file_path.read_text(encoding="utf-8")
        else:
            body = f"Файл не найден: {file_path}"
        self.vm = DocViewerViewModel(body, parent=self)

        self._engine = setup_qml_shell(QApplication.instance(), self._theme)
        self.setup_island()
        self.add_content(self.quick)

    # Island lifecycle (widget, context, deferred release) — IslandDialogMixin.

    def island_source(self) -> str:
        return ROOT_QML
