"""Event creation/edit dialog: QML island in the stable QDialog facade."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.domain import entity_registry
from app.domain.enums.entity_type import EntityType
from app.presentation.dialog_results import (
    EventCreateResult,
    EventDialogResult,
    EventEditResult,
    RelatedRef,
    relation_items,
)
from app.presentation.qml import setup_qml_shell
from app.presentation.qml.engine import QML_IMPORT_PATH
from app.presentation.qml.island import IslandDialogMixin
from app.presentation.theme import get_default_theme
from app.presentation.utils.date_utils import era_flag, split_date_era
from app.presentation.viewmodels.event_dialog_island_view_model import (
    EventDialogIslandViewModel,
    RelatedSectionState,
)
from app.presentation.views.event_types_dialog import type_dot_icon
from app.presentation.views.ai_capable_dialog import AiCapableDialogBase
from app.presentation.views.theme_date_popup import ThemeDatePopup

ROOT_QML = str(Path(QML_IMPORT_PATH) / "EventDialogRoot.qml")
ROLE_COLOR_INDEX = Qt.ItemDataRole.UserRole + 1

# The tab collections, type ids and captions come from the entity registry's
# EVENT relation list (wave 3, A4); the Python duck attribute names are the
# dialog's own QML/test surface and stay local.
_EVENT_REFS = entity_registry.related_refs(EntityType.EVENT)
_TAB_DUCK_NAMES = ("org_tab", "char_tab", "item_tab", "loc_tab")
_TABS: list[tuple[str, str, str, str]] = [
    (duck, ref.attr, ref.entity_type.value, ref.label)
    for duck, ref in zip(_TAB_DUCK_NAMES, _EVENT_REFS)
]
_REL_ATTRS = tuple(attr for _, attr, _, _ in _TABS)


class _ClickProxy:
    def __init__(self, callback: Callable[[], None], enabled: Callable[[], bool] = lambda: True):
        self._callback = callback
        self._enabled = enabled

    def click(self) -> None:
        if self._enabled():
            self._callback()

    def isEnabled(self) -> bool:
        return self._enabled()


class _FieldProxy:
    def __init__(self, getter: Callable[[], str], setter: Callable[[str], None]):
        self._getter = getter
        self._setter = setter

    def text(self) -> str:
        return self._getter()

    def setText(self, value: str) -> None:
        self._setter(value)


class _DateProxy:
    """Visibility duck for the dialog's date fields (piece C3a, D6).

    The legacy ``date()``/``setDate()`` transit died with piece C3b (design
    D12): the bridge currency is the coordinate pair the ViewModel owns, so
    writers go through ``vm.set_dates`` and readers through ``vm._start_date``
    / ``vm._end_date``; what remains here is the visibility half QML-side
    layouts and Python wiring/tests still ask the field objects for.
    """

    def __init__(self, dialog: "EventDialog", which: str):
        self._dialog = dialog
        self._which = which

    def isVisible(self) -> bool:
        return self._which == "start" or not self._dialog.vm._no_end

    def isHidden(self) -> bool:
        return not self.isVisible()


class _CheckProxy:
    def __init__(self, vm: EventDialogIslandViewModel):
        self._vm = vm

    def isChecked(self) -> bool:
        return self._vm._no_end

    def setChecked(self, value: bool) -> None:
        self._vm.set_no_end(value)


class _TypeComboProxy:
    def __init__(self, dialog: "EventDialog"):
        self._dialog = dialog

    def count(self) -> int:
        return len(self._dialog.vm._types) + 1

    def itemText(self, index: int) -> str:
        return self._dialog.vm.typeNames[index]

    def itemData(self, index: int, role=Qt.ItemDataRole.UserRole):
        if index == 0:
            return None
        item = self._dialog.vm._types[index - 1]
        if role == ROLE_COLOR_INDEX:
            return getattr(item, "color_index", None)
        if role == Qt.ItemDataRole.DecorationRole:
            return type_dot_icon(self._dialog._theme, getattr(item, "color_index", 1))
        return getattr(item, "id", None)

    def itemIcon(self, index: int):
        if index == 0:
            from PySide6.QtGui import QIcon
            return QIcon()
        return type_dot_icon(
            self._dialog._theme,
            getattr(self._dialog.vm._types[index - 1], "color_index", 1),
        )

    def currentData(self):
        return self._dialog.vm.selected_type_id

    def currentIndex(self) -> int:
        return self._dialog.vm._selected_type_index

    def setCurrentIndex(self, index: int) -> None:
        self._dialog.vm.selectType(index)

    def findData(self, value) -> int:
        if value is None:
            return 0
        for index, item in enumerate(self._dialog.vm._types, 1):
            if getattr(item, "id", None) == value:
                return index
        return -1

    def findText(self, value: str) -> int:
        for index, text in enumerate(self._dialog.vm.typeNames):
            if text == value:
                return index
        return -1


class _ListItemProxy:
    def __init__(self, row: dict, index: int):
        self._row = row
        self.index = index

    def text(self) -> str:
        return self._row["name"]

    def data(self, role):
        return self._row["id"] if role == 256 else None


class _ListProxy:
    def __init__(self, state: RelatedSectionState):
        self._state = state

    def count(self) -> int:
        return len(self._state.rows)

    def item(self, index: int):
        return _ListItemProxy(self._state.rows[index], index)

    def setCurrentRow(self, row: int) -> None:
        self._state.select(row)

    def setCurrentItem(self, item: _ListItemProxy) -> None:
        self._state.select(item.index)

    def currentRow(self) -> int:
        return self._state.selectedIndex


class _RelatedProxy:
    def __init__(self, state: RelatedSectionState):
        self._state = state
        self.list_widget = _ListProxy(state)
        self.link_button = _ClickProxy(state.requestLink)
        self.create_button = _ClickProxy(state.requestCreate)
        self.remove_button = _ClickProxy(
            state.unlinkSelected, lambda: state.selectedIndex >= 0
        )

    @property
    def _available(self):
        return self._state._available

    def set_entities(self, entities):
        self._state.set_entities(entities)

    def set_available(self, entities):
        self._state.set_available(entities)

    def add_entity(self, entity):
        self._state.add_entity(entity)

    def get_current_ids(self):
        return self._state.get_current_ids()


class _TabsProxy:
    def isHidden(self) -> bool:
        return False


class EventDialog(AiCapableDialogBase, IslandDialogMixin, QDialog):
    island_context_names = {"eventDialogVm": "vm"}

    def island_source(self) -> str:
        return ROOT_QML

    saved = Signal(object)  # EventCreateResult | EventEditResult (dialog_results)
    create_related_requested = Signal(str, str)
    mention_clicked = Signal(str, int)

    def __init__(
        self,
        event_dialog_vm,
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        super().__init__(parent)
        self._vm = event_dialog_vm
        self._theme = theme
        self._qml_theme = theme if theme is not None else get_default_theme()
        self._event_id: int | None = None
        self._pending_type_id: int | None = None
        self._saving = False
        self._close_guard = None
        self._date_target = "start"
        self.setWindowTitle("Новое событие")
        self.setMinimumSize(700, 620)

        self.vm = EventDialogIslandViewModel(owner=self, parent=self)
        self._ai_buttons = [
            self.vm.nameAi,
            self.vm.characteristicsAi,
            self.vm.backstoryAi,
        ]
        self._entity_button = self.vm.entityAi
        self._sections = self.vm.sections

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._engine = setup_qml_shell(QApplication.instance(), self._qml_theme)
        # Context, widget and scene — IslandDialogMixin.
        self.setup_island()
        layout.addWidget(self.quick)

        self.vm.characteristicsHost.attachWidget(self.quick)
        self.vm.backstoryHost.attachWidget(self.quick)
        self.vm.characteristicsEdit.mention_clicked.connect(self.mention_clicked)
        self.vm.backstoryEdit.mention_clicked.connect(self.mention_clicked)
        self.vm.saveRequested.connect(self._on_save)
        self.vm.cancelRequested.connect(self._on_cancel_clicked)
        self.vm.datePopupRequested.connect(self._open_date_popup)

        self.date_popup = ThemeDatePopup(self)
        self.date_popup.date_selected.connect(self._set_selected_date)
        for _widget_attr, attr, entity_type, label in _TABS:
            state = self._sections[attr]
            state.createRequested.connect(
                lambda a=attr, t=entity_type: self.create_related_requested.emit(a, t)
            )
            state.linkRequested.connect(
                lambda a=attr, lbl=label: self._open_related_picker(a, lbl)
            )

        # Transitional non-widget ducks keep existing Python wiring/tests usable;
        # the visible content remains exclusively the QML island.
        self.name_input = _FieldProxy(lambda: self.vm.name, lambda v: setattr(self.vm, "name", v))
        self.characteristics_input = self.vm.characteristicsEdit
        self.backstory_input = self.vm.backstoryEdit
        self.start_date_input = _DateProxy(self, "start")
        self.end_date_input = _DateProxy(self, "end")
        self.no_end_date_cb = _CheckProxy(self.vm)
        self.type_combo = _TypeComboProxy(self)
        self.save_button = _ClickProxy(self.vm.requestSave, lambda: self.vm.valid)
        self.cancel_button = _ClickProxy(self._on_cancel_clicked)
        for widget_attr, attr, _entity_type, _label in _TABS:
            setattr(self, widget_attr, _RelatedProxy(self._sections[attr]))
        self.tabs = _TabsProxy()

    @property
    def event_id(self) -> int | None:
        return self._event_id

    def populate(self, event: Any) -> None:
        self._event_id = getattr(event, "id", None)
        self.setWindowTitle("Редактировать событие")
        self.vm.name = getattr(event, "name", "")
        event_type = getattr(event, "event_type", None)
        self._pending_type_id = getattr(event_type, "id", None)
        self.vm.set_event_types(self.vm._types, self._pending_type_id)
        start = getattr(event, "start_date", None)
        end = getattr(event, "end_date", None)
        if start is not None:
            self.vm.set_dates(
                start=start, start_bc=era_flag(getattr(event, "start_bc", False))
            )
        if end is not None:
            self.vm.set_dates(
                end=end, end_bc=era_flag(getattr(event, "end_bc", False))
            )
            self.vm.set_no_end(False)
        else:
            self.vm.set_no_end(True)
        description = getattr(event, "description", None)
        if description is not None:
            self.vm.characteristicsHost.storage = (
                getattr(description, "characteristics", "") or ""
            )
            self.vm.backstoryHost.storage = getattr(description, "backstory", "") or ""
        for attr in _REL_ATTRS:
            self._sections[attr].set_entities(list(getattr(event, attr, []) or []))

    def set_event_types(self, types, current_type_id: int | None = None) -> None:
        if current_type_id is not None:
            self._pending_type_id = current_type_id
        self.vm.set_event_types(list(types), self._pending_type_id)

    def set_available_entities(self, attr: str, entities: list[Any]) -> None:
        section = self._sections.get(attr)
        if section is not None:
            section.set_available(entities)

    def add_related_entity(self, attr: str, entity: Any) -> None:
        section = self._sections.get(attr)
        if section is not None:
            section.add_entity(entity)

    def get_data(self) -> dict:
        data = {
            "name": self.vm.name.strip(),
            "characteristics": self.vm.characteristicsHost.storage.strip(),
            "backstory": self.vm.backstoryHost.storage.strip(),
            "start_date": self.vm._start_date,
            "end_date": None if self.vm._no_end else self.vm._end_date,
            "start_bc": self.vm._start_bc,
            "end_bc": self.vm._end_bc,
            "event_type_id": self.vm.selected_type_id,
        }
        if self._event_id is not None:
            data["event_id"] = self._event_id
        for attr in _REL_ATTRS:
            data[attr] = relation_items(self.build_result_relations()[attr])
        return data

    def build_result(self) -> EventDialogResult:
        """The typed save contract (design D5): edit iff an event is loaded."""
        relations = self.build_result_relations()
        args: dict[str, Any] = {
            "name": self.vm.name.strip(),
            "characteristics": self.vm.characteristicsHost.storage.strip(),
            "backstory": self.vm.backstoryHost.storage.strip(),
            "start_date": self.vm._start_date,
            "end_date": None if self.vm._no_end else self.vm._end_date,
            "start_bc": self.vm._start_bc,
            "end_bc": self.vm._end_bc,
            "event_type_id": self.vm.selected_type_id,
            **relations,
        }
        if self._event_id is not None:
            return EventEditResult(event_id=self._event_id, **args)
        return EventCreateResult(**args)

    def build_result_relations(self) -> dict[str, tuple[RelatedRef, ...]]:
        """Desired links per relation attr as contract objects (no junk keys)."""
        return {
            attr: tuple(
                RelatedRef(entity_id)
                for entity_id in self._sections[attr].get_current_ids()
                if entity_id is not None
            )
            for attr in _REL_ATTRS
        }

    def get_mention_edits(self):
        return [self.vm.characteristicsEdit, self.vm.backstoryEdit]

    # The AI proxy surface (get_ai_buttons/get_entity_button/set_save_locked/
    # set_close_guard/_is_generation_active) is provided by
    # AiCapableDialogBase — the shared conformance base of the controller
    # contract (audit B1, design D5).

    def _on_save(self) -> None:
        if self._saving or not self.vm.valid:
            return
        self._saving = True
        self.vm.set_saving(True)
        self.saved.emit(self.build_result())

    def finish_saving(self, success: bool) -> None:
        self._saving = False
        self.vm.set_saving(False)
        if success:
            self.accept()

    def _on_cancel_clicked(self) -> None:
        if self._saving:
            return
        if self._close_guard is not None:
            self._close_guard()
        else:
            super().reject()

    def reject(self) -> None:
        if self._saving or self._is_generation_active():
            return
        super().reject()

    def closeEvent(self, event) -> None:
        if self._saving:
            event.ignore()
            return
        if self._is_generation_active() and self._close_guard is not None:
            event.ignore()
            self._close_guard()
            return
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:
        if (
            event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
            and (self._saving or self._is_generation_active())
        ):
            event.ignore()
            return
        super().keyPressEvent(event)

    def _open_date_popup(
        self, which: str, x: float, y: float, width: float, height: float
    ) -> None:
        self._date_target = which
        top_left = self.quick.mapToGlobal(QPoint(int(x), int(y)))
        anchor = QRect(top_left, QSize(max(int(width), 0), max(int(height), 0)))
        # Since piece C3b (design D3) the popup bridge carries the dialog's own
        # coordinate pair — the game-calendar grid paints any valid coordinate
        # itself (intercalary chip included), so the picture-only clamp of
        # piece C3a is gone; an invalid stored coordinate, if any survived,
        # just leaves the popup un-prefilled.
        if which == "start":
            current = (self.vm._start_date, self.vm._start_bc)
        else:
            current = (self.vm._end_date, self.vm._end_bc)
        self.date_popup.open_at(anchor, current)

    def _set_selected_date(self, selected) -> None:
        # The popup answers with a (date, era) pair; a bare date keeps the
        # era the dialog already holds for that bound.
        value, is_bc = split_date_era(selected)
        if self._date_target == "start":
            self.vm.set_dates(start=value, start_bc=is_bc)
        else:
            self.vm.set_dates(end=value, end_bc=is_bc)

    def _open_related_picker(self, attr: str, label: str) -> None:
        section = self._sections[attr]
        candidates = section.candidates()
        if not candidates:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Выберите {label.lower()}")
        dialog.setMinimumSize(300, 400)
        layout = QVBoxLayout(dialog)
        items = QListWidget(dialog)
        items.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        for entity in candidates:
            item = QListWidgetItem(getattr(entity, "name", str(entity)))
            item.setData(256, getattr(entity, "id", None))
            items.addItem(item)
        layout.addWidget(items)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_ids = {item.data(256) for item in items.selectedItems()}
            for entity in candidates:
                if getattr(entity, "id", None) in selected_ids:
                    section.add_entity(entity)

    def _update_validity(self) -> None:
        self.vm.stateChanged.emit()

    def _restyle_type_icons(self) -> None:
        self.vm.stateChanged.emit()

    # Island lifecycle (context, deferred release) — IslandDialogMixin.
