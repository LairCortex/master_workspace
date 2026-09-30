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
from unittest.mock import AsyncMock

import pytest

from app.application.services.entity_service import EntityService
from app.application.services.event_service import EventService
from app.domain.time_of_day import TimeOfDay
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
from app.infrastructure.repositories.event_type_repository import EventTypeRepository
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


async def _make_event(
    session, name: str, start_date=D1, end_date=D2, **links
) -> EventModel:
    desc = DescriptionModel(characteristics="ev ch", backstory="ev bs")
    session.add(desc)
    await session.flush()
    ev = EventModel(name=name, start_date=start_date, end_date=end_date, description_id=desc.id, **links)
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
        event_type_repo=EventTypeRepository(session),
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

    async def test_failing_create_rolls_back_and_propagates(self, async_session):
        w = await _world(async_session)
        # Commit the fixture baseline so the operation below has its own
        # transaction to roll back (mirrors app state where prior data is committed).
        await async_session.commit()
        before_chars = len(await w.char_svc.get_all())
        # save-error-reporting: a mid-sync failure is rolled back and the
        # exception propagates (the old silent None was the W5 debt).
        with pytest.raises(Exception):
            await w.event_service.create_event_with_relations(
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
            attribute_names=["name", "end_date_raw", "description", "organizations", "characters"],
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
        # NB: the old characterization "missing event -> silent None" lived
        # here; save-error-reporting replaced it with
        # TestUpdateEventWithRelationsFailurePropagation.
        # test_missing_event_raises_value_error_not_attribute_error.


# ── Desired behavior: services never swallow a save failure ───────────────
#
# ``save-error-reporting`` spec (change ``fix-silent-dialog-save-debt``):
# rollback stays the service's job, but the failure travels outward so the
# wiring can report exactly one modal message. These tests are written
# against that rule (RED phase) — the silent ``return None`` they replace is
# characterized above.

EMPTY_RELATIONS = {
    "organizations": [], "characters": [], "items": [], "locations": [],
}


class TestCreateEventWithRelationsFailurePropagation:
    async def test_commit_failure_raises_after_exactly_one_rollback(
        self, async_session, monkeypatch,
    ):
        w = await _world(async_session)
        await async_session.commit()  # fixture baseline in its own transaction
        commits = AsyncMock(side_effect=RuntimeError("disk is gone"))
        rollbacks = AsyncMock(wraps=async_session.rollback)
        monkeypatch.setattr(async_session, "commit", commits)
        monkeypatch.setattr(async_session, "rollback", rollbacks)

        with pytest.raises(RuntimeError, match="disk is gone"):
            await w.event_service.create_event_with_relations(
                name="Doomed",
                start_date=D1,
                end_date=D2,
                characteristics="c",
                backstory="b",
                relations=dict(EMPTY_RELATIONS),
            )

        assert commits.await_count == 1
        assert rollbacks.await_count == 1
        # The rolled-back transaction left no trace of the failed event.
        events = [e.name for e in await w.event_repo.get_all()]
        assert "Doomed" not in events


class TestUpdateEventWithRelationsFailurePropagation:
    async def test_commit_failure_raises_after_exactly_one_rollback(
        self, async_session, monkeypatch,
    ):
        w = await _world(async_session)
        await async_session.commit()
        commits = AsyncMock(side_effect=RuntimeError("disk is gone"))
        rollbacks = AsyncMock(wraps=async_session.rollback)
        monkeypatch.setattr(async_session, "commit", commits)
        monkeypatch.setattr(async_session, "rollback", rollbacks)

        with pytest.raises(RuntimeError, match="disk is gone"):
            await w.event_service.update_event_with_relations(
                w.event.id,
                name="Doomed Renamed",
                start_date=D1,
                end_date=D2,
                characteristics="c",
                backstory="b",
                relations=dict(EMPTY_RELATIONS),
            )

        assert commits.await_count == 1
        assert rollbacks.await_count == 1
        events = [e.name for e in await w.event_repo.get_all()]
        assert "Brawl" in events and "Doomed Renamed" not in events

    async def test_missing_event_raises_value_error_not_attribute_error(
        self, async_session, monkeypatch,
    ):
        w = await _world(async_session)
        await async_session.commit()
        rollbacks = AsyncMock(wraps=async_session.rollback)
        monkeypatch.setattr(async_session, "rollback", rollbacks)

        # A missing id must fail as an intelligible ValueError *before* the
        # refresh: the AttributeError of ``refresh(None)`` used to be swallowed
        # on the way to a silent None.
        with pytest.raises(ValueError, match="999999") as exc_info:
            await w.event_service.update_event_with_relations(
                999999,
                name="X",
                start_date=D1,
                end_date=None,
                characteristics="c",
                backstory="b",
                relations=dict(EMPTY_RELATIONS),
            )
        assert not isinstance(exc_info.value, AttributeError)
        assert rollbacks.await_count == 1


# ── get_last_event_for_entity (NRI-0022 task 6.1) ──────────────────────────


def _lookup_service(session) -> EventService:
    """A bare-session EventService for the membership lookup: the method only
    reads through the event repository's session, the entity services and the
    type repository play no part in it."""
    return EventService(
        event_repo=EventRepository(session),
        description_repo=BaseRepository(session, DescriptionModel),
        organization_service=AsyncMock(),
        character_service=AsyncMock(),
        item_service=AsyncMock(),
        location_service=AsyncMock(),
        event_type_repo=EventTypeRepository(session),
    )


class TestGetLastEventForEntity:
    """Chronological «last by start» membership lookup (design D7).

    The order runs on the shared era key (BC precedes CE, BC counts down
    toward 1 г. до н.э.), ties of the same start moment resolve to the
    smaller id, and both empty answers (no membership, unknown key) are a
    plain ``None`` — the search full path turns them into «preview only».
    """

    async def test_latest_ad_start_wins(self, async_session):
        char = await _make_char(async_session, "Герой")
        await _make_event(async_session, "Раннее", characters=[char])
        latest = await _make_event(
            async_session, "Позднее",
            start_date=date(1300, 5, 1), end_date=None, characters=[char],
        )
        await _make_event(
            async_session, "Среднее",
            start_date=date(1250, 1, 1), end_date=None, characters=[char],
        )
        found = await _lookup_service(async_session).get_last_event_for_entity(
            "character", char.id
        )
        assert found is not None and found.id == latest.id

    async def test_ce_after_bc_across_the_era_border(self, async_session):
        char = await _make_char(async_session, "Летописец")
        await _make_event(
            async_session, "До нашей эры",
            start_date=date(500, 1, 1), start_bc=True, end_date=None,
            characters=[char],
        )
        ce = await _make_event(
            async_session, "Наша эра",
            start_date=date(100, 1, 1), end_date=None, characters=[char],
        )
        found = await _lookup_service(async_session).get_last_event_for_entity(
            "character", char.id
        )
        assert found is not None and found.id == ce.id

    async def test_bc_only_later_bc_year_wins(self, async_session):
        char = await _make_char(async_session, "Архивариус")
        await _make_event(
            async_session, "500 до н.э.",
            start_date=date(500, 1, 1), start_bc=True, end_date=None,
            characters=[char],
        )
        later_bc = await _make_event(
            async_session, "200 до н.э.",
            start_date=date(200, 6, 1), start_bc=True, end_date=None,
            characters=[char],
        )
        found = await _lookup_service(async_session).get_last_event_for_entity(
            "character", char.id
        )
        assert found is not None and found.id == later_bc.id

    async def test_same_start_moment_tie_goes_to_smaller_id(self, async_session):
        char = await _make_char(async_session, "Свидетель")
        first = await _make_event(
            async_session, "Первый", end_date=None, characters=[char],
        )
        second = await _make_event(
            async_session, "Второй", end_date=None, characters=[char],
        )
        assert first.id < second.id
        found = await _lookup_service(async_session).get_last_event_for_entity(
            "character", char.id
        )
        assert found is not None and found.id == first.id

    async def test_same_calendar_date_across_eras_is_not_a_tie(
        self, async_session,
    ):
        """Same year/month/day in different eras is NOT the same moment: the
        CE row starts later, so the id tie-break never applies here."""
        char = await _make_char(async_session, "Пограничник")
        await _make_event(
            async_session, "Тот же год до н.э.",
            start_date=date(100, 1, 1), start_bc=True, end_date=None,
            characters=[char],
        )
        ce = await _make_event(
            async_session, "Тот же год н.э.",
            start_date=date(100, 1, 1), end_date=None, characters=[char],
        )
        found = await _lookup_service(async_session).get_last_event_for_entity(
            "character", char.id
        )
        assert found is not None and found.id == ce.id

    async def test_entity_without_events_returns_none(self, async_session):
        char = await _make_char(async_session, "Одиночка")
        assert await _lookup_service(async_session).get_last_event_for_entity(
            "character", char.id
        ) is None

    async def test_unknown_type_key_returns_none(self, async_session):
        char = await _make_char(async_session, "Герой")
        await _make_event(
            async_session, "Событие", end_date=None, characters=[char],
        )
        service = _lookup_service(async_session)
        assert await service.get_last_event_for_entity("no-such-type", char.id) is None
        # The event type itself has no event membership either.
        assert await service.get_last_event_for_entity("event", char.id) is None

    async def test_membership_covers_all_four_relation_kinds(
        self, async_session,
    ):
        char = await _make_char(async_session, "Герой")
        org = OrganizationModel(name="Гильдия", start_date=D1)
        item = ItemModel(name="Клинок", start_date=D1)
        loc = LocationModel(name="Таверна", start_date=D1)
        async_session.add_all([org, item, loc])
        await async_session.flush()
        late = await _make_event(
            async_session, "Позднее",
            start_date=date(1300, 1, 1), end_date=None,
            characters=[char], organizations=[org], items=[item], locations=[loc],
        )
        await _make_event(
            async_session, "Раннее",
            characters=[char], organizations=[org], items=[item], locations=[loc],
        )
        service = _lookup_service(async_session)
        for key, obj in (
            ("character", char), ("organization", org),
            ("item", item), ("location", loc),
        ):
            found = await service.get_last_event_for_entity(key, obj.id)
            assert found is not None and found.id == late.id


class TestSessionAliveAfterSaveFailure:
    """Spec «После сбоя сессия остаётся рабочей»: one failed save must not
    poison the shared session for the next, unrelated save."""

    async def test_second_save_succeeds_after_failed_one(
        self, async_session, monkeypatch,
    ):
        w = await _world(async_session)
        await async_session.commit()

        # 1. The save that must fail — and say so (exception outward, rollback).
        commits = AsyncMock(side_effect=RuntimeError("disk is gone"))
        monkeypatch.setattr(async_session, "commit", commits)
        with pytest.raises(RuntimeError, match="disk is gone"):
            await w.event_service.create_event_with_relations(
                name="Doomed",
                start_date=D1,
                end_date=D2,
                characteristics="c",
                backstory="b",
                relations=dict(EMPTY_RELATIONS),
            )
        monkeypatch.delattr(async_session, "commit")
        assert commits.await_count == 1

        # 2. The next save through the same session works untouched.
        ev = await w.event_service.create_event_with_relations(
            name="Aftermath",
            start_date=D1,
            end_date=None,
            characteristics="",
            backstory="",
            relations={},
        )
        assert ev is not None
        assert ev.name == "Aftermath"
        names = [e.name for e in await w.event_repo.get_all()]
        assert "Aftermath" in names
        assert "Doomed" not in names


# ── Parent link guard (NRI-0023 task 3.2, design Д1) ───────────────────────
#
# Exactly two levels is a save-time rule of this service: the parent must
# exist, must itself be parentless and must not be the edited event.  The
# refusal is a Russian ValueError — the wiring's save handler renders any
# exception into the one modal the user reads («Не удалось сохранить
# событие: …»), so the message text is user-facing and pinned here.


class TestEventParentGuard:
    async def _chain(self, session):
        """fair (main) → toast (its sub-event), plus feast — a second main."""
        fair = await _make_event(session, "Fair")
        feast = await _make_event(session, "Feast")
        toast = await _make_event(session, "Toast", parent_id=fair.id)
        return fair, feast, toast

    async def test_create_with_unknown_parent_rejected(self, async_session):
        w = await _world(async_session)
        await async_session.commit()  # fixture baseline in its own transaction
        with pytest.raises(ValueError, match="родительское событие 999999 не найдено"):
            await w.event_service.create_event_with_relations(
                name="Orphan",
                start_date=D1,
                end_date=None,
                characteristics="c",
                backstory="b",
                relations=dict(EMPTY_RELATIONS),
                parent_id=999999,
            )
        # The refusal happened before anything was written and the unit rolled
        # the session back — no half-saved event stays behind.
        names = [e.name for e in await w.event_repo.get_all()]
        assert "Orphan" not in names

    async def test_create_with_subevent_as_parent_rejected(self, async_session):
        # spec «Подсобытие не обрастает детьми»: a child can never be a parent
        w = await _world(async_session)
        fair, _, toast = await self._chain(async_session)
        await async_session.commit()
        with pytest.raises(ValueError, match="не может быть подсобытием"):
            await w.event_service.create_event_with_relations(
                name="Grandchild",
                start_date=D1,
                end_date=None,
                characteristics="c",
                backstory="b",
                relations=dict(EMPTY_RELATIONS),
                parent_id=toast.id,
            )
        names = [e.name for e in await w.event_repo.get_all()]
        assert "Grandchild" not in names
        assert fair.parent_id is None

    async def test_update_to_self_rejected(self, async_session):
        w = await _world(async_session)
        await async_session.commit()
        with pytest.raises(ValueError, match="родителем самого себя"):
            await w.event_service.update_event_with_relations(
                w.event.id,
                name="Brawl",
                start_date=D1,
                end_date=D2,
                characteristics="c",
                backstory="b",
                relations=dict(EMPTY_RELATIONS),
                parent_id=w.event.id,
            )
        await async_session.refresh(w.event, attribute_names=["parent_id"])
        assert w.event.parent_id is None  # the refused save left no trace

    async def test_update_to_unknown_parent_rejected(self, async_session):
        w = await _world(async_session)
        _, _, toast = await self._chain(async_session)
        await async_session.commit()
        with pytest.raises(ValueError, match="родительское событие 999999 не найдено"):
            await w.event_service.update_event_with_relations(
                toast.id,
                name="Toast",
                start_date=D1,
                end_date=D2,
                characteristics="c",
                backstory="b",
                relations=dict(EMPTY_RELATIONS),
                parent_id=999999,
            )
        await async_session.refresh(toast, attribute_names=["parent_id"])
        assert toast.parent_id is not None  # the old link survived

    async def test_update_to_subevent_as_parent_rejected(self, async_session):
        # Making «Fair» a child of its own child «Toast» would open a third
        # level (and a cycle) — rule «без своего родителя» refuses it.
        w = await _world(async_session)
        fair, _, toast = await self._chain(async_session)
        await async_session.commit()
        with pytest.raises(ValueError, match="не может быть подсобытием"):
            await w.event_service.update_event_with_relations(
                fair.id,
                name="Fair",
                start_date=D1,
                end_date=D2,
                characteristics="c",
                backstory="b",
                relations=dict(EMPTY_RELATIONS),
                parent_id=toast.id,
            )
        await async_session.refresh(fair, attribute_names=["parent_id"])
        assert fair.parent_id is None

    async def test_create_with_main_parent_attaches(self, async_session):
        w = await _world(async_session)
        fair, _, _ = await self._chain(async_session)
        child = await w.event_service.create_event_with_relations(
            name="Oath",
            start_date=D1,
            end_date=None,
            characteristics="c",
            backstory="b",
            relations=dict(EMPTY_RELATIONS),
            parent_id=fair.id,
        )
        assert child.parent_id == fair.id
        await async_session.refresh(child, attribute_names=["parent_id"])
        assert child.parent_id == fair.id

    async def test_update_reparents_child(self, async_session):
        # spec «Перецепка»: the child moves to another main event
        w = await _world(async_session)
        _, feast, toast = await self._chain(async_session)
        result = await w.event_service.update_event_with_relations(
            toast.id,
            name="Toast",
            start_date=D1,
            end_date=D2,
            characteristics="c",
            backstory="b",
            relations=dict(EMPTY_RELATIONS),
            parent_id=feast.id,
        )
        await async_session.refresh(result, attribute_names=["parent_id"])
        assert result.parent_id == feast.id

    async def test_update_promotes_to_main(self, async_session):
        # spec «Подъём в основные»: the explicit None detaches the child
        w = await _world(async_session)
        fair, _, toast = await self._chain(async_session)
        result = await w.event_service.update_event_with_relations(
            toast.id,
            name="Toast",
            start_date=D1,
            end_date=D2,
            characteristics="c",
            backstory="b",
            relations=dict(EMPTY_RELATIONS),
            parent_id=None,
        )
        await async_session.refresh(result, attribute_names=["parent_id"])
        assert result.parent_id is None
        await async_session.refresh(fair, attribute_names=["parent_id"])
        assert fair.parent_id is None  # the old parent stays main as well

    async def test_update_without_parent_argument_keeps_the_link(
        self, async_session,
    ):
        # The PARENT_UNSET default (design Д1, same trick as TYPE_UNSET): a
        # caller that predates the sub-event feature must never silently
        # promote a child it is only renaming.
        w = await _world(async_session)
        fair, _, toast = await self._chain(async_session)
        result = await w.event_service.update_event_with_relations(
            toast.id,
            name="Toast Renamed",
            start_date=D1,
            end_date=D2,
            characteristics="c",
            backstory="b",
            relations=dict(EMPTY_RELATIONS),
        )
        await async_session.refresh(result, attribute_names=["name", "parent_id"])
        assert result.name == "Toast Renamed"
        assert result.parent_id == fair.id


# ── Wall-clock start time plumbing (NRI-0023 task 7.2, spec «Необязательное
# время начала события») ─────────────────────────────────────────────────────
#
# The dialog hands the service a TimeOfDay (or None); the model stores the
# minutes from the day start in the ACTIVE calendar's unit, so the service
# tests read the value back through the same property. The sentinel default is
# the PARENT_UNSET precedent: a caller that predates the time field must never
# clear a stored time while merely renaming.


class TestEventStartTime:
    async def test_create_stores_the_time_and_none_stays_none(self, async_session):
        w = await _world(async_session)
        timed = await w.event_service.create_event_with_relations(
            name="Рассвет",
            start_date=D1,
            end_date=None,
            characteristics="c",
            backstory="b",
            relations=dict(EMPTY_RELATIONS),
            start_time=TimeOfDay(9, 30),
        )
        plain = await w.event_service.create_event_with_relations(
            name="Без времени",
            start_date=D1,
            end_date=None,
            characteristics="c",
            backstory="b",
            relations=dict(EMPTY_RELATIONS),
        )
        # The mapped column is start_time_raw (the start_time face is a plain
        # property over it, unrefreshable — the group-1 mapping contract).
        await async_session.refresh(timed, attribute_names=["start_time_raw"])
        await async_session.refresh(plain, attribute_names=["start_time_raw"])
        # spec «Время задано» / «Время не задано — не выдумано»: the value
        # round-trips exactly, and an empty selection is NULL, never 00:00.
        assert timed.start_time == TimeOfDay(9, 30)
        assert timed.start_time_raw == 9 * 60 + 30
        assert plain.start_time is None
        assert plain.start_time_raw is None

    async def test_update_sets_and_clears_the_time(self, async_session):
        w = await _world(async_session)
        await async_session.commit()
        updated = await w.event_service.update_event_with_relations(
            w.event.id,
            name="Brawl",
            start_date=D1,
            end_date=D2,
            characteristics="c",
            backstory="b",
            relations=dict(EMPTY_RELATIONS),
            start_time=TimeOfDay(14, 0),
        )
        await async_session.refresh(updated, attribute_names=["start_time_raw"])
        assert updated.start_time == TimeOfDay(14, 0)
        cleared = await w.event_service.update_event_with_relations(
            w.event.id,
            name="Brawl",
            start_date=D1,
            end_date=D2,
            characteristics="c",
            backstory="b",
            relations=dict(EMPTY_RELATIONS),
            start_time=None,
        )
        await async_session.refresh(cleared, attribute_names=["start_time_raw"])
        assert cleared.start_time is None

    async def test_update_without_time_argument_keeps_the_time(
        self, async_session,
    ):
        # The START_TIME_UNSET default: renaming an event through an
        # old-signature caller must not silently wipe its stored wall clock.
        w = await _world(async_session)
        timed = await _make_event(
            async_session, "Timed", start_time=TimeOfDay(7, 45),
        )
        await async_session.commit()
        result = await w.event_service.update_event_with_relations(
            timed.id,
            name="Timed Renamed",
            start_date=D1,
            end_date=D2,
            characteristics="c",
            backstory="b",
            relations=dict(EMPTY_RELATIONS),
        )
        await async_session.refresh(result, attribute_names=["name", "start_time_raw"])
        assert result.name == "Timed Renamed"
        assert result.start_time == TimeOfDay(7, 45)
