"""Search ViewModel — global search plus the sync state of its QML island."""
from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

from app.presentation.utils.date_utils import era_flag, format_game_date

_TYPE_LABELS = {
    "events": "События",
    "organizations": "Организации",
    "characters": "Персонажи",
    "items": "Предметы",
    "locations": "Локации",
}

_TYPE_TO_ENTITY = {
    "events": "event",
    "organizations": "organization",
    "characters": "character",
    "items": "item",
    "locations": "location",
}

DEBOUNCE_INTERVAL_MS = 300


class SearchViewModel(QObject):
    results_changed = Signal()
    rowsChanged = Signal()
    queryChanged = Signal()
    listVisibleChanged = Signal()
    debounceActiveChanged = Signal()
    searchRequested = Signal(str)
    resultSelected = Signal(str, int)

    def __init__(self, search_service, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._search_service = search_service
        self.results: Dict[str, List[Any]] = {}
        self._rows: list[dict[str, Any]] = []
        self._query = ""
        self._list_visible = False
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

    @Slot(int)
    def select(self, index: int) -> None:
        if not 0 <= index < len(self._rows):
            return
        row = self._rows[index]
        if not row["clickable"] or row["id"] is None:
            return
        self.resultSelected.emit(row["type"], row["id"])
        self._set_list_visible(False)

    async def search(self, query: str) -> None:
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
            label = _TYPE_LABELS.get(type_key, type_key)
            entity_type = _TYPE_TO_ENTITY.get(type_key, type_key)
            rows.append(
                self._row(
                    "sectionHeader",
                    f"— {label} ({len(entities)}) —",
                )
            )
            for entity in entities:
                name = getattr(entity, "name", str(entity))
                start_date = getattr(entity, "start_date", None)
                date_text = (
                    format_game_date(
                        start_date,
                        "",
                        is_bc=era_flag(getattr(entity, "start_bc", False)),
                    )
                    if start_date
                    else ""
                )
                text = f"{name}  [{date_text}]" if date_text else name
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
