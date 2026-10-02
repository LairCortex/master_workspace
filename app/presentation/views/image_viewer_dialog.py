"""Full-size image viewer — a sheet on SheetFrame (nri-0024 task 2.5).

The last blocking show of the app retires with this slice (design Д7): the
viewer joins the sheet family the way the documents did in task 2.2. The QML
island stays untouched as the content — the original at full size in its
Flickable, so an image bigger than the sheet is reachable by scroll (spec
image-display «Прокрутка крупного изображения»); the widget-side SheetFrame
carries the shared chrome (header «Просмотр изображения» + «Закрыть» = the
plain Esc cancel, the scrim duck the connector dims through), and
``ApplicationWiring.open_sheet`` owns the show: WindowModal over its opening
layer (panel, card or sheet — the parent chain is the stack), released on
the single ``finished`` channel, returning exactly to that layer (spec
«Закрытие окна просмотра»). The show rides ``open()`` — the qasync loop
never nests here (spec modal-sheets «Прикладные диалоги не входят во
вложенный цикл событий»).
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.dialog_image_provider import clear_dialog_pixmap, put_dialog_pixmap
from app.presentation.qml.island import QML_IMPORT_PATH, IslandDialogMixin
from app.presentation.theme import get_default_theme
from app.presentation.viewmodels.image_viewer_view_model import ImageViewerViewModel
from app.presentation.views.sheet_frame import SheetFrame

ROOT_QML = str(Path(QML_IMPORT_PATH) / "ImageViewerRoot.qml")


class ImageViewerDialog(IslandDialogMixin, SheetFrame):
    island_context_names = {"imageViewerVm": "vm"}

    def island_source(self) -> str:
        return ROOT_QML

    def __init__(
        self,
        original: QPixmap | None,
        preview: QPixmap | None = None,
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        self._theme = theme if theme is not None else get_default_theme()
        # The frame threads the sheet name into windowTitle AND the header
        # label (one value, the SheetFrame contract) and seats the scrim duck
        # for the connector's stack dim.
        super().__init__("Просмотр изображения", parent, self._theme)
        # Sheet default (design Д6): the former window's 720×600 — a sheet
        # never remembers a placement, every opening starts at this size.
        self.resize(720, 600)
        self._key = uuid4().hex

        self.vm = ImageViewerViewModel(parent=self)
        pixmap: QPixmap | None = None
        used_preview = False
        if original is not None and not original.isNull():
            pixmap = original
        elif preview is not None and not preview.isNull():
            pixmap = preview
            used_preview = True

        self._engine = setup_qml_shell(QApplication.instance(), self._theme)
        if pixmap is not None:
            put_dialog_pixmap(self._key, pixmap)
            self.vm.set_source(
                f"image://dialog/{self._key}",
                used_preview=used_preview,
                unavailable=False,
            )
        else:
            self.vm.set_source("", used_preview=False, unavailable=True)

        # Dialog-owned context (IslandDialogMixin): this viewer is opened over
        # live islands and released when its sheet closes, so a bridge of its
        # own in the shared engine root context would take their colors down.
        self.setup_island()
        self.add_content(self.quick)
        # The island's «Закрыть» keeps the outcome it always had (the sheet
        # closes = the Esc cancel); the frame's header button is its twin.
        self._root.closeRequested.connect(self.close)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — Qt API
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            marker = self._root.property("defaultButton") if self._root is not None else None
            clicked = getattr(marker, "clicked", None) if marker is not None else None
            if clicked is not None:
                clicked.emit()
                return
        super().keyPressEvent(event)

    def _release_island(self) -> None:
        clear_dialog_pixmap(self._key)
        super()._release_island()

    # Release scheduling (accept/reject/done/close) — IslandDialogMixin.
