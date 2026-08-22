"""Integration tests — full stack with in-memory SQLite."""
from datetime import date

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.infrastructure.db.models import Base, DescriptionModel
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.event_repository import EventRepository
from app.infrastructure.repositories.organization_repository import OrganizationRepository
from app.infrastructure.repositories.character_repository import CharacterRepository
from app.infrastructure.repositories.item_repository import ItemRepository
from app.infrastructure.repositories.location_repository import LocationRepository

from app.application.services.event_service import EventService
from app.application.services.search_service import SearchService
from app.application.services.entity_service import EntityService


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


class TestFullEventFlow:
    """End-to-end: create event via service, verify in DB, search."""

    @pytest.mark.asyncio
    async def test_create_and_retrieve_event(self, session):
        desc_repo = BaseRepository(session, DescriptionModel)
        event_repo = EventRepository(session)
        svc = EventService(
            event_repo=event_repo,
            description_repo=desc_repo,
            organization_service=AsyncMock(),
            character_service=AsyncMock(),
            item_service=AsyncMock(),
            location_service=AsyncMock(),
        )

        event = await svc.create_event(
            name="Battle of Plains",
            characteristics="Massive battle",
            backstory="Two kingdoms clash",
            start_date=date(1200, 1, 1),
            end_date=date(1200, 12, 31),
        )
        await session.commit()

        result = await svc.get_event(event.id)
        assert result is not None
        assert result.name == "Battle of Plains"
        assert result.description_id is not None

    @pytest.mark.asyncio
    async def test_create_event_and_search(self, session):
        desc_repo = BaseRepository(session, DescriptionModel)
        event_repo = EventRepository(session)
        org_repo = OrganizationRepository(session)
        char_repo = CharacterRepository(session)
        item_repo = ItemRepository(session)
        loc_repo = LocationRepository(session)

        event_svc = EventService(
            event_repo=event_repo,
            description_repo=desc_repo,
            organization_service=AsyncMock(),
            character_service=AsyncMock(),
            item_service=AsyncMock(),
            location_service=AsyncMock(),
        )
        search_svc = SearchService(
            event=event_repo,
            organization=org_repo,
            character=char_repo,
            item=item_repo,
            location=loc_repo,
        )

        await event_svc.create_event(
            name="Siege of Castle",
            characteristics="Long siege",
            backstory="The fortress fell",
            start_date=date(1201, 3, 1),
            end_date=date(1201, 9, 30),
        )
        await session.commit()

        results = await search_svc.search_all("Siege")
        assert len(results["events"]) == 1
        assert results["events"][0].name == "Siege of Castle"

    @pytest.mark.asyncio
    async def test_create_multiple_entities_and_search_all(self, session):
        desc_repo = BaseRepository(session, DescriptionModel)
        event_repo = EventRepository(session)
        org_repo = OrganizationRepository(session)
        char_repo = CharacterRepository(session)
        item_repo = ItemRepository(session)
        loc_repo = LocationRepository(session)

        event_svc = EventService(
            event_repo=event_repo,
            description_repo=desc_repo,
            organization_service=AsyncMock(),
            character_service=AsyncMock(),
            item_service=AsyncMock(),
            location_service=AsyncMock(),
        )
        org_svc = EntityService(repo=org_repo, description_repo=desc_repo)
        char_svc = EntityService(repo=char_repo, description_repo=desc_repo)

        await event_svc.create_event(
            name="War of the Ring",
            characteristics="Epic",
            backstory="The ring must be destroyed",
            start_date=date(3018, 9, 22),
            end_date=date(3019, 3, 25),
        )
        await org_svc.create_entity(
            name="Fellowship of the Ring",
            characteristics="United group",
            backstory="Formed in Rivendell",
            start_date=date(3018, 10, 25),
            end_date=date(3019, 2, 26),
        )
        await char_svc.create_entity(
            name="Gandalf the Grey",
            characteristics="Wizard",
            backstory="Maiar spirit",
            start_date=date(1, 1, 1),
            end_date=date(9999, 12, 31),
        )
        await session.commit()

        search_svc = SearchService(
            event=event_repo,
            organization=org_repo,
            character=char_repo,
            item=item_repo,
            location=loc_repo,
        )
        results = await search_svc.search_all("Ring")
        assert len(results["events"]) == 1
        assert len(results["organizations"]) == 1
        assert len(results["characters"]) == 0

    @pytest.mark.asyncio
    async def test_timeline_ordering(self, session):
        desc_repo = BaseRepository(session, DescriptionModel)
        event_repo = EventRepository(session)
        svc = EventService(
            event_repo=event_repo,
            description_repo=desc_repo,
            organization_service=AsyncMock(),
            character_service=AsyncMock(),
            item_service=AsyncMock(),
            location_service=AsyncMock(),
        )

        await svc.create_event(name="Later", characteristics="x", backstory="y",
                               start_date=date(1300, 1, 1), end_date=date(1300, 12, 31))
        await svc.create_event(name="Earlier", characteristics="x", backstory="y",
                               start_date=date(1100, 1, 1), end_date=date(1100, 12, 31))
        await svc.create_event(name="Middle", characteristics="x", backstory="y",
                               start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        await session.commit()

        events = await svc.get_all_events()
        names = [e.name for e in events]
        assert names == ["Earlier", "Middle", "Later"]

    @pytest.mark.asyncio
    async def test_search_by_description_content(self, session):
        desc_repo = BaseRepository(session, DescriptionModel)
        event_repo = EventRepository(session)
        org_repo = OrganizationRepository(session)
        char_repo = CharacterRepository(session)
        item_repo = ItemRepository(session)
        loc_repo = LocationRepository(session)

        event_svc = EventService(
            event_repo=event_repo,
            description_repo=desc_repo,
            organization_service=AsyncMock(),
            character_service=AsyncMock(),
            item_service=AsyncMock(),
            location_service=AsyncMock(),
        )
        char_svc = EntityService(repo=char_repo, description_repo=desc_repo)

        await event_svc.create_event(
            name="Ambush",
            characteristics="Forest skirmish",
            backstory="Bandits attacked travelers",
            start_date=date(1205, 6, 1),
            end_date=date(1205, 6, 2),
        )
        await char_svc.create_entity(
            name="Warrior",
            characteristics="Strong swordsman",
            backstory="Trained in the north",
            start_date=date(1180, 1, 1),
            end_date=date(1250, 12, 31),
        )
        await session.commit()

        search_svc = SearchService(
            event=event_repo,
            organization=org_repo,
            character=char_repo,
            item=item_repo,
            location=loc_repo,
        )

        # Search by backstory content
        results = await search_svc.search_all("Bandits")
        assert len(results["events"]) == 1
        assert results["events"][0].name == "Ambush"

        # Search by characteristics content
        results = await search_svc.search_all("swordsman")
        assert len(results["characters"]) == 1
        assert results["characters"][0].name == "Warrior"

        # Partial 2-char search
        results = await search_svc.search_all("Am")
        assert len(results["events"]) == 1

    @pytest.mark.asyncio
    async def test_search_no_duplicates_across_fields(self, session):
        desc_repo = BaseRepository(session, DescriptionModel)
        event_repo = EventRepository(session)
        org_repo = OrganizationRepository(session)
        char_repo = CharacterRepository(session)
        item_repo = ItemRepository(session)
        loc_repo = LocationRepository(session)

        event_svc = EventService(
            event_repo=event_repo,
            description_repo=desc_repo,
            organization_service=AsyncMock(),
            character_service=AsyncMock(),
            item_service=AsyncMock(),
            location_service=AsyncMock(),
        )
        # "Dragon" appears in name, characteristics, and backstory
        await event_svc.create_event(
            name="Dragon attack",
            characteristics="Dragon fire",
            backstory="The Dragon awoke",
            start_date=date(1300, 1, 1),
            end_date=date(1300, 12, 31),
        )
        await session.commit()

        search_svc = SearchService(
            event=event_repo, organization=org_repo,
            character=char_repo, item=item_repo, location=loc_repo,
        )
        results = await search_svc.search_all("Dragon")
        assert len(results["events"]) == 1  # no duplicates

    @pytest.mark.asyncio
    async def test_update_and_delete_event(self, session):
        desc_repo = BaseRepository(session, DescriptionModel)
        event_repo = EventRepository(session)
        svc = EventService(
            event_repo=event_repo,
            description_repo=desc_repo,
            organization_service=AsyncMock(),
            character_service=AsyncMock(),
            item_service=AsyncMock(),
            location_service=AsyncMock(),
        )

        event = await svc.create_event(
            name="Original",
            characteristics="x", backstory="y",
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31),
        )
        await session.commit()

        await svc.update_event(event.id, name="Updated")
        await session.commit()

        result = await svc.get_event(event.id)
        assert result.name == "Updated"

        deleted = await svc.delete_event(event.id)
        await session.commit()
        assert deleted is True

        result = await svc.get_event(event.id)
        assert result is None
