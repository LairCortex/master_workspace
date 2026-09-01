"""Timeline ViewModel — event list, selection, date filtering and the W4 view knobs.

Beyond the W3 contract (id-based selection, visible-set filtering, the derived
``rows`` projection) the ViewModel owns the two view knobs of the W4 scale
ladder (design D2/D4): the current ``unit`` (сутки/месяц/год) and ``group_by``
(entity kind or ``None``). They are plain in-memory view state — defaults
``DAY``/``None``, never serialized — so the panel always reopens as
«сутки · без группировки» (spec «Вид не переживает перезапуск»).
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from PySide6.QtCore import QObject, Signal

from app.presentation.views.timeline_rows import Row, ScaleUnit, build_rows


class EntityKind(Enum):
    """Entity kind the W4 grouping switcher can group the scale by.

    Values are the same singular entity-type strings the panel already uses
    (the "+"-menu, search results); :attr:`event_attr` maps a kind onto the
    domain ``Event`` relation holding that kind's links. View-level only:
    :func:`build_rows` itself consumes a materialized id→names mapping, never
    this enum or the domain (W4 D8).
    """

    CHARACTER = "character"
    LOCATION = "location"
    ORGANIZATION = "organization"
    ITEM = "item"

    @property
    def event_attr(self) -> str:
        """Attribute of a domain ``Event`` holding this kind's link list."""
        return f"{self.value}s"


class TimelineViewModel(QObject):
    events_changed = Signal()
    selected_event_changed = Signal()

    def __init__(self, event_service, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._event_service = event_service
        self._all_events: list[Any] = []
        self.events: list[Any] = []
        self.rows: list[Row] = []
        self.selected_event: Any | None = None
        self._current_filter: tuple[date | None, date | None] = (None, None)
        # W4 view knobs — view state only, never persisted (spec «Вид не
        # переживает перезапуск»): every fresh ViewModel starts «сутки · выкл».
        self._unit: ScaleUnit = ScaleUnit.DAY
        self._group_by: EntityKind | None = None

    # ── W4 view knobs (design D2) ──────────────────────────────────────────

    @property
    def unit(self) -> ScaleUnit:
        """Current rung of the scale ladder (default :attr:`ScaleUnit.DAY`)."""
        return self._unit

    @unit.setter
    def unit(self, value: ScaleUnit) -> None:
        # Changing the rung re-models ``rows`` only: the filter and the
        # selection survive untouched (tasks 4.1/4.3, spec scenario
        # «Переключение не трогает выбор»); an unchanged value is a no-op.
        if value is self._unit:
            return
        self._unit = value
        self._rebuild_rows()
        self.events_changed.emit()

    @property
    def group_by(self) -> EntityKind | None:
        """Entity kind the list is grouped by, ``None`` = grouping off."""
        return self._group_by

    @group_by.setter
    def group_by(self, value: EntityKind | None) -> None:
        if value is self._group_by:
            return
        self._group_by = value
        self._rebuild_rows()
        self.events_changed.emit()

    def _group_map(self) -> dict[int, tuple[str, ...]] | None:
        """Materialize the «event → group names» mapping for ``build_rows``.

        Read straight off the domain relations (``event.characters`` etc.) —
        only the link names, so the Qt-free core stays domain-agnostic
        (W4 D8). An unlinked event maps to an empty tuple, which the core
        normalizes into the trailing «Без привязки» section.
        """
        if self._group_by is None:
            return None
        attr = self._group_by.event_attr
        return {
            e.id: tuple(
                name for link in (getattr(e, attr, None) or ())
                if (name := getattr(link, "name", ""))
            )
            for e in self.events
        }

    def _rebuild_rows(self) -> None:
        """Re-project the visible sample into ``rows`` at the current knobs."""
        start, end = self._current_filter
        self.rows = build_rows(
            self.events, start, end, unit=self._unit, groups=self._group_map(),
        )

    # ── data loading and filtering (W3 contract, unchanged) ────────────────

    async def load_events(self) -> None:
        self._all_events = list(await self._event_service.get_all_events())
        self._apply_filter()

    def filter_by_dates(self, start: date | None, end: date | None) -> None:
        """Filter events by date range. None clears the filter."""
        self._current_filter = (start, end)
        self._apply_filter()

    def _apply_filter(self) -> None:
        """Recompute the visible set and its derived rows, then keep the
        selection consistent with it.

        A selected event that fell out of the visible set is dropped here (and
        ``selected_event_changed`` fires), so the panel — which prunes the
        same id while re-modelling the new set — the ViewModel and the detail
        panel never disagree about what is selected (task 3.3).

        ``rows`` is the vertical scale's row projection (W3b task 4.1): the
        filter bounds seed ``build_rows`` when a range is live, otherwise the
        sample derives its own min–max range (spec «Диапазон без фильтра»).
        It is recomputed before ``events_changed`` so any consumer reading it
        from the signal sees data consistent with ``events``. The projection
        uses the current ladder rung and grouping (W4 task 4.1), which can
        never change ``events`` itself.
        """
        start, end = self._current_filter
        if start is None or end is None:
            self.events = list(self._all_events)
        else:
            self.events = [
                e for e in self._all_events
                if e.start_date >= start and (e.end_date is None or e.end_date <= end)
            ]
        self._rebuild_rows()
        self.events_changed.emit()
        # Internal revalidation, not an external selection: it must NOT drag
        # the ladder down (a filter tweak on MONTH keeps the rung, spec
        # «Фильтр переживает лестницу»), unlike select_event_by_id below.
        if self.selected_event is not None:
            self._select_from_visible(self.selected_event.id)

    # ── selection and the ladder descent (W3 id-contract, W4 D4) ───────────

    def _select_from_visible(self, event_id: int | None) -> None:
        """Assign the selection from the visible set; a miss clears it."""
        self.selected_event = next(
            (e for e in self.events if e.id == event_id), None
        )
        self.selected_event_changed.emit()

    def _ensure_day_unit_for(self, event: Any) -> None:
        """Drop the ladder to DAY so ``event`` owns an EVENT row (W4 D4).

        Event lines exist on the daily rung only, so any external selection
        (search results) or jump command has to land here first: the view is
        rebuilt (``events_changed`` fires) *before* the caller asserts the
        selection, mirroring «ставит unit=DAY, пересобирает rows, затем
        выбирает». Grouping is NOT reset — on DAY it only orders events inside
        a day, so the row exists either way (spec «Сутки остаются
        хронологией»). A no-op when already on DAY.
        """
        self.unit = ScaleUnit.DAY

    def select_event_by_id(self, event_id: int | None) -> None:
        """Select by event id (W3 id-contract); a miss clears the selection.

        External selections — the search path and the jump commands arrive
        through here — descend the ladder to DAY first when the event owns no
        row on the current rung (spec «Внешний выбор с крупной ступени
        спускает лестницу»). An id outside the *filtered sample* is a plain
        miss: it clears the selection in every layer without a pointless
        descent (W3 behavior, unchanged).
        """
        event = next((e for e in self.events if e.id == event_id), None)
        if event is not None:
            self._ensure_day_unit_for(event)
        self.selected_event = event
        self.selected_event_changed.emit()
