"""Event creation/edit dialog: QML island in the stable QDialog facade."""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Callable

import shiboken6
from PySide6.QtCore import QEvent, QPoint, QRect, QSize, QTimer, Qt, Signal
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QWidget

from app.domain import entity_registry
from app.domain.enums.entity_type import EntityType
from app.presentation.card_tab_host import CardTabHost
from app.presentation.module_block_host import ModuleBlockHost
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
from app.presentation.qml.island_size import fit_dialog_to_island
from app.presentation.theme import get_default_theme
from app.presentation.utils.date_utils import era_flag, event_start_time, split_date_era
from app.presentation.viewmodels.event_dialog_island_view_model import (
    EventDialogIslandViewModel,
    RelatedSectionState,
)
from app.presentation.views.event_types_dialog import type_dot_icon
from app.presentation.views.ai_capable_dialog import AiCapableDialogBase
from app.presentation.views.related_picker_sheet import RelatedPickerSheet
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
    # Live-audit 2026-10-13 finding 2: the sheet canvas clears the widget's
    # framebuffer, so a dropped cocoa render frame below the content shows the
    # theme surface, never the white OS window canvas.
    ISLAND_SHEET_CANVAS = True

    def island_source(self) -> str:
        return ROOT_QML

    saved = Signal(object)  # EventCreateResult | EventEditResult (dialog_results)
    create_related_requested = Signal(str, str)
    # (type key, stored id as text) — str keeps an external composite id
    # intact (add-dnd-game-face design Д4; kernel ids arrive as the string of
    # the number and the composition edge converts them back to int)
    mention_clicked = Signal(str, str)
    #: NRI-0024 (task 2.5, design Д7): child-sheet show channel — the related
    #: picker is built here (its list is this dialog's section state) and the
    #: connector shows it through the one ``open_sheet`` path, so it stacks
    #: over this dialog, dims it one share, and its close returns here.
    sheet_requested = Signal(object)

    def __init__(
        self,
        event_dialog_vm,
        parent: QWidget | None = None,
        theme=None,
        now_vm=None,
        external_sources: Sequence[Any] = (),
        wiring: Any = None,
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
        self.setMinimumSize(720, 620)

        self.vm = EventDialogIslandViewModel(
            owner=self,
            parent=self,
            # NRI-0021 task 6.1 (spec «Дата „сейчас“ — дефолт новых записей»):
            # the new-dialog date bounds default to the game's «now»; the edit
            # flow's populate() overwrites them with the saved dates.
            now=(now_vm.coord, now_vm.is_bc) if now_vm is not None else None,
            # add-dnd-game-face (design Д1): the composition's external sources
            # reach every mention host of this dialog.
            external_sources=external_sources,
        )
        # NRI-0021 task 4.4 (design Д2/Д5): the read-only «С начала» line
        # follows the game's «now» while this dialog is open — same carrier
        # as the card (the wiring's widget VM), same teardown rule
        # (_release_island runs on every close route).
        self._now_vm = None
        if now_vm is not None:
            self._now_vm = now_vm
            self.vm.applyNow(now_vm.coord, now_vm.is_bc)
            now_vm.nowChanged.connect(self._resync_event_text)
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

        # add-dnd-game-face task 7.2 (design Д10): the external sources' extra
        # tabs ride the grouping strip's tail. The host collects them at
        # populate() (a fresh card has no record yet, so it shows the kernel
        # groups alone), overlays the module widget on the body slot the QML
        # page publishes, and releases every tab's subscriptions when this
        # island releases (the norm «a released island answers NOTHING»).
        self._card_tabs = CardTabHost(
            self,
            self.vm,
            external_sources,
            wiring,
            target_key=EntityType.EVENT.value,
        )
        # dd-card-redesign task 4.2 (design Д2): the same declarative block
        # channel as the entity card — the event screen grows module blocks at
        # the two anchors through the very same kernel mechanism (the event
        # has no music field, its «after_music» anchor is the form's tail).
        self._module_blocks = ModuleBlockHost(
            self,
            self.vm,
            external_sources,
            wiring,
            target_key=EntityType.EVENT.value,
        )
        # A fresh event never sees populate() — the empty-id collection is
        # the fresh-record answer of the channel (the same rule as the card).
        self._module_blocks.refresh(None)
        # dd-card-redesign task 3.2/3.4 (spec «Размер окна с табами следует
        # самому высокому содержимому»): the single screen opens at the pinned
        # 720×620 exactly as 0.19.1 did — no fit call touches that state. When
        # a guest tab joins, the scene re-publishes the bigger natural size
        # (strip + tallest page + stitched band + buttons) and the window
        # re-fits through the shared island sizer, floored at the pinned pair.
        self.vm.groupsChanged.connect(self._refit_for_guest_tabs)
        # Live-audit 2026-10-13 blocker (spec «Размер окна с табами следует
        # самому высокому содержимому»): a module frame can also arrive after
        # the opening fit — populate() re-aims the channel and the controller
        # republishes the loaded frame later than the constructor measured.
        # The ask then grows while the window stands still and the stitched
        # band with the buttons rides the scene below the bottom edge (the
        # card's live failure). The scene publishes the grown ask through
        # implicitHeightChanged — one coalesced re-fit follows it; the frame
        # signals themselves measure too early (the Repeater is still under
        # construction). The single-screen dialog returns inside the handler.
        self._root.implicitHeightChanged.connect(self._refit_after_module_frame)
        # Checkpoint-2 audit (spec dnd-encounters «Пустое событие тоже с
        # двумя табами»): the strip collects at construction too — a fresh
        # event opens with «Встреча» standing and honestly empty (staging
        # unlocks with the saved record). populate() re-aims edited cards.
        self._card_tabs.refresh(None)

        # NRI-0014 task 4.2 (E1): the scene only exists from here, so replay
        # the window title the constructor set before the island loaded. The
        # setWindowTitle override threads every later rename (populate) too.
        self.setWindowTitle(self.windowTitle())

        # P3 (NRI-0015): parent-less — under a chrome-attached ancestor the
        # generic QPushButton chrome rule would accent-fill every day cell
        # through the stylesheet parent chain; the popup sheet is its only skin.
        self.date_popup = ThemeDatePopup()
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

    def setWindowTitle(self, title: str) -> None:
        # NRI-0014 task 4.2 (E1): the header's title is the windowTitle, single
        # threaded value — a rename (populate → «Редактировать событие») lands
        # in the scene without a second owner. The guarded replay in the
        # constructor publishes the pre-island title once after the load.
        super().setWindowTitle(title)
        if getattr(self, "_root", None) is not None:
            self._root.setProperty("sheetTitle", title)

    def _refit_after_module_frame(self) -> None:
        # Coalesce one polish pass: the Repeater grows row by row and every
        # added row re-publishes the ask — one re-fit on the next loop turn
        # measures the settled scene (the entity card's facade carries the
        # long comment; live-audit 2026-10-13 blocker).
        QTimer.singleShot(0, self, self._refit_for_guest_tabs)

    def _refit_for_guest_tabs(self) -> None:
        # dd-card-redesign task 3.4: the re-fit door for the tabbed assembly
        # only — the single-screen dialog keeps the 720×620 the constructor
        # pinned, so the «ядро неотличимо от 0.19.1» profile pin holds without
        # a resize. The floor is that pinned pair: down the window never goes.
        root = getattr(self, "_root", None)
        if root is None or not shiboken6.isValid(root):
            return  # the island is gone — the emit raced the teardown
        if not self.vm.moduleGroups:
            return
        fit_dialog_to_island(self, root, floor=(720, 620))
        # Live-audit 2026-10-13 finding 2: the window grows with the strip; the
        # cocoa render control can drop the frame of a resize landing while the
        # native sheet animates. One render request on the next loop turn, when
        # the geometry has settled (the context-object form drops the request
        # if the dialog dies first).
        QTimer.singleShot(0, self, self.quick.update)

    def set_sheet_scrim_alpha(self, alpha: float) -> None:
        # NRI-0014 task 4.3 (CR5): the stack owner (ApplicationWiring counts
        # the sheets opened under this one) hands the finished dim alpha to
        # the sheetScrim layer; the dialog judges no depth, it only publishes
        # the value the scene paints. Closing a game releases the scene one
        # turn after the dialog dies while child sheets may still cascade
        # closed around it — a lift aimed at a released island drops silently
        # (the XlsxImportDialog publish_* contract): paint has nowhere to go.
        root = getattr(self, "_root", None)
        if root is not None and shiboken6.isValid(root):
            root.setProperty("sheetScrimAlpha", alpha)

    def prefill_parent(self, parent: Any) -> None:
        """Open the create dialog as a sub-event of ``parent`` (NRI-0023
        task 6.1, spec «Создание подсобытия правым кликом»): the parent id
        rides the save contract through ``vm.parent_id``, the start date is
        the parent's one (its era included). The start TIME stays empty —
        the «Час»/«Минута» combos (task 7.2) keep their штатный «—» default,
        the spec pins the prefilled time as empty. The end date keeps the
        flow's own default, exactly as in a plain create."""
        self.vm.parent_id = getattr(parent, "id", None)
        start = getattr(parent, "start_date", None)
        if start is not None:
            self.vm.set_dates(
                start=start, start_bc=era_flag(getattr(parent, "start_bc", False))
            )

    def set_parent_options(self, events: list[Any]) -> None:
        """Fill the «Родительское событие» combo's candidate pool (task 7.1):
        the connector's event list goes to the ViewModel as-is; the VM keeps
        main events only, and the edited event is excluded through the id this
        facade already holds — which is why the connector loads it AFTER
        populate() in the edit flow."""
        self.vm.set_parent_options(list(events), exclude_id=self._event_id)

    def populate(self, event: Any) -> None:
        self._event_id = getattr(event, "id", None)
        self.setWindowTitle("Редактировать событие")
        self.vm.name = getattr(event, "name", "")
        event_type = getattr(event, "event_type", None)
        self._pending_type_id = getattr(event_type, "id", None)
        self.vm.set_event_types(self.vm._types, self._pending_type_id)
        # NRI-0023 tasks 7.1/7.2: the parent link and the wall-clock start
        # ride the very slots the card's combos edit, so a save that never
        # touches them re-writes what was loaded (and an out-of-bounds hour
        # from a narrowed calendar reads empty — the VM's sanitisation).
        self.vm.parent_id = getattr(event, "parent_id", None)
        self.vm.set_start_time(event_start_time(event))
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
        # Task 7.2: the record is known from here — the external sources may
        # now declare their extra tabs for exactly this event.
        self._card_tabs.refresh(
            str(self._event_id) if self._event_id is not None else None
        )
        # Task 4.2: the module-block channel is collected the same way.
        self._module_blocks.refresh(
            str(self._event_id) if self._event_id is not None else None
        )

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
            # NRI-0023 task 6.1/7.1: the sub-event link (prefill on the
            # «Создать подсобытие» flow, the combo's value once edited);
            # task 7.2: the optional wall-clock start, None = без времени.
            "parent_id": self.vm.parent_id,
            "start_time": self.vm.start_time,
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

    def external_tab_saves(self) -> tuple:
        """The module tabs' staged writes (add-dnd-game-face task 11.1,
        design Д10): the connector awaits these coroutines inside its locked
        save task, after the kernel event fields were written and before the
        timeline reloads. Which tabs stage and how is the host's bookkeeping
        (CardTabHost.save_hooks); the dialog only forwards — the connector
        never reaches into the host's private dict. A refusal raised by a tab
        keeps the card open with its own Russian text (the connector reports
        it and lifts the saving state)."""
        return self._card_tabs.save_hooks()

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
        # PR-029 (spec qml-shell «Минразмер и defaultButton»): Enter is the
        # sheet's save shortcut. The scene keeps what it consumes — the two
        # multiline MentionFields take Return into their own text, so a newline
        # typed in «Предыстория» never reaches this line — and while the form
        # is invalid, saving or generating the «Сохранить» marker is disabled,
        # so the shared bridge leaves the key where Qt would have left it.
        if self.take_island_default_key(event):
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
        # Task 2.5: the exec'd picker dialog is gone — the same choice is the
        # shared island sheet now, handed to the connector's stack over this
        # dialog (spec modal-sheets «Цепочка … закрытие верхнего возвращает к
        # нижнему»); PR-020 moved its rows onto RowItem so the accessibility
        # tree can name and press them.
        picker = RelatedPickerSheet(
            f"Выберите {label.lower()}", section, candidates, self, self._theme
        )
        self.sheet_requested.emit(picker)

    def _update_validity(self) -> None:
        self.vm.stateChanged.emit()

    def _restyle_type_icons(self) -> None:
        self.vm.stateChanged.emit()

    def _release_island(self) -> None:
        # add-dnd-game-face task 7.2: the module tabs leave first — their own
        # subscriptions retire through release_tab while the island still
        # answers, then the island teardown proceeds (no listener survives).
        self._card_tabs.release()
        # dd-card-redesign task 4.2: the module-block handlers retire the same
        # way — no module listener may outlive the dialog.
        self._module_blocks.release()
        # NRI-0021 task 4.4: the «now» subscription leaves with the dialog
        # (DEFECT-1 posture — no listener survives its window).
        if self._now_vm is not None:
            self._now_vm.nowChanged.disconnect(self._resync_event_text)
            self._now_vm = None
        super()._release_island()

    def _resync_event_text(self) -> None:
        """nowChanged receiver: re-read the served value into the VM, whose
        eventTextChanged then repaints the read-only row."""
        if self._now_vm is not None:
            self.vm.applyNow(self._now_vm.coord, self._now_vm.is_bc)

    # Island lifecycle (context, deferred release) — IslandDialogMixin.
