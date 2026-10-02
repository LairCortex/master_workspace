"""Thin native facade for the entity-preview QML island (NRI-0022 task 4.1).

The right splitter column since the snapshot moved to its own window. The
facade is deliberately dumb (design D1/D2): the wiring feeds it entities
(:meth:`EntityPreviewWidget.show_entity` / :meth:`clear`) and listens to the
one selection bus (:attr:`entity_requested`, fed by relation rows and mention
links); the picture's click opens the same viewer dialog the card uses, at the
same 4096 slot. No editable state lives anywhere in this column.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.island import IslandDialogMixin, QML_IMPORT_PATH
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
    #: through the entity service and answers back with ``show_entity``.
    entity_requested = Signal(str, int)
    #: NRI-0024 (task 2.5, design Д7): child-sheet show channel — the picture
    #: builds its viewer (this column holds the shown entity) and the
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
        # qml-shell); the age line counts against it and follows its moves.
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
        self.vm.imageRequested.connect(self._open_image_viewer)

    def island_source(self) -> str:
        return ROOT_QML

    def load_island_scene(self, quick) -> None:
        # The VM is a raw context pointer: adopted under the (post-widget)
        # context so the scene dies before it at child destruction (the
        # detail-panel pattern).
        self.vm.setParent(self._context)
        super().load_island_scene(quick)

    def _release_island(self) -> None:
        # DEFECT-1 (NRI-0016) posture: the «now» subscription leaves with the
        # island, never via the collector (spec app-logging).
        self.vm.detach_now_listener()
        super()._release_island()

    def show_entity(self, entity_type: str, entity: Any) -> None:
        """Display one loaded entity (the wiring's single write channel)."""
        self.vm.show_entity(entity_type, entity)

    def clear(self) -> None:
        """Back to the self-explaining empty state."""
        self.vm.clear()

    def _open_image_viewer(self) -> None:
        # Task 4.3: the original at full size with the 4096 preview behind it,
        # exactly the card's viewer posture; an unavailable file degrades
        # inside ImageViewerDialog (its own unavailable flag). Task 2.5 of
        # nri-0024 moved the show from exec() to the connector's sheet stack.
        entity = self.vm.shown_entity
        original = load_entity_original(entity)
        preview = load_entity_preview(entity, slot_size=4096)
        viewer = ImageViewerDialog(
            original, preview, parent=self, theme=self._theme
        )
        self.sheet_requested.emit(viewer)

    # Island lifecycle (context, deferred closeEvent release) — IslandDialogMixin.
