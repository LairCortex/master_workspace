"""Global search service across all entity types."""
from __future__ import annotations

from typing import Any, Dict, List

from app.domain import entity_registry
from app.domain.enums.entity_type import EntityType
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.event_repository import EventRepository


class SearchService:
    def __init__(
        self,
        event: EventRepository,
        organization: BaseRepository,
        character: BaseRepository,
        item: BaseRepository,
        location: BaseRepository,
    ) -> None:
        # collection keys are the registry's plural forms (wave 3, A4), in
        # the registry's canonical order — the search scope itself
        self._repos: Dict[str, BaseRepository] = {
            entity_registry.descriptor(EntityType.EVENT).plural: event,
            entity_registry.descriptor(EntityType.ORGANIZATION).plural: organization,
            entity_registry.descriptor(EntityType.CHARACTER).plural: character,
            entity_registry.descriptor(EntityType.ITEM).plural: item,
            entity_registry.descriptor(EntityType.LOCATION).plural: location,
        }

    async def search_all(self, query: str) -> Dict[str, List[Any]]:
        results: Dict[str, List[Any]] = {}
        for key, repo in self._repos.items():
            results[key] = list(await repo.search(query))
        return results

    async def search_names(self, query: str) -> List[Dict[str, Any]]:
        """Search by name only across all entities. Returns [{type, id, name}, ...]."""
        results: List[Dict[str, Any]] = []
        for key, repo in self._repos.items():
            entities = await repo.search_by_name(query)
            for e in entities:
                hit_type = entity_registry.type_for_collection(key)
                results.append({"type": hit_type.value, "id": e.id, "name": e.name})
        return results
