"""Generic entity service for CRUD on any entity type."""
from __future__ import annotations

from datetime import date
from functools import partial
from typing import Any, Dict, Sequence

from app.application.services.mention_rewrite import rewrite_mentions
from app.application.services.relation_sync import sync_related
from app.domain import entity_registry
from app.domain.enums.entity_type import EntityType
from app.infrastructure.db.uow import GameSessionUoW
from app.infrastructure.images.store import ImageStore
from app.infrastructure.repositories import entity_type_for_model
from app.infrastructure.repositories.base_repository import BaseRepository


class EntityService:
    def __init__(
        self,
        repo: BaseRepository,
        description_repo: BaseRepository,
        related_services: Dict[str, "EntityService"] | None = None,
        image_store: ImageStore | None = None,
        uow: GameSessionUoW | None = None,
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
        # Wave 5 (design D4): the single transaction finish point. The app
        # hands every service the SAME unit (shared non-reentrancy guard);
        # a bare-session construction (the ~40 service unit tests) self-builds
        # one over the repository's session, so no caller needs to know.
        self._uow = uow if uow is not None else GameSessionUoW(repo.session)

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

    async def delete_entity_and_description(
        self, entity_id: int, description_id: int
    ) -> None:
        """Remove a popup-created entity together with its description row.

        No transaction is opened here (task 5.11): the caller — the connector's
        batched popup cleanup, the only place with the whole pending list —
        owns the unit-of-work transaction around the loop. The two lookups are
        the repositories' job, so the connector no longer holds a session or
        an ORM model. The entity (the description's referrer) goes first.
        """
        await self._repo.delete(entity_id)
        await self._desc_repo.delete(description_id)

    # ── M2M relation sync (ported 1:1 from the main.py closures) ─────────

    @property
    def _session(self):
        # The repository already holds the session (same pattern as the app wiring)
        return self._repo.session

    def _sibling_service(self, attr_name: str) -> "EntityService | None":
        """The sibling service owning the link collection named ``attr_name``.

        Dispatch is an exhaustive ``match`` over ``EntityType`` (wave 3, D2):
        a registry type handled here in the future must be listed explicitly,
        so forgetting it fails as ``MatchError`` in tests instead of silently
        skipping the relation (audit A4: «тихо выходят из if rel_type is
        None: return»).
        """
        match entity_registry.type_for_collection(attr_name):
            case (
                EntityType.CHARACTER
                | EntityType.ITEM
                | EntityType.LOCATION
                | EntityType.ORGANIZATION
            ) as link_type:
                return self._related_services.get(link_type.value)
            case EntityType.EVENT | EntityType.RATING:
                # the event and rating collections are never card links;
                # they are synced by the event/card services themselves
                return None
            case None:
                # a related_changes key that is not a link collection at all
                return None

    async def sync_related(self, entity: Any, attr_name: str, desired_ids: set) -> None:
        """Link-only M2M sync for one attribute: add missing, remove extras.

        Delegates to the single application-layer synchronizer (C3) with the
        link-only flag: related entities are only fetched, never created.
        """
        rel_svc = self._sibling_service(attr_name)
        if rel_svc is None:
            return

        await sync_related(
            rel_svc,
            getattr(entity, attr_name),
            ({"_existing_id": aid} for aid in desired_ids),
            create_missing=False,
        )

    async def apply_related_changes(self, entity: Any, related_changes: dict) -> None:
        """Resync every M2M attribute a dialog payload names (link-only).

        The one «related_changes → per-attribute sync» loop shared by the
        entity-card save (``update_entity_with_relations``) and the wiring's
        popup-create path (C3): each attribute is loaded into the identity
        map first (the link-only sync must not lazy-load), unknown attribute
        names and types without a sibling service are skipped.
        """
        for attr_name, change_data in related_changes.items():
            if self._sibling_service(attr_name) is None:
                continue
            await self._session.refresh(entity, attribute_names=[attr_name])
            await self.sync_related(
                entity, attr_name, set(change_data.get("current_ids", []))
            )

    async def update_entity_with_relations(
        self,
        entity_id: int,
        field_data: dict,
        characteristics: str,
        backstory: str,
        related_changes: dict,
    ):
        """Update entity fields + description and resync M2M relations.

        Ported from the on_entity_saved closure in on_entity_click (main.py),
        except for the failure path (``save-error-reporting``): commit on
        success returns the updated entity; a missing entity raises
        ``ValueError`` before the relation refresh; any failure rolls the
        transaction back and re-raises (no more rollback + silent None).

        Wave 5 (design D4.3, closes audit Q14 scenario 3): the whole body runs
        inside the unit of work's single transaction — no manual ``commit``
        halfway, no separate image-GC commit behind it. The GC of a replaced
        image is a post-write hook now: it runs only once the mutation has
        committed, and its failure is logged, never surfaced as a false
        "could not save" over already-written data.
        """
        async with self._uow.transaction():
            # Snapshot name and image_id before mutating so rename rewrite
            # compares the pre-update name and image GC can run after commit.
            current = await self.get_entity(entity_id)
            old_name = getattr(current, "name", None) if current else None
            old_image_id = None
            has_image_field = "image_id" in field_data
            if has_image_field:
                old_image_id = getattr(current, "image_id", None) if current else None

            # Update basic entity fields
            await self.update_entity(entity_id, **field_data)

            # Update description
            refreshed = await self.get_entity(entity_id)
            if refreshed is None:
                # Without this check the relation-refresh below would raise a
                # bare AttributeError on None — the caller must see the real
                # reason (design D1 of fix-silent-dialog-save-debt).
                raise ValueError(f"сущность {entity_id} не найдена")
            if refreshed.description:
                refreshed.description.characteristics = characteristics
                refreshed.description.backstory = backstory

            # Sync M2M relationships (link-only, never creates)
            await self.apply_related_changes(refreshed, related_changes)

            new_name = field_data.get("name")
            if new_name is not None and new_name != old_name:
                mention_type = entity_type_for_model(self._repo.model).value
                await rewrite_mentions(self._session, mention_type, entity_id, new_name)

            if has_image_field and self._image_store is not None:
                new_image_id = field_data.get("image_id")
                if new_image_id != old_image_id:
                    self._uow.after_write(
                        partial(self._image_store.gc_after_commit, old_image_id)
                    )

            return refreshed
