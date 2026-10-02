"""Thin native facade for the detail-panel QML island."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.island import IslandDialogMixin, QML_IMPORT_PATH
from app.presentation.qml.tooltip_shim import install_island_tooltips
from app.presentation.theme import get_default_theme
from app.presentation.utils.image_utils import load_entity_original, load_entity_preview
from app.presentation.viewmodels.detail_panel_view_model import (
    DetailPanelViewModel,
    build_detail_summary,
)
from app.presentation.views.image_viewer_dialog import ImageViewerDialog

ROOT_QML = str(Path(QML_IMPORT_PATH) / "DetailPanelRoot.qml")

# Compatibility for tests/consumers that exercised the old pure helper.
_build_summary = build_detail_summary


class DetailPanel(IslandDialogMixin, QWidget):
    island_context_names = {"detailPanelVm": "vm"}

    entity_clicked = Signal(str, int)
    # NRI-0022 (task 3.1): the single-click selection relay for the wiring —
    # the preview target, next to the double-click ``entity_clicked`` card.
    entity_selected = Signal(str, int)
    #: NRI-0024 (task 2.5, design Д7): child-sheet show channel — the panel
    #: builds the sheet whose content it owns (the viewer, fed by this row's
    #: entity) and the connector shows it through the one ``open_sheet`` path,
    #: so the picture opens as a sheet in the stack, not on a nested loop.
    sheet_requested = Signal(object)

    def __init__(
        self,
        detail_vm,
        parent: QWidget | None = None,
        theme=None,
        now_date_vm=None,
    ) -> None:
        super().__init__(parent)
        self._vm = detail_vm
        self._theme = theme if theme is not None else get_default_theme()
        self._current_event_id: int | None = None
        # NRI-0021 task 4.1: the game's «now» VM joins the Python VM only (the
        # island context stays minimal — detailPanelVm + palette, spec
        # qml-shell); the composition root hands it through MainWindow.
        self.vm = DetailPanelViewModel(self._theme, now_vm=now_date_vm, parent=self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Panel-owned private context (IslandDialogMixin): the VM and the
        # token bridge never reach the shared engine root, where a name is
        # one global slot nulled for every island when its writer dies.
        self._engine = setup_qml_shell(QApplication.instance(), self._theme)
        self.setup_island()
        layout.addWidget(self.quick)

        self.vm.entityActivated.connect(self.entity_clicked)
        self.vm.entitySelected.connect(self.entity_selected)
        self.vm.imageRequested.connect(self._open_image_viewer)

    def _release_island(self) -> None:
        # DEFECT-1 (NRI-0016): the VM is parented into the island context,
        # so its C++ side leaves with the island while the wrapper lives on
        # this facade — unsubscribe it before that window opens (the release
        # runs when this panel's window closes, see the mixin contract).
        # NRI-0021 (task 4.1): the «now» subscription follows the same rule.
        self.vm.detach_theme_listener()
        self.vm.detach_now_listener()
        super()._release_island()

    def island_source(self) -> str:
        return ROOT_QML

    def load_island_scene(self, quick) -> None:
        # The VM is a raw context pointer: adopted under the (post-widget)
        # context so the scene dies before it at child destruction, exactly
        # as the hand-written context did.
        self.vm.setParent(self._context)
        # NRI-0015 (M1): the tab strips declare Nri.tooltip; the bridge is the
        # island's own (timeline/editor pattern), declared BEFORE the load.
        self._tooltip_bridge = install_island_tooltips(quick, self._context)
        super().load_island_scene(quick)

    def show_event(self, event: Any) -> None:
        self._current_event_id = getattr(event, "id", None)
        self.vm.show_event(event)

    def clear(self) -> None:
        self._current_event_id = None
        self.vm.clear()

    def select_entity(self, entity_type: str, entity_id: int) -> None:
        """Programmatic middle-column selection for the preview's navigation
        bus (NRI-0022 task 5.1, design D4): the type's tab opens and the VM
        washes the row through the very ``select`` slot the island delegates
        drive; a pair absent from the current lists (or a type key with no
        tab at all) changes nothing. The tab write goes FIRST because moving
        the strip fires QML's ``hideRowHighlight`` synchronously — washing
        before that call would simply be painted out."""
        try:
            tab = self.vm.ENTITY_TYPES.index(entity_type)
        except ValueError:
            return
        if self.vm.models[tab].entity(entity_type, entity_id) is None:
            return
        self._root.setProperty("currentTab", tab)
        self.vm.select(entity_type, entity_id)

    def _open_image_viewer(self, entity: Any) -> None:
        # Task 2.5: the viewer left exec() — it is a sheet now, built here
        # (this widget holds the entity's pixels) and shown by the connector
        # through the stack (parent chain: the panel never dims, the main
        # layer is simply covered by the WindowModal sheet).
        original = load_entity_original(entity)
        preview = load_entity_preview(entity, slot_size=4096)
        viewer = ImageViewerDialog(
            original, preview, parent=self, theme=self._theme
        )
        self.sheet_requested.emit(viewer)

    # Island lifecycle (context, deferred closeEvent release) — IslandDialogMixin.
