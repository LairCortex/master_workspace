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

    async def search_names(self, query: str) -> List[Dict[str, Any]]:
        """Search by name only across all entities. Returns [{type, id, name}, ...]."""
        _type_map = {
            "events": "event",
            "organizations": "organization",
            "characters": "character",
            "items": "item",
            "locations": "location",
        }
        results: List[Dict[str, Any]] = []
        for key, repo in self._repos.items():
            entities = await repo.search_by_name(query)
            for e in entities:
                results.append({"type": _type_map[key], "id": e.id, "name": e.name})
        return results
