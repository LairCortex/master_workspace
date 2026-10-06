"""Synchronous state and wiring proxies for the event-dialog QML island."""
from __future__ import annotations

from datetime import date
from typing import Any, Callable

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtWidgets import QMessageBox

from app.application.services.llm_status import LlmStatus
from app.domain import entity_registry
from app.domain.date_era import duration_parts, era_key
from app.domain.enums.entity_type import EntityType
from app.domain.options import EntityOption, EventOption, EventTypeOption
from app.domain.game_calendar import (
    GameCoord,
    InvalidGameDateError,
    as_game_coord,
    current_calendar,
)
from app.domain.time_of_day import TimeOfDay
from app.presentation.entity_icons import icon_for
from app.presentation.utils.date_utils import (
    format_duration_words,
    format_event_start,
    format_game_date,
    iso_or_coord,
    worst_case_date_caption,
)
from app.presentation.utils.time_options import minute_options
from app.presentation.viewmodels.mention_field_host import MentionFieldHost

#: Caption of the read-only elapsed line of the event dialog (NRI-0021
#: task 4.4, spec «Read-only отображение производных величин»): the visible
#: «С начала: <формула>» row; the formula itself is the single duration word
#: helper, counted from the event start to «now» regardless of the end.
SINCE_LABEL = "С начала: "
#: The empty head of the dialog's three dropdown lists (NRI-0023 tasks 7.1/7.2,
#: specs «Поле „Родительское событие“…» and «Списки часов и минут…»): index 0
#: of every model means «нет значения» — no parent, no hour, no minute.
EMPTY_OPTION = "—"
#: Lucide glyphs of the dialog's four relation tabs, in the registry's EVENT
#: relation order (the same order as the tab captions) — read off the one
#: type→icon map (Lucide pass 2026-09-30, one knowledge, one place).
RELATED_TAB_ICONS: tuple[str, ...] = tuple(
    icon_for(ref.entity_type)
    for ref in entity_registry.related_refs(EntityType.EVENT)
)

AI_STATE_PROPERTY = "aiState"
AI_STATE_ACTIVE = "active"
AI_STATE_DISABLED = "disabled"
NOT_CONFIGURED_MESSAGE = (
    "AI-ассистент не настроен.\n"
    "Настройте LLM в меню LLM → Настройка LLM…\n"
    "(укажите endpoint, модель и при необходимости ключ API)."
)
NO_WORLD_PROMPT_MESSAGE = (
    "Не задан промпт мира.\n"
    "Перейдите в меню LLM → Настройка LLM… и опишите ваш мир."
)  # NRI-0016 LS3: the one dictionary root «промпт» (design V5)


def ai_state_is(obj: QObject, state: str) -> bool:
    value = obj.property(AI_STATE_PROPERTY)
    return value is not None and value == state


class RelatedSectionState(QObject):
    changed = Signal()
    linkRequested = Signal()
    createRequested = Signal()

    def __init__(
        self, parent: QObject | None = None, *, can_create: bool = True
    ) -> None:
        super().__init__(parent)
        self._entities: list[Any] = []
        self._available: list[Any] = []
        self._selected = -1
        self._can_create = can_create

    #: Visibility of the section's «Создать нового» entry (design claim
    #: 2026-10-06: a shown button must work).  The related-create popup card
    #: is the one consumer built with False — at depth = 1 the nested create
    #: signal has no receiver, so its card hides the button; every other
    #: section (event dialog, plain cards) keeps the default True.  Set once
    #: at construction, never rewritten — hence a constant property.
    canCreate = Property(bool, lambda self: self._can_create, constant=True)

    rows = Property(
        "QVariant",
        lambda self: [
            {"id": getattr(item, "id", None), "name": getattr(item, "name", str(item))}
            for item in self._entities
        ],
        notify=changed,
    )
    selectedIndex = Property(int, lambda self: self._selected, notify=changed)

    # PR-032: the entrances below flatten whatever row arrives into frozen
    # EntityOptions.  The connector feeds live ORM rows (the edited entity's
    # relation lists, the census for the picker) and the section rows/candidates
    # are re-read from the QML side long after a failed save rolled the shared
    # session back — an expired lazy attribute read there was the
    # MissingGreenlet storm.  Nothing stored here can go lazy.

    def set_entities(self, entities: list[Any]) -> None:
        self._entities = [EntityOption.coerce(entity) for entity in entities]
        self._selected = -1
        self.changed.emit()

    def set_available(self, entities: list[Any]) -> None:
        self._available = [EntityOption.coerce(entity) for entity in entities]

    def add_entity(self, entity: Any) -> None:
        option = EntityOption.coerce(entity)
        if option.id not in self.get_current_ids():
            self._entities.append(option)
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


class AiStateHolder(QObject):
    """Shared QObject mixin behind both AI proxies (NRI-0011 D3, precedent
    IslandDialogMixin): the single ``aiState`` contract (the string values and
    the QML-facing property paths stay exactly as before, ``ai_state_is()``
    keeps reading them), the LLM-context fields and the state refresh.

    Only a signal declared in the very same class can notify a PySide6
    ``Property`` (a cross-class ``notify`` registers as non-bindable), so all
    six QML-facing proxy properties and ``stateChanged`` live here while each
    proxy keeps its own rules through the hooks referenced from below.
    """

    stateChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._status = LlmStatus.NOT_CONFIGURED
        self._has_world_prompt = False
        self._ai_state = AI_STATE_DISABLED

    aiState = Property(str, lambda self: self._ai_state, notify=stateChanged)
    generating = Property(bool, lambda self: self._is_generating(), notify=stateChanged)
    clickable = Property(bool, lambda self: self._is_clickable(), notify=stateChanged)
    currentText = Property(str, lambda self: self._current_text(), notify=stateChanged)
    # A4 (live fix 2026-09-30): a batch wave makes the AI button a stop — the
    # QML face reads this instead of the retired mute «⏹» text() the widgets
    # era left behind. Declared HERE (same class as ``stateChanged``) for the
    # bindability rule above; each proxy keeps its own answer through the hook.
    isCancelling = Property(bool, lambda self: self._is_cancelling(), notify=stateChanged)

    def update_llm_state(self, status: str, has_world_prompt: bool) -> None:
        self._status = status
        self._has_world_prompt = has_world_prompt
        self._refresh_ai_state()

    def _is_cancelling(self) -> bool:
        return False

    def _refresh_ai_state(self) -> None:
        self._ai_state = AI_STATE_ACTIVE if self._is_ai_active() else AI_STATE_DISABLED
        self.stateChanged.emit()


class AiFieldProxy(AiStateHolder):
    generate_requested = Signal(str, str, str, str)

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
        self._generating = False

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

    # The aiState/generating/clickable/currentText properties and the LLM-state
    # refresh are inherited from AiStateHolder; this proxy keeps its own rules:
    # a field generation never overlaps itself, and AI is offered only while the
    # assistant is ready and a world prompt exists (the generating guard for
    # clicks lives in requestGenerate/isEnabled, unchanged).

    def _is_ai_active(self) -> bool:
        return self._status == LlmStatus.READY and self._has_world_prompt

    def _is_generating(self) -> bool:
        return self._generating

    def _is_clickable(self) -> bool:
        return not self._generating

    def _current_text(self) -> str:
        return self._getter()

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
        if self._status != LlmStatus.READY:
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


class EntityGenerateProxy(AiStateHolder):
    batch_requested = Signal()
    batch_cancel_requested = Signal()

    def __init__(self, owner, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._owner = owner
        self._wave = False
        self._single = False

    @property
    def is_cancelling(self) -> bool:
        return self._wave

    # aiState/generating/clickable/currentText and update_llm_state come from
    # AiStateHolder; the package rule stays here: AI is offered while a batch
    # wave is running (the button doubles as stop) or when neither a wave nor a
    # single-field generation is in flight and the assistant is configured.

    def isEnabled(self) -> bool:
        return not self._single

    def click(self) -> None:
        self.requestGenerate()

    def set_wave_running(self, running: bool) -> None:
        self._wave = running
        self._refresh_ai_state()

    def set_single_in_flight(self, running: bool) -> None:
        self._single = running
        self._refresh_ai_state()

    def _is_ai_active(self) -> bool:
        return self._wave or (
            not self._single and self._status == LlmStatus.READY and self._has_world_prompt
        )

    def _is_generating(self) -> bool:
        return self._wave

    def _is_cancelling(self) -> bool:
        # A4: while the wave runs the button's press stops it — the QML face
        # prints the Lucide «circle-stop» glyph on this answer.
        return self._wave

    def _is_clickable(self) -> bool:
        return not self._single

    def _current_text(self) -> str:
        return ""

    @Slot()
    def requestGenerate(self) -> None:  # noqa: N802
        if self._wave:
            self.batch_cancel_requested.emit()
        elif self._single:
            return
        elif self._status != LlmStatus.READY:
            QMessageBox.information(self._owner, "AI-ассистент", NOT_CONFIGURED_MESSAGE)
        elif not self._has_world_prompt:
            QMessageBox.information(self._owner, "AI-ассистент", NO_WORLD_PROMPT_MESSAGE)
        else:
            self.batch_requested.emit()


class EventDialogIslandViewModel(QObject):
    stateChanged = Signal()
    #: Derived-surface fan-out (NRI-0021 task 4.4): re-raised when the
    #: read-only «С начала» line must be re-read (start edited or «now» moved).
    eventTextChanged = Signal()
    saveRequested = Signal()
    cancelRequested = Signal()
    datePopupRequested = Signal(str, float, float, float, float)

    def __init__(
        self,
        owner=None,
        parent: QObject | None = None,
        now: tuple[GameCoord, bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._owner = owner
        self._name = ""
        # Date bridges carry (GameCoord, era) pairs (piece C3a, designs D4/D6,
        # since task 5.2).  NRI-0021 task 6.1 (spec «Дата „сейчас“ — дефолт
        # новых записей»): a new dialog opens with the game's «now» — the
        # facade injects the widget VM's served (coord, era) pair at
        # construction and an edit's populate() overwrites it with the saved
        # dates; a VM built without a game keeps the legacy «сегодня, н.э.»
        # fallback (today's numbers as the equal month-day coordinate).
        if now is not None:
            now_coord, now_bc = now
            self._start_date: GameCoord = now_coord
            self._end_date: GameCoord = now_coord
            self._start_bc = self._end_bc = bool(now_bc)
        else:
            self._start_date = as_game_coord(date.today())
            self._end_date = as_game_coord(date.today())
            self._start_bc = False
            self._end_bc = False
        self._no_end = False
        # NRI-0023 task 6.1 (spec «Создание подсобытия правым кликом»): the
        # parent link the dialog carries. The «Создать подсобытие» flow
        # prefills it through the facade; a plain create stays None. Task 7.1
        # moves its visible face (the «Родительское событие» combo) onto this
        # same slot — the value lives here, in the ViewModel, nowhere else.
        self._parent_id: int | None = None
        # NRI-0023 task 7.1 (spec «Поле „Родительское событие“ в карточке
        # события»): the combo's raw candidate list (the connector hands over
        # the game's events) and the edited event's id, excluded from the list
        # so a card never offers itself as its own parent.
        self._parent_candidates: list[Any] = []
        self._parent_exclude_id: int | None = None
        # NRI-0023 task 7.2 (spec event-time «Списки часов и минут…»): the
        # wall-clock start as the two combo selections. A None hour means «без
        # времени»; a None minute with a chosen hour saves as minute 0.
        self._start_hour: int | None = None
        self._start_minute: int | None = None
        # NRI-0021 task 4.4: the mirrored game «now» (fed by the facade from
        # the widget VM); None without a game open — the «С начала» line then
        # stays empty.
        self._now_coord: GameCoord | None = None
        self._now_bc = False
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
    relatedTabIcons = Property(
        "QVariant", lambda self: list(RELATED_TAB_ICONS), constant=True
    )

    def _set_name(self, value: str) -> None:
        if value != self._name:
            self._name = value
            self.stateChanged.emit()

    def _set_parent_id(self, value: int | None) -> None:
        if value != self._parent_id:
            self._parent_id = None if value is None else int(value)
            self.stateChanged.emit()

    name = Property(str, lambda self: self._name, _set_name, notify=stateChanged)
    # NRI-0023 task 6.1: the sub-event parent slot (Python contract; task 7.1
    # binds the «Родительское событие» combo onto this same value).
    parent_id = Property(
        "QVariant", lambda self: self._parent_id, _set_parent_id, notify=stateChanged
    )
    # ``Iso`` strings (piece C3a, design D5): ISO while the coordinate is
    # representable as a real date (bit-for-bit the previous string), the
    # domain codec text otherwise; QML reads them verbatim and parses none.
    startIso = Property(str, lambda self: iso_or_coord(self._start_date), notify=stateChanged)
    endIso = Property(str, lambda self: iso_or_coord(self._end_date), notify=stateChanged)
    startDisplay = Property(
        str,
        # NRI-0023 task 8.1 (design Д9, spec event-time «Время на поверхностях
        # события»): the card prints its start through the single surface
        # helper — a chosen time rides the date as «, HH:MM», the empty one
        # keeps the caption bit-for-bit (start_time is None then).
        lambda self: format_event_start(
            self._start_date, self._start_bc, self.start_time
        ),
        notify=stateChanged,
    )
    endDisplay = Property(
        str,
        lambda self: format_game_date(self._end_date, is_bc=self._end_bc),
        notify=stateChanged,
    )
    # Width floor (nri-0017 task 1.1, design F1): the widest caption the
    # active calendar can print, handed to both ThemeDateFields as their
    # worstCaseText so their minimum width never lets the elide eat the year
    # (M2). It depends on the calendar, not on the dates, so one hint serves
    # both fields; the dialog VM is rebuilt whenever the calendar is (C2).
    worstCaseDisplay = Property(
        str, lambda self: worst_case_date_caption(), notify=stateChanged
    )
    # Era facets (add-era-aware-dates, task 4.1 / design D6): the display
    # strings above already carry the «N г. до н.э.» suffix — QML never derives
    # an era, it only mirrors these ready-made flags onto its field facets.
    startBc = Property(bool, lambda self: self._start_bc, notify=stateChanged)
    endBc = Property(bool, lambda self: self._end_bc, notify=stateChanged)
    noEnd = Property(bool, lambda self: self._no_end, notify=stateChanged)
    # NRI-0021 task 4.4 (spec «Прошедшее время от начала события»): the
    # read-only «С начала: <формула>» line — counted from the start to «now»
    # whatever the end says (an open and a closed event read the same), a
    # future start reads «через N», the same day reads «сегодня».  Display
    # only: like the card's age, it never enters the save result.
    eventText = Property(str, lambda self: self._event_text(), notify=eventTextChanged)
    saveLocked = Property(bool, lambda self: self._save_locked, notify=stateChanged)
    saving = Property(bool, lambda self: self._saving, notify=stateChanged)
    valid = Property(
        bool,
        lambda self: bool(self._name.strip())
        and bool(
            self.characteristicsHost.storage.strip()
            or self.backstoryHost.storage.strip()
        )
        # «end не раньше start» lives on the single chronological key
        # (design D2) — a bare date compare is wrong across the eras.
        and (
            self._no_end
            or era_key(self._end_date, self._end_bc)
            >= era_key(self._start_date, self._start_bc)
        )
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

    # ── «Родительское событие» (NRI-0023 task 7.1, spec «Поле „Родительское
    # событие“ в карточке события») ──────────────────────────────────────────
    # The list is «—» plus every MAIN event of the game — sub-events never
    # qualify (two-level nesting), and the edited event is excluded so a card
    # cannot parent itself.  The connector list is flattened to EventOptions
    # at set_parent_options (PR-032); the filtering happens at read, so
    # loading before or after populate cannot matter.  index 0 of the model
    # means «без родителя».

    def _parent_choices(self) -> list[Any]:
        return [
            item
            for item in self._parent_candidates
            if getattr(item, "parent_id", None) is None
            and getattr(item, "id", None) != self._parent_exclude_id
        ]

    def set_parent_options(
        self, events: list[Any], exclude_id: int | None = None
    ) -> None:
        """Hand the combo its candidates (the connector's event list, the
        whole set — the main-only/self filtering is the read-time rule).
        PR-032: the rows are flattened to EventOptions right here, so the
        parentNames/selectedParentIndex metacalls survive a later rollback."""
        self._parent_candidates = [EventOption.coerce(event) for event in events]
        self._parent_exclude_id = exclude_id
        self.stateChanged.emit()

    parentNames = Property(
        "QVariant",
        lambda self: [EMPTY_OPTION] + [
            getattr(item, "name", "") for item in self._parent_choices()
        ],
        notify=stateChanged,
    )
    selectedParentIndex = Property(
        int, lambda self: self._selected_parent_index(), notify=stateChanged
    )

    def _selected_parent_index(self) -> int:
        if self._parent_id is None:
            return 0
        for index, item in enumerate(self._parent_choices(), 1):
            if getattr(item, "id", None) == self._parent_id:
                return index
        return 0

    @Slot(int)
    def selectParent(self, index: int) -> None:  # noqa: N802
        choices = self._parent_choices()
        if not 0 <= index <= len(choices):
            return
        self._set_parent_id(
            None if index == 0 else getattr(choices[index - 1], "id", None)
        )

    # ── «Час»/«Минута» (NRI-0023 task 7.2, spec «Списки часов и минут в
    # карточке события») ─────────────────────────────────────────────────────
    # Bounds come from the active calendar — nothing here hardcodes 24/60.
    # The minute list offers the pure helper's ladder, is enabled only while
    # an hour is chosen, and «час без минут» saves as minute 0.

    @property
    def start_time(self) -> TimeOfDay | None:
        """The save-bound value: None without an hour (never a fabricated
        00:00), else the hour with the chosen minute or 0 («час без минут»)."""
        if self._start_hour is None:
            return None
        return TimeOfDay(hour=self._start_hour, minute=self._start_minute or 0)

    def set_start_time(self, start_time: TimeOfDay | None) -> None:
        """Load a stored time into the two selections, sanitised against the
        ACTIVE calendar (spec «Смена размера суток…»): an hour outside the
        current day or a minute the current ladder cannot show reads as empty
        and therefore never re-participates in a save until the user picks a
        valid value."""
        calendar = current_calendar()
        hour: int | None = None
        minute: int | None = None
        if start_time is not None and 0 <= start_time.hour < calendar.day_hours:
            hour = start_time.hour
            if start_time.minute in minute_options(calendar.minutes_per_hour):
                minute = start_time.minute
        self._start_hour = hour
        self._start_minute = minute
        self.stateChanged.emit()

    hourOptions = Property(
        "QVariant",
        lambda self: [EMPTY_OPTION] + [
            str(hour) for hour in range(current_calendar().day_hours)
        ],
        notify=stateChanged,
    )
    minuteOptions = Property(
        "QVariant",
        lambda self: [EMPTY_OPTION] + [
            str(minute) for minute in minute_options(current_calendar().minutes_per_hour)
        ],
        notify=stateChanged,
    )
    selectedHourIndex = Property(
        int,
        lambda self: 0 if self._start_hour is None else self._start_hour + 1,
        notify=stateChanged,
    )
    selectedMinuteIndex = Property(
        int, lambda self: self._selected_minute_index(), notify=stateChanged
    )
    # «Список минут SHALL становиться активным только при выбранном часе».
    minuteEnabled = Property(
        bool, lambda self: self._start_hour is not None, notify=stateChanged
    )

    def _selected_minute_index(self) -> int:
        # absent-safe QML binding (the same posture as _event_text): a minute
        # the ACTIVE ladder cannot offer — only reachable if the calendar was
        # swapped after the value was set, since load and selection both
        # sanitise against the current ladder — reads as the empty «—».
        if self._start_minute is None:
            return 0
        options = minute_options(current_calendar().minutes_per_hour)
        if self._start_minute not in options:
            return 0
        return options.index(self._start_minute) + 1

    @Slot(int)
    def selectHour(self, index: int) -> None:  # noqa: N802
        day_hours = current_calendar().day_hours
        if not 0 <= index <= day_hours:
            return
        self._start_hour = None if index == 0 else index - 1
        if self._start_hour is None:
            # No hour — no minute either (the list is disabled; the empty
            # hour must not leave a hidden minute behind for the save).
            self._start_minute = None
        self.stateChanged.emit()

    @Slot(int)
    def selectMinute(self, index: int) -> None:  # noqa: N802
        options = minute_options(current_calendar().minutes_per_hour)
        if not 0 <= index <= len(options):
            return
        self._start_minute = None if index == 0 else options[index - 1]
        self.stateChanged.emit()

    def set_dates(
        self,
        start: GameCoord | date | None = None,
        end: GameCoord | date | None = None,
        start_bc: bool | None = None,
        end_bc: bool | None = None,
    ) -> None:
        # Design D4/C3b: taps from the game-calendar grid arrive as coordinates
        # already; a plain ``date`` stays legal legacy input, the month-day
        # coordinate of the same numbers.
        if start is not None:
            self._start_date = as_game_coord(start)
        if end is not None:
            self._end_date = as_game_coord(end)
        if start_bc is not None:
            self._start_bc = bool(start_bc)
        if end_bc is not None:
            self._end_bc = bool(end_bc)
        self.stateChanged.emit()
        # The «С начала» line counts on the start bound (task 4.4).
        self.eventTextChanged.emit()

    def _event_text(self) -> str:
        """The read-only «С начала: <формула>» line of the dialog (spec
        «Прошедшее время от начала события»): start→«now» through the one
        duration rule, the end ignored by design; empty without a «now».
        A pair the active calendar refuses (the Д1 seeded-today «now», whose
        numbers the start default now carries since task 6.1, on a custom
        calendar) hides the row
        instead of raising inside the QML binding — display-only,
        absent-safe."""
        if self._now_coord is None:
            return ""
        try:
            parts = duration_parts(
                self._start_date, self._start_bc, self._now_coord, self._now_bc
            )
        except InvalidGameDateError:
            return ""
        return SINCE_LABEL + format_duration_words(parts)

    @Slot(object, bool)
    def applyNow(self, coord: GameCoord, is_bc: bool) -> None:  # noqa: N802
        """Mirror the game's «now» (the facade feeds this at open and on
        every nowChanged); the line is display-only and re-read."""
        self._now_coord = coord
        self._now_bc = bool(is_bc)
        self.eventTextChanged.emit()

    def set_no_end(self, value: bool) -> None:
        if value != self._no_end:
            self._no_end = value
            self.stateChanged.emit()

    def set_event_types(
        self, types: list[Any], current_type_id: int | None = None
    ) -> None:
        # PR-032: flatten at the entrance — the «Тип» binding metacall must
        # never touch a possibly-expired ORM row after a failed save.
        self._types = [EventTypeOption.coerce(event_type) for event_type in types]
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
