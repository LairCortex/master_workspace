"""Search ViewModel — global search across all entities."""
from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtCore import QObject, Signal


class SearchViewModel(QObject):
    results_changed = Signal()

    def __init__(self, search_service, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._search_service = search_service
        self.results: Dict[str, List[Any]] = {}

    async def search(self, query: str) -> None:
        if not query.strip():
            self.results = {}
            self.results_changed.emit()
            return
        self.results = await self._search_service.search_all(query)
        self.results_changed.emit()
