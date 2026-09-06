"""Synchronous state and wiring proxies for the event-dialog QML island."""
from __future__ import annotations

from datetime import date
from typing import Any, Callable

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtWidgets import QMessageBox

from app.presentation.utils.date_utils import format_game_date
from app.presentation.viewmodels.mention_field_host import MentionFieldHost
AI_STATE_PROPERTY = "aiState"
AI_STATE_ACTIVE = "active"
AI_STATE_DISABLED = "disabled"
NOT_CONFIGURED_MESSAGE = (
    "AI-ассистент не настроен.\n"
    "Настройте LLM в меню LLM → Настройка LLM…\n"
    "(укажите endpoint, модель и при необходимости ключ API)."
)
NO_WORLD_PROMPT_MESSAGE = (
    "Не задан промт мира.\n"
    "Перейдите в меню LLM → Настройка LLM… и опишите ваш мир."
)


def ai_state_is(obj: QObject, state: str) -> bool:
    value = obj.property(AI_STATE_PROPERTY)
    return value is not None and value == state


class RelatedSectionState(QObject):
    changed = Signal()
    linkRequested = Signal()
    createRequested = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._entities: list[Any] = []
        self._available: list[Any] = []
        self._selected = -1

    rows = Property(
        "QVariant",
        lambda self: [
            {"id": getattr(item, "id", None), "name": getattr(item, "name", str(item))}
            for item in self._entities
        ],
        notify=changed,
    )
    selectedIndex = Property(int, lambda self: self._selected, notify=changed)

    def set_entities(self, entities: list[Any]) -> None:
        self._entities = list(entities)
        self._selected = -1
        self.changed.emit()

    def set_available(self, entities: list[Any]) -> None:
        self._available = list(entities)

    def add_entity(self, entity: Any) -> None:
        if getattr(entity, "id", None) not in self.get_current_ids():
            self._entities.append(entity)
            self.changed.emit()

    def get_current_ids(self) -> list[int | None]:
        return [getattr(item, "id", None) for item in self._entities]

    def candidates(self) -> list[Any]:
        current = set(self.get_current_ids())
        return [
            item for item in self._available
            if getattr(item, "id", None) not in current
        ]

    @Slot(int)
    def select(self, index: int) -> None:
        selected = index if 0 <= index < len(self._entities) else -1
        if selected != self._selected:
            self._selected = selected
            self.changed.emit()

    @Slot()
    def requestLink(self) -> None:  # noqa: N802
        self.linkRequested.emit()

    @Slot()
    def requestCreate(self) -> None:  # noqa: N802
        self.createRequested.emit()

    @Slot()
    def unlinkSelected(self) -> None:  # noqa: N802
        if 0 <= self._selected < len(self._entities):
            self._entities.pop(self._selected)
            self._selected = -1
            self.changed.emit()


class MentionEditProxy(QObject):
    mention_search_requested = Signal(str)
    mention_clicked = Signal(str, int)

    def __init__(self, host: MentionFieldHost, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.host = host
        host.searchRequested.connect(self.mention_search_requested)
        host.mentionClicked.connect(self.mention_clicked)

    def show_mention_results(self, results: list[dict]) -> None:
        self.host.showResults(results)

    def getContent(self) -> str:
        return self.host.storage

    def setContent(self, value: str) -> None:
        self.host.storage = value

    def toPlainText(self) -> str:
        return self.host.display

    def setPlainText(self, value: str) -> None:
        self.host.storage = value


class AiFieldProxy(QObject):
    generate_requested = Signal(str, str, str, str)
    stateChanged = Signal()

    def __init__(
        self,
        entity_type: str,
        field_name: str,
        field_label: str,
        getter: Callable[[], str],
        setter: Callable[[str], None],
        owner,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._entity_type = entity_type
        self._field_name = field_name
        self._field_label = field_label
        self._getter = getter
        self._setter = setter
        self._owner = owner
        self._status = "not_configured"
        self._has_world_prompt = False
        self._generating = False
        self._ai_state = AI_STATE_DISABLED

    @property
    def entity_type(self) -> str:
        return self._entity_type

    @property
    def field_name(self) -> str:
        return self._field_name

    @property
    def field_label(self) -> str:
        return self._field_label

    @property
    def is_generating(self) -> bool:
        return self._generating

    @property
    def current_text(self) -> str:
        return self._getter()

    currentText = Property(str, lambda self: self.current_text, notify=stateChanged)
    aiState = Property(str, lambda self: self._ai_state, notify=stateChanged)
    generating = Property(bool, lambda self: self._generating, notify=stateChanged)
    clickable = Property(bool, lambda self: not self._generating, notify=stateChanged)

    def update_llm_state(self, status: str, has_world_prompt: bool) -> None:
        self._status = status
        self._has_world_prompt = has_world_prompt
        state = (
            AI_STATE_ACTIVE
            if status == "ready" and has_world_prompt
            else AI_STATE_DISABLED
        )
        self._ai_state = state
        self.stateChanged.emit()

    def set_generating(self, generating: bool) -> None:
        self._generating = generating
        self.stateChanged.emit()

    def set_result_text(self, text: str) -> None:
        self._setter(text)
        self.set_generating(False)

    def click(self) -> None:
        self.requestGenerate()

    def isEnabled(self) -> bool:
        return not self._generating

    @Slot()
    def requestGenerate(self) -> None:  # noqa: N802
        if self._generating:
            return
        if self._status != "ready":
            QMessageBox.information(self._owner, "AI-ассистент", NOT_CONFIGURED_MESSAGE)
            return
        if not self._has_world_prompt:
            QMessageBox.information(self._owner, "AI-ассистент", NO_WORLD_PROMPT_MESSAGE)
            return
        self.generate_requested.emit(
            self._entity_type,
            self._field_name,
            self._field_label,
            self.current_text,
        )


class EntityGenerateProxy(QObject):
    batch_requested = Signal()
    batch_cancel_requested = Signal()
    stateChanged = Signal()

    def __init__(self, owner, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._owner = owner
        self._status = "not_configured"
        self._has_world_prompt = False
        self._wave = False
        self._single = False
        self._ai_state = AI_STATE_DISABLED

    @property
    def is_cancelling(self) -> bool:
        return self._wave

    aiState = Property(str, lambda self: self._ai_state, notify=stateChanged)
    generating = Property(bool, lambda self: self._wave, notify=stateChanged)
    clickable = Property(bool, lambda self: not self._single, notify=stateChanged)
    currentText = Property(str, lambda self: "", constant=True)

    def update_llm_state(self, status: str, has_world_prompt: bool) -> None:
        self._status = status
        self._has_world_prompt = has_world_prompt
        self._refresh()

    def isEnabled(self) -> bool:
        return not self._single

    def text(self) -> str:
        return "⏹" if self._wave else "✨"

    def click(self) -> None:
        self.requestGenerate()

    def set_wave_running(self, running: bool) -> None:
        self._wave = running
        self._refresh()

    def set_single_in_flight(self, running: bool) -> None:
        self._single = running
        self._refresh()

    def _refresh(self) -> None:
        active = self._wave or (
            not self._single and self._status == "ready" and self._has_world_prompt
        )
        self._ai_state = AI_STATE_ACTIVE if active else AI_STATE_DISABLED
        self.stateChanged.emit()

    @Slot()
    def requestGenerate(self) -> None:  # noqa: N802
        if self._wave:
            self.batch_cancel_requested.emit()
        elif self._single:
            return
        elif self._status != "ready":
            QMessageBox.information(self._owner, "AI-ассистент", NOT_CONFIGURED_MESSAGE)
        elif not self._has_world_prompt:
            QMessageBox.information(self._owner, "AI-ассистент", NO_WORLD_PROMPT_MESSAGE)
        else:
            self.batch_requested.emit()


class EventDialogIslandViewModel(QObject):
    stateChanged = Signal()
    saveRequested = Signal()
    cancelRequested = Signal()
    datePopupRequested = Signal(str, float, float, float, float)

    def __init__(self, owner=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._owner = owner
        self._name = ""
        self._start_date = date.today()
        self._end_date = date.today()
        self._no_end = False
        self._save_locked = False
        self._saving = False
        self._types: list[Any] = []
        self._selected_type_index = 0
        self.characteristicsHost = MentionFieldHost(self)
        self.backstoryHost = MentionFieldHost(self)
        self.characteristicsEdit = MentionEditProxy(self.characteristicsHost, self)
        self.backstoryEdit = MentionEditProxy(self.backstoryHost, self)
        self.characteristicsHost.storageChanged.connect(self.stateChanged)
        self.backstoryHost.storageChanged.connect(self.stateChanged)
        self.nameAi = AiFieldProxy(
            "event", "name", "Название",
            lambda: self._name, self._set_name, owner, self,
        )
        self.characteristicsAi = AiFieldProxy(
            "event", "characteristics", "Характеристики",
            lambda: self.characteristicsHost.storage,
            lambda value: setattr(self.characteristicsHost, "storage", value),
            owner,
            self,
        )
        self.backstoryAi = AiFieldProxy(
            "event", "backstory", "Предыстория",
            lambda: self.backstoryHost.storage,
            lambda value: setattr(self.backstoryHost, "storage", value),
            owner,
            self,
        )
        self.entityAi = EntityGenerateProxy(owner, self)
        self.sections = {
            "organizations": RelatedSectionState(self),
            "characters": RelatedSectionState(self),
            "items": RelatedSectionState(self),
            "locations": RelatedSectionState(self),
        }
        self.organizations = self.sections["organizations"]
        self.characters = self.sections["characters"]
        self.items = self.sections["items"]
        self.locations = self.sections["locations"]

    characteristicsMentionHost = Property(
        QObject, lambda self: self.characteristicsHost, constant=True
    )
    backstoryMentionHost = Property(
        QObject, lambda self: self.backstoryHost, constant=True
    )
    nameAiProxy = Property(QObject, lambda self: self.nameAi, constant=True)
    characteristicsAiProxy = Property(
        QObject, lambda self: self.characteristicsAi, constant=True
    )
    backstoryAiProxy = Property(QObject, lambda self: self.backstoryAi, constant=True)
    entityAiProxy = Property(QObject, lambda self: self.entityAi, constant=True)
    organizationsSection = Property(
        QObject, lambda self: self.organizations, constant=True
    )
    charactersSection = Property(QObject, lambda self: self.characters, constant=True)
    itemsSection = Property(QObject, lambda self: self.items, constant=True)
    locationsSection = Property(QObject, lambda self: self.locations, constant=True)

    def _set_name(self, value: str) -> None:
        if value != self._name:
            self._name = value
            self.stateChanged.emit()

    name = Property(str, lambda self: self._name, _set_name, notify=stateChanged)
    startIso = Property(str, lambda self: self._start_date.isoformat(), notify=stateChanged)
    endIso = Property(str, lambda self: self._end_date.isoformat(), notify=stateChanged)
    startDisplay = Property(
        str, lambda self: format_game_date(self._start_date), notify=stateChanged
    )
    endDisplay = Property(
        str, lambda self: format_game_date(self._end_date), notify=stateChanged
    )
    noEnd = Property(bool, lambda self: self._no_end, notify=stateChanged)
    saveLocked = Property(bool, lambda self: self._save_locked, notify=stateChanged)
    saving = Property(bool, lambda self: self._saving, notify=stateChanged)
    valid = Property(
        bool,
        lambda self: bool(self._name.strip())
        and bool(
            self.characteristicsHost.storage.strip()
            or self.backstoryHost.storage.strip()
        )
        and (self._no_end or self._end_date >= self._start_date)
        and not self._save_locked
        and not self._saving,
        notify=stateChanged,
    )
    typeNames = Property(
        "QVariant",
        lambda self: ["Без типа"] + [getattr(item, "name", "") for item in self._types],
        notify=stateChanged,
    )
    selectedTypeIndex = Property(
        int, lambda self: self._selected_type_index, notify=stateChanged
    )
    selectedColorIndex = Property(
        int,
        lambda self: (
            0
            if self._selected_type_index == 0
            else int(getattr(self._types[self._selected_type_index - 1], "color_index", 1))
        ),
        notify=stateChanged,
    )

    def set_dates(self, start: date | None = None, end: date | None = None) -> None:
        if start is not None:
            self._start_date = start
        if end is not None:
            self._end_date = end
        self.stateChanged.emit()

    def set_no_end(self, value: bool) -> None:
        if value != self._no_end:
            self._no_end = value
            self.stateChanged.emit()

    def set_event_types(
        self, types: list[Any], current_type_id: int | None = None
    ) -> None:
        self._types = list(types)
        self._selected_type_index = 0
        if current_type_id is not None:
            for index, event_type in enumerate(self._types, 1):
                if getattr(event_type, "id", None) == current_type_id:
                    self._selected_type_index = index
                    break
        self.stateChanged.emit()

    @property
    def selected_type_id(self) -> int | None:
        if self._selected_type_index == 0:
            return None
        return getattr(self._types[self._selected_type_index - 1], "id", None)

    @Slot(bool)
    def setNoEnd(self, value: bool) -> None:  # noqa: N802
        self.set_no_end(value)

    @Slot(int)
    def selectType(self, index: int) -> None:  # noqa: N802
        if 0 <= index <= len(self._types) and index != self._selected_type_index:
            self._selected_type_index = index
            self.stateChanged.emit()

    @Slot(str, float, float, float, float)
    def requestDatePopup(  # noqa: N802
        self, which: str, x: float, y: float, width: float, height: float
    ) -> None:
        self.datePopupRequested.emit(which, x, y, width, height)

    @Slot()
    def requestSave(self) -> None:  # noqa: N802
        if self.valid:
            self.saveRequested.emit()

    @Slot()
    def requestCancel(self) -> None:  # noqa: N802
        self.cancelRequested.emit()

    def set_save_locked(self, locked: bool) -> None:
        if locked != self._save_locked:
            self._save_locked = locked
            self.stateChanged.emit()

    def set_saving(self, saving: bool) -> None:
        if saving != self._saving:
            self._saving = saving
            self.stateChanged.emit()
