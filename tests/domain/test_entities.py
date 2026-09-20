"""Tests for domain entities — TDD: write tests first.

Since piece C3a (design D4) the entity dates are game-calendar coordinates:
a plain ``datetime.date`` stays accepted and reads back as the equal
``MonthDay``, and coordinates absent from the active calendar are refused
with the distinguishable ``InvalidGameDateError``."""
from datetime import date

import pytest

from app.domain.date_era import cmp_era_dates
from app.domain.entities.base import BaseEntity
from app.domain.entities.description import Description
from app.domain.entities.event import Event
from app.domain.entities.event_type import EventType
from app.domain.entities.organization import Organization
from app.domain.entities.character import Character
from app.domain.entities.item import Item
from app.domain.entities.location import Location
from app.domain.entities.rating import Rating
from app.domain.enums.entity_type import EntityType
from app.domain.game_calendar import (
    IntercalaryDay,
    InvalidGameDateError,
    MonthDay,
)


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
        # C3a (D4): input date reads back as the equal MonthDay coordinate
        assert e.start_date == MonthDay(1200, 1, 1)
        assert e.end_date == MonthDay(1200, 12, 31)
        assert e.description.characteristics == "Battle"
        assert e.organizations == []
        assert e.characters == []
        assert e.items == []
        assert e.locations == []
        # Fields inherited from BaseEntity
        assert e.id is None
        assert e.music_url is None
        assert e.ratings == []


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

    def test_event_has_no_type_by_default(self):
        e = Event(
            name="Quiet Day",
            description=Description(characteristics="x", backstory="y"),
            start_date=date(1200, 1, 1),
        )
        assert e.event_type is None

    def test_event_with_assigned_type(self):
        t = EventType(name="Побочное", color_index=2)
        e = Event(
            name="Side Job",
            description=Description(characteristics="x", backstory="y"),
            start_date=date(1200, 1, 1),
            event_type=t,
        )
        assert e.event_type is t


# --- EventType (W4) ---

class TestEventType:
    def test_create_event_type(self):
        t = EventType(name="Слух", color_index=3, sort_order=2, id=7)
        assert t.name == "Слух"
        assert t.color_index == 3
        assert t.sort_order == 2
        assert t.id == 7

    def test_event_type_defaults(self):
        t = EventType(name="Находка", color_index=6)
        assert t.sort_order == 0
        assert t.id is None


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
        assert org.image is None
        assert org.music_url is None
        assert org.characters == []
        assert org.items == []
        assert org.locations == []
        assert org.ratings == []

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


# --- BaseEntity inheritance & shared validation ---

class TestBaseEntity:
    @pytest.mark.parametrize("cls", [Event, Organization, Character, Item, Location])
    def test_entities_inherit_base_entity(self, cls):
        assert issubclass(cls, BaseEntity)

    @pytest.mark.parametrize("cls", [Event, Organization, Character, Item, Location])
    def test_base_validation_requires_name(self, cls):
        with pytest.raises(ValueError, match="name"):
            cls(
                name="",
                description=Description(characteristics="x", backstory="y"),
                start_date=date(1200, 1, 1),
            )


# --- Era-aware date validation (through the era border) ---

class TestEraAwareDateValidation:
    def test_event_spanning_eras_is_allowed(self):
        """Start 500 г. до н.э., end 100 г. н.э. — конец позже начала через границу эр."""
        ev = Event(
            name="Empire",
            description=Description(characteristics="x", backstory="y"),
            start_date=date(500, 1, 1),
            end_date=date(100, 1, 1),
            start_bc=True,
        )
        assert ev.start_bc is True
        assert ev.end_bc is False

    def test_event_end_earlier_in_bc_era_is_rejected(self):
        """Конец 200 г. до н.э. при начале 100 г. до н.э. — раньше начала."""
        with pytest.raises(ValueError, match="end_date.*start_date"):
            Event(
                name="Test",
                description=Description(characteristics="x", backstory="y"),
                start_date=date(100, 1, 1),
                end_date=date(200, 1, 1),
                start_bc=True,
                end_bc=True,
            )

    def test_event_bc_same_year_ordering_follows_era_key(self):
        """Внутри одного BC-года дни идут естественно: 15 марта раньше конца февраля нельзя."""
        ev = Event(
            name="Ides",
            description=Description(characteristics="x", backstory="y"),
            start_date=date(44, 2, 1),
            end_date=date(44, 3, 15),
            start_bc=True,
            end_bc=True,
        )
        # C3a: поля — координаты, порядок — общий хронологический ключ
        assert cmp_era_dates((ev.end_date, True), (ev.start_date, True)) > 0
        with pytest.raises(ValueError, match="end_date.*start_date"):
            Event(
                name="Reversed",
                description=Description(characteristics="x", backstory="y"),
                start_date=date(44, 3, 15),
                end_date=date(44, 2, 1),
                start_bc=True,
                end_bc=True,
            )

    def test_rating_spanning_eras_is_allowed(self):
        r = Rating(
            description=Description(characteristics="x", backstory="y"),
            start_date=date(300, 1, 1),
            end_date=date(300, 1, 1),
            level=3,
            start_bc=True,
        )
        assert r.start_bc is True
        assert r.end_bc is False

    def test_rating_end_earlier_in_bc_era_is_rejected(self):
        with pytest.raises(ValueError, match="end_date.*start_date"):
            Rating(
                description=Description(characteristics="x", backstory="y"),
                start_date=date(100, 1, 1),
                end_date=date(200, 1, 1),
                level=2,
                start_bc=True,
                end_bc=True,
            )


# --- Game-calendar coordinates as the entity's date (C3a task 2.1) ---


class TestEntityDateCoordinates:
    """Spec «Дата с эрой» (C3a delta): дата сущности — координата календаря,
    обычная дата — её частный случай, несуществующая координата отклоняется
    отличимой ошибкой без тихой нормализации."""

    def test_plain_date_coerces_to_the_equal_month_day(self):
        """Сценарий «Обычная календарная дата — частный случай координаты»."""
        ev = Event(
            name="Coerced",
            description=Description(characteristics="x", backstory="y"),
            start_date=date(1200, 6, 1),
            end_date=date(1200, 12, 31),
        )
        assert isinstance(ev.start_date, MonthDay)
        assert ev.start_date == MonthDay(1200, 6, 1)
        assert ev.end_date == MonthDay(1200, 12, 31)

    def test_rating_plain_date_coerces_to_the_equal_month_day(self):
        r = Rating(
            description=Description(characteristics="x", backstory="y"),
            start_date=date(1200, 6, 1),
            end_date=date(1200, 12, 31),
            level=4,
        )
        assert r.start_date == MonthDay(1200, 6, 1)
        assert r.end_date == MonthDay(1200, 12, 31)

    def test_game_coordinates_pass_through_unchanged(self):
        coord = MonthDay(1200, 6, 1)
        ev = Event(
            name="Native coord",
            description=Description(characteristics="x", backstory="y"),
            start_date=coord,
            end_date=None,
        )
        assert ev.start_date is coord

    def test_nonexistent_start_coord_is_refused_with_distinguishable_error(self):
        """Сценарий «Дня не существует в активном календаре»: 31 апреля нет —
        отличимый отказ InvalidGameDateError, никакой подмены датой."""
        with pytest.raises(InvalidGameDateError):
            Event(
                name="April 31st",
                description=Description(characteristics="x", backstory="y"),
                start_date=MonthDay(2026, 4, 31),
            )

    def test_nonexistent_end_coord_is_refused_with_distinguishable_error(self):
        with pytest.raises(InvalidGameDateError):
            Event(
                name="Bad end",
                description=Description(characteristics="x", backstory="y"),
                start_date=MonthDay(2026, 1, 1),
                end_date=MonthDay(2026, 2, 30),
            )

    def test_intercalary_coord_is_refused_under_the_standard_preset(self):
        """Вставной день под пресетом «Стандартный» — та же отличимая ошибка."""
        with pytest.raises(InvalidGameDateError):
            Event(
                name="Mask day",
                description=Description(characteristics="x", backstory="y"),
                start_date=IntercalaryDay(44, 0),
                start_bc=True,
            )
        with pytest.raises(InvalidGameDateError):
            Rating(
                description=Description(characteristics="x", backstory="y"),
                start_date=IntercalaryDay(44, 0),
                level=2,
            )

    def test_mixed_era_end_before_start_keeps_the_previous_error_text(self):
        """Конец до н.э. при начале н.э. — «конец раньше начала» прежним
        текстом, проверка через единый ключ через границу эр."""
        with pytest.raises(ValueError, match="end_date must not be before start_date") as exc:
            Event(
                name="Back into BC",
                description=Description(characteristics="x", backstory="y"),
                start_date=MonthDay(1, 1, 1),
                end_date=MonthDay(44, 3, 5),
                end_bc=True,
            )
        assert str(exc.value) == "end_date must not be before start_date"

    def test_rating_mixed_era_end_before_start_keeps_the_previous_error_text(self):
        with pytest.raises(ValueError, match="end_date must not be before start_date") as exc:
            Rating(
                description=Description(characteristics="x", backstory="y"),
                start_date=MonthDay(1, 1, 1),
                end_date=MonthDay(300, 1, 1),
                end_bc=True,
                level=1,
            )
        assert str(exc.value) == "end_date must not be before start_date"

