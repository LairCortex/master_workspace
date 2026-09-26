"""Global search QML island in the stable ``SearchBar`` facade."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Signal
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.island import IslandDialogMixin, QML_IMPORT_PATH
from app.presentation.theme import get_default_theme
from app.presentation.viewmodels.search_viewmodel import SearchViewModel

ROOT_QML = str(Path(QML_IMPORT_PATH) / "SearchBarRoot.qml")


class SearchBar(IslandDialogMixin, QWidget):
    # NRI-0021 (task 3.2, spec qml-shell «Контекст каждого острова
    # минимален»): the island gains exactly one more name — the game-date
    # widget's own sync VM (null for unit-built islands without a game, the
    # row then stays hidden); searchBarVm stays purely the search VM.
    island_context_names = {"searchBarVm": "_vm", "nowDateVm": "_now_date_vm"}

    search_requested = Signal(str)
    result_selected = Signal(str, int)  # (entity_type, entity_id)

    def __init__(
        self,
        search_vm,
        parent: QWidget | None = None,
        theme=None,
        now_date_vm: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._owns_vm = not isinstance(search_vm, QObject)
        self._vm = (
            search_vm
            if not self._owns_vm
            else SearchViewModel(search_vm, parent=self)
        )
        # Injected, never adopted: the game's «now» VM belongs to the
        # composition root (its lifetime outlives the island scene — the
        # wiring subscribes to it too, design Д2).
        self._now_date_vm = now_date_vm
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

    def now_date_anchor(
        self, x: float, y: float, width: float, height: float
    ) -> QRect:
        """Map the «now» chip's island-local rectangle to a global one.

        The VM's ``datePopupRequested`` carries scene coordinates (the QML
        island convention); the widgets popup is a top-level, so the wiring
        asks this facade — the island's owner — for the global anchor
        (pattern of WorldSnapshotWidget's private mapper, exposed here).
        """
        top_left = self.quick.mapToGlobal(QPoint(int(x), int(y)))
        return QRect(top_left, QSize(max(int(width), 0), max(int(height), 0)))

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
