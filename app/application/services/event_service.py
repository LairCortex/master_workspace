"""Event application service."""
from __future__ import annotations

from datetime import date
from typing import Any, List, Sequence

from sqlalchemy import select

from app.application.services.entity_service import EntityService
from app.application.services.mention_rewrite import rewrite_mentions
from app.application.services.relation_sync import sync_related
from app.domain import entity_registry
from app.domain.enums.entity_type import EntityType
from app.infrastructure.db.models import EventModel
from app.infrastructure.db.uow import GameSessionUoW
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.event_repository import EventRepository
from app.infrastructure.repositories.event_type_repository import EventTypeRepository

# color_index addresses color.chart.{1..8} tokens (W4); no colorpicker exists.
COLOR_INDEX_MIN = 1
COLOR_INDEX_MAX = 8

#: ``update_event_with_relations`` default: leave the event's type untouched.
#: A plain ``None`` default could not tell "no type" from "caller predates W4".
TYPE_UNSET = object()


class EventService:
    def __init__(
        self,
        event_repo: EventRepository,
        description_repo: BaseRepository,
        organization_service: EntityService,
        character_service: EntityService,
        item_service: EntityService,
        location_service: EntityService,
        event_type_repo: EventTypeRepository,
        uow: GameSessionUoW | None = None,
    ) -> None:
        self._event_repo = event_repo
        self._desc_repo = description_repo
        self._organization_service = organization_service
        self._character_service = character_service
        self._item_service = item_service
        self._location_service = location_service
        self._event_type_repo = event_type_repo
        # Wave 5 (design D4): the single transaction finish point; the app
        # injects the SAME unit the entity services and the connector share
        # (one non-reentrancy guard across all write paths). Bare-session
        # constructions (unit tests) self-build one over the event session.
        self._uow = uow if uow is not None else GameSessionUoW(event_repo.session)

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

    async def get_events_at_date(self, target_key: int) -> Sequence:
        """Events covering a moment given by its era key (design D2/D4) —
        callers translate their (date, era) pair through ``era_key``."""
        return await self._event_repo.get_events_at_date(target_key)

    # ── Event types (W4) ───────────────────────────────────────────────────

    async def get_event_types(self) -> Sequence:
        """The game's event types in display order."""
        return await self._event_type_repo.get_all_ordered()

    async def save_event_type(
        self,
        name: str,
        color_index: int,
        sort_order: int | None = None,
        type_id: int | None = None,
    ):
        """Create (``type_id=None``) or update an event type; committed.

        ``color_index`` must address one of the eight chart tokens (1..8);
        anything else raises ``ValueError``. Without an explicit ``sort_order``
        new types are appended after the current last one.
        """
        if (
            isinstance(color_index, bool)
            or not isinstance(color_index, int)
            or not COLOR_INDEX_MIN <= color_index <= COLOR_INDEX_MAX
        ):
            raise ValueError(
                f"color_index must be an int in "
                f"{COLOR_INDEX_MIN}..{COLOR_INDEX_MAX}, got {color_index!r}"
            )
        # Rollback wrapper (audit Q14 scenario 5, task 5.2): a failed flush or
        # commit used to leave the single shared session dirty, bleeding the
        # garbage into the next operation the lock hands it.
        try:
            if type_id is not None:
                kwargs: dict[str, Any] = {"name": name, "color_index": color_index}
                if sort_order is not None:
                    kwargs["sort_order"] = sort_order
                obj = await self._event_type_repo.update(type_id, **kwargs)
            else:
                if sort_order is None:
                    sort_order = await self._event_type_repo.next_sort_order()
                obj = await self._event_type_repo.create(
                    name=name, color_index=color_index, sort_order=sort_order,
                )
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        return obj

    async def delete_event_type(self, type_id: int) -> bool:
        """Delete a type, first unbinding every event that had it (W4 spec).

        Unbind (``event_type_id = NULL`` through the ORM, so already-loaded
        event objects stay truthful in this session) and the type's DELETE
        run in one transaction; events themselves are never touched beyond
        that column.
        """
        session = self._session
        try:
            events = (await session.execute(
                select(EventModel).where(EventModel.event_type_id == type_id)
            )).scalars().all()
            for event in events:
                # The relationship (not just the FK column) is mutated: the
                # app session never expires instances, so a bulk UPDATE would
                # leave loaded events pointing at a deleted type in memory.
                event.event_type = None
            deleted = await self._event_type_repo.delete(type_id)
            await session.commit()
            return deleted
        except Exception:
            # The failure used to be swallowed here (audit Q14 scenario 7):
            # the user was never told the delete failed. The session is rolled
            # back so it stays usable, but the error now travels to the caller,
            # and the dialog turns it into a user-facing message (task 5.2).
            await session.rollback()
            raise

    # M2M collection attribute names of an event: the entity registry's
    # EVENT relation order (wave 3, finding A4) — the same order every view
    # of an event's related lists uses
    RELATION_ATTRS = [
        ref.attr for ref in entity_registry.related_refs(EntityType.EVENT)
    ]

    @property
    def _session(self):
        # The repository already holds the session (same pattern as the app wiring)
        return self._event_repo.session

    # ── Save-with-relations (ported 1:1 from the main.py closures) ───────

    async def create_event_with_relations(
        self,
        name: str,
        start_date: date,
        end_date: date | None,
        characteristics: str,
        backstory: str,
        relations: dict,
        event_type_id: int | None = None,
        start_bc: bool = False,
        end_bc: bool = False,
    ):
        """Create an event (with description) and sync all four M2M collections.

        Wave 5 (design D4.3): the whole write lives in one unit-of-work
        transaction — commit on clean exit, rollback + re-raise on any failure
        (the old 1:1 closure semantics — swallow the error, return None — went
        away with ``save-error-reporting``: the caller must learn why the save
        failed; an error mid-way never leaves a half-written event).
        The optional ``event_type_id`` (W4) assigns a type at creation
        (None = без типа). ``start_bc``/``end_bc`` (task 3.4) carry the dates'
        eras into the ORM era columns; the model hooks derive the keys.
        """
        async with self._uow.transaction():
            event = await self.create_event(
                name=name,
                characteristics=characteristics,
                backstory=backstory,
                start_date=start_date,
                end_date=end_date,
                event_type_id=event_type_id,
                start_bc=start_bc,
                end_bc=end_bc,
            )
            await self._session.refresh(
                event, attribute_names=self.RELATION_ATTRS + ["event_type"],
            )
            await self.apply_event_relations(
                event,
                relations.get("organizations", []),
                relations.get("characters", []),
                relations.get("items", []),
                relations.get("locations", []),
            )
            return event

    async def update_event_with_relations(
        self,
        event_id: int,
        name: str,
        start_date: date,
        end_date: date | None,
        characteristics: str,
        backstory: str,
        relations: dict,
        event_type_id: Any = TYPE_UNSET,
        start_bc: bool = False,
        end_bc: bool = False,
    ):
        """Update event fields + description and resync all four M2M collections.

        Ported from the on_event_updated closure in main.py: the whole write
        now finishes through one unit-of-work transaction (design D4.3) — a
        missing event raises ``ValueError`` before the refresh, any failure
        rolls back and re-raises, and success commits exactly once (no more
        rollback + silent None). W4: an explicit ``event_type_id``
        (id or None for «без типа») reassigns the type; callers that predate
        the feature leave the sentinel and keep the current one.
        ``start_bc``/``end_bc`` (task 3.4) rewrite the dates' eras; the model
        hooks re-derive the chronological keys.
        """
        async with self._uow.transaction():
            current = await self.get_event(event_id)
            old_name = current.name if current else None
            fields: dict[str, Any] = {
                "name": name, "start_date": start_date, "end_date": end_date,
                "start_bc": start_bc, "end_bc": end_bc,
            }
            if event_type_id is not TYPE_UNSET:
                fields["event_type_id"] = event_type_id
            await self.update_event(event_id, **fields)
            updated_event = await self.get_event(event_id)
            if updated_event is None:
                # Without this check the refresh below would raise a bare
                # AttributeError on None — the caller must see the real reason.
                raise ValueError(f"событие {event_id} не найдено")
            if updated_event.description:
                updated_event.description.characteristics = characteristics
                updated_event.description.backstory = backstory

            # Sync M2M relationships
            await self._session.refresh(
                updated_event,
                attribute_names=self.RELATION_ATTRS + ["event_type"],
            )
            await self.apply_event_relations(
                updated_event,
                relations.get("organizations", []),
                relations.get("characters", []),
                relations.get("items", []),
                relations.get("locations", []),
            )
            if name != old_name:
                await rewrite_mentions(self._session, "event", event_id, name)
            return updated_event

    # ── M2M relation sync (ported 1:1 from the main.py closures) ─────────

    async def apply_event_relations(
        self,
        event: Any,
        org_items: List[dict],
        char_items: List[dict],
        item_items: List[dict],
        loc_items: List[dict],
    ) -> None:
        """        Sync all four event M2M collections with the dialog's item lists.

        Each item dict either carries ``_existing_id`` (link existing) or is
        a create-entity kwargs mapping (create + link — the create_missing
        trajectory of the single synchronizer, C3). Entities from the
        previous state that are not in the list get unlinked.
        """
        await sync_related(
            self._organization_service, event.organizations, org_items,
            create_missing=True,
        )
        await sync_related(
            self._character_service, event.characters, char_items,
            create_missing=True,
        )
        await sync_related(
            self._item_service, event.items, item_items,
            create_missing=True,
        )
        await sync_related(
            self._location_service, event.locations, loc_items,
            create_missing=True,
        )
