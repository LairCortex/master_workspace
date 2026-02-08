"""Global search service across all entity types."""
from __future__ import annotations

from typing import Any, Dict, List


class SearchService:
    def __init__(self, event, organization, character, item, location) -> None:
        self._repos = {
            "events": event,
            "organizations": organization,
            "characters": character,
            "items": item,
            "locations": location,
        }

    async def search_all(self, query: str) -> Dict[str, List[Any]]:
        results: Dict[str, List[Any]] = {}
        for key, repo in self._repos.items():
            results[key] = list(await repo.search(query))
        return results
