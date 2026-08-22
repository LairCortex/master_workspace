"""Tests for repositories — TDD: tests first."""
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import (
    DescriptionModel, OrganizationModel,
    CharacterModel, ItemModel, LocationModel,
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

    @pytest.mark.asyncio
    async def test_delete_not_found(self, async_session: AsyncSession):
        repo = BaseRepository(async_session, DescriptionModel)
        assert await repo.delete(999) is False

    @pytest.mark.asyncio
    async def test_search_by_name(self, async_session: AsyncSession):
        repo = BaseRepository(async_session, ItemModel)
        await repo.create(name="Sword of Dawn", start_date=date(500, 1, 1))
        await repo.create(name="Shield", start_date=date(500, 1, 1))
        results = await repo.search_by_name("sword")
        assert len(results) == 1
        assert results[0].name == "Sword of Dawn"


# ── BaseRepository.search: one parameterized set for the 4 entity types ──

ENTITY_REPOS = [
    (OrganizationRepository, OrganizationModel),
    (CharacterRepository, CharacterModel),
    (ItemRepository, ItemModel),
    (LocationRepository, LocationModel),
]


@pytest.mark.parametrize(("repo_cls", "model"), ENTITY_REPOS, ids=["organization", "character", "item", "location"])
class TestEntitySearch:
    """BaseRepository.search is inherited by all entity repositories."""

    @pytest.mark.asyncio
    async def test_search_by_name(self, async_session: AsyncSession, repo_cls, model):
        desc = await _make_desc(async_session)
        repo = repo_cls(async_session)
        await repo.create(name="Battle of Plains", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        await repo.create(name="Siege of Castle", description_id=desc.id,
            start_date=date(1201, 1, 1), end_date=date(1201, 12, 31))
        results = await repo.search("Battle")
        assert len(results) == 1
        assert results[0].name == "Battle of Plains"

    @pytest.mark.asyncio
    async def test_search_is_case_insensitive(self, async_session: AsyncSession, repo_cls, model):
        desc = await _make_desc(async_session)
        repo = repo_cls(async_session)
        await repo.create(name="Battle of Plains", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        assert len(await repo.search("bAtTlE")) == 1

    @pytest.mark.asyncio
    async def test_search_by_characteristics(self, async_session: AsyncSession, repo_cls, model):
        desc = await _make_desc(async_session, chars="Massive cavalry charge", back="y")
        repo = repo_cls(async_session)
        await repo.create(name="Entry1", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        results = await repo.search("cavalry")
        assert len(results) == 1
        assert results[0].name == "Entry1"

    @pytest.mark.asyncio
    async def test_search_by_backstory(self, async_session: AsyncSession, repo_cls, model):
        desc = await _make_desc(async_session, chars="x", back="Two ancient kingdoms clashed")
        repo = repo_cls(async_session)
        await repo.create(name="Entry2", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        results = await repo.search("ancient")
        assert len(results) == 1
        assert results[0].name == "Entry2"

    @pytest.mark.asyncio
    async def test_search_no_duplicates_on_multiple_hits(self, async_session: AsyncSession, repo_cls, model):
        # Matches name AND description in one row -> still a single result
        desc = await _make_desc(async_session, chars="Dragon attack", back="Dragon era")
        repo = repo_cls(async_session)
        await repo.create(name="Dragon war", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        assert len(await repo.search("Dragon")) == 1


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
        await repo.create(name="Battle of Plains", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        await repo.create(name="Siege of Castle", description_id=desc.id,
            start_date=date(1201, 1, 1), end_date=date(1201, 12, 31))
        results = await repo.search("Battle")
        assert len(results) == 1
        assert results[0].name == "Battle of Plains"

    @pytest.mark.asyncio
    async def test_search_events_by_partial_name_2_chars(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        await repo.create(name="Battle of Plains", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        results = await repo.search("Ba")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_events_by_characteristics(self, async_session: AsyncSession):
        desc = await _make_desc(async_session, chars="Massive cavalry charge", back="y")
        repo = EventRepository(async_session)
        await repo.create(name="Event1", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        results = await repo.search("cavalry")
        assert len(results) == 1
        assert results[0].name == "Event1"

    @pytest.mark.asyncio
    async def test_search_events_by_backstory(self, async_session: AsyncSession):
        desc = await _make_desc(async_session, chars="x", back="Two ancient kingdoms clashed")
        repo = EventRepository(async_session)
        await repo.create(name="Event2", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        results = await repo.search("ancient")
        assert len(results) == 1
        assert results[0].name == "Event2"

    @pytest.mark.asyncio
    async def test_search_events_no_duplicates(self, async_session: AsyncSession):
        desc = await _make_desc(async_session, chars="Dragon attack", back="Dragon era")
        repo = EventRepository(async_session)
        await repo.create(name="Dragon war", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        results = await repo.search("Dragon")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_get_all_ordered_by_start_date(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        await repo.create(name="Later", description_id=desc.id,
            start_date=date(1300, 1, 1), end_date=date(1300, 12, 31))
        await repo.create(name="Earlier", description_id=desc.id,
            start_date=date(1100, 1, 1), end_date=date(1100, 12, 31))
        events = await repo.get_all_ordered()
        assert events[0].name == "Earlier"
        assert events[1].name == "Later"

    @pytest.mark.asyncio
    async def test_get_events_at_date(self, async_session: AsyncSession):
        d1 = await _make_desc(async_session)
        d2 = await _make_desc(async_session)
        repo = EventRepository(async_session)
        await repo.create(name="Closed", description_id=d1.id, start_date=date(1200, 1, 1), end_date=date(1200, 6, 30))
        await repo.create(name="Infinite", description_id=d2.id, start_date=date(1300, 1, 1), end_date=None)
        names = {e.name for e in await repo.get_events_at_date(date(1200, 6, 15))}
        assert names == {"Closed"}
        names = {e.name for e in await repo.get_events_at_date(date(1300, 3, 1))}
        assert names == {"Infinite"}


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


# ── ItemRepository ────────────────────────────────────────────────────────

class TestItemRepository:
    @pytest.mark.asyncio
    async def test_crud(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = ItemRepository(async_session)
        item = await repo.create(name="Sword", description_id=desc.id,
            start_date=date(500, 1, 1), end_date=date(3000, 12, 31))
        assert item.name == "Sword"


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


# ── RatingRepository ──────────────────────────────────────────────────────

class TestRatingRepository:
    @pytest.mark.asyncio
    async def test_crud(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = RatingRepository(async_session)
        rating = await repo.create(description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31), level=5)
        assert rating.level == 5
        result = await repo.get_by_id(rating.id)
        assert result.level == 5
