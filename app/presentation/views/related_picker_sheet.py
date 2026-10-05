"""The «Выберите <тип>» binding picker as a QML-island sheet (PR-020).

One widget for the event dialog and the entity card (they shared the old
exec'd dialog body line for line, then the shared SheetFrame builder). The
frame keeps the sheet contract it always had — a SheetFrame named by the
target caption (spec modal-sheets «текст, соответствующий windowTitle»),
shown by the connector through the one ``open_sheet`` path, no nested event
loop, ОК commits, Отмена/Esc/header «Закрыть» hand the opener back untouched,
Enter keeps the ОК outcome (the PR-029 island default-key bridge).

What changed: the content. The widgets ``QListWidget`` is gone — its virtual
cells never reached the cocoa accessibility projection, so the live audit
found the rows nameless and no channel could select one (PR-020; the same
item-view hole PR-022 pinned for the desk). The candidate rows are library
``RowItem``s now: ListItem role and Press owned by the component, the entity
name supplied by the usage site, the press spelling its meaning («Выбирает
сущность»). In this list a press selects its row and accepts the sheet — the
SheetPresetRoot migrated-OK idiom — so an assistive user lands in the section
with the entity linked; the mouse keeps the MultiSelection toggle semantics
(the VM owns the set, the commit walks the candidates in order).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.island import IslandDialogMixin, QML_IMPORT_PATH
from app.presentation.theme import get_default_theme
from app.presentation.viewmodels.related_picker_view_model import (
    RelatedPickerViewModel,
)
from app.presentation.views.sheet_frame import SheetFrame

ROOT_QML = str(Path(QML_IMPORT_PATH) / "RelatedPickerRoot.qml")


class RelatedPickerSheet(IslandDialogMixin, SheetFrame):
    """The multi-selection candidate sheet (see the module docstring)."""

    island_context_names = {"relatedPickerVm": "vm"}

    def island_source(self) -> str:
        return ROOT_QML

    def __init__(
        self,
        title: str,
        state,
        candidates: list[Any],
        parent=None,
        theme=None,
    ) -> None:
        # The island is skinned by the token bridge only, but the bridge still
        # needs a runtime — the widgets-era ``None`` falls back to the process
        # default, exactly like the viewer sheet sharing this frame family.
        self._theme = theme if theme is not None else get_default_theme()
        super().__init__(title, parent, self._theme)
        self.setMinimumSize(300, 400)  # the floor the old dialog carried
        self._state = state
        self._candidates = list(candidates)

        # The VM and the palette are window children — a context property is a
        # raw pointer, so QML must never outlive them (the launcher's seam).
        self.vm = RelatedPickerViewModel(parent=self)
        self.vm.load(self._candidates)

        self._engine = setup_qml_shell(QApplication.instance(), self._theme)
        self.setup_island()
        self.add_content(self.quick, 1)
        self._root.okRequested.connect(self.accept)
        # Queued, NOT direct (the preset dialog's lesson): a QML handler that
        # tears its own scene down through a synchronous done() aborts Qt when
        # the release outruns the JS frame; the hop costs the cancel path
        # nothing — «cancel creates nothing» was always just done().
        self._root.cancelRequested.connect(self.reject, Qt.QueuedConnection)

    def accept(self) -> None:
        """The commit stays on this side of the tree (the retired
        ``accepted`` hook): every selected candidate joins the section in the
        candidates' own order, whoever accepted — ОК, a row press, Enter or a
        programmatic accept."""
        for entity in self.vm.selected_entities(self._candidates):
            self._state.add_entity(entity)
        super().accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — Qt API
        # Enter clicks the island's «ОК» marker (PR-029 bridge, one knowledge
        # in the mixin); every other key — Esc included — rides QDialog's own
        # handling (Esc rejects, the cancel the old default box answered).
        if self.take_island_default_key(event):
            return
        super().keyPressEvent(event)
