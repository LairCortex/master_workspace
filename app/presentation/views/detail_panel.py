"""Thin native facade for the detail-panel QML island."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtQml import QQmlComponent, QQmlContext
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.engine import QML_IMPORT_PATH
from app.presentation.theme import get_default_theme
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.utils.image_utils import load_entity_original, load_entity_preview
from app.presentation.viewmodels.detail_panel_view_model import (
    DetailPanelViewModel,
    build_detail_summary,
)
from app.presentation.views.image_viewer_dialog import ImageViewerDialog

ROOT_QML = str(Path(QML_IMPORT_PATH) / "DetailPanelRoot.qml")

# Compatibility for tests/consumers that exercised the old pure helper.
_build_summary = build_detail_summary


class DetailPanel(QWidget):
    entity_clicked = Signal(str, int)

    def __init__(
        self,
        detail_vm,
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        super().__init__(parent)
        self._vm = detail_vm
        self._theme = theme if theme is not None else get_default_theme()
        self._current_event_id: int | None = None
        self.vm = DetailPanelViewModel(self._theme, parent=self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        engine = setup_qml_shell(QApplication.instance(), self._theme)
        self._engine = engine
        self.quick = QQuickWidget(engine, self)
        self.quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self._palette = QmlPalette(self._theme, parent=self)
        self._context = QQmlContext(engine.rootContext(), self)
        self.vm.setParent(self._context)
        self._palette.setParent(self._context)
        self._context.setContextProperty("detailPanelVm", self.vm)
        self._context.setContextProperty("islandPalette", self._palette)
        source = QUrl.fromLocalFile(ROOT_QML)
        self._component = QQmlComponent(engine, source, self)
        root = self._component.create(self._context)
        assert root is not None, self._component.errors()
        self.quick.setContent(source, self._component, root)
        assert self.quick.status() == QQuickWidget.Status.Ready, self.quick.errors()
        layout.addWidget(self.quick)
        self._root = self.quick.rootObject()

        self.vm.entityActivated.connect(self.entity_clicked)
        self.vm.imageRequested.connect(self._open_image_viewer)

    def show_event(self, event: Any) -> None:
        self._current_event_id = getattr(event, "id", None)
        self.vm.show_event(event)

    def clear(self) -> None:
        self._current_event_id = None
        self.vm.clear()

    def _open_image_viewer(self, entity: Any) -> None:
        original = load_entity_original(entity)
        preview = load_entity_preview(entity, slot_size=4096)
        ImageViewerDialog(
            original, preview, parent=self, theme=self._theme
        ).exec()

    def _release_island(self) -> None:
        self.quick.setSource(QUrl())

    def closeEvent(self, event) -> None:
        QTimer.singleShot(0, self, self._release_island)
        super().closeEvent(event)
