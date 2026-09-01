"""Unit tests for event types: EventTypeRepository + EventService (W4, tasks 2.3/2.4).

Covers CRUD and ordering, `color_index` 1..8 validation, delete-unlinks-events
in one transaction, per-game isolation, and that selecting N events loads
their `event_type` without N+1 (constant number of queries).
"""
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy import select

from app.application.services.entity_service import EntityService
from app.application.services.event_service import EventService
from app.infrastructure.db.database import create_engine
from app.infrastructure.db.models import DescriptionModel, EventModel, EventTypeModel
from app.infrastructure.db.migrations import init_db
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.character_repository import CharacterRepository
from app.infrastructure.repositories.event_repository import EventRepository
from app.infrastructure.repositories.event_type_repository import EventTypeRepository
from app.infrastructure.repositories.item_repository import ItemRepository
from app.infrastructure.repositories.location_repository import LocationRepository
from app.infrastructure.repositories.organization_repository import OrganizationRepository

D1 = date(1200, 1, 1)
D2 = date(1200, 12, 31)


async def _make_service(session) -> EventService:
    desc_repo = BaseRepository(session, DescriptionModel)
    return EventService(
        event_repo=EventRepository(session),
        description_repo=desc_repo,
        organization_service=EntityService(OrganizationRepository(session), desc_repo),
        character_service=EntityService(CharacterRepository(session), desc_repo),
        item_service=EntityService(ItemRepository(session), desc_repo),
        location_service=EntityService(LocationRepository(session), desc_repo),
    )


async def _make_event(session, name: str, event_type_id: int | None = None) -> EventModel:
    desc = DescriptionModel(characteristics="ev ch", backstory="ev bs")
    session.add(desc)
    await session.flush()
    ev = EventModel(
        name=name, start_date=D1, end_date=D2,
        description_id=desc.id, event_type_id=event_type_id,
    )
    session.add(ev)
    await session.flush()
    return ev


# ── EventTypeRepository: CRUD + order ──────────────────────────────────────

class TestEventTypeRepository:
    async def test_crud_round_trip(self, async_session):
        repo = EventTypeRepository(async_session)
        created = await repo.create(name="Сюжет", color_index=1, sort_order=0)
        assert created.id is not None

        fetched = await repo.get_by_id(created.id)
        assert fetched.name == "Сюжет" and fetched.color_index == 1

        await repo.update(created.id, name="Главный сюжет", color_index=4)
        assert fetched.name == "Главный сюжет" and fetched.color_index == 4

        assert await repo.delete(created.id) is True
        assert await repo.get_by_id(created.id) is None
        assert await repo.delete(created.id) is False

    async def test_get_all_ordered_by_sort_order(self, async_session):
        repo = EventTypeRepository(async_session)
        await repo.create(name="Третья", color_index=3, sort_order=5)
        await repo.create(name="Первая", color_index=1, sort_order=0)
        await repo.create(name="Вторая", color_index=2, sort_order=3)
        names = [t.name for t in await repo.get_all_ordered()]
        assert names == ["Первая", "Вторая", "Третья"]

    async def test_next_sort_order_appends(self, async_session):
        repo = EventTypeRepository(async_session)
        assert await repo.next_sort_order() == 0
        await repo.create(name="X", color_index=1, sort_order=7)
        assert await repo.next_sort_order() == 8


# ── EventService: get/save/delete types ────────────────────────────────────

class TestEventServiceEventTypes:
    async def test_get_event_types_empty_then_seeded(self, async_session):
        svc = await _make_service(async_session)
        assert list(await svc.get_event_types()) == []
        await svc.save_event_type(name="Слух", color_index=3)
        types = list(await svc.get_event_types())
        assert [t.name for t in types] == ["Слух"]
        assert types[0].color_index == 3

    async def test_save_creates_updates_and_orders(self, async_session):
        svc = await _make_service(async_session)
        first = await svc.save_event_type(name="Побочное", color_index=2)
        second = await svc.save_event_type(name="Встреча", color_index=4)
        # Appended after the current last one
        assert [t.name for t in await svc.get_event_types()] == ["Побочное", "Встреча"]

        updated = await svc.save_event_type(
            name="Переименованное", color_index=5, type_id=first.id,
        )
        assert updated.id == first.id and updated.name == "Переименованное"
        # Explicit sort_order moves it to the front
        await svc.save_event_type(
            name="Переименованное", color_index=5, sort_order=-1, type_id=first.id,
        )
        assert [t.name for t in await svc.get_event_types()] == [
            "Переименованное", "Встреча",
        ]

    async def test_save_unknown_type_returns_none(self, async_session):
        svc = await _make_service(async_session)
        assert await svc.save_event_type(name="X", color_index=1, type_id=999999) is None

    @pytest.mark.parametrize("bad_index", [0, 9, -1, 3.5, "3", None, True])
    async def test_save_rejects_color_index_outside_1_8(self, async_session, bad_index):
        svc = await _make_service(async_session)
        with pytest.raises(ValueError, match="color_index"):
            await svc.save_event_type(name="Bad", color_index=bad_index)
        assert list(await svc.get_event_types()) == []

    async def test_save_accepts_palette_boundaries(self, async_session):
        svc = await _make_service(async_session)
        lo = await svc.save_event_type(name="Low", color_index=1)
        hi = await svc.save_event_type(name="High", color_index=8)
        assert (lo.color_index, hi.color_index) == (1, 8)

    async def test_delete_unlinks_events_events_stay_intact(self, async_session):
        svc = await _make_service(async_session)
        occupied = await svc.save_event_type(name="Слух", color_index=3)
        other = await svc.save_event_type(name="Находка", color_index=6)

        events = [await _make_event(async_session, f"Rumor {i}", occupied.id) for i in range(3)]
        kept = await _make_event(async_session, "Treasure", other.id)
        plain = await _make_event(async_session, "Nameless")
        await async_session.commit()

        assert await svc.delete_event_type(occupied.id) is True

        types = list(await svc.get_event_types())
        assert [t.name for t in types] == ["Находка"]  # other type untouched

        # All events survive, unlinked ones are validly type-less
        ids = {e.id for e in events} | {kept.id, plain.id}
        rows = (await async_session.execute(
            select(EventModel.id, EventModel.event_type_id).where(EventModel.id.in_(ids))
        )).all()
        by_id = dict(rows)
        assert set(by_id) == ids
        for e in events:
            assert by_id[e.id] is None
        assert by_id[kept.id] == other.id  # other assignment preserved
        assert by_id[plain.id] is None
        # Reloading through the repository resolves the relationship to None
        refetched = await svc.get_event(events[0].id)
        assert refetched.event_type is None

    async def test_delete_missing_type_returns_false(self, async_session):
        svc = await _make_service(async_session)
        assert await svc.delete_event_type(999999) is False


class TestEventTypesNotSharedBetweenGames:
    async def test_edit_one_game_leaves_another_untouched(self):
        e1 = create_engine("sqlite+aiosqlite:///:memory:")
        e2 = create_engine("sqlite+aiosqlite:///:memory:")
        try:
            await init_db(e1)
            await init_db(e2)

            from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
            f1 = async_sessionmaker(e1, class_=AsyncSession, expire_on_commit=False)
            f2 = async_sessionmaker(e2, class_=AsyncSession, expire_on_commit=False)
            async with f1() as s1, f2() as s2:
                repo1 = EventTypeRepository(s1)
                first = (await repo1.get_all_ordered())[0]
                first.name = "Мой сюжет"
                await repo1.create(name="Кастомный", color_index=7, sort_order=9)
                await s1.commit()

                names2 = [t.name for t in await EventTypeRepository(s2).get_all_ordered()]
                assert names2[:1] == ["Сюжет"]  # not renamed, not extended
                assert len(names2) == 6
        finally:
            await e1.dispose()
            await e2.dispose()


# ── Event → event_type mapping without N+1 (task 2.4) ──────────────────────

class TestEventTypeLoadingWithoutNPlus1:
    async def test_get_all_events_loads_type_in_constant_queries(
        self, async_engine, async_session
    ):
        svc = await _make_service(async_session)
        rumor = await svc.save_event_type(name="Слух", color_index=3)
        for i in range(10):
            await _make_event(async_session, f"Event {i}", rumor.id)
        await _make_event(async_session, "Nameless")  # the NULL-type row
        await async_session.commit()

        statements: list[str] = []

        def _capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        sa_event.listen(async_engine.sync_engine, "before_cursor_execute", _capture)
        try:
            events = list(await svc.get_all_events())
        finally:
            sa_event.remove(async_engine.sync_engine, "before_cursor_execute", _capture)

        assert len(events) == 11
        for e in events:
            if e.name.startswith("Event "):
                assert e.event_type is not None
                assert e.event_type.name == "Слух"
            else:
                assert e.event_type is None

        type_queries = [s for s in statements if "FROM event_types" in s]
        # N+1 would mean one event_types SELECT per event: exactly one batched
        # selectin (id IN (...)) is issued for the whole page, for any N.
        assert len(type_queries) == 1
        assert " IN (" in type_queries[0]
