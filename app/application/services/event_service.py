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

    # M2M collection attribute names (kept 1:1 with the main.py closures)
    RELATION_ATTRS = ["organizations", "characters", "items", "locations"]

    @property
    def _session(self):
        # The repository already holds the session (same pattern as the app wiring)
        return self._event_repo._session

    # ── Save-with-relations (ported 1:1 from the main.py closures) ───────

    async def create_event_with_relations(
        self,
        name: str,
        start_date: date,
        end_date: date | None,
        characteristics: str,
        backstory: str,
        relations: dict,
    ):
        """Create an event (with description) and sync all four M2M collections.

        1:1 port of the on_saved closure in main.py: commit on success,
        rollback on error (error is swallowed, None is returned — the old
        closure did not re-raise and did not notify the user).
        """
        try:
            event = await self.create_event(
                name=name,
                characteristics=characteristics,
                backstory=backstory,
                start_date=start_date,
                end_date=end_date,
            )
            await self._session.refresh(event, attribute_names=self.RELATION_ATTRS)
            await self.apply_event_relations(
                event,
                relations.get("organizations", []),
                relations.get("characters", []),
                relations.get("items", []),
                relations.get("locations", []),
            )
            await self._session.commit()
            return event
        except Exception:
            await self._session.rollback()
            return None

    async def update_event_with_relations(
        self,
        event_id: int,
        name: str,
        start_date: date,
        end_date: date | None,
        characteristics: str,
        backstory: str,
        relations: dict,
    ):
        """Update event fields + description and resync all four M2M collections.

        1:1 port of the on_event_updated closure in main.py. Returns the
        updated event, or None if the event is missing / an error occurred
        (rollback + silent fail, as before).
        """
        try:
            await self.update_event(
                event_id,
                name=name,
                start_date=start_date,
                end_date=end_date,
            )
            updated_event = await self.get_event(event_id)
            if updated_event and updated_event.description:
                updated_event.description.characteristics = characteristics
                updated_event.description.backstory = backstory

            # Sync M2M relationships
            await self._session.refresh(updated_event, attribute_names=self.RELATION_ATTRS)
            await self.apply_event_relations(
                updated_event,
                relations.get("organizations", []),
                relations.get("characters", []),
                relations.get("items", []),
                relations.get("locations", []),
            )
            await self._session.commit()
            return updated_event
        except Exception:
            await self._session.rollback()
            return None

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
