"""Generic entity service for CRUD on any entity type."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, Sequence

from app.infrastructure.images.store import ImageStore
from app.infrastructure.repositories.base_repository import BaseRepository

# Map attr names to entity_type strings for relationship syncing
# (ported from main.py, where the relation-sync closures lived)
_ATTR_TO_ENTITY_TYPE = {
    "characters": "character",
    "items": "item",
    "organizations": "organization",
    "locations": "location",
}


class EntityService:
    def __init__(
        self,
        repo: BaseRepository,
        description_repo: BaseRepository,
        related_services: Dict[str, "EntityService"] | None = None,
        image_store: ImageStore | None = None,
    ) -> None:
        self._repo = repo
        self._desc_repo = description_repo
        # Maps entity_type -> service for that type, used to fetch related
        # entities during M2M sync (replaces Application._get_entity_service
        # lookups in the old main.py closures).
        self._related_services = related_services or {}
        # Used to GC a replaced/removed image after the ref-mutation commits
        # (design D6/task 6.2) — None for entity types without an image field
        # (the "image_id" key is simply absent from field_data for those).
        self._image_store = image_store

    def set_related_services(self, services: Dict[str, "EntityService"]) -> None:
        """Point at sibling services (populated by the Application catalog)."""
        self._related_services = services

    async def create_entity(
        self,
        name: str,
        characteristics: str,
        backstory: str,
        start_date: date,
        end_date: date,
        **extra: Any,
    ):
        desc = await self._desc_repo.create(characteristics=characteristics, backstory=backstory)
        return await self._repo.create(
            name=name,
            description_id=desc.id,
            start_date=start_date,
            end_date=end_date,
            **extra,
        )

    async def get_entity(self, entity_id: int):
        return await self._repo.get_by_id(entity_id)

    async def get_all(self) -> Sequence:
        return await self._repo.get_all()

    async def update_entity(self, entity_id: int, **kwargs: Any):
        return await self._repo.update(entity_id, **kwargs)

    async def delete_entity(self, entity_id: int) -> bool:
        return await self._repo.delete(entity_id)

    # ── M2M relation sync (ported 1:1 from the main.py closures) ─────────

    @property
    def _session(self):
        # The repository already holds the session (same pattern as the app wiring)
        return self._repo._session

    @staticmethod
    def _relation_type(attr_name: str) -> str | None:
        return _ATTR_TO_ENTITY_TYPE.get(attr_name)

    async def sync_related(self, entity: Any, attr_name: str, desired_ids: set) -> None:
        """Link-only M2M sync for one attribute: add missing, remove extras.

        1:1 port of the per-attribute sync block from on_entity_saved in
        main.py: related entities are only fetched (never created).
        """
        rel_type = self._relation_type(attr_name)
        if rel_type is None:
            return
        rel_svc = self._related_services.get(rel_type)
        if rel_svc is None:
            return

        collection = getattr(entity, attr_name)
        current_ids = {e.id for e in collection}

        # Add missing
        for aid in desired_ids - current_ids:
            rel_entity = await rel_svc.get_entity(aid)
            if rel_entity:
                collection.append(rel_entity)

        # Remove extras
        to_remove = [e for e in collection if e.id in (current_ids - desired_ids)]
        for e in to_remove:
            collection.remove(e)

    async def update_entity_with_relations(
        self,
        entity_id: int,
        field_data: dict,
        characteristics: str,
        backstory: str,
        related_changes: dict,
    ):
        """Update entity fields + description and resync M2M relations.

        1:1 port of the on_entity_saved closure in on_entity_click (main.py):
        commit on success, rollback + silent None on error.
        """
        try:
            # Snapshot the current image_id (if this entity type has the
            # field) before mutating it, so a replace/remove can be GC'd
            # after commit (design D6: commit-first, then gc_after_commit —
            # never inside the same transaction as the ref mutation).
            old_image_id = None
            has_image_field = "image_id" in field_data
            if has_image_field:
                current = await self.get_entity(entity_id)
                old_image_id = getattr(current, "image_id", None) if current else None

            # Update basic entity fields
            await self.update_entity(entity_id, **field_data)

            # Update description
            refreshed = await self.get_entity(entity_id)
            if refreshed and refreshed.description:
                refreshed.description.characteristics = characteristics
                refreshed.description.backstory = backstory

            # Sync M2M relationships (link-only, never creates)
            for attr_name, change_data in related_changes.items():
                desired_ids = set(change_data.get("current_ids", []))
                rel_type = self._relation_type(attr_name)
                if not rel_type:
                    continue
                if not self._related_services.get(rel_type):
                    continue

                ent = await self.get_entity(entity_id)
                await self._session.refresh(ent, attribute_names=[attr_name])
                await self.sync_related(ent, attr_name, desired_ids)

            await self._session.commit()

            if has_image_field and self._image_store is not None:
                new_image_id = field_data.get("image_id")
                if new_image_id != old_image_id:
                    await self._image_store.gc_after_commit(old_image_id)

            return refreshed
        except Exception:
            await self._session.rollback()
            return None
