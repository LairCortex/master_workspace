"""Search ViewModel — global search plus the sync state of its QML island."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication

from app.domain import entity_registry
from app.presentation.utils.date_utils import (
    era_flag,
    event_start_time,
    format_event_start,
)
from app.presentation.views.timeline_rows import event_parent_id

DEBOUNCE_INTERVAL_MS = 300


class SearchViewModel(QObject):
    results_changed = Signal()
    rowsChanged = Signal()
    queryChanged = Signal()
    listVisibleChanged = Signal()
    debounceActiveChanged = Signal()
    searchRequested = Signal(str)
    resultSelected = Signal(str, int)
    # NRI-0022 (task 6.2, design D7): the second result gesture — the double
    # click (and the accessibility Press, which per the RowItem contract
    # mirrors the double-click path) asks for EDITING: the wiring opens the
    # entity's card or the event editor. ``resultSelected`` stayed the single
    # left-click channel (its meaning moved to the full path in the wiring).
    resultActivated = Signal(str, int)

    def __init__(self, search_service, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._search_service = search_service
        self.results: Dict[str, List[Any]] = {}
        self._rows: list[dict[str, Any]] = []
        self._query = ""
        self._list_visible = False
        # NRI-0023 task 8.2 (design Д9, spec global-search «Подсобытие названо
        # через родителя»): the game-wide event `id → имя` card the wiring
        # hands in with every query — built одним проходом over the ladder's
        # loaded sample, it names a sub-event's parent even when the parent
        # never matched the query itself. Empty (the default) keeps rows
        # exactly as they were: an unnameable parent adds no prefix.
        self._event_names: Mapping[int, str] = {}
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(DEBOUNCE_INTERVAL_MS)
        self._debounce_timer.timeout.connect(self._on_debounce_timeout)

    # ---- QML-facing sync state ----

    def _get_rows(self) -> list[dict[str, Any]]:
        return self._rows

    rows = Property("QVariant", _get_rows, notify=rowsChanged)

    def _get_query(self) -> str:
        return self._query

    query = Property(str, _get_query, notify=queryChanged)

    def _get_list_visible(self) -> bool:
        return self._list_visible

    listVisible = Property(bool, _get_list_visible, notify=listVisibleChanged)

    def _get_debounce_interval(self) -> int:
        return self._debounce_timer.interval()

    debounceInterval = Property(int, _get_debounce_interval, constant=True)

    def _get_debounce_active(self) -> bool:
        return self._debounce_timer.isActive()

    debounceActive = Property(
        bool, _get_debounce_active, notify=debounceActiveChanged
    )

    def _get_double_click_interval_ms(self) -> int:
        """The platform double-click interval — NRI-0022 (task 6.2): the
        island holds a single click by this much, because a real double click
        releases its FIRST click before the double-click event arrives, and an
        immediate single-click jump would hide the results list from under the
        second click (the edit gesture would never land)."""
        return QGuiApplication.instance().doubleClickInterval()

    doubleClickIntervalMs = Property(
        int, _get_double_click_interval_ms, constant=True
    )

    @Slot(str)
    def setQuery(self, query: str) -> None:  # noqa: N802
        if query != self._query:
            self._query = query
            self.queryChanged.emit()
        if len(query.strip()) < 2:
            self._stop_debounce()
            self.results = {}
            self._set_rows([])
            self._set_list_visible(False)
            return
        was_active = self._debounce_timer.isActive()
        self._debounce_timer.start()
        if not was_active:
            self.debounceActiveChanged.emit()

    @Slot()
    def requestSearch(self) -> None:  # noqa: N802
        self._stop_debounce()
        self._emit_search()

    def _clickable_target(self, index: int) -> tuple[str, int] | None:
        """(type, id) behind one list index; ``None`` for an out-of-range
        index and for the non-clickable rows (section headers, the no-match
        line) — the single guard both result gestures share (NRI-0022)."""
        if not 0 <= index < len(self._rows):
            return None
        row = self._rows[index]
        if not row["clickable"] or row["id"] is None:
            return None
        return (row["type"], row["id"])

    @Slot(int)
    def select(self, index: int) -> None:  # noqa: N802
        """Single left click on a result row (its meaning — the full path —
        lives in the wiring; the VM only names the hit and collapses)."""
        target = self._clickable_target(index)
        if target is None:
            return
        self.resultSelected.emit(*target)
        self._set_list_visible(False)

    @Slot(int)
    def activate(self, index: int) -> None:  # noqa: N802
        """Double click on a result row (NRI-0022 task 6.2): the edit gesture
        — the wiring opens the entity card or the event editor; the list
        collapses the same way."""
        target = self._clickable_target(index)
        if target is None:
            return
        self.resultActivated.emit(*target)
        self._set_list_visible(False)

    async def search(self, query: str, event_names: Mapping[int, str] | None = None) -> None:
        # NRI-0023 task 8.2: the wiring hands the `id → имя` card of every
        # game event with the query (the ladder's loaded sample, one pass);
        # it is the only naming source for a sub-event's parent, which does
        # not have to match the query itself. Absent — rows stay as before.
        self._event_names = dict(event_names) if event_names else {}
        if not query.strip():
            self.results = {}
            self.results_changed.emit()
            self._set_rows([])
            self._set_list_visible(False)
            return
        self.results = await self._search_service.search_all(query)
        self.results_changed.emit()
        self._publish_results()

    # ---- row adaptation (the service/domain contract remains unchanged) ----

    @staticmethod
    def _row(
        kind: str,
        text: str,
        *,
        entity_type: str = "",
        entity_id: int | None = None,
        date_text: str = "",
        clickable: bool = False,
    ) -> dict[str, Any]:
        return {
            "kind": kind,
            "text": text,
            "type": entity_type,
            "id": entity_id,
            "dateText": date_text,
            "clickable": clickable,
        }

    def _publish_results(self) -> None:
        rows: list[dict[str, Any]] = []
        for type_key, entities in self.results.items():
            if not entities:
                continue
            # section captions and payload types resolve through the entity
            # registry (wave 3, finding A4), keeping the tolerant fallback
            # for keys outside the registry
            desc = entity_registry.by_collection(type_key)
            label = desc.plural_label if desc else type_key
            entity_type = desc.key if desc else type_key
            rows.append(
                self._row(
                    "sectionHeader",
                    f"— {label} ({len(entities)}) —",
                )
            )
            for entity in entities:
                name = getattr(entity, "name", str(entity))
                # NRI-0023 task 8.2 (spec global-search «Подсобытие названо
                # через родителя»): a row of a sub-event carries its parent's
                # name through « · » straight after the child's own name —
                # read off the wiring's id → имя card; a parent the card
                # cannot name (absent link, stale id) adds no prefix, the row
                # stays the plain name. Duck-typed like every other surface:
                # only events carry a parent link at all.
                parent_id = event_parent_id(entity)
                parent_name = (
                    self._event_names.get(parent_id)
                    if parent_id is not None
                    else None
                )
                label = f"{name} · {parent_name}" if parent_name else str(name)
                start_date = getattr(entity, "start_date", None)
                # The start caption rides the single event-surface helper
                # (task 8.1): a chosen time gains its «, HH:MM» tail, an
                # untimed event prints word-for-word what it always did.
                date_text = (
                    format_event_start(
                        start_date,
                        era_flag(getattr(entity, "start_bc", False)),
                        event_start_time(entity),
                    )
                    if start_date
                    else ""
                )
                text = f"{label}  [{date_text}]" if date_text else label
                rows.append(
                    self._row(
                        "result",
                        text,
                        entity_type=entity_type,
                        entity_id=getattr(entity, "id", None),
                        date_text=date_text,
                        clickable=getattr(entity, "id", None) is not None,
                    )
                )
        if not rows and len(self._query.strip()) >= 2:
            rows = [self._row("noMatch", "Ничего не найдено")]
        self._set_rows(rows)
        self._set_list_visible(bool(rows))

    def _emit_search(self) -> None:
        self._stop_debounce()
        query = self._query.strip()
        if len(query) >= 2:
            self.searchRequested.emit(query)

    def _on_debounce_timeout(self) -> None:
        self.debounceActiveChanged.emit()
        self._emit_search()

    def _stop_debounce(self) -> None:
        if self._debounce_timer.isActive():
            self._debounce_timer.stop()
            self.debounceActiveChanged.emit()

    def _set_rows(self, rows: list[dict[str, Any]]) -> None:
        if rows == self._rows:
            return
        self._rows = rows
        self.rowsChanged.emit()

    def _set_list_visible(self, visible: bool) -> None:
        if visible == self._list_visible:
            return
        self._list_visible = visible
        self.listVisibleChanged.emit()
