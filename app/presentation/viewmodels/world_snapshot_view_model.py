"""Render-ready flat model for the world snapshot QML island."""
from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    Property,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor

from app.domain import entity_registry
from app.domain.enums.entity_type import EntityType
from app.domain.game_calendar import GameCoord, as_game_coord
from app.presentation.entity_icons import icon_for
from app.presentation.theme.rating import rating_to_color
from app.presentation.utils.date_utils import (
    era_flag,
    event_start_time,
    format_event_start,
    format_game_date,
    iso_or_coord,
    split_date_era,
    worst_case_date_caption,
)
from app.presentation.utils.image_utils import resolve_preview_path
from app.presentation.views.timeline_rows import event_parent_id


ICON_SIZE = 24
_TRANSPARENT = "#00000000"
# Section header copy is this view's presentation surface; the collection
# keys, canonical order and type ids derive from the entity registry (wave 3,
# A4 — including the plural morphology it centralizes). The Lucide glyph of
# a section is NOT stored here: since the 2026-09-30 Lucide pass the icons
# live in the one map ``presentation.entity_icons`` (one knowledge, one place).
_SECTION_KINDS: tuple[tuple[EntityType, str], ...] = (
    (EntityType.EVENT, "Активные события"),
    (EntityType.LOCATION, "Локации"),
    (EntityType.ORGANIZATION, "Организации"),
    (EntityType.CHARACTER, "Персонажи"),
    (EntityType.ITEM, "Предметы"),
)
_SECTION_ORDER: tuple[str, ...] = tuple(
    entity_registry.descriptor(etype).plural for etype, _ in _SECTION_KINDS
)
_SECTION_META: dict[str, tuple[str, str]] = {
    entity_registry.descriptor(etype).plural: (header, etype.value)
    for etype, header in _SECTION_KINDS
}
#: the four card-type sections the panel renders, as (section key, type key):
#: the section key is the registry plural — the internal bucket name and the
#: relation attribute a slice event carries its entities on; the type key is
#: what the wiring's world census is keyed by (PR-019)
_CARD_SECTIONS: tuple[tuple[str, str], ...] = tuple(
    (entity_registry.collection(etype.value), etype.value)
    for etype, _ in _SECTION_KINDS
    if etype is not EntityType.EVENT
)
#: the card types whose rows answer activation with a card jump (the events
#: section stays a reading surface) — exactly the four types the world census
#: arrives under (PR-019)
SUPPORTED_ENTITY_TYPES = frozenset(type_key for _, type_key in _CARD_SECTIONS)


class WorldSnapshotRowModel(QAbstractListModel):
    """Flat section/entity rows with named roles consumed directly by QML."""

    _ROLE_NAMES = (
        "rowKind",
        "sectionKey",
        "type",
        "id",
        "name",
        "displayText",
        "ratingHex",
        "fontBold",
        "tooltipHtml",
        "iconKey",
        "iconName",
        "iconPath",
        "iconSize",
        "expanded",
        "selectable",
    )
    _ROLES = {
        Qt.ItemDataRole.UserRole + offset: name.encode()
        for offset, name in enumerate(_ROLE_NAMES, 1)
    }
    _ROLE_BY_NAME = {name.decode(): role for role, name in _ROLES.items()}

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        name = self._ROLES.get(role)
        if name is None:
            return None
        return self._rows[index.row()].get(name.decode())

    def roleNames(self) -> dict[int, bytes]:  # noqa: N802
        return self._ROLES

    def replace(self, rows: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def refresh_rating_colors(self, runtime) -> None:
        changed = False
        for row in self._rows:
            rating = row.get("_rating")
            if rating is None:
                continue
            color = rating_to_color(rating, runtime).name(QColor.NameFormat.HexArgb)
            if color != row["ratingHex"]:
                row["ratingHex"] = color
                changed = True
        if changed and self._rows:
            role = self._ROLE_BY_NAME["ratingHex"]
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self._rows) - 1, 0), [role]
            )

    @property
    def rows(self) -> list[dict[str, Any]]:
        return self._rows


class WorldSnapshotViewModel(QObject):
    """Snapshot state, formatting, expansion and selection routing."""

    stateChanged = Signal()
    dateChanged = Signal()
    snapshotRequested = Signal(object)
    entitySelected = Signal(str, int)
    datePopupRequested = Signal(float, float, float, float)

    def __init__(
        self,
        theme=None,
        now_vm=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._model = WorldSnapshotRowModel(self)
        self._sections: dict[str, list[dict[str, Any]]] = {}
        self._expanded = {
            "events": False,
            "locations": True,
            "organizations": True,
            "characters": True,
            "items": True,
        }
        self._empty_text = "Выберите дату и нажмите «Показать»"
        self._stats_text = ""
        self._clear_enabled = False
        # The snapshot date bridge carries a (GameCoord, era) pair (piece C3a,
        # designs D4/D9).  NRI-0021 task 6.2 (spec world-snapshot «Поле стартует
        # с игровой даты»): the field's initial value is the game's «now», read
        # from the widget VM the composition root hands in; a VM built without
        # a game keeps the legacy «сегодня, н.э.» fallback.  The reference is
        # kept for «Сброс» (which re-reads it) but NO nowChanged subscription
        # is taken — a date the master chose survives every «сейчас» edit
        # until the next reset (spec «Выбранная дата не сбивается правкой
        # „сейчас“»).
        self._now_vm = now_vm
        if now_vm is not None:
            self._date: GameCoord = now_vm.coord
            self._date_bc = bool(now_vm.is_bc)
        else:
            self._date = as_game_coord(date.today())
            self._date_bc = False
        # DEFECT-1 (NRI-0016): handle kept for the explicit unsubscription
        # (spec app-logging «Слушатели состояния не переживают окно»); the
        # snapshot panel detaches the VM when its island releases.
        self._theme_subscription = theme.add_listener(self._on_theme_changed) if theme is not None else None

    def detach_theme_listener(self) -> None:
        """Stop listening for theme swaps (island teardown); idempotent."""
        if self._theme_subscription is not None:
            self._theme.remove_listener(self._theme_subscription)
            self._theme_subscription = None

    rowModel = Property(QObject, lambda self: self._model, constant=True)
    rows = Property(QObject, lambda self: self._model, constant=True)
    emptyText = Property(str, lambda self: self._empty_text, notify=stateChanged)
    statsText = Property(str, lambda self: self._stats_text, notify=stateChanged)
    clearEnabled = Property(bool, lambda self: self._clear_enabled, notify=stateChanged)
    # ``Iso`` string (piece C3a, design D5): the previous ``isoformat()`` while
    # the coordinate is a real-world date, the domain codec text otherwise;
    # QML reads it verbatim (the reverse ISO slot went away as fictional).
    dateIso = Property(str, lambda self: iso_or_coord(self._date), notify=dateChanged)
    dateDisplay = Property(
        str,
        lambda self: format_game_date(self._date, is_bc=self._date_bc),
        notify=dateChanged,
    )
    # Width floor (nri-0017 task 1.1, design F1): the widest caption the
    # active calendar can print, handed to the ThemeDateField as its
    # worstCaseText so the field's minimum width never lets the elide eat
    # the year (M2); it depends on the calendar, not on the shown date.
    worstCaseDisplay = Property(
        str, lambda self: worst_case_date_caption(), notify=dateChanged
    )
    # Era facet (add-era-aware-dates, task 4.1 / design D6): the display string
    # above already carries the «N г. до н.э.» suffix — QML mirrors this flag,
    # it never computes the era itself.
    dateBc = Property(bool, lambda self: self._date_bc, notify=dateChanged)

    def populate(
        self,
        events: Sequence[Any],
        for_date: date | None,
        event_names: Mapping[int, str] | None = None,
        world_entities: Mapping[str, Sequence[Any]] | None = None,
    ) -> None:
        # ``event_names`` is the wiring's id → имя card of every game event
        # (NRI-0023 task 8.3, design Д9): the slice alone cannot name the
        # parent of an orphaned sub-event, and the stub row is spec'd to
        # carry the parent's NAME. Absent card — an orphan just stays the
        # plain row it always was (nothing invented from an unnamed id).
        #
        # ``world_entities`` (PR-019) is the wiring's census of the game: the
        # four card types keyed by type id, whatever the event slice holds.
        # The snapshot is the world's CURRENT state (spec world-snapshot
        # «Секции снимка» + entity-addition «Успешное создание»: a saved
        # entity reaches every surface of the game), so a section paints
        # whenever the world has entities of that type — an event-less world
        # or a date with nothing active on it empties the EVENTS section, it
        # never swallows the entity sections.
        events = list(events)
        self._clear_enabled = True
        entities = self._collect_entities(events, world_entities)
        if not events and not any(entities.values()):
            # Nothing to read at all — the hint is this section's own
            # emptiness, named by its cause (spec «Причина пустоты названа
            # точно»), and it is the panel's only empty state.
            self._sections = {}
            self._model.replace([])
            self._stats_text = ""
            self._empty_text = (
                "Нет событий в игре"
                if for_date is None
                else "На эту дату нет активных событий"
            )
            self.stateChanged.emit()
            return

        self._sections = {}
        if events:
            self._sections["events"] = self._event_tree(events, event_names)
        for section, values in entities.items():
            records = list(values.values())
            if section in {"locations", "organizations"}:
                records.sort(key=lambda entity: str(getattr(entity, "name", "")))
            else:
                records.sort(
                    key=lambda entity: (
                        -self._rating_of(entity),
                        str(getattr(entity, "name", "")),
                    )
                )
            self._sections[section] = [
                self._entity_row(entity, _SECTION_META[section][1])
                for entity in records
            ]

        self._empty_text = ""
        self._stats_text = self._stats(events, entities, for_date)
        self._rebuild_rows()
        self.stateChanged.emit()

    @staticmethod
    def _collect_entities(
        events: Sequence[Any],
        world_entities: Mapping[str, Sequence[Any]] | None,
    ) -> dict[str, dict[int, Any]]:
        """Per-section buckets (id → entity) of everything the sections show.

        Two sources meet in one bucket by identifier, so an entity linked from
        several slice events occupies a single row (spec «Сущность из
        нескольких событий показана один раз») and the census only adds the
        entities the slice relations could not reach — a just-created, still
        unlinked one above all (PR-019).
        """
        entities: dict[str, dict[int, Any]] = {
            section: {} for section, _ in _CARD_SECTIONS
        }
        for event in events:
            for section, _type_key in _CARD_SECTIONS:
                for entity in getattr(event, section, ()) or ():
                    entities[section][entity.id] = entity
        for type_key, records in (world_entities or {}).items():
            # strict on unknown keys, like the registry's other readers: a
            # census key the panel does not render is a wiring bug, not a
            # section to invent
            bucket = entities[entity_registry.collection(type_key)]
            for entity in records:
                bucket[entity.id] = entity
        return entities

    @Slot()
    def clear(self) -> None:
        self._sections = {}
        self._model.replace([])
        self._empty_text = "Выберите дату и нажмите «Показать»"
        self._stats_text = ""
        self._clear_enabled = False
        self.stateChanged.emit()
        # NRI-0021 task 6.2 (spec world-snapshot «Сброс возвращает исходное
        # состояние»): «Сброс» also returns the date field to the game's «now»
        # — read at reset time, so a later «сейчас» edit lands here rather
        # than silently moving a date the master is still looking at.
        self._reset_date_to_now()

    def _reset_date_to_now(self) -> None:
        """Return the date field to the served «now» (no game VM — field
        untouched, the legacy no-game behavior); an identical value is
        silent, exactly the ``set_date`` contract."""
        if self._now_vm is None:
            return
        coord = self._now_vm.coord
        is_bc = bool(self._now_vm.is_bc)
        if coord == self._date and is_bc == self._date_bc:
            return
        self._date = coord
        self._date_bc = is_bc
        self.dateChanged.emit()

    def set_date(self, value: GameCoord | date | tuple[GameCoord | date | None, bool] | None) -> None:
        # Accepts the popup bridge's (coordinate, era) pair; a bare coordinate
        # or date keeps the era the snapshot already shows (piece C3a, D4:
        # a plain date is the month-day coordinate of the same numbers).
        selected, is_bc = split_date_era(value)
        if selected is None:  # the snapshot needs a concrete date
            return
        coord = as_game_coord(selected)
        era = self._date_bc if is_bc is None else is_bc
        if coord == self._date and bool(era) == self._date_bc:
            return
        self._date = coord
        self._date_bc = bool(era)
        self.dateChanged.emit()

    @Slot()
    def requestShow(self) -> None:  # noqa: N802
        self.snapshotRequested.emit((self._date, self._date_bc))

    @Slot()
    def requestShowAll(self) -> None:  # noqa: N802
        self.snapshotRequested.emit(None)

    @Slot(float, float, float, float)
    def requestDatePopup(  # noqa: N802
        self, x: float, y: float, width: float, height: float
    ) -> None:
        self.datePopupRequested.emit(x, y, width, height)

    @Slot("QVariant")
    def toggleSection(self, section_or_index) -> None:  # noqa: N802
        section = self._section_key(section_or_index)
        if section not in self._expanded:
            return
        self._expanded[section] = not self._expanded[section]
        self._rebuild_rows()

    @Slot(int)
    def select(self, index: int) -> None:
        if not 0 <= index < len(self._model.rows):
            return
        row = self._model.rows[index]
        if row["rowKind"] != "entityRow" or row["type"] not in SUPPORTED_ENTITY_TYPES:
            return
        self.entitySelected.emit(row["type"], row["id"])

    def _section_key(self, value) -> str | None:
        if isinstance(value, str):
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            if 0 <= value < len(self._model.rows):
                row = self._model.rows[value]
                if row["rowKind"] == "sectionHeader":
                    return row["sectionKey"]
        return None

    def _rebuild_rows(self) -> None:
        rows: list[dict[str, Any]] = []
        for section in _SECTION_ORDER:
            children = self._sections.get(section, [])
            if not children:
                continue
            label, entity_type = _SECTION_META[section]
            # The header count is the count of EVENTS (task 8.3, spec
            # «Подсобытия в счётчике, заглушки — нет»): the always-expanded
            # children are events and ride along, the parent stubs explain
            # an orphan but are not events themselves.
            event_count = sum(
                1 for child in children if child["rowKind"] != "stubRow"
            )
            rows.append(
                {
                    "rowKind": "sectionHeader",
                    "sectionKey": section,
                    "type": entity_type,
                    "id": -1,
                    "name": label,
                    "displayText": f"{label} ({event_count})",
                    "ratingHex": _TRANSPARENT,
                    "fontBold": True,
                    "tooltipHtml": "",
                    "iconKey": entity_type,
                    "iconName": icon_for(entity_type),
                    "iconPath": "",
                    "iconSize": ICON_SIZE,
                    "expanded": self._expanded[section],
                    "selectable": False,
                }
            )
            if self._expanded[section]:
                rows.extend(children)
        self._model.replace(rows)

    def _event_tree(
        self, events: Sequence[Any], event_names: Mapping[int, str] | None
    ) -> list[dict[str, Any]]:
        """The «События» section as the two-level tree of the slice (NRI-0023
        task 8.3, spec «Состав снимка» / «Сортировка секций»): parents keep the
        slice's chronological order, their sub-events follow immediately under
        the parent (the slice already orders children chronologically, the
        same (day, time, id) key as the ladder), a child whose parent the
        slice excludes gets a parent STUB row directly above it — name only,
        no dates, never selectable. The snapshot is a reading surface, not a
        navigation control, so the tree is always fully expanded (design Д9);
        with no links at all the list is word-for-word the old flat one.
        """
        present = {event.id for event in events}
        children_of: dict[int, list[Any]] = {}
        tops: list[tuple[Any, int | None]] = []
        for event in events:
            parent_id = event_parent_id(event)
            if parent_id is not None and parent_id in present:
                children_of.setdefault(parent_id, []).append(event)
            else:
                # A top-level event (no link) rides with parent_id None; an
                # orphan keeps its out-of-slice parent id for the stub.
                tops.append((event, parent_id))
        rows: list[dict[str, Any]] = []
        stubbed: set[int] = set()
        for event, orphan_parent in tops:
            if orphan_parent is not None and orphan_parent not in stubbed:
                stubbed.add(orphan_parent)
                stub = self._stub_row(orphan_parent, event_names)
                if stub is not None:
                    rows.append(stub)
            # An orphan keeps its child depth under the stub it got — on the
            # ladder a stubbed parent's children are indented too; without a
            # nameable parent the orphan still reads as the child it is.
            rows.append(self._event_row(event, depth=1 if orphan_parent else 0))
            for child in children_of.get(event.id, ()):
                rows.append(self._event_row(child, depth=1))
        return rows

    def _stub_row(
        self, parent_id: int, event_names: Mapping[int, str] | None
    ) -> dict[str, Any] | None:
        """The parent placeholder: the stub is the parent's NAME over the
        orphan group — no dates (the parent is not in the slice), no click
        target (``rowKind != "entityRow"`` keeps :meth:`select` silent), no
        stats entry (``_stats`` counts the events, never these rows). An id
        the card cannot name produces no stub rather than a nameless one."""
        name = (event_names or {}).get(parent_id)
        if not name:
            return None
        return {
            "rowKind": "stubRow",
            "sectionKey": "events",
            "type": "event",
            "id": int(parent_id),
            "name": str(name),
            "displayText": str(name),
            "ratingHex": _TRANSPARENT,
            "fontBold": False,
            "tooltipHtml": "",
            "iconKey": "event",
            "iconName": icon_for(EntityType.EVENT),
            "iconPath": "",
            "iconSize": ICON_SIZE,
            "expanded": False,
            "selectable": False,
        }

    def _event_row(self, event: Any, depth: int = 0) -> dict[str, Any]:
        # NRI-0023 task 8.1 (design Д9, spec world-snapshot «Дата начала в
        # строке события SHALL печататься с временем»): the start rides the
        # single surface helper — a chosen time gains its «, HH:MM» tail, an
        # untimed event prints word-for-word the caption it always had; the
        # end stays a plain day (only the start carries a time).
        start = format_event_start(
            getattr(event, "start_date", None),
            era_flag(getattr(event, "start_bc", False)),
            event_start_time(event),
        )
        end = format_game_date(
            getattr(event, "end_date", None),
            "∞",
            is_bc=era_flag(getattr(event, "end_bc", False)),
        )
        name = str(getattr(event, "name", event))
        # The tree's horizontal indent (task 8.3, spec «Подсобытие отступом
        # под родителем»): a child's caption opens with the indent; a top-
        # level row keeps its caption bit-for-bit, the empty-time half too.
        indent = "" if depth <= 0 else "\u00a0" * (4 * depth)
        return {
            "rowKind": "entityRow",
            "sectionKey": "events",
            "type": "event",
            "id": int(event.id),
            "name": name,
            "displayText": f"{indent}{start} — {end}  |  {name}",
            "ratingHex": _TRANSPARENT,
            "fontBold": False,
            "tooltipHtml": "",
            "iconKey": "event",
            "iconName": icon_for(EntityType.EVENT),
            "iconPath": "",
            "iconSize": ICON_SIZE,
            "expanded": False,
            "selectable": False,
        }

    def _entity_row(self, entity: Any, entity_type: str) -> dict[str, Any]:
        rating = self._rating_of(entity)
        name = str(getattr(entity, "name", entity))
        display = name if rating <= 1 else f"{name}  [{rating}/20]"
        # the plural morphology lives in the registry only (wave 3, A4)
        section_key = entity_registry.collection(entity_type)
        icon_name = icon_for(entity_type)
        preview_path = resolve_preview_path(entity)
        tooltip = [f"<b>{name}</b> ({entity_type})", f"Рейтинг: {rating}/20"]
        description = getattr(entity, "description", None)
        characteristics = getattr(description, "characteristics", "") if description else ""
        if isinstance(characteristics, str) and characteristics.strip():
            tooltip.append(f"<i>{characteristics.strip()[:200]}</i>")
        return {
            "rowKind": "entityRow",
            "sectionKey": section_key,
            "type": entity_type,
            "id": int(entity.id),
            "name": name,
            "displayText": display,
            "ratingHex": rating_to_color(rating, self._theme).name(
                QColor.NameFormat.HexArgb
            ),
            "fontBold": rating >= 15,
            "tooltipHtml": "<br>".join(tooltip),
            "iconKey": entity_type,
            # The section glyph stays delivered even when the photo wins
            # (iconPath) — the QML fallback paints it for entities without
            # a picture (Lucide pass 2026-09-30).
            "iconName": icon_name,
            "iconPath": (
                preview_path.resolve().as_uri()
                if preview_path is not None and preview_path.exists()
                else ""
            ),
            "iconSize": ICON_SIZE,
            "expanded": False,
            "selectable": True,
            "_rating": rating,
        }

    @staticmethod
    def _rating_of(entity: Any) -> int:
        rating = getattr(entity, "rating", 1)
        return rating if isinstance(rating, int) and not isinstance(rating, bool) else 1

    @staticmethod
    def _stats(events, entities, for_date) -> str:
        # ``for_date`` reaches here as the requested payload: a (coordinate,
        # era) pair from the date bridge or a bare legacy date (== «н.э.»).
        shown_date, is_bc = split_date_era(for_date)
        prefix = (
            "Показано: все события"
            if shown_date is None
            else f"Дата: {format_game_date(shown_date, is_bc=bool(is_bc))}"
        )
        return (
            f"{prefix}  |  Событий: {len(events)}  |  "
            f"Персонажей: {len(entities['characters'])}  |  "
            f"Организаций: {len(entities['organizations'])}  |  "
            f"Локаций: {len(entities['locations'])}  |  "
            f"Предметов: {len(entities['items'])}"
        )

    def _on_theme_changed(self) -> None:
        self._model.refresh_rating_colors(self._theme)
