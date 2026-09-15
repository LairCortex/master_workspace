"""Synchronous state and list models for the detail-panel QML island."""
from __future__ import annotations

from typing import Any, Iterable

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    Property,
    QByteArray,
    Qt,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor

from app.presentation.theme.rating import rating_to_color
from app.presentation.utils.date_utils import era_flag, format_game_date
from app.presentation.utils.image_utils import resolve_preview_path


def _truncate(text: str, max_len: int = 120) -> str:
    text = text.replace("\n", " ").strip()
    return text[:max_len] + "…" if len(text) > max_len else text


def build_detail_summary(entity: Any, entity_type: str) -> str:
    """Build the render-ready HTML summary formerly owned by the widget row."""
    parts: list[str] = []
    rating = getattr(entity, "rating", None)
    if isinstance(rating, int) and rating >= 1:
        parts.append(f"<b>Рейтинг:</b> {rating}/20")

    description = getattr(entity, "description", None)
    if description:
        characteristics = getattr(description, "characteristics", None)
        if characteristics and characteristics.strip():
            parts.append(f"<b>Хар-ки:</b> {_truncate(characteristics)}")
        backstory = getattr(description, "backstory", None)
        if backstory and backstory.strip():
            parts.append(f"<b>Предыстория:</b> {_truncate(backstory)}")

    if entity_type == "character":
        personality = getattr(entity, "personality", None)
        if personality and personality.strip():
            parts.append(f"<b>Личность:</b> {_truncate(personality)}")

    if entity_type in ("organization", "character", "location"):
        tasks = getattr(entity, "tasks", None)
        if tasks and tasks.strip():
            parts.append(f"<b>Задачи:</b> {_truncate(tasks)}")

    counts = []
    for attr, label in (
        ("characters", "персонажей"),
        ("organizations", "организаций"),
        ("items", "предметов"),
        ("locations", "локаций"),
    ):
        related = getattr(entity, attr, None)
        if related is not None and len(related) > 0:
            counts.append(f"{len(related)} {label}")
    if counts:
        parts.append(f"<b>Связи:</b> {', '.join(counts)}")
    return "<br>".join(parts) if parts else "<i>нет данных</i>"


def _tint_text(rating: int, runtime) -> str:
    color = rating_to_color(rating, runtime)
    if isinstance(color, QColor):
        return color.name(QColor.NameFormat.HexArgb)
    return str(color)


class DetailRowsModel(QAbstractListModel):
    NameRole = Qt.ItemDataRole.UserRole + 1
    SummaryRole = NameRole + 1
    EntityTypeRole = SummaryRole + 1
    EntityIdRole = EntityTypeRole + 1
    ImageSourceRole = EntityIdRole + 1
    RatingTintRole = ImageSourceRole + 1

    _ROLES = {
        NameRole: QByteArray(b"name"),
        SummaryRole: QByteArray(b"summary"),
        EntityTypeRole: QByteArray(b"entityType"),
        EntityIdRole: QByteArray(b"entityId"),
        ImageSourceRole: QByteArray(b"imageSource"),
        RatingTintRole: QByteArray(b"ratingTint"),
    }

    def __init__(self, runtime=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._runtime = runtime
        self._rows: list[dict[str, Any]] = []

    def roleNames(self) -> dict[int, QByteArray]:
        return self._ROLES

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        name = self._ROLES.get(role)
        if name is None:
            return None
        return self._rows[index.row()][bytes(name).decode()]

    def set_entities(self, entities: Iterable[Any], entity_type: str) -> None:
        self.beginResetModel()
        self._rows = [
            self._make_row(entity, entity_type) for entity in entities
        ]
        self.endResetModel()

    def clear(self) -> None:
        self.beginResetModel()
        self._rows = []
        self.endResetModel()

    def recompute_tints(self) -> None:
        for row_index, row in enumerate(self._rows):
            tint = _tint_text(row["_rating"], self._runtime)
            if tint == row["ratingTint"]:
                continue
            row["ratingTint"] = tint
            index = self.index(row_index, 0)
            self.dataChanged.emit(index, index, [self.RatingTintRole])

    def entity(self, entity_type: str, entity_id: int) -> Any | None:
        for row in self._rows:
            if row["entityType"] == entity_type and row["entityId"] == entity_id:
                return row["_entity"]
        return None

    def _make_row(self, entity: Any, entity_type: str) -> dict[str, Any]:
        rating = getattr(entity, "rating", 1)
        if not isinstance(rating, int):
            rating = 1
        preview_path = resolve_preview_path(entity)
        image_source = (
            QUrl.fromLocalFile(str(preview_path)).toString()
            if preview_path is not None
            else ""
        )
        return {
            "name": getattr(entity, "name", str(entity)),
            "summary": build_detail_summary(entity, entity_type),
            "entityType": entity_type,
            "entityId": getattr(entity, "id", 0) or 0,
            "imageSource": image_source,
            "ratingTint": _tint_text(rating, self._runtime),
            "_rating": rating,
            "_entity": entity,
        }


class DetailPanelViewModel(QObject):
    """Header plus four stable list models; all presentation rules stay here."""

    headerChanged = Signal()
    entityActivated = Signal(str, int)
    imageRequested = Signal(object)

    TAB_TITLES = ("Организации", "Персонажи", "Предметы", "Локации")
    ENTITY_TYPES = ("organization", "character", "item", "location")
    EVENT_ATTRS = ("organizations", "characters", "items", "locations")

    def __init__(self, runtime=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._runtime = runtime
        self._title = ""
        self._date_text = ""
        self.models = [
            DetailRowsModel(runtime, self) for _ in self.TAB_TITLES
        ]
        if runtime is not None:
            runtime.add_listener(self.retheme)

    title = Property(str, lambda self: self._title, notify=headerChanged)
    dateText = Property(str, lambda self: self._date_text, notify=headerChanged)
    tabTitles = Property(
        "QVariant", lambda self: list(self.TAB_TITLES), constant=True
    )
    organizations = Property(QObject, lambda self: self.models[0], constant=True)
    characters = Property(QObject, lambda self: self.models[1], constant=True)
    items = Property(QObject, lambda self: self.models[2], constant=True)
    locations = Property(QObject, lambda self: self.models[3], constant=True)

    def show_event(self, event: Any) -> None:
        self._title = getattr(event, "name", "")
        start = format_game_date(
            getattr(event, "start_date", None),
            is_bc=era_flag(getattr(event, "start_bc", False)),
        )
        end = format_game_date(
            getattr(event, "end_date", None),
            "∞",
            is_bc=era_flag(getattr(event, "end_bc", False)),
        )
        self._date_text = f"{start} — {end}"
        self.headerChanged.emit()
        for model, attr, entity_type in zip(
            self.models, self.EVENT_ATTRS, self.ENTITY_TYPES
        ):
            model.set_entities(getattr(event, attr, []) or [], entity_type)

    def clear(self) -> None:
        self._title = ""
        self._date_text = ""
        self.headerChanged.emit()
        for model in self.models:
            model.clear()

    @Slot(str, int)
    def activate(self, entity_type: str, entity_id: int) -> None:
        if self._find_entity(entity_type, entity_id) is not None:
            self.entityActivated.emit(entity_type, entity_id)

    @Slot(str, int)
    def requestImage(self, entity_type: str, entity_id: int) -> None:
        entity = self._find_entity(entity_type, entity_id)
        if entity is not None:
            self.imageRequested.emit(entity)

    @Slot()
    def retheme(self) -> None:
        for model in self.models:
            model.recompute_tints()

    def _find_entity(self, entity_type: str, entity_id: int) -> Any | None:
        for model in self.models:
            entity = model.entity(entity_type, entity_id)
            if entity is not None:
                return entity
        return None
