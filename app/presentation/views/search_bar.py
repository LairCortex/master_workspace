"""Global search QML island in the stable ``SearchBar`` facade."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.island import IslandDialogMixin, QML_IMPORT_PATH
from app.presentation.theme import get_default_theme
from app.presentation.viewmodels.search_viewmodel import SearchViewModel

ROOT_QML = str(Path(QML_IMPORT_PATH) / "SearchBarRoot.qml")


class SearchBar(IslandDialogMixin, QWidget):
    island_context_names = {"searchBarVm": "_vm"}

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
        self.setup_island()
        layout.addWidget(self.quick)

        self._vm.searchRequested.connect(self.search_requested)
        self._vm.resultSelected.connect(self.result_selected)

        # A QQuickWidget in SizeRootObjectToView never reports the scene's
        # implicit height as a size hint, so the results list laid out below
        # the field stayed clipped to the field's own height. The facade
        # mirrors the island's implicit height onto the widget instead.
        self._root.implicitHeightChanged.connect(self._sync_island_height)
        self._sync_island_height()

    def island_source(self) -> str:
        return ROOT_QML

    def load_island_scene(self, quick) -> None:
        if self._owns_vm:
            # The context is created AFTER the island widget, so adopting the
            # VM under it keeps the scene dying before the VM at child
            # destruction (QML must never outlive a context property). An
            # injected VM belongs to its caller and is never re-parented.
            self._vm.setParent(self._context)
        super().load_island_scene(quick)

    def _sync_island_height(self) -> None:
        root = self.quick.rootObject()
        if root is None:
            return
        height = int(round(root.implicitHeight()))
        if height > 0 and height != self.height():
            self.setFixedHeight(height)

    # Island lifecycle (context, deferred closeEvent release) — IslandDialogMixin.
