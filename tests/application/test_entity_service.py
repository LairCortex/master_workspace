"""Integration tests for EntityService M2M link-only sync on a real DB.

Characterizes the behavior of the on_entity_saved closure from main.py:
- sync_related: ONLY links existing entities (never creates),
  adds missing, removes extras, skips unknown ids silently.
- update_entity_with_relations: fields + description + relation resync,
  commit on success, rollback + silent None on error.
"""
import types
from datetime import date

import pytest

from app.application.services.entity_service import EntityService
from app.infrastructure.db.models import (
    CharacterModel,
    DescriptionModel,
    ItemModel,
    LocationModel,
    OrganizationModel,
)
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.character_repository import CharacterRepository
from app.infrastructure.repositories.item_repository import ItemRepository
from app.infrastructure.repositories.location_repository import LocationRepository
from app.infrastructure.repositories.organization_repository import OrganizationRepository

D1 = date(1300, 1, 1)


async def _world(async_session):
    """Item entity linked to one org and one location; siblings unlinked."""
    ns = types.SimpleNamespace()
    ns.desc_repo = BaseRepository(async_session, DescriptionModel)
    org_repo = OrganizationRepository(async_session)
    item_repo = ItemRepository(async_session)
    loc_repo = LocationRepository(async_session)
    char_repo = CharacterRepository(async_session)

    ns.org_svc = EntityService(org_repo, ns.desc_repo)
    ns.loc_svc = EntityService(loc_repo, ns.desc_repo)
    ns.char_svc = EntityService(char_repo, ns.desc_repo)
    ns.item_svc = EntityService(
        item_repo,
        ns.desc_repo,
        related_services={
            "organization": ns.org_svc,
            "location": ns.loc_svc,
            "character": ns.char_svc,
        },
    )

    desc = DescriptionModel(characteristics="ch", backstory="bs")
    async_session.add(desc)
    await async_session.flush()

    ns.guild = OrganizationModel(name="Guild", start_date=D1)
    ns.mercs = OrganizationModel(name="Mercs", start_date=D1)
    ns.tavern = LocationModel(name="Tavern", start_date=D1)
    ns.dock = LocationModel(name="Dock", start_date=D1)
    for o in (ns.guild, ns.mercs, ns.tavern, ns.dock):
        async_session.add(o)
    await async_session.flush()

    # Initial state: item linked to Guild + Tavern, not to Mercs/Dock
    ns.item = ItemModel(
        name="Sword",
        start_date=D1,
        description_id=desc.id,
        rating=3,
        organizations=[ns.guild],
        locations=[ns.tavern],
    )
    async_session.add(ns.item)
    await async_session.flush()
    await async_session.refresh(
        ns.item, attribute_names=["organizations", "locations"],
    )
    return ns


class TestSyncRelated:
    async def test_add_missing_and_remove_extras(self, async_session):
        w = await _world(async_session)
        # Desired: keep Tavern, add Dock, drop nothing
        await w.item_svc.sync_related(w.item, "locations", {w.tavern.id, w.dock.id})
        await async_session.refresh(w.item, attribute_names=["locations"])
        assert sorted(l.name for l in w.item.locations) == ["Dock", "Tavern"]

    async def test_only_link_never_creates(self, async_session):
        w = await _world(async_session)
        orgs_before = len(await w.org_svc.get_all())
        # 4242 does not exist — must be skipped silently, nothing created
        await w.item_svc.sync_related(
            w.item, "organizations", {w.mercs.id, 4242},
        )
        await async_session.refresh(w.item, attribute_names=["organizations"])
        assert [o.name for o in w.item.organizations] == ["Mercs"]  # Guild unlinked
        assert len(await w.org_svc.get_all()) == orgs_before

    async def test_unknown_attr_is_noop(self, async_session):
        w = await _world(async_session)
        await w.item_svc.sync_related(w.item, "nonsense", {1, 2, 3})
        await async_session.refresh(w.item, attribute_names=["organizations", "locations"])
        assert [o.name for o in w.item.organizations] == ["Guild"]
        assert [l.name for l in w.item.locations] == ["Tavern"]

    async def test_missing_sibling_service_is_noop(self, async_session):
        w = await _world(async_session)
        bare_svc = EntityService(ItemRepository(async_session), w.desc_repo)
        await bare_svc.sync_related(w.item, "organizations", {w.mercs.id})
        await async_session.refresh(w.item, attribute_names=["organizations"])
        assert [o.name for o in w.item.organizations] == ["Guild"]  # unchanged


class TestUpdateEntityWithRelations:
    async def test_update_fields_description_and_relations(self, async_session):
        w = await _world(async_session)
        result = await w.item_svc.update_entity_with_relations(
            w.item.id,
            field_data={"rating": 9, "music_url": "http://m/9"},
            characteristics="New ch",
            backstory="New bs",
            related_changes={
                "organizations": {"current_ids": [w.mercs.id]},  # swap Guild → Mercs
                "locations": {"current_ids": []},                 # unlink Tavern
            },
        )
        assert result is not None
        await async_session.refresh(
            result,
            attribute_names=["name", "rating", "music_url", "description", "organizations", "locations"],
        )
        assert result.rating == 9
        assert result.music_url == "http://m/9"
        assert result.description.characteristics == "New ch"
        assert result.description.backstory == "New bs"
        assert [o.name for o in result.organizations] == ["Mercs"]
        assert result.locations == []

    async def test_update_null_description_is_tolerated(self, async_session):
        w = await _world(async_session)
        bare = ItemModel(name="Bare", start_date=D1)
        async_session.add(bare)
        await async_session.flush()
        await async_session.refresh(
            bare, attribute_names=["organizations", "locations"],
        )
        result = await w.item_svc.update_entity_with_relations(
            bare.id,
            field_data={"rating": 2},
            characteristics="Ch",
            backstory="Bs",
            related_changes={"organizations": {"current_ids": [w.guild.id]}},
        )
        assert result is not None
        await async_session.refresh(result, attribute_names=["rating", "description", "organizations"])
        assert result.description is None
        assert result.rating == 2
        assert [o.name for o in result.organizations] == ["Guild"]

    async def test_error_is_rolled_back_silently(self, async_session, mocker):
        w = await _world(async_session)
        await async_session.commit()  # fixture baseline in its own transaction
        # update_entity raising must end in rollback + silent None (characterized
        # 1:1 with the old closure's `except Exception: rollback` — no re-raise)
        mocker.patch.object(
            w.item_svc, "update_entity", side_effect=RuntimeError("db gone"),
        )
        result = await w.item_svc.update_entity_with_relations(
            w.item.id,
            field_data={"rating": 7},
            characteristics="c",
            backstory="b",
            related_changes={"organizations": {"current_ids": []}},
        )
        assert result is None
        # Prior committed state is intact
        from sqlalchemy import select

        row = (await async_session.execute(select(ItemModel).where(ItemModel.id == w.item.id))).scalars().first()
        assert row is not None
        assert row.rating == 3
