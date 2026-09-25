"""Render-ready flat model for the world snapshot QML island."""
from __future__ import annotations

from datetime import date
from typing import Any, Sequence

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    Property,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

from app.domain import entity_registry
from app.domain.enums.entity_type import EntityType
from app.domain.game_calendar import GameCoord, as_game_coord
from app.presentation.theme.rating import rating_to_color
from app.presentation.utils.date_utils import (
    era_flag,
    format_game_date,
    iso_or_coord,
    split_date_era,
    worst_case_date_caption,
)
from app.presentation.utils.image_utils import load_entity_preview, resolve_preview_path


ICON_SIZE = 24
SUPPORTED_ENTITY_TYPES = frozenset(
    etype.value
    for etype in (
        EntityType.LOCATION,
        EntityType.ORGANIZATION,
        EntityType.CHARACTER,
        EntityType.ITEM,
    )
)
_TRANSPARENT = "#00000000"
# Section header copy and glyphs are this view's presentation surface; the
# collection keys, canonical order and type ids derive from the entity
# registry (wave 3, A4 — including the plural morphology it centralizes).
_SECTION_KINDS: tuple[tuple[EntityType, str, str], ...] = (
    (EntityType.EVENT, "📅  Активные события", "📅"),
    (EntityType.LOCATION, "📍  Локации", "📍"),
    (EntityType.ORGANIZATION, "👥  Организации", "👥"),
    (EntityType.CHARACTER, "🧑  Персонажи", "🧑"),
    (EntityType.ITEM, "🗡  Предметы", "🗡"),
)
_SECTION_ORDER: tuple[str, ...] = tuple(
    entity_registry.descriptor(etype).plural for etype, _, _ in _SECTION_KINDS
)
_SECTION_META: dict[str, tuple[str, str, str]] = {
    entity_registry.descriptor(etype).plural: (header, etype.value, glyph)
    for etype, header, glyph in _SECTION_KINDS
}


def _text_icon(text: str, size: int = ICON_SIZE) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setFont(
        QFont("Segoe UI Emoji, Apple Color Emoji, Noto Color Emoji", int(size * 0.7))
    )
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return QIcon(pixmap)


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
        "icon",
        "iconKey",
        "iconText",
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

    def __init__(self, theme=None, parent: QObject | None = None) -> None:
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
        # designs D4/D9); the default is «сегодня, н.э.» — today's numbers as
        # the equal month-day coordinate.
        self._date: GameCoord = as_game_coord(date.today())
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

    def populate(self, events: Sequence[Any], for_date: date | None) -> None:
        events = list(events)
        self._clear_enabled = True
        if not events:
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

        entities: dict[str, dict[int, Any]] = {
            "locations": {},
            "organizations": {},
            "characters": {},
            "items": {},
        }
        for event in events:
            for section, attribute in (
                ("locations", "locations"),
                ("organizations", "organizations"),
                ("characters", "characters"),
                ("items", "items"),
            ):
                for entity in getattr(event, attribute, ()) or ():
                    entities[section][entity.id] = entity

        self._sections = {
            "events": [self._event_row(event) for event in events],
        }
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

    @Slot()
    def clear(self) -> None:
        self._sections = {}
        self._model.replace([])
        self._empty_text = "Выберите дату и нажмите «Показать»"
        self._stats_text = ""
        self._clear_enabled = False
        self.stateChanged.emit()

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
            label, entity_type, emoji = _SECTION_META[section]
            rows.append(
                {
                    "rowKind": "sectionHeader",
                    "sectionKey": section,
                    "type": entity_type,
                    "id": -1,
                    "name": label,
                    "displayText": f"{label} ({len(children)})",
                    "ratingHex": _TRANSPARENT,
                    "fontBold": True,
                    "tooltipHtml": "",
                    "icon": _text_icon(emoji),
                    "iconKey": entity_type,
                    "iconText": emoji,
                    "iconPath": "",
                    "iconSize": ICON_SIZE,
                    "expanded": self._expanded[section],
                    "selectable": False,
                }
            )
            if self._expanded[section]:
                rows.extend(children)
        self._model.replace(rows)

    def _event_row(self, event: Any) -> dict[str, Any]:
        start = format_game_date(
            getattr(event, "start_date", None),
            is_bc=era_flag(getattr(event, "start_bc", False)),
        )
        end = format_game_date(
            getattr(event, "end_date", None),
            "∞",
            is_bc=era_flag(getattr(event, "end_bc", False)),
        )
        name = str(getattr(event, "name", event))
        return {
            "rowKind": "entityRow",
            "sectionKey": "events",
            "type": "event",
            "id": int(event.id),
            "name": name,
            "displayText": f"{start} — {end}  |  {name}",
            "ratingHex": _TRANSPARENT,
            "fontBold": False,
            "tooltipHtml": "",
            "icon": _text_icon("📅"),
            "iconKey": "event",
            "iconText": "📅",
            "iconPath": "",
            "iconSize": ICON_SIZE,
            "expanded": False,
            "selectable": False,
        }

    def _entity_row(self, entity: Any, entity_type: str) -> dict[str, Any]:
        rating = self._rating_of(entity)
        name = str(getattr(entity, "name", entity))
        display = name if rating <= 1 else f"{name}  [{rating}/20]"
        pixmap = load_entity_preview(entity, slot_size=ICON_SIZE)
        # the plural morphology lives in the registry only (wave 3, A4)
        section_key = entity_registry.collection(entity_type)
        icon_text = _SECTION_META[section_key][2]
        icon = QIcon(pixmap) if not pixmap.isNull() else _text_icon(icon_text)
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
            "icon": icon,
            "iconKey": entity_type,
            "iconText": icon_text,
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
