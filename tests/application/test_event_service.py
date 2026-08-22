"""Integration tests for EventService.apply_event_relations on a real DB.

Characterizes the M2M sync behavior that used to live in the
`_process_entity_items` closure in main.py:
- item with `_existing_id` -> link existing entity (no duplicate append)
- item without it -> create via EntityService and link
- previously linked entities not in the list -> unlinked
- unknown existing id -> silently skipped
"""
import types
from datetime import date

from app.application.services.entity_service import EntityService
from app.application.services.event_service import EventService
from app.infrastructure.db.models import (
    CharacterModel,
    DescriptionModel,
    EventModel,
    ItemModel,
    LocationModel,
    OrganizationModel,
)
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.character_repository import CharacterRepository
from app.infrastructure.repositories.event_repository import EventRepository
from app.infrastructure.repositories.item_repository import ItemRepository
from app.infrastructure.repositories.location_repository import LocationRepository
from app.infrastructure.repositories.organization_repository import OrganizationRepository

D1 = date(1200, 1, 1)
D2 = date(1200, 12, 31)


async def _make_char(session, name: str) -> CharacterModel:
    desc = DescriptionModel(characteristics=f"{name} ch", backstory=f"{name} bs")
    session.add(desc)
    await session.flush()
    obj = CharacterModel(
        name=name, start_date=D1, end_date=D2, description_id=desc.id,
    )
    session.add(obj)
    await session.flush()
    return obj


async def _make_event(session, name: str, **links) -> EventModel:
    desc = DescriptionModel(characteristics="ev ch", backstory="ev bs")
    session.add(desc)
    await session.flush()
    ev = EventModel(name=name, start_date=D1, end_date=D2, description_id=desc.id, **links)
    session.add(ev)
    await session.flush()
    return ev


async def _world(session):
    """Build the service catalog + fixture data; returns a simple namespace."""
    ns = types.SimpleNamespace()
    ns.desc_repo = BaseRepository(session, DescriptionModel)
    ns.event_repo = EventRepository(session)
    ns.org_svc = EntityService(OrganizationRepository(session), ns.desc_repo)
    ns.char_svc = EntityService(CharacterRepository(session), ns.desc_repo)
    ns.item_svc = EntityService(ItemRepository(session), ns.desc_repo)
    ns.loc_svc = EntityService(LocationRepository(session), ns.desc_repo)
    ns.event_service = EventService(
        event_repo=ns.event_repo,
        description_repo=ns.desc_repo,
        organization_service=ns.org_svc,
        character_service=ns.char_svc,
        item_service=ns.item_svc,
        location_service=ns.loc_svc,
    )
    # Event preloaded with three linked characters
    ns.c1, ns.c2, ns.c3 = (
        await _make_char(session, "Old One"),
        await _make_char(session, "Old Two"),
        await _make_char(session, "Old Three"),
    )
    ns.event = await _make_event(session, "Brawl", characters=[ns.c1, ns.c2, ns.c3])
    # An unlinked character that must never appear on its own
    ns.free = await _make_char(session, "Free")
    ns.org = OrganizationModel(name="Guild", start_date=D1)
    session.add(ns.org)
    ns.item = ItemModel(name="Sword", start_date=D1)
    session.add(ns.item)
    ns.loc = LocationModel(name="Tavern", start_date=D1)
    session.add(ns.loc)
    await session.flush()
    # Mirror the app contract: on_saved refreshes the event's M2M collections
    # before relation sync (selectin is not loaded for add+flush-ed objects).
    await session.refresh(
        ns.event,
        attribute_names=["organizations", "characters", "items", "locations"],
    )
    return ns


def _new_char_item(name: str) -> dict:
    return {
        "name": name,
        "characteristics": f"{name} ch",
        "backstory": f"{name} bs",
        "start_date": D1,
        "end_date": D2,
    }


class TestApplyEventRelations:
    async def test_create_new_and_link(self, async_session):
        w = await _world(async_session)
        await w.event_service.apply_event_relations(
            w.event, [], [_new_char_item("Fresh")], [], [],
        )
        await async_session.refresh(w.event, attribute_names=["characters"])
        names = sorted(c.name for c in w.event.characters)
        # Full-sync semantics: only listed entities stay — all old ones unlinked
        assert names == ["Fresh"]
        fresh = [c for c in w.event.characters if c.name == "Fresh"][0]
        assert fresh.id not in (w.c1.id, w.c2.id, w.c3.id, w.free.id)
        # Created row has its own description
        await async_session.refresh(fresh, attribute_names=["description"])
        assert fresh.description is not None
        assert fresh.description.characteristics == "Fresh ch"

    async def test_mixed_existing_and_new(self, async_session):
        w = await _world(async_session)
        await w.event_service.apply_event_relations(
            w.event,
            [],
            [
                {"_existing_id": w.c1.id},
                _new_char_item("Fresh"),
            ],
            [],
            [],
        )
        await async_session.refresh(w.event, attribute_names=["characters"])
        names = sorted(c.name for c in w.event.characters)
        assert names == ["Fresh", "Old One"]

    async def test_only_existing_no_duplicates_no_create(self, async_session):
        w = await _world(async_session)
        before = len(await w.char_svc.get_all())
        await w.event_service.apply_event_relations(
            w.event, [], [{"_existing_id": w.c2.id}], [], [],
        )
        await async_session.refresh(w.event, attribute_names=["organizations", "characters"])
        # c2 was already linked — no duplicate; c1/c3 unlinked
        assert [c.name for c in w.event.characters] == ["Old Two"]
        assert len(await w.char_svc.get_all()) == before  # nothing created
        # Empty org list unlinks nothing (none were linked) and creates nothing
        assert w.event.organizations == []

    async def test_empty_lists_unlink_all(self, async_session):
        w = await _world(async_session)
        await w.event_service.apply_event_relations(w.event, [], [], [], [])
        await async_session.refresh(w.event, attribute_names=["characters"])
        assert w.event.characters == []

    async def test_unknown_existing_id_is_skipped(self, async_session):
        w = await _world(async_session)
        await w.event_service.apply_event_relations(
            w.event, [], [{"_existing_id": 999999}], [], [],
        )
        await async_session.refresh(w.event, attribute_names=["characters"])
        # Unknown id not linked; everything else unlinked
        assert w.event.characters == []

    async def test_all_four_relations_synced_independently(self, async_session):
        w = await _world(async_session)
        # Link one org to the event beforehand
        w.event.organizations.append(w.org)
        await async_session.flush()
        await w.event_service.apply_event_relations(
            w.event,
            [{"_existing_id": w.org.id}],   # keep org
            [_new_char_item("Hero")],        # new character
            [{"name": "Dagger", "characteristics": "", "backstory": "",
              "start_date": D1, "end_date": D2}],  # new item
            [{"_existing_id": w.loc.id}],    # link location
        )
        await async_session.refresh(
            w.event,
            attribute_names=["organizations", "characters", "items", "locations"],
        )
        assert [o.name for o in w.event.organizations] == ["Guild"]
        assert [c.name for c in w.event.characters] == ["Hero"]
        assert [i.name for i in w.event.items] == ["Dagger"]
        assert [loc.name for loc in w.event.locations] == ["Tavern"]

    async def test_unlinked_entity_stays_unlinked(self, async_session):
        w = await _world(async_session)
        await w.event_service.apply_event_relations(
            w.event,
            [],
            [
                {"_existing_id": w.c1.id},
                {"_existing_id": w.c2.id},
                {"_existing_id": w.c3.id},
                {"_existing_id": w.free.id},  # previously unlinked — now linked
            ],
            [],
            [],
        )
        await async_session.refresh(w.event, attribute_names=["characters"])
        names = sorted(c.name for c in w.event.characters)
        assert names == ["Free", "Old One", "Old Three", "Old Two"]


# ── create_event_with_relations / update_event_with_relations ─────────────


class TestCreateEventWithRelations:
    async def test_create_with_new_and_existing_relations(self, async_session):
        w = await _world(async_session)
        ev = await w.event_service.create_event_with_relations(
            name="Council",
            start_date=D1,
            end_date=D2,
            characteristics="Ch text",
            backstory="BS text",
            relations={
                "organizations": [{"_existing_id": w.org.id}],
                "characters": [_new_char_item("Hero")],
                "items": [],
                "locations": [],
            },
        )
        assert ev is not None
        assert ev.name == "Council"
        await async_session.refresh(
            ev, attribute_names=["description", "organizations", "characters"],
        )
        assert ev.description.characteristics == "Ch text"
        assert ev.description.backstory == "BS text"
        assert [o.name for o in ev.organizations] == ["Guild"]
        assert [c.name for c in ev.characters] == ["Hero"]

    async def test_create_with_empty_relations(self, async_session):
        w = await _world(async_session)
        ev = await w.event_service.create_event_with_relations(
            name="Quiet",
            start_date=D1,
            end_date=None,
            characteristics="",
            backstory="",
            relations={},
        )
        assert ev is not None
        assert ev.end_date is None
        await async_session.refresh(
            ev,
            attribute_names=["organizations", "characters", "items", "locations"],
        )
        assert ev.organizations == []
        assert ev.characters == []
        assert ev.items == []
        assert ev.locations == []

    async def test_failing_create_is_rolled_back_silently(self, async_session):
        w = await _world(async_session)
        # Commit the fixture baseline so the operation below has its own
        # transaction to roll back (mirrors app state where prior data is committed).
        await async_session.commit()
        before_chars = len(await w.char_svc.get_all())
        ev = await w.event_service.create_event_with_relations(
            name="Doomed",
            start_date=D1,
            end_date=D2,
            characteristics="",
            backstory="",
            relations={
                "organizations": [],
                "characters": [_new_char_item("Ghost")],
                # Incomplete item dict -> create_entity raises mid-sync
                "items": [{"name": "Bad"}],
                "locations": [],
            },
        )
        # 1:1 behavior: error swallowed, session rolled back, None returned
        assert ev is None
        events = list(await w.event_repo.get_all())
        assert all(e.name != "Doomed" for e in events)
        # The partially-created character is gone too (single transaction)
        assert len(await w.char_svc.get_all()) == before_chars


class TestUpdateEventWithRelations:
    async def test_update_fields_description_and_relations(self, async_session):
        w = await _world(async_session)
        result = await w.event_service.update_event_with_relations(
            w.event.id,
            name="Brawl Redux",
            start_date=D1,
            end_date=None,
            characteristics="New ch",
            backstory="New bs",
            relations={
                "organizations": [{"_existing_id": w.org.id}],
                "characters": [
                    {"_existing_id": w.c1.id},
                    _new_char_item("Renegade"),
                ],
                "items": [],
                "locations": [],
            },
        )
        assert result is not None
        await async_session.refresh(
            result,
            attribute_names=["name", "end_date", "description", "organizations", "characters"],
        )
        assert result.name == "Brawl Redux"
        assert result.end_date is None
        assert result.description.characteristics == "New ch"
        assert result.description.backstory == "New bs"
        assert [o.name for o in result.organizations] == ["Guild"]
        # Old Two / Old Three unlinked (not in the desired list)
        assert sorted(c.name for c in result.characters) == ["Old One", "Renegade"]

    async def test_update_null_description_is_tolerated(self, async_session):
        w = await _world(async_session)
        bare = EventModel(name="Bare", start_date=D1, end_date=D2)
        async_session.add(bare)
        await async_session.flush()
        await async_session.refresh(
            bare, attribute_names=["organizations", "characters", "items", "locations"],
        )
        result = await w.event_service.update_event_with_relations(
            bare.id,
            name="Bare 2",
            start_date=D1,
            end_date=None,
            characteristics="Ch",
            backstory="Bs",
            relations={"organizations": [], "characters": [], "items": [], "locations": []},
        )
        # description is None — must not raise, name still updated
        assert result is not None
        await async_session.refresh(result, attribute_names=["name", "description"])
        assert result.name == "Bare 2"
        assert result.description is None

    async def test_update_missing_event_returns_none(self, async_session):
        w = await _world(async_session)
        result = await w.event_service.update_event_with_relations(
            999999,
            name="X",
            start_date=D1,
            end_date=None,
            characteristics="c",
            backstory="b",
            relations={"organizations": [], "characters": [], "items": [], "locations": []},
        )
        # Current behavior: refresh(None) raises inside the service,
        # rollback + silent None (characterized 1:1, not "fixed").
        assert result is None
