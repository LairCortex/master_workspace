"""Tests for repositories — TDD: tests first."""
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import (
    DescriptionModel, EventModel, OrganizationModel,
    CharacterModel, ItemModel, LocationModel, RatingModel,
)
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.event_repository import EventRepository
from app.infrastructure.repositories.organization_repository import OrganizationRepository
from app.infrastructure.repositories.character_repository import CharacterRepository
from app.infrastructure.repositories.item_repository import ItemRepository
from app.infrastructure.repositories.location_repository import LocationRepository
from app.infrastructure.repositories.rating_repository import RatingRepository


# ── helpers ───────────────────────────────────────────────────────────────

async def _make_desc(session: AsyncSession, chars: str = "x", back: str = "y") -> DescriptionModel:
    d = DescriptionModel(characteristics=chars, backstory=back)
    session.add(d)
    await session.flush()
    return d


# ── BaseRepository ────────────────────────────────────────────────────────

class TestBaseRepository:
    @pytest.mark.asyncio
    async def test_create_and_get_by_id(self, async_session: AsyncSession):
        repo = BaseRepository(async_session, DescriptionModel)
        obj = await repo.create(characteristics="Strong", backstory="Old")
        assert obj.id is not None
        result = await repo.get_by_id(obj.id)
        assert result.characteristics == "Strong"

    @pytest.mark.asyncio
    async def test_get_all(self, async_session: AsyncSession):
        repo = BaseRepository(async_session, DescriptionModel)
        await repo.create(characteristics="A", backstory="1")
        await repo.create(characteristics="B", backstory="2")
        items = await repo.get_all()
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_update(self, async_session: AsyncSession):
        repo = BaseRepository(async_session, DescriptionModel)
        obj = await repo.create(characteristics="Old", backstory="x")
        updated = await repo.update(obj.id, characteristics="New")
        assert updated.characteristics == "New"

    @pytest.mark.asyncio
    async def test_delete(self, async_session: AsyncSession):
        repo = BaseRepository(async_session, DescriptionModel)
        obj = await repo.create(characteristics="Del", backstory="x")
        await repo.delete(obj.id)
        result = await repo.get_by_id(obj.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, async_session: AsyncSession):
        repo = BaseRepository(async_session, DescriptionModel)
        result = await repo.get_by_id(999)
        assert result is None


# ── EventRepository ───────────────────────────────────────────────────────

class TestEventRepository:
    @pytest.mark.asyncio
    async def test_create_event(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        event = await repo.create(
            name="Battle", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31),
        )
        assert event.id is not None
        assert event.name == "Battle"

    @pytest.mark.asyncio
    async def test_get_event_with_relations(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        event = await repo.create(
            name="E1", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31),
        )
        result = await repo.get_by_id(event.id)
        assert result is not None
        assert hasattr(result, "organizations")

    @pytest.mark.asyncio
    async def test_search_events_by_name(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        await repo.create(name="Battle of Plains", description_id=desc.id, start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        await repo.create(name="Siege of Castle", description_id=desc.id, start_date=date(1201, 1, 1), end_date=date(1201, 12, 31))
        results = await repo.search("Battle")
        assert len(results) == 1
        assert results[0].name == "Battle of Plains"

    @pytest.mark.asyncio
    async def test_search_events_by_partial_name_2_chars(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        await repo.create(name="Battle of Plains", description_id=desc.id, start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        results = await repo.search("Ba")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_events_by_characteristics(self, async_session: AsyncSession):
        desc = await _make_desc(async_session, chars="Massive cavalry charge", back="y")
        repo = EventRepository(async_session)
        await repo.create(name="Event1", description_id=desc.id, start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        results = await repo.search("cavalry")
        assert len(results) == 1
        assert results[0].name == "Event1"

    @pytest.mark.asyncio
    async def test_search_events_by_backstory(self, async_session: AsyncSession):
        desc = await _make_desc(async_session, chars="x", back="Two ancient kingdoms clashed")
        repo = EventRepository(async_session)
        await repo.create(name="Event2", description_id=desc.id, start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        results = await repo.search("ancient")
        assert len(results) == 1
        assert results[0].name == "Event2"

    @pytest.mark.asyncio
    async def test_search_events_no_duplicates(self, async_session: AsyncSession):
        desc = await _make_desc(async_session, chars="Dragon attack", back="Dragon era")
        repo = EventRepository(async_session)
        await repo.create(name="Dragon war", description_id=desc.id, start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        results = await repo.search("Dragon")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_get_all_ordered_by_start_date(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        await repo.create(name="Later", description_id=desc.id, start_date=date(1300, 1, 1), end_date=date(1300, 12, 31))
        await repo.create(name="Earlier", description_id=desc.id, start_date=date(1100, 1, 1), end_date=date(1100, 12, 31))
        events = await repo.get_all_ordered()
        assert events[0].name == "Earlier"
        assert events[1].name == "Later"


# ── OrganizationRepository ────────────────────────────────────────────────

class TestOrganizationRepository:
    @pytest.mark.asyncio
    async def test_crud(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = OrganizationRepository(async_session)
        org = await repo.create(
            name="Guild", description_id=desc.id,
            start_date=date(1000, 1, 1), end_date=date(1500, 12, 31),
            tasks="Protect",
        )
        assert org.name == "Guild"
        result = await repo.get_by_id(org.id)
        assert result.tasks == "Protect"

    @pytest.mark.asyncio
    async def test_search(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = OrganizationRepository(async_session)
        await repo.create(name="Thieves Guild", description_id=desc.id, start_date=date(1000, 1, 1), end_date=date(1500, 12, 31))
        await repo.create(name="Mages Tower", description_id=desc.id, start_date=date(1000, 1, 1), end_date=date(1500, 12, 31))
        results = await repo.search("Guild")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_by_backstory(self, async_session: AsyncSession):
        desc = await _make_desc(async_session, chars="x", back="Founded in darkness")
        repo = OrganizationRepository(async_session)
        await repo.create(name="Org1", description_id=desc.id, start_date=date(1000, 1, 1), end_date=date(1500, 12, 31))
        results = await repo.search("darkness")
        assert len(results) == 1


# ── CharacterRepository ──────────────────────────────────────────────────

class TestCharacterRepository:
    @pytest.mark.asyncio
    async def test_crud(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = CharacterRepository(async_session)
        char = await repo.create(
            name="Hero", description_id=desc.id,
            start_date=date(1100, 1, 1), end_date=date(1200, 1, 1),
            personality="Brave", image="/img/hero.png", tasks="Save",
        )
        assert char.name == "Hero"
        result = await repo.get_by_id(char.id)
        assert result.personality == "Brave"

    @pytest.mark.asyncio
    async def test_search(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = CharacterRepository(async_session)
        await repo.create(name="Gandalf the Grey", description_id=desc.id, start_date=date(1, 1, 1), end_date=date(9999, 12, 31))
        await repo.create(name="Frodo Baggins", description_id=desc.id, start_date=date(1, 1, 1), end_date=date(9999, 12, 31))
        results = await repo.search("Gandalf")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_by_characteristics(self, async_session: AsyncSession):
        desc = await _make_desc(async_session, chars="Powerful wizard", back="y")
        repo = CharacterRepository(async_session)
        await repo.create(name="Mage1", description_id=desc.id, start_date=date(1, 1, 1), end_date=date(9999, 12, 31))
        results = await repo.search("wizard")
        assert len(results) == 1


# ── ItemRepository ────────────────────────────────────────────────────────

class TestItemRepository:
    @pytest.mark.asyncio
    async def test_crud(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = ItemRepository(async_session)
        item = await repo.create(name="Sword", description_id=desc.id, start_date=date(500, 1, 1), end_date=date(3000, 12, 31))
        assert item.name == "Sword"

    @pytest.mark.asyncio
    async def test_search(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = ItemRepository(async_session)
        await repo.create(name="Magic Sword", description_id=desc.id, start_date=date(500, 1, 1), end_date=date(3000, 12, 31))
        await repo.create(name="Shield", description_id=desc.id, start_date=date(500, 1, 1), end_date=date(3000, 12, 31))
        results = await repo.search("Sword")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_by_backstory(self, async_session: AsyncSession):
        desc = await _make_desc(async_session, chars="x", back="Forged by dwarves")
        repo = ItemRepository(async_session)
        await repo.create(name="Axe", description_id=desc.id, start_date=date(500, 1, 1), end_date=date(3000, 12, 31))
        results = await repo.search("dwarves")
        assert len(results) == 1


# ── LocationRepository ────────────────────────────────────────────────────

class TestLocationRepository:
    @pytest.mark.asyncio
    async def test_crud(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = LocationRepository(async_session)
        loc = await repo.create(
            name="Mordor", description_id=desc.id,
            start_date=date(100, 1, 1), end_date=date(3000, 12, 31),
            tasks="Defend", image="/maps/mordor.png",
        )
        assert loc.name == "Mordor"

    @pytest.mark.asyncio
    async def test_search(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = LocationRepository(async_session)
        await repo.create(name="Mordor", description_id=desc.id, start_date=date(100, 1, 1), end_date=date(3000, 12, 31))
        await repo.create(name="Shire", description_id=desc.id, start_date=date(100, 1, 1), end_date=date(3000, 12, 31))
        results = await repo.search("Shire")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_by_characteristics(self, async_session: AsyncSession):
        desc = await _make_desc(async_session, chars="Volcanic wasteland", back="y")
        repo = LocationRepository(async_session)
        await repo.create(name="Place1", description_id=desc.id, start_date=date(100, 1, 1), end_date=date(3000, 12, 31))
        results = await repo.search("Volcanic")
        assert len(results) == 1


# ── RatingRepository ──────────────────────────────────────────────────────

class TestRatingRepository:
    @pytest.mark.asyncio
    async def test_crud(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = RatingRepository(async_session)
        rating = await repo.create(description_id=desc.id, start_date=date(1200, 1, 1), end_date=date(1200, 12, 31), level=5)
        assert rating.level == 5
        result = await repo.get_by_id(rating.id)
        assert result.level == 5
