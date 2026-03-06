"""Tests for domain entities — TDD: write tests first."""
from datetime import date

import pytest

from app.domain.entities.description import Description
from app.domain.entities.event import Event
from app.domain.entities.organization import Organization
from app.domain.entities.character import Character
from app.domain.entities.item import Item
from app.domain.entities.location import Location
from app.domain.entities.rating import Rating
from app.domain.enums.entity_type import EntityType


# --- Description ---

class TestDescription:
    def test_create_description(self):
        d = Description(characteristics="Strong", backstory="Born in fire")
        assert d.characteristics == "Strong"
        assert d.backstory == "Born in fire"
        assert d.id is None

    def test_create_description_with_id(self):
        d = Description(id=1, characteristics="Wise", backstory="Ancient")
        assert d.id == 1


# --- Event ---

class TestEvent:
    def test_create_event_minimal(self):
        desc = Description(characteristics="Battle", backstory="The great war")
        e = Event(
            name="Battle of the Plains",
            description=desc,
            start_date=date(1200, 1, 1),
            end_date=date(1200, 12, 31),
        )
        assert e.name == "Battle of the Plains"
        assert e.start_date == date(1200, 1, 1)
        assert e.end_date == date(1200, 12, 31)
        assert e.description.characteristics == "Battle"
        assert e.organizations == []
        assert e.characters == []
        assert e.items == []
        assert e.locations == []

    def test_event_requires_name(self):
        with pytest.raises(ValueError, match="name"):
            Event(
                name="",
                description=Description(characteristics="x", backstory="y"),
                start_date=date(1200, 1, 1),
                end_date=date(1200, 12, 31),
            )

    def test_event_requires_description(self):
        with pytest.raises(ValueError, match="description"):
            Event(
                name="Test",
                description=None,
                start_date=date(1200, 1, 1),
                end_date=date(1200, 12, 31),
            )

    def test_event_requires_start_date(self):
        with pytest.raises(ValueError, match="start_date"):
            Event(
                name="Test",
                description=Description(characteristics="x", backstory="y"),
                start_date=None,
                end_date=date(1200, 12, 31),
            )

    def test_event_allows_no_end_date(self):
        """end_date is optional — None means ongoing/infinite."""
        ev = Event(
            name="Test",
            description=Description(characteristics="x", backstory="y"),
            start_date=date(1200, 1, 1),
            end_date=None,
        )
        assert ev.end_date is None

    def test_event_end_date_not_before_start(self):
        with pytest.raises(ValueError, match="end_date.*start_date"):
            Event(
                name="Test",
                description=Description(characteristics="x", backstory="y"),
                start_date=date(1200, 6, 1),
                end_date=date(1200, 1, 1),
            )


# --- Organization ---

class TestOrganization:
    def test_create_organization(self):
        desc = Description(characteristics="Secret", backstory="Founded long ago")
        org = Organization(
            name="The Guild",
            description=desc,
            start_date=date(1000, 1, 1),
            end_date=date(1500, 12, 31),
        )
        assert org.name == "The Guild"
        assert org.tasks is None
        assert org.music_url is None
        assert org.characters == []
        assert org.items == []
        assert org.locations == []

    def test_organization_with_tasks(self):
        org = Organization(
            name="Order",
            description=Description(characteristics="x", backstory="y"),
            start_date=date(1000, 1, 1),
            end_date=date(1500, 12, 31),
            tasks="Protect the realm",
        )
        assert org.tasks == "Protect the realm"

    def test_organization_requires_name(self):
        with pytest.raises(ValueError, match="name"):
            Organization(
                name="",
                description=Description(characteristics="x", backstory="y"),
                start_date=date(1000, 1, 1),
                end_date=date(1500, 12, 31),
            )

    def test_organization_requires_dates(self):
        with pytest.raises(ValueError, match="start_date"):
            Organization(
                name="Guild",
                description=Description(characteristics="x", backstory="y"),
                start_date=None,
                end_date=date(1500, 12, 31),
            )


# --- Character ---

class TestCharacter:
    def test_create_character(self):
        desc = Description(characteristics="Brave", backstory="Orphan")
        ch = Character(
            name="Aragon",
            description=desc,
            start_date=date(1100, 3, 15),
            end_date=date(1200, 7, 20),
        )
        assert ch.name == "Aragon"
        assert ch.personality is None
        assert ch.image is None
        assert ch.music_url is None
        assert ch.tasks is None
        assert ch.items == []
        assert ch.locations == []
        assert ch.ratings == []

    def test_character_with_all_fields(self):
        ch = Character(
            name="Gandalf",
            description=Description(characteristics="Wise", backstory="Maiar"),
            start_date=date(1, 1, 1),
            end_date=date(9999, 12, 31),
            personality="Mysterious and wise",
            image="/images/gandalf.png",
            tasks="Guide the fellowship",
            music_url="https://example.com/theme.mp3",
        )
        assert ch.personality == "Mysterious and wise"
        assert ch.image == "/images/gandalf.png"
        assert ch.music_url == "https://example.com/theme.mp3"

    def test_character_requires_name(self):
        with pytest.raises(ValueError, match="name"):
            Character(
                name="",
                description=Description(characteristics="x", backstory="y"),
                start_date=date(1100, 1, 1),
                end_date=date(1200, 1, 1),
            )


# --- Item ---

class TestItem:
    def test_create_item(self):
        desc = Description(characteristics="Magical", backstory="Forged in Mt. Doom")
        item = Item(
            name="The One Ring",
            description=desc,
            start_date=date(500, 1, 1),
            end_date=date(3000, 12, 31),
        )
        assert item.name == "The One Ring"
        assert item.locations == []
        assert item.ratings == []
        assert item.music_url is None

    def test_item_requires_name(self):
        with pytest.raises(ValueError, match="name"):
            Item(
                name="",
                description=Description(characteristics="x", backstory="y"),
                start_date=date(500, 1, 1),
                end_date=date(3000, 12, 31),
            )


# --- Location ---

class TestLocation:
    def test_create_location(self):
        desc = Description(characteristics="Dark", backstory="Ancient fortress")
        loc = Location(
            name="Mordor",
            description=desc,
            start_date=date(100, 1, 1),
            end_date=date(3000, 12, 31),
        )
        assert loc.name == "Mordor"
        assert loc.tasks is None
        assert loc.image is None
        assert loc.music_url is None
        assert loc.characters == []
        assert loc.organizations == []
        assert loc.ratings == []

    def test_location_with_map(self):
        loc = Location(
            name="Shire",
            description=Description(characteristics="Green", backstory="Peaceful"),
            start_date=date(100, 1, 1),
            end_date=date(3000, 12, 31),
            image="/maps/shire.png",
        )
        assert loc.image == "/maps/shire.png"

    def test_location_requires_name(self):
        with pytest.raises(ValueError, match="name"):
            Location(
                name="",
                description=Description(characteristics="x", backstory="y"),
                start_date=date(100, 1, 1),
                end_date=date(3000, 12, 31),
            )


# --- Rating ---

class TestRating:
    def test_create_rating(self):
        desc = Description(characteristics="Power level", backstory="Based on deeds")
        r = Rating(
            description=desc,
            start_date=date(1200, 1, 1),
            end_date=date(1200, 12, 31),
            level=5,
        )
        assert r.level == 5
        assert r.description.characteristics == "Power level"

    def test_rating_requires_level(self):
        with pytest.raises(ValueError, match="level"):
            Rating(
                description=Description(characteristics="x", backstory="y"),
                start_date=date(1200, 1, 1),
                end_date=date(1200, 12, 31),
                level=None,
            )

    def test_rating_requires_dates(self):
        with pytest.raises(ValueError, match="start_date"):
            Rating(
                description=Description(characteristics="x", backstory="y"),
                start_date=None,
                end_date=date(1200, 12, 31),
                level=5,
            )


# --- EntityType Enum ---

class TestEntityType:
    def test_all_types_exist(self):
        assert EntityType.EVENT.value == "event"
        assert EntityType.ORGANIZATION.value == "organization"
        assert EntityType.CHARACTER.value == "character"
        assert EntityType.ITEM.value == "item"
        assert EntityType.LOCATION.value == "location"
        assert EntityType.RATING.value == "rating"
