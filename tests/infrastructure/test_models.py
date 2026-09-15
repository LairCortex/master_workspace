"""Tests for SQLAlchemy ORM models — TDD: tests first."""
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.date_era import era_key
from app.infrastructure.db.models import (
    DescriptionModel,
    EventModel,
    OrganizationModel,
    CharacterModel,
    ItemModel,
    LocationModel,
    RatingModel,
)


# --- DescriptionModel ---

class TestDescriptionModel:
    @pytest.mark.asyncio
    async def test_create_description(self, async_session: AsyncSession):
        desc = DescriptionModel(characteristics="Strong", backstory="Born in fire")
        async_session.add(desc)
        await async_session.commit()

        result = await async_session.get(DescriptionModel, desc.id)
        assert result is not None
        assert result.characteristics == "Strong"
        assert result.backstory == "Born in fire"


# --- EventModel ---

class TestEventModel:
    @pytest.mark.asyncio
    async def test_create_event(self, async_session: AsyncSession):
        desc = DescriptionModel(characteristics="Battle", backstory="War")
        async_session.add(desc)
        await async_session.flush()

        event = EventModel(
            name="Battle of Plains",
            description_id=desc.id,
            start_date=date(1200, 1, 1),
            end_date=date(1200, 12, 31),
        )
        async_session.add(event)
        await async_session.commit()

        result = await async_session.get(EventModel, event.id)
        assert result.name == "Battle of Plains"
        assert result.start_date == date(1200, 1, 1)

    @pytest.mark.asyncio
    async def test_event_organization_m2m(self, async_session: AsyncSession):
        desc1 = DescriptionModel(characteristics="e", backstory="e")
        desc2 = DescriptionModel(characteristics="o", backstory="o")
        async_session.add_all([desc1, desc2])
        await async_session.flush()

        event = EventModel(name="E1", description_id=desc1.id, start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        org = OrganizationModel(name="O1", description_id=desc2.id,
            start_date=date(1000, 1, 1), end_date=date(1500, 12, 31))
        event.organizations.append(org)
        async_session.add(event)
        await async_session.commit()

        result = await async_session.get(EventModel, event.id)
        assert len(result.organizations) == 1
        assert result.organizations[0].name == "O1"

    @pytest.mark.asyncio
    async def test_event_character_m2m(self, async_session: AsyncSession):
        desc1 = DescriptionModel(characteristics="e", backstory="e")
        desc2 = DescriptionModel(characteristics="c", backstory="c")
        async_session.add_all([desc1, desc2])
        await async_session.flush()

        event = EventModel(name="E1", description_id=desc1.id, start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        char = CharacterModel(name="Hero", description_id=desc2.id,
            start_date=date(1100, 1, 1), end_date=date(1200, 1, 1))
        event.characters.append(char)
        async_session.add(event)
        await async_session.commit()

        result = await async_session.get(EventModel, event.id)
        assert len(result.characters) == 1

    @pytest.mark.asyncio
    async def test_event_item_m2m(self, async_session: AsyncSession):
        desc1 = DescriptionModel(characteristics="e", backstory="e")
        desc2 = DescriptionModel(characteristics="i", backstory="i")
        async_session.add_all([desc1, desc2])
        await async_session.flush()

        event = EventModel(name="E1", description_id=desc1.id, start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        item = ItemModel(name="Sword", description_id=desc2.id, start_date=date(500, 1, 1), end_date=date(3000, 12, 31))
        event.items.append(item)
        async_session.add(event)
        await async_session.commit()

        result = await async_session.get(EventModel, event.id)
        assert len(result.items) == 1

    @pytest.mark.asyncio
    async def test_event_location_m2m(self, async_session: AsyncSession):
        desc1 = DescriptionModel(characteristics="e", backstory="e")
        desc2 = DescriptionModel(characteristics="l", backstory="l")
        async_session.add_all([desc1, desc2])
        await async_session.flush()

        event = EventModel(name="E1", description_id=desc1.id, start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        loc = LocationModel(name="Forest", description_id=desc2.id,
            start_date=date(100, 1, 1), end_date=date(3000, 12, 31))
        event.locations.append(loc)
        async_session.add(event)
        await async_session.commit()

        result = await async_session.get(EventModel, event.id)
        assert len(result.locations) == 1


# --- OrganizationModel ---

class TestOrganizationModel:
    @pytest.mark.asyncio
    async def test_create_organization_with_tasks(self, async_session: AsyncSession):
        desc = DescriptionModel(characteristics="Secret", backstory="Old")
        async_session.add(desc)
        await async_session.flush()

        org = OrganizationModel(
            name="Guild",
            description_id=desc.id,
            start_date=date(1000, 1, 1),
            end_date=date(1500, 12, 31),
            tasks="Protect the realm",
            music_url="https://example.com/theme.mp3",
        )
        async_session.add(org)
        await async_session.commit()

        result = await async_session.get(OrganizationModel, org.id)
        assert result.tasks == "Protect the realm"
        assert result.music_url == "https://example.com/theme.mp3"

    @pytest.mark.asyncio
    async def test_org_character_m2m(self, async_session: AsyncSession):
        d1 = DescriptionModel(characteristics="o", backstory="o")
        d2 = DescriptionModel(characteristics="c", backstory="c")
        async_session.add_all([d1, d2])
        await async_session.flush()

        org = OrganizationModel(name="O1", description_id=d1.id,
            start_date=date(1000, 1, 1), end_date=date(1500, 12, 31))
        char = CharacterModel(name="C1", description_id=d2.id, start_date=date(1100, 1, 1), end_date=date(1200, 1, 1))
        org.characters.append(char)
        async_session.add(org)
        await async_session.commit()

        result = await async_session.get(OrganizationModel, org.id)
        assert len(result.characters) == 1


# --- CharacterModel ---

class TestCharacterModel:
    @pytest.mark.asyncio
    async def test_create_character_full(self, async_session: AsyncSession):
        desc = DescriptionModel(characteristics="Brave", backstory="Orphan")
        async_session.add(desc)
        await async_session.flush()

        char = CharacterModel(
            name="Aragon",
            description_id=desc.id,
            start_date=date(1100, 3, 15),
            end_date=date(1200, 7, 20),
            personality="Noble",
            image="/img/aragon.png",
            tasks="Lead",
            music_url="file:///music/hero_theme.ogg",
        )
        async_session.add(char)
        await async_session.commit()

        result = await async_session.get(CharacterModel, char.id)
        assert result.personality == "Noble"
        assert result.image == "/img/aragon.png"
        assert result.music_url == "file:///music/hero_theme.ogg"

    @pytest.mark.asyncio
    async def test_character_rating_m2m(self, async_session: AsyncSession):
        d1 = DescriptionModel(characteristics="c", backstory="c")
        d2 = DescriptionModel(characteristics="r", backstory="r")
        async_session.add_all([d1, d2])
        await async_session.flush()

        char = CharacterModel(name="C1", description_id=d1.id, start_date=date(1100, 1, 1), end_date=date(1200, 1, 1))
        rating = RatingModel(description_id=d2.id, start_date=date(1150, 1, 1), end_date=date(1150, 12, 31), level=7)
        char.ratings.append(rating)
        async_session.add(char)
        await async_session.commit()

        result = await async_session.get(CharacterModel, char.id)
        assert len(result.ratings) == 1
        assert result.ratings[0].level == 7


# --- ItemModel ---

class TestItemModel:
    @pytest.mark.asyncio
    async def test_create_item(self, async_session: AsyncSession):
        desc = DescriptionModel(characteristics="Magical", backstory="Forged")
        async_session.add(desc)
        await async_session.flush()

        item = ItemModel(
            name="Ring",
            description_id=desc.id,
            start_date=date(500, 1, 1),
            end_date=date(3000, 12, 31),
            music_url="ring-theme.flac",
        )
        async_session.add(item)
        await async_session.commit()

        result = await async_session.get(ItemModel, item.id)
        assert result.name == "Ring"
        assert result.music_url == "ring-theme.flac"


# --- LocationModel ---

class TestLocationModel:
    @pytest.mark.asyncio
    async def test_create_location(self, async_session: AsyncSession):
        desc = DescriptionModel(characteristics="Dark", backstory="Fortress")
        async_session.add(desc)
        await async_session.flush()

        loc = LocationModel(
            name="Mordor",
            description_id=desc.id,
            start_date=date(100, 1, 1),
            end_date=date(3000, 12, 31),
            image="/maps/mordor.png",
            tasks="Defend",
            music_url="mordor-theme.ogg",
        )
        async_session.add(loc)
        await async_session.commit()

        result = await async_session.get(LocationModel, loc.id)
        assert result.image == "/maps/mordor.png"
        assert result.tasks == "Defend"
        assert result.music_url == "mordor-theme.ogg"


# --- RatingModel ---

class TestRatingModel:
    @pytest.mark.asyncio
    async def test_create_rating(self, async_session: AsyncSession):
        desc = DescriptionModel(characteristics="Power", backstory="Deeds")
        async_session.add(desc)
        await async_session.flush()

        rating = RatingModel(description_id=desc.id, start_date=date(1200, 1, 1), end_date=date(1200, 12, 31), level=5)
        async_session.add(rating)
        await async_session.commit()

        result = await async_session.get(RatingModel, rating.id)
        assert result.level == 5


# --- Era-aware date columns (add-era-aware-dates, task 2.1) ---

# (model, extra kwargs making it constructible) for every dated table.
_DATED_MODELS = [
    (EventModel, {"name": "E"}),
    (OrganizationModel, {"name": "O"}),
    (CharacterModel, {"name": "C"}),
    (ItemModel, {"name": "I"}),
    (LocationModel, {"name": "L"}),
    (RatingModel, {"level": 3}),
]


class TestEraDateColumns:
    """Round-trip save fills era flags and derived keys on all six tables."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("model,extra", _DATED_MODELS)
    async def test_bc_dates_round_trip_with_keys(
        self, async_session: AsyncSession, model, extra
    ):
        desc = DescriptionModel(characteristics="c", backstory="b")
        async_session.add(desc)
        await async_session.flush()

        obj = model(
            description_id=desc.id,
            start_date=date(44, 3, 5),
            start_bc=1,
            end_date=date(45, 4, 10),  # BC 45-й — раньше 44-го (зеркальный ход)
            end_bc=1,
            **extra,
        )
        async_session.add(obj)
        await async_session.commit()

        result = await async_session.get(model, obj.id)
        assert result.start_bc == 1
        assert result.end_bc == 1
        assert result.start_date == date(44, 3, 5)
        assert result.end_date == date(45, 4, 10)
        # Ключи = общий помощник D2, а не ординалы дат
        assert result.start_key == era_key(date(44, 3, 5), True)
        assert result.end_key == era_key(date(45, 4, 10), True)
        # BC-ключи строго negative: любая дата до н.э. раньше любой н.э.
        assert result.start_key < 0 and result.end_key < 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("model,extra", _DATED_MODELS)
    async def test_ce_defaults_round_trip_with_keys(
        self, async_session: AsyncSession, model, extra
    ):
        desc = DescriptionModel(characteristics="c", backstory="b")
        async_session.add(desc)
        await async_session.flush()

        obj = model(
            description_id=desc.id,
            start_date=date(1200, 1, 1),
            **extra,
        )
        async_session.add(obj)
        await async_session.commit()

        result = await async_session.get(model, obj.id)
        # Эра по умолчанию — н.э.; ключ = ординал; открытый конец → без ключа
        assert result.start_bc == 0
        assert result.end_bc == 0
        assert result.start_key == era_key(date(1200, 1, 1), False)
        assert result.end_key is None

    @pytest.mark.asyncio
    async def test_date_update_resyncs_keys(self, async_session: AsyncSession):
        # Переезд даты через эру должен переписать и ключ (D2 на записи).
        desc = DescriptionModel(characteristics="c", backstory="b")
        async_session.add(desc)
        await async_session.flush()

        event = EventModel(
            name="E", description_id=desc.id, start_date=date(2026, 1, 1),
        )
        async_session.add(event)
        await async_session.commit()

        event.start_date = date(500, 1, 1)
        event.start_bc = 1
        await async_session.commit()

        result = await async_session.get(EventModel, event.id)
        assert result.start_bc == 1
        assert result.start_key == era_key(date(500, 1, 1), True)


# --- Description relationship ---

class TestDescriptionRelationship:
    @pytest.mark.asyncio
    async def test_event_has_description(self, async_session: AsyncSession):
        desc = DescriptionModel(characteristics="Battle", backstory="War")
        async_session.add(desc)
        await async_session.flush()

        event = EventModel(name="E1", description_id=desc.id, start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        async_session.add(event)
        await async_session.commit()

        result = await async_session.get(EventModel, event.id)
        assert result.description_id == desc.id
