"""Event application service."""
from __future__ import annotations

from datetime import date
from typing import Any, List, Sequence

from app.application.services.entity_service import EntityService
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.event_repository import EventRepository


class EventService:
    def __init__(
        self,
        event_repo: EventRepository,
        description_repo: BaseRepository,
        organization_service: EntityService,
        character_service: EntityService,
        item_service: EntityService,
        location_service: EntityService,
    ) -> None:
        self._event_repo = event_repo
        self._desc_repo = description_repo
        self._organization_service = organization_service
        self._character_service = character_service
        self._item_service = item_service
        self._location_service = location_service

    async def create_event(
        self,
        name: str,
        characteristics: str,
        backstory: str,
        start_date: date,
        end_date: date,
        **extra: Any,
    ):
        desc = await self._desc_repo.create(characteristics=characteristics, backstory=backstory)
        return await self._event_repo.create(
            name=name,
            description_id=desc.id,
            start_date=start_date,
            end_date=end_date,
            **extra,
        )

    async def get_event(self, event_id: int):
        return await self._event_repo.get_by_id(event_id)

    async def get_all_events(self) -> Sequence:
        return await self._event_repo.get_all_ordered()

    async def update_event(self, event_id: int, **kwargs: Any):
        return await self._event_repo.update(event_id, **kwargs)

    async def delete_event(self, event_id: int) -> bool:
        return await self._event_repo.delete(event_id)

    async def get_events_at_date(self, target_date: date) -> Sequence:
        return await self._event_repo.get_events_at_date(target_date)

    # ── M2M relation sync (ported 1:1 from the main.py closures) ─────────

    async def apply_event_relations(
        self,
        event: Any,
        org_items: List[dict],
        char_items: List[dict],
        item_items: List[dict],
        loc_items: List[dict],
    ) -> None:
        """Sync all four event M2M collections with the dialog's item lists.

        Each item dict either carries ``_existing_id`` (link existing) or is
        a create-entity kwargs mapping (create + link). Entities from the
        previous state that are not in the list get unlinked.
        """
        await self._process_items(org_items, self._organization_service, event.organizations)
        await self._process_items(char_items, self._character_service, event.characters)
        await self._process_items(item_items, self._item_service, event.items)
        await self._process_items(loc_items, self._location_service, event.locations)

    async def _process_items(self, items: List[dict], svc: EntityService, collection) -> None:
        existing_ids = {obj.id for obj in collection}
        new_ids = set()

        for ent in items:
            eid = ent.get("_existing_id")
            if eid:
                new_ids.add(eid)
                if eid not in existing_ids:
                    obj = await svc.get_entity(eid)
                    if obj:
                        collection.append(obj)
            else:
                obj = await svc.create_entity(**ent)
                collection.append(obj)
                new_ids.add(obj.id)

        # Remove unlinked entities (were in event before but not in new list)
        to_remove = [obj for obj in collection if obj.id not in new_ids]
        for obj in to_remove:
            collection.remove(obj)
