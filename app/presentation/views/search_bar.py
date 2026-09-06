"""Global search QML island in the stable ``SearchBar`` facade."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtQml import QQmlComponent, QQmlContext
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.engine import QML_IMPORT_PATH, release_island
from app.presentation.theme import get_default_theme
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.viewmodels.search_viewmodel import SearchViewModel

ROOT_QML = str(Path(QML_IMPORT_PATH) / "SearchBarRoot.qml")


class SearchBar(QWidget):
    search_requested = Signal(str)
    result_selected = Signal(str, int)  # (entity_type, entity_id)

    def __init__(
        self,
        search_vm,
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        super().__init__(parent)
        self._owns_vm = not isinstance(search_vm, QObject)
        self._vm = (
            search_vm
            if not self._owns_vm
            else SearchViewModel(search_vm, parent=self)
        )
        self._theme = theme if theme is not None else get_default_theme()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._engine = setup_qml_shell(QApplication.instance(), self._theme)
        self.quick = QQuickWidget(self._engine, self)
        self.quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self._palette = QmlPalette(self._theme, parent=self)
        self._context = QQmlContext(self._engine.rootContext(), self)
        if self._owns_vm:
            self._vm.setParent(self._context)
        self._palette.setParent(self._context)
        self._context.setContextProperty("searchBarVm", self._vm)
        self._context.setContextProperty("islandPalette", self._palette)

        source = QUrl.fromLocalFile(ROOT_QML)
        self._component = QQmlComponent(self._engine, source, self)
        root = self._component.create(self._context)
        assert root is not None, self._component.errors()
        self.quick.setContent(source, self._component, root)
        assert self.quick.status() == QQuickWidget.Status.Ready, self.quick.errors()
        layout.addWidget(self.quick)
        self._root = self.quick.rootObject()

        self._vm.searchRequested.connect(self.search_requested)
        self._vm.resultSelected.connect(self.result_selected)

        # A QQuickWidget in SizeRootObjectToView never reports the scene's
        # implicit height as a size hint, so the results list laid out below
        # the field stayed clipped to the field's own height. The facade
        # mirrors the island's implicit height onto the widget instead.
        self._root.implicitHeightChanged.connect(self._sync_island_height)
        self._sync_island_height()

    def _sync_island_height(self) -> None:
        root = self.quick.rootObject()
        if root is None:
            return
        height = int(round(root.implicitHeight()))
        if height > 0 and height != self.height():
            self.setFixedHeight(height)

    def _release_island(self) -> None:
        release_island(self.quick)

    def closeEvent(self, event) -> None:
        QTimer.singleShot(0, self, self._release_island)
        super().closeEvent(event)
