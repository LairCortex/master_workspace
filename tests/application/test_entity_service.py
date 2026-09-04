"""Integration tests for EntityService M2M link-only sync on a real DB.

Characterizes the behavior of the on_entity_saved closure from main.py:
- sync_related: ONLY links existing entities (never creates),
  adds missing, removes extras, skips unknown ids silently.
- update_entity_with_relations: fields + description + relation resync,
  commit on success, rollback + silent None on error.
"""
import types
from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.application.services.entity_service import EntityService
from app.infrastructure.db.models import (
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
        assert sorted(loc.name for loc in w.item.locations) == ["Dock", "Tavern"]

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
        assert [loc.name for loc in w.item.locations] == ["Tavern"]

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

    async def test_error_propagates_after_rollback(self, async_session, mocker):
        w = await _world(async_session)
        await async_session.commit()  # fixture baseline in its own transaction
        # save-error-reporting: a failing update is rolled back and the
        # exception propagates (the old silent None was the W5 debt;
        # TestUpdateEntityWithRelationsFailurePropagation covers the commit leg)
        mocker.patch.object(
            w.item_svc, "update_entity", side_effect=RuntimeError("db gone"),
        )
        with pytest.raises(RuntimeError, match="db gone"):
            await w.item_svc.update_entity_with_relations(
                w.item.id,
                field_data={"rating": 7},
                characteristics="c",
                backstory="b",
                related_changes={"organizations": {"current_ids": []}},
            )
        # Prior committed state is intact
        from sqlalchemy import select

        row = (await async_session.execute(select(ItemModel).where(ItemModel.id == w.item.id))).scalars().first()
        assert row is not None
        assert row.rating == 3


# ── Desired behavior: the service never swallows a save failure ───────────
#
# ``save-error-reporting`` spec (change ``fix-silent-dialog-save-debt``),
# the same triple of expectations as the EventService RED tests: a failing
# commit re-raises after exactly one rollback, and a missing id fails as an
# intelligible ValueError instead of the swallowed AttributeError of
# ``refresh(None)`` / a silent None.


class TestUpdateEntityWithRelationsFailurePropagation:
    async def test_commit_failure_raises_after_exactly_one_rollback(
        self, async_session, monkeypatch,
    ):
        w = await _world(async_session)
        await async_session.commit()  # fixture baseline in its own transaction
        # Rollback expiry invalidates the flushed instance (async attribute
        # access after it would hit a missing greenlet), so grab the id now.
        item_id = w.item.id
        commits = AsyncMock(side_effect=RuntimeError("disk is gone"))
        rollbacks = AsyncMock(wraps=async_session.rollback)
        monkeypatch.setattr(async_session, "commit", commits)
        monkeypatch.setattr(async_session, "rollback", rollbacks)

        with pytest.raises(RuntimeError, match="disk is gone"):
            await w.item_svc.update_entity_with_relations(
                item_id,
                field_data={"rating": 7},
                characteristics="c",
                backstory="b",
                related_changes={"organizations": {"current_ids": []}},
            )

        assert commits.await_count == 1
        assert rollbacks.await_count == 1
        # The rolled-back transaction left the committed rating intact.
        refreshed = await w.item_svc.get_entity(item_id)
        assert refreshed.rating == 3

    async def test_missing_entity_raises_value_error_not_attribute_error(
        self, async_session, monkeypatch,
    ):
        w = await _world(async_session)
        await async_session.commit()

        # A missing id must fail as an intelligible ValueError *before* the
        # relation-sync refresh: the AttributeError of ``refresh(None)`` used
        # to be swallowed on the way to a silent None.
        with pytest.raises(ValueError, match="999999") as exc_info:
            await w.item_svc.update_entity_with_relations(
                999999,
                field_data={"rating": 7},
                characteristics="c",
                backstory="b",
                related_changes={"organizations": {"current_ids": []}},
            )
        assert not isinstance(exc_info.value, AttributeError)
