"""SheetListViewModel — list state for the QML «Чар-листы» island.

Design D2 (port-sheet-list-preset-dialogs-qml-q3a): the thin state half of the
list dialog. Two row models with ``id``/``label`` roles (the templates tab and
the sheets tab), the current tab, per-tab selection ids and the
``canOpen/canRename/canDelete/presetButtonVisible`` flags — the flags replicate
the widgets dialog's ``_sync_actions_enabled`` rules:

- templates tab: open/rename need a selection; delete additionally refuses the
  sheet open in the editor (``set_open_sheet_id``) and any template that still
  has sheets (the instance count is computed in ``set_rows`` from the rows
  Python fed in — the same count the widgets dialog kept while refreshing);
- sheets tab: open/rename need a selection; delete additionally refuses the
  open instance (``set_open_instance_id``) and seated instances
  (``set_seated_ids``);
- «Создать из пресета…» is an action of the templates tab only (spec).

The «лист — шаблон» label is composed HERE (Python), never in QML — one rule
implementation only. All async flows (create/open/rename/delete/refresh under
``run_locked``) stay in the QDialog facade; QML calls the sync slots and the
island root emits its ``*Requested`` signals.
"""
from __future__ import annotations

from typing import Any, Sequence

from PySide6.QtCore import QObject, Property, Signal, Slot

TAB_TEMPLATES = 0
TAB_INSTANCES = 1

# The sheets-tab label separator («лист — шаблон»), same em dash the widgets
# dialog used.
LABEL_SEPARATOR = "—"


class SheetListViewModel(QObject):
    """Templates/sheets row models + per-tab selection + availability flags."""

    rowsChanged = Signal()
    selectionChanged = Signal()
    tabChanged = Signal()
    flagsChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._template_rows: list[dict] = []
        self._instance_rows: list[dict] = []
        # id -> plain name (rename prefills never show the «лист — шаблон» label)
        self._template_names: dict[int, str] = {}
        self._instance_names: dict[int, str] = {}
        # template id -> number of sheets on it (templates-tab delete blocker)
        self._instance_counts: dict[int, int] = {}
        self._tab = TAB_TEMPLATES
        self._selected_template_index = -1
        self._selected_instance_index = -1
        self._open_sheet_id: int | None = None
        self._open_instance_id: int | None = None
        self._seated_ids: set[int] = set()
        self._flag_state = self._compute_flags()

    # ---- QML surface (row roles per design D2/D4) ----

    def _get_templates(self) -> list[dict]:
        return self._template_rows

    templateList = Property("QVariant", _get_templates, notify=rowsChanged)

    def _get_instances(self) -> list[dict]:
        return self._instance_rows

    instanceList = Property("QVariant", _get_instances, notify=rowsChanged)

    def _get_current_tab(self) -> int:
        return self._tab

    currentTab = Property(int, _get_current_tab, notify=tabChanged)

    def _get_selected_template_id(self) -> Any:
        # QVariant: "no selection" reaches QML as null, not 0/-1.
        return self.selected_template_id

    selectedTemplateId = Property(
        "QVariant", _get_selected_template_id, notify=selectionChanged
    )

    def _get_selected_instance_id(self) -> Any:
        return self.selected_instance_id

    selectedInstanceId = Property(
        "QVariant", _get_selected_instance_id, notify=selectionChanged
    )

    def _get_can_open(self) -> bool:
        return self._selected_id() is not None

    canOpen = Property(bool, _get_can_open, notify=flagsChanged)

    def _get_can_rename(self) -> bool:
        return self._selected_id() is not None

    canRename = Property(bool, _get_can_rename, notify=flagsChanged)

    def _get_can_delete(self) -> bool:
        selected = self._selected_id()
        if selected is None:
            return False
        if self._tab == TAB_INSTANCES:
            return (
                selected != self._open_instance_id
                and selected not in self._seated_ids
            )
        return (
            selected != self._open_sheet_id
            and self._instance_counts.get(selected, 0) == 0
        )

    canDelete = Property(bool, _get_can_delete, notify=flagsChanged)

    def _get_preset_button_visible(self) -> bool:
        # «Создать из пресета…» is an action of the «Шаблоны» tab only (spec).
        return self._tab == TAB_TEMPLATES

    presetButtonVisible = Property(
        bool, _get_preset_button_visible, notify=flagsChanged
    )

    # ---- Python (facade / tests) contract ----

    @property
    def current_tab(self) -> int:
        return self._tab

    @property
    def selected_template_id(self) -> int | None:
        return self._id_at(self._template_rows, self._selected_template_index)

    @property
    def selected_instance_id(self) -> int | None:
        return self._id_at(self._instance_rows, self._selected_instance_index)

    @property
    def selected_template_name(self) -> str | None:
        sheet_id = self.selected_template_id
        if sheet_id is None:
            return None
        return self._template_names.get(sheet_id)

    @property
    def selected_instance_name(self) -> str | None:
        instance_id = self.selected_instance_id
        if instance_id is None:
            return None
        return self._instance_names.get(instance_id)

    # QML calls in through meta-object slots (sync only, spec qml-shell).
    @Slot(int)
    def setCurrentTab(self, index: int) -> None:
        if index not in (TAB_TEMPLATES, TAB_INSTANCES):
            return
        if index == self._tab:
            return
        self._tab = index
        self.tabChanged.emit()
        # The flags are tab-relative (selection, presets-tab visibility).
        self._recompute_flags()

    @Slot(int)
    def selectTemplate(self, index: int) -> None:
        """Select a template row; anything outside the list means "no selection"."""
        if not 0 <= index < len(self._template_rows):
            index = -1
        self._change_index("_selected_template_index", index)

    @Slot(int)
    def selectInstance(self, index: int) -> None:
        if not 0 <= index < len(self._instance_rows):
            index = -1
        self._change_index("_selected_instance_index", index)

    # -- Python-side mutators used by the facade --------------------------------

    def set_open_sheet_id(self, sheet_id: int | None) -> None:
        """The template open in the editor cannot be deleted (spec)."""
        if sheet_id == self._open_sheet_id:
            return
        self._open_sheet_id = sheet_id
        self._recompute_flags()

    def set_open_instance_id(self, instance_id: int | None) -> None:
        if instance_id == self._open_instance_id:
            return
        self._open_instance_id = instance_id
        self._recompute_flags()

    def set_seated_ids(self, instance_ids: set[int] | None) -> None:
        seated = set(instance_ids or ())
        if seated == self._seated_ids:
            return
        self._seated_ids = seated
        self._recompute_flags()

    def set_rows(
        self,
        templates: Sequence[Any] = (),
        instances: Sequence[Any] = (),
    ) -> None:
        """Rebuild both row models from the service rows (Python-side refresh).

        Composes the «лист — шаблон» labels, recounts the sheets per template
        (the templates-tab delete blocker) and keeps every selection that
        survived the refresh (matched by id, not by position).
        """
        selected_template_id = self.selected_template_id
        selected_instance_id = self.selected_instance_id

        self._template_names = {row.id: row.name for row in templates}
        self._template_rows = [
            {"id": row.id, "label": row.name} for row in templates
        ]

        self._instance_names = {row.id: row.name for row in instances}
        self._instance_rows = [
            {
                "id": row.id,
                "label": (
                    f"{row.name} {LABEL_SEPARATOR} {self._template_names[row.template_id]}"
                    if row.template_id in self._template_names
                    else row.name
                ),
            }
            for row in instances
        ]
        self._instance_counts = {}
        for row in instances:
            self._instance_counts[row.template_id] = (
                self._instance_counts.get(row.template_id, 0) + 1
            )

        self._selected_template_index = self._index_of_id(
            self._template_rows, selected_template_id
        )
        self._selected_instance_index = self._index_of_id(
            self._instance_rows, selected_instance_id
        )

        self.rowsChanged.emit()
        self.selectionChanged.emit()
        self._recompute_flags()

    def select_template_by_id(self, sheet_id: int) -> None:
        """Move the selection to ``sheet_id`` (post-create/rename re-selection);
        an unknown id leaves the selection untouched."""
        self._select_by_id("_selected_template_index", self._template_rows, sheet_id)

    def select_instance_by_id(self, instance_id: int) -> None:
        self._select_by_id("_selected_instance_index", self._instance_rows, instance_id)

    # ---- internals ----

    def _selected_id(self) -> int | None:
        if self._tab == TAB_INSTANCES:
            return self.selected_instance_id
        return self.selected_template_id

    def _compute_flags(self) -> tuple[bool, bool, bool, bool]:
        return (
            self._get_can_open(),
            self._get_can_rename(),
            self._get_can_delete(),
            self._get_preset_button_visible(),
        )

    def _recompute_flags(self) -> None:
        # Qt notify semantics: flagsChanged only when a flag value moves.
        state = self._compute_flags()
        if state != self._flag_state:
            self._flag_state = state
            self.flagsChanged.emit()

    @staticmethod
    def _id_at(rows: list[dict], index: int) -> int | None:
        if 0 <= index < len(rows):
            return rows[index]["id"]
        return None

    @staticmethod
    def _index_of_id(rows: list[dict], row_id: int | None) -> int:
        if row_id is None:
            return -1
        for i, row in enumerate(rows):
            if row["id"] == row_id:
                return i
        return -1

    def _select_by_id(
        self, index_attr: str, rows: list[dict], row_id: int
    ) -> None:
        index = self._index_of_id(rows, row_id)
        if index == -1:
            return  # the row is gone: same no-op the old widgets scan did
        self._change_index(index_attr, index)

    def _change_index(self, index_attr: str, index: int) -> None:
        if index == getattr(self, index_attr):
            return
        setattr(self, index_attr, index)
        self.selectionChanged.emit()
        self._recompute_flags()
