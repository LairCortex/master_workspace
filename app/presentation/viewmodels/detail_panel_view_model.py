"""Synchronous state and list models for the detail-panel QML island."""
from __future__ import annotations

from datetime import date
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

from app.domain import entity_registry
from app.domain.date_era import duration_parts
from app.domain.enums.entity_type import EntityType
from app.domain.game_calendar import GameCoord, InvalidGameDateError
from app.presentation.theme.rating import rating_to_color
from app.presentation.utils.date_utils import (
    AGE_ENTITY_TYPES,
    AGE_LABEL,
    era_flag,
    format_age_words,
    format_duration_words,
    format_game_date,
)
from app.presentation.utils.image_utils import resolve_preview_path

#: The «now» carrier the summary and the date row count against (NRI-0021
#: design Д5): the active calendar's coordinate plus its era flag, or ``None``
#: while the panel has no game «now» (unit-built panels — no derived text).
NowPair = tuple[GameCoord | date, bool]

#: relation refs of the event card, registry order (wave 3, finding A4)
_event_refs = entity_registry.related_refs(EntityType.EVENT)


def _truncate(text: str, max_len: int = 120) -> str:
    text = text.replace("\n", " ").strip()
    return text[:max_len] + "…" if len(text) > max_len else text


def build_detail_summary(
    entity: Any, entity_type: str, now: NowPair | None = None
) -> str:
    """Build the render-ready HTML summary formerly owned by the widget row.

    ``now`` (NRI-0021 task 4.1, design Д5) is the game's «now» coordinate
    pair; for a character or item it adds the «Возраст: <формула>» line — the
    single age rule assembled by ``format_age_words`` (started entities age
    to their end, unstarted ones read «через N»).  Locations and
    organizations never carry the line, and without a «now» the summary is
    exactly the pre-NRI-0021 text.  A coordinate pair the active calendar
    refuses (a custom-calendar game on the Д1 seeded-today «now») hides the
    line — a derived text that cannot be counted never breaks the row, the
    same absence posture as Д1's damaged-value rule."""
    parts: list[str] = []
    if entity_type in AGE_ENTITY_TYPES and now is not None:
        start = getattr(entity, "start_date", None)
        if start is not None:
            try:
                age = format_age_words(
                    start,
                    era_flag(getattr(entity, "start_bc", False)),
                    getattr(entity, "end_date", None),
                    era_flag(getattr(entity, "end_bc", False)),
                    now[0],
                    now[1],
                )
            except InvalidGameDateError:
                age = None
            if age is not None:
                parts.append(f"<b>{AGE_LABEL}:</b> {age}")
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


def _event_elapsed_suffix(start: GameCoord | date, start_bc: bool, now: NowPair) -> str:
    """The event-time tail of the panel's date row (NRI-0021 task 4.2, spec
    «Прошедшее время от начала события»): « · <формула> назад», « · через N»
    or « · сегодня».  Always counted from the event start — an open-ended and
    a closed event read the same; only the standard duration words are used."""
    parts = duration_parts(start, start_bc, now[0], now[1])
    if not (parts.years or parts.months or parts.days):
        return " · сегодня"
    if parts.ahead:
        return f" · {format_duration_words(parts)}"
    return f" · {format_duration_words(parts)} назад"


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
    # NRI-0022 (task 3.1): the panel-wide single row selection, painted by the
    # delegate as the rounded accent wash; only the VM moves it (``select`` /
    # ``tabSwitched`` re-answer the role through :meth:`apply_selection`).
    SelectedRole = RatingTintRole + 1

    _ROLES = {
        NameRole: QByteArray(b"name"),
        SummaryRole: QByteArray(b"summary"),
        EntityTypeRole: QByteArray(b"entityType"),
        EntityIdRole: QByteArray(b"entityId"),
        ImageSourceRole: QByteArray(b"imageSource"),
        RatingTintRole: QByteArray(b"ratingTint"),
        SelectedRole: QByteArray(b"selected"),
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

    def set_entities(
        self, entities: Iterable[Any], entity_type: str, now: NowPair | None = None
    ) -> None:
        self.beginResetModel()
        self._rows = [
            self._make_row(entity, entity_type, now) for entity in entities
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

    def apply_selection(self, selection: tuple[str, int] | None) -> None:
        """Re-answer the ``selected`` role for the given panel-wide (type, id)
        pair (``None`` = no wash, NRI-0022 task 3.1); rows whose answer
        flipped get a targeted dataChanged, the delegate paints the wash from
        the role alone."""
        for row_index, row in enumerate(self._rows):
            answer = selection is not None and (
                row["entityType"],
                row["entityId"],
            ) == selection
            if answer == row["selected"]:
                continue
            row["selected"] = answer
            index = self.index(row_index, 0)
            self.dataChanged.emit(index, index, [self.SelectedRole])

    def _make_row(
        self, entity: Any, entity_type: str, now: NowPair | None = None
    ) -> dict[str, Any]:
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
            "summary": build_detail_summary(entity, entity_type, now),
            "entityType": entity_type,
            "entityId": getattr(entity, "id", 0) or 0,
            "imageSource": image_source,
            "ratingTint": _tint_text(rating, self._runtime),
            "selected": False,
            "_rating": rating,
            "_entity": entity,
        }


class DetailPanelViewModel(QObject):
    """Header plus four stable list models; all presentation rules stay here."""

    headerChanged = Signal()
    entityActivated = Signal(str, int)
    # NRI-0022 (task 3.1): the single-click/Press selection, announced to the
    # preview (wiring) next to the unchanged double-click ``entityActivated``.
    entitySelected = Signal(str, int)
    imageRequested = Signal(object)

    # The four tabs and their payload keys are generated at import time from the
    # domain entity registry (wave 3, finding A4/C5): the same EVENT relation
    # order as the event dialog, so both views of one event always agree.
    # NRI-0018 (Д5): this single full-caption list is the tab strip's text,
    # accessibility name and tooltip at once — the short-caption TAB_LABELS of
    # the NRI-0015 era retired together with the registry's tab_label field.
    TAB_TITLES = tuple(_ref.label for _ref in _event_refs)
    ENTITY_TYPES = tuple(_ref.entity_type.value for _ref in _event_refs)
    EVENT_ATTRS = tuple(_ref.attr for _ref in _event_refs)

    def __init__(
        self,
        runtime=None,
        now_vm=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._runtime = runtime
        self._title = ""
        self._date_text = ""
        # NRI-0015 (M4): drives the empty-panel hint — no timeline row picked.
        self._event_shown = False
        # NRI-0021 (tasks 4.1/4.2, design Д2/Д5): the game-«now» VM (value
        # reader + single nowChanged broadcast) and the last shown event, kept
        # so a «now» edit re-renders the derived texts without a re-open.
        self._now_vm = now_vm
        self._shown_event: Any = None
        # NRI-0022 (task 3.2, design D3): the panel's ONE selection — the
        # (type, id) pair of the last single-clicked/Pressed row. A tab switch
        # hides the highlight but never resets this; only a new ``select`` (or
        # a new game — the facade is rebuilt) replaces it.
        self._selected: tuple[str, int] | None = None
        if now_vm is not None:
            now_vm.nowChanged.connect(self._on_now_changed)
        self.models = [
            DetailRowsModel(runtime, self) for _ in self.TAB_TITLES
        ]
        # DEFECT-1 (NRI-0016): handle kept for the explicit unsubscription
        # the spec app-logging «Слушатели состояния не переживают окно»
        # demands — the panel detaches the VM when its island releases;
        # weakness alone cannot here (the VM's C++ side may die with the
        # island context while this wrapper lives on the facade).
        self._theme_subscription = runtime.add_listener(self.retheme) if runtime is not None else None

    def detach_theme_listener(self) -> None:
        """Stop listening for theme swaps (island teardown); idempotent."""
        if self._theme_subscription is not None:
            self._runtime.remove_listener(self._theme_subscription)
            self._theme_subscription = None

    def detach_now_listener(self) -> None:
        """Stop following the game's «now» (island teardown, NRI-0021 task
        4.1 — the DEFECT-1 posture: the subscription never outlives the
        panel); idempotent."""
        if self._now_vm is not None:
            self._now_vm.nowChanged.disconnect(self._on_now_changed)
            self._now_vm = None

    def _now_pair(self) -> NowPair | None:
        """The served «now» pair, or ``None`` for a panel built without the
        game's «now» VM (then the derived texts simply stay absent)."""
        if self._now_vm is None:
            return None
        return (self._now_vm.coord, self._now_vm.is_bc)

    def _on_now_changed(self) -> None:
        """The one broadcast refresh (spec «Смена даты пересчитывает всё»):
        the shown event is re-rendered through the very show_event path —
        age lines and the event-time suffix recompute from the kept entity,
        no second rule anywhere."""
        if self._shown_event is not None:
            self.show_event(self._shown_event)

    title = Property(str, lambda self: self._title, notify=headerChanged)
    dateText = Property(str, lambda self: self._date_text, notify=headerChanged)
    eventSelected = Property(
        bool, lambda self: self._event_shown, notify=headerChanged
    )
    tabTitles = Property(
        "QVariant", lambda self: list(self.TAB_TITLES), constant=True
    )
    organizations = Property(QObject, lambda self: self.models[0], constant=True)
    characters = Property(QObject, lambda self: self.models[1], constant=True)
    items = Property(QObject, lambda self: self.models[2], constant=True)
    locations = Property(QObject, lambda self: self.models[3], constant=True)

    def show_event(self, event: Any) -> None:
        self._title = getattr(event, "name", "")
        self._event_shown = True
        self._shown_event = event  # kept for the now_changed re-render
        start_coord = getattr(event, "start_date", None)
        start_bc = era_flag(getattr(event, "start_bc", False))
        start = format_game_date(start_coord, is_bc=start_bc)
        end = format_game_date(
            getattr(event, "end_date", None),
            "∞",
            is_bc=era_flag(getattr(event, "end_bc", False)),
        )
        self._date_text = f"{start} — {end}"
        now = self._now_pair()
        # NRI-0021 task 4.2 (spec «Суффикс строки дат панели»): the event
        # time tail rides the same single duration formula.  A pair the
        # active calendar refuses (Д1-seeded «now» on a custom calendar)
        # leaves the plain pre-NRI-0021 range — the row never breaks.
        if now is not None and start_coord is not None:
            try:
                self._date_text += _event_elapsed_suffix(start_coord, start_bc, now)
            except InvalidGameDateError:
                pass
        self.headerChanged.emit()
        for model, attr, entity_type in zip(
            self.models, self.EVENT_ATTRS, self.ENTITY_TYPES
        ):
            model.set_entities(getattr(event, attr, []) or [], entity_type, now)

    def clear(self) -> None:
        self._title = ""
        self._date_text = ""
        self._event_shown = False
        self._shown_event = None
        self.headerChanged.emit()
        for model in self.models:
            model.clear()

    @Slot(str, int)
    def activate(self, entity_type: str, entity_id: int) -> None:
        if self._find_entity(entity_type, entity_id) is not None:
            self.entityActivated.emit(entity_type, entity_id)

    @Slot(str, int)
    def select(self, entity_type: str, entity_id: int) -> None:
        """Single mouse click / accessibility Press on a row (NRI-0022 task
        3.1): the selection moves as the panel's ONE — the previously washed
        row loses its highlight even across tabs — and the preview target is
        announced through ``entitySelected``. A pair outside the shown lists
        stays ignored, the same posture as ``activate``."""
        if self._find_entity(entity_type, entity_id) is None:
            return
        self._selected = (entity_type, entity_id)
        self._paint_highlight()
        self.entitySelected.emit(entity_type, entity_id)

    @Slot()
    def hideRowHighlight(self) -> None:  # noqa: N802
        """The tab strip moved (NRI-0022 task 3.2, design D3): the wash is
        screen state and leaves the screen, while the remembered selection
        (and the preview it fed) stays until the next ``select``."""
        for model in self.models:
            model.apply_selection(None)

    def _paint_highlight(self) -> None:
        for model in self.models:
            model.apply_selection(self._selected)

    @property
    def last_selected(self) -> tuple[str, int] | None:
        """The remembered panel selection — survives the highlight-hiding tab
        switches (NRI-0022 task 3.2); ``None`` while the panel never selected."""
        return self._selected

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
