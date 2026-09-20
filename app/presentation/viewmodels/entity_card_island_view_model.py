"""Synchronous state model for the entity-card QML island."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Property, QObject, Signal, Slot

from app.domain.game_calendar import GameCoord, as_game_coord
from app.presentation.utils.date_utils import format_game_date, iso_or_coord
from app.presentation.viewmodels.event_dialog_island_view_model import (
    AiFieldProxy,
    EntityGenerateProxy,
    MentionEditProxy,
    RelatedSectionState,
)
from app.presentation.viewmodels.mention_field_host import MentionFieldHost


class EntityCardIslandViewModel(QObject):
    stateChanged = Signal()
    saveRequested = Signal()
    cancelRequested = Signal()
    datePopupRequested = Signal(str, float, float, float, float)
    imagePickRequested = Signal()
    imageClearRequested = Signal()
    imageOpenRequested = Signal()
    musicOpenRequested = Signal(str)
    characterSheetRequested = Signal()

    def __init__(
        self,
        entity_type: str,
        field_specs,
        related_configs,
        owner=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._entity_type = entity_type
        self._field_specs = list(field_specs)
        self._related_configs = list(related_configs)
        self._name = ""
        self._rating = 1
        # Date bridges carry (GameCoord, era) pairs (piece C3a, designs D4/D6,
        # since task 5.2); the default is «сегодня, н.э.» — today's numbers as
        # the equal month-day coordinate.
        self._start_date: GameCoord = as_game_coord(date.today())
        self._end_date: GameCoord = as_game_coord(date.today())
        self._start_bc = False
        self._end_bc = False
        self._no_end = False
        self._music_url = ""
        self._music_editing = True
        self._image_source = ""
        self._image_available = False
        self._character_sheet_available = False
        self._save_locked = False
        self._saving = False

        mention_specs = [
            ("characteristics", "Характеристики"),
            ("backstory", "Предыстория"),
            *[
                (spec.name, spec.label)
                for spec in self._field_specs
                if spec.kind == "mention"
            ],
        ]
        self._hosts: dict[str, MentionFieldHost] = {}
        self._mention_proxies: dict[str, MentionEditProxy] = {}
        self._ai_proxies: dict[str, AiFieldProxy] = {}
        for name, label in mention_specs:
            host = MentionFieldHost(self)
            proxy = MentionEditProxy(host, self)
            ai = AiFieldProxy(
                entity_type,
                name,
                label,
                lambda h=host: h.storage,
                lambda value, h=host: setattr(h, "storage", value),
                owner,
                self,
            )
            host.storageChanged.connect(self.stateChanged)
            self._hosts[name] = host
            self._mention_proxies[name] = proxy
            self._ai_proxies[name] = ai

        self.nameAi = AiFieldProxy(
            entity_type,
            "name",
            "Название",
            lambda: self._name,
            self._set_name,
            owner,
            self,
        )
        self.entityAi = EntityGenerateProxy(owner, self)

        self._sections: dict[str, RelatedSectionState] = {
            cfg["attr"]: RelatedSectionState(self) for cfg in self._related_configs
        }

    def _set_name(self, value: str) -> None:
        value = value or ""
        if value != self._name:
            self._name = value
            self.stateChanged.emit()

    name = Property(str, lambda self: self._name, _set_name, notify=stateChanged)
    entityType = Property(str, lambda self: self._entity_type, constant=True)
    rating = Property(int, lambda self: self._rating, notify=stateChanged)
    # ``Iso`` strings (piece C3a, design D5): ISO while the coordinate is
    # representable as a real date (bit-for-bit the previous string), the
    # domain codec text otherwise; QML reads them verbatim and parses none.
    startIso = Property(str, lambda self: iso_or_coord(self._start_date), notify=stateChanged)
    endIso = Property(str, lambda self: iso_or_coord(self._end_date), notify=stateChanged)
    startDisplay = Property(
        str,
        lambda self: format_game_date(self._start_date, is_bc=self._start_bc),
        notify=stateChanged,
    )
    endDisplay = Property(
        str,
        lambda self: format_game_date(self._end_date, is_bc=self._end_bc),
        notify=stateChanged,
    )
    # Era facets (add-era-aware-dates, task 4.1 / design D6): the display
    # strings already carry the «N г. до н.э.» suffix — QML mirrors these flags,
    # it never computes the era itself.
    startBc = Property(bool, lambda self: self._start_bc, notify=stateChanged)
    endBc = Property(bool, lambda self: self._end_bc, notify=stateChanged)
    noEnd = Property(bool, lambda self: self._no_end, notify=stateChanged)
    musicUrl = Property(str, lambda self: self._music_url, notify=stateChanged)
    musicEditing = Property(bool, lambda self: self._music_editing, notify=stateChanged)
    hasImage = Property(
        bool,
        lambda self: any(spec.kind == "image" for spec in self._field_specs),
        constant=True,
    )
    imageSource = Property(str, lambda self: self._image_source, notify=stateChanged)
    imageAvailable = Property(
        bool, lambda self: self._image_available, notify=stateChanged
    )
    characterSheetAvailable = Property(
        bool, lambda self: self._character_sheet_available, notify=stateChanged
    )
    saveEnabled = Property(
        bool,
        lambda self: not self._save_locked and not self._saving,
        notify=stateChanged,
    )
    saving = Property(bool, lambda self: self._saving, notify=stateChanged)
    nameAiProxy = Property(QObject, lambda self: self.nameAi, constant=True)
    entityAiProxy = Property(QObject, lambda self: self.entityAi, constant=True)
    characteristicsHost = Property(
        QObject, lambda self: self._hosts["characteristics"], constant=True
    )
    backstoryHost = Property(
        QObject, lambda self: self._hosts["backstory"], constant=True
    )
    characteristicsAiProxy = Property(
        QObject, lambda self: self._ai_proxies["characteristics"], constant=True
    )
    backstoryAiProxy = Property(
        QObject, lambda self: self._ai_proxies["backstory"], constant=True
    )
    extraFields = Property(
        "QVariant",
        lambda self: [
            {
                "name": spec.name,
                "label": spec.label,
                "kind": spec.kind,
                "mentionHost": self._hosts.get(spec.name),
                "aiProxy": self._ai_proxies.get(spec.name),
            }
            for spec in self._field_specs
            if spec.kind == "mention"
        ],
        constant=True,
    )
    relatedSections = Property(
        "QVariant",
        lambda self: [
            {
                "attr": cfg["attr"],
                "label": cfg["label"],
                "entityType": cfg["entity_type"],
                "section": self._sections[cfg["attr"]],
            }
            for cfg in self._related_configs
        ],
        constant=True,
    )

    @property
    def hosts(self) -> dict[str, MentionFieldHost]:
        return self._hosts

    @property
    def mention_proxies(self) -> dict[str, MentionEditProxy]:
        return self._mention_proxies

    @property
    def ai_proxies(self) -> dict[str, AiFieldProxy]:
        return self._ai_proxies

    @property
    def sections(self) -> dict[str, RelatedSectionState]:
        return self._sections

    def set_rating(self, value: int) -> None:
        value = max(1, min(20, int(value)))
        if value != self._rating:
            self._rating = value
            self.stateChanged.emit()

    def set_dates(
        self,
        start: GameCoord | date | None = None,
        end: GameCoord | date | None = None,
        start_bc: bool | None = None,
        end_bc: bool | None = None,
    ) -> None:
        # Design D4: a plain date arriving from the (unchanged) QCalendarWidget
        # popups is the month-day coordinate of the same numbers.
        if start is not None:
            self._start_date = as_game_coord(start)
        if end is not None:
            self._end_date = as_game_coord(end)
        if start_bc is not None:
            self._start_bc = bool(start_bc)
        if end_bc is not None:
            self._end_bc = bool(end_bc)
        self.stateChanged.emit()

    def set_no_end(self, value: bool) -> None:
        if value != self._no_end:
            self._no_end = value
            self.stateChanged.emit()

    def set_music_url(self, value: str) -> None:
        value = (value or "").strip()
        self._music_url = value
        self._music_editing = not bool(value)
        self.stateChanged.emit()

    def set_image_source(self, source: str, available: bool) -> None:
        self._image_source = source
        self._image_available = available
        self.stateChanged.emit()

    def set_character_sheet_available(self, available: bool) -> None:
        self._character_sheet_available = bool(available)
        self.stateChanged.emit()

    def set_save_locked(self, locked: bool) -> None:
        self._save_locked = bool(locked)
        self.stateChanged.emit()

    def set_saving(self, saving: bool) -> None:
        self._saving = bool(saving)
        self.stateChanged.emit()

    @Slot(int)
    def setRating(self, value: int) -> None:  # noqa: N802
        self.set_rating(value)

    @Slot(bool)
    def setNoEnd(self, value: bool) -> None:  # noqa: N802
        self.set_no_end(value)

    @Slot(str)
    def setMusicUrl(self, value: str) -> None:  # noqa: N802
        self._music_url = value
        self.stateChanged.emit()

    @Slot()
    def toggleMusicEdit(self) -> None:  # noqa: N802
        if self._music_editing:
            self.set_music_url(self._music_url)
        else:
            self._music_editing = True
            self.stateChanged.emit()

    @Slot()
    def requestMusicOpen(self) -> None:  # noqa: N802
        if self._music_url:
            self.musicOpenRequested.emit(self._music_url)

    @Slot(str, float, float, float, float)
    def requestDatePopup(  # noqa: N802
        self, which: str, x: float, y: float, width: float, height: float
    ) -> None:
        self.datePopupRequested.emit(which, x, y, width, height)

    @Slot()
    def requestSave(self) -> None:  # noqa: N802
        if self.saveEnabled:
            self.saveRequested.emit()

    @Slot()
    def requestCancel(self) -> None:  # noqa: N802
        self.cancelRequested.emit()

    @Slot()
    def requestImagePick(self) -> None:  # noqa: N802
        self.imagePickRequested.emit()

    @Slot()
    def requestImageClear(self) -> None:  # noqa: N802
        self.imageClearRequested.emit()

    @Slot()
    def requestImageOpen(self) -> None:  # noqa: N802
        if self._image_available:
            self.imageOpenRequested.emit()

    @Slot()
    def requestCharacterSheet(self) -> None:  # noqa: N802
        if self._character_sheet_available:
            self.characterSheetRequested.emit()
