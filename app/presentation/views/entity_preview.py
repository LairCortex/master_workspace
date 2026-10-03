"""Thin native facade for the entity-preview QML island (NRI-0022 task 4.1).

The right splitter column since the snapshot moved to its own window. The
facade is deliberately dumb (design D1/D2): the wiring feeds it whole frames
(:meth:`EntityPreviewWidget.show_slots` / :meth:`clear`) and listens to the
one selection bus (:attr:`entity_requested`, fed by relation rows and mention
links) plus NRI-0025's pin channel (:attr:`pin_toggle_requested`). The
picture's click opens the same viewer dialog the card uses — built from the
pane that raised the request, at the same 4096 slot. No editable state and no
slot rules live anywhere in this column (design Д1: the connector owns them).
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.island import IslandDialogMixin, QML_IMPORT_PATH
from app.presentation.qml.tooltip_shim import install_island_tooltips
from app.presentation.theme import get_default_theme
from app.presentation.utils.image_utils import load_entity_original, load_entity_preview
from app.presentation.viewmodels.entity_preview_view_model import (
    EntityPreviewViewModel,
)
from app.presentation.views.image_viewer_dialog import ImageViewerDialog

ROOT_QML = str(Path(QML_IMPORT_PATH) / "EntityPreviewRoot.qml")


class EntityPreviewWidget(IslandDialogMixin, QWidget):
    island_context_names = {"entityPreviewVm": "vm"}

    #: Selection relay to the connector (task 4.1 / design D2): (type, id) of
    #: an activated relation row or mention anchor — the wiring loads it
    #: through the entity service and answers back with the next frame.
    entity_requested = Signal(str, int)
    #: NRI-0025 task 2.2 (design Д2/Д3): a pane's pin was activated — the pair
    #: plus the card's current pinned state; the connector owns the slot rules
    #: (limit, order, storage) and answers with the next ``show_slots`` frame.
    pin_toggle_requested = Signal(str, int, bool)
    #: NRI-0024 (task 2.5, design Д7): child-sheet show channel — the picture
    #: builds its viewer (this column holds the shown entities) and the
    #: connector shows it through the one ``open_sheet`` path, the same sheet
    #: posture as the middle column.
    sheet_requested = Signal(object)

    def __init__(
        self,
        parent: QWidget | None = None,
        theme=None,
        now_date_vm=None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme if theme is not None else get_default_theme()
        # NRI-0021 posture reused: the game's «now» VM joins the Python VM
        # only (the island context stays minimal — previewVm + palette, spec
        # qml-shell); the age line counts against it and follows its moves —
        # since NRI-0025 one subscription repaints every card of the column.
        self.vm = EntityPreviewViewModel(now_vm=now_date_vm, parent=self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Panel-owned private context (IslandDialogMixin): the VM and the
        # palette never reach the shared engine root context.
        self._engine = setup_qml_shell(QApplication.instance(), self._theme)
        self.setup_island()
        layout.addWidget(self.quick)

        self.vm.entityRequested.connect(self.entity_requested)
        self.vm.pinToggleRequested.connect(self.pin_toggle_requested)
        self.vm.imageRequested.connect(self._open_image_viewer)

    def island_source(self) -> str:
        return ROOT_QML

    def load_island_scene(self, quick) -> None:
        # The VM is a raw context pointer: adopted under the (post-widget)
        # context so the scene dies before it at child destruction (the
        # detail-panel pattern). Since NRI-0025 task 4.2 the pin declares
        # Nri.tooltip, so the island gained its own tooltip bridge — the
        # detail-panel/timeline pattern, declared BEFORE the root compiles
        # (the HoverHandlers resolve ``tooltipBridge`` at hover time).
        self.vm.setParent(self._context)
        self._tooltip_bridge = install_island_tooltips(quick, self._context)
        super().load_island_scene(quick)

    def _release_island(self) -> None:
        # DEFECT-1 (NRI-0016) posture: the «now» subscription leaves with the
        # island, never via the collector (spec app-logging).
        self.vm.detach_now_listener()
        super()._release_island()

    def show_slots(
        self,
        pins: Sequence[tuple[str, Any]],
        live: tuple[str, Any] | None,
    ) -> None:
        """Paint one full frame (the wiring's single write channel, design
        Д1): pinned entities in pin order plus the live entity (``None`` =
        empty live area)."""
        self.vm.show_slots(pins, live)

    def clear(self) -> None:
        """Back to the self-explaining empty state."""
        self.vm.clear()

    def _open_image_viewer(
        self, entity_type: str, entity_id: int, pinned: bool
    ) -> None:
        # Task 4.3, re-paneled by NRI-0025 task 2.2: the requesting pane's
        # entity builds the viewer — original at full size with the 4096
        # preview behind it, exactly the card's viewer posture; an
        # unavailable file degrades inside ImageViewerDialog (its own
        # unavailable flag). A pair that stopped being shown between press and
        # signal opens nothing. Task 2.5 of nri-0024 moved the show from
        # exec() to the connector's sheet stack.
        entity = self.vm.pane_entity(entity_type, entity_id, pinned)
        if entity is None:
            return
        original = load_entity_original(entity)
        preview = load_entity_preview(entity, slot_size=4096)
        viewer = ImageViewerDialog(
            original, preview, parent=self, theme=self._theme
        )
        self.sheet_requested.emit(viewer)

    # Island lifecycle (context, deferred closeEvent release) — IslandDialogMixin.
