"""Full-size image viewer — QML island (R3 pack 1)."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QKeyEvent, QPixmap
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QWidget

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.dialog_image_provider import clear_dialog_pixmap, put_dialog_pixmap
from app.presentation.qml.engine import QML_IMPORT_PATH, island_context, load_island, release_island
from app.presentation.theme import get_default_theme
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.viewmodels.image_viewer_view_model import ImageViewerViewModel

ROOT_QML = str(Path(QML_IMPORT_PATH) / "ImageViewerRoot.qml")


class ImageViewerDialog(QDialog):
    def __init__(
        self,
        original: QPixmap | None,
        preview: QPixmap | None = None,
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme if theme is not None else get_default_theme()
        self.setWindowTitle("Просмотр изображения")
        self.resize(700, 600)
        self._key = uuid4().hex

        self.vm = ImageViewerViewModel(parent=self)
        pixmap: QPixmap | None = None
        used_preview = False
        if original is not None and not original.isNull():
            pixmap = original
        elif preview is not None and not preview.isNull():
            pixmap = preview
            used_preview = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        engine = setup_qml_shell(QApplication.instance(), self._theme)
        self._engine = engine
        if pixmap is not None:
            put_dialog_pixmap(self._key, pixmap)
            self.vm.set_source(
                f"image://dialog/{self._key}",
                used_preview=used_preview,
                unavailable=False,
            )
        else:
            self.vm.set_source("", used_preview=False, unavailable=True)

        self.quick = QQuickWidget(engine, self)
        self.quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self._palette = QmlPalette(self._theme, parent=self)
        # Dialog-owned context: this viewer is opened over live islands and
        # destroyed right after ``exec()``, so a bridge of its own in the
        # shared engine root context would take their colors down with it.
        self._context = island_context(
            engine, self, imageViewerVm=self.vm, islandPalette=self._palette
        )
        self._palette.setParent(self._context)
        self._component = load_island(self.quick, self._context, ROOT_QML)
        assert self.quick.status() == QQuickWidget.Status.Ready, self.quick.errors()
        layout.addWidget(self.quick)
        self._root = self.quick.rootObject()
        self._root.closeRequested.connect(self.close)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
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
        release_island(self.quick)

    def done(self, result: int) -> None:
        QTimer.singleShot(0, self, self._release_island)
        super().done(result)
