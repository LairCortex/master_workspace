"""SQLAlchemy ORM models for NRI scenario manager."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ── Association tables (M2M) ──────────────────────────────────────────────

event_organization = Table(
    "event_organization", Base.metadata,
    Column("event_id", Integer, ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
    Column("organization_id", Integer, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True),
)

event_character = Table(
    "event_character", Base.metadata,
    Column("event_id", Integer, ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
    Column("character_id", Integer, ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True),
)

event_item = Table(
    "event_item", Base.metadata,
    Column("event_id", Integer, ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
    Column("item_id", Integer, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
)

event_location = Table(
    "event_location", Base.metadata,
    Column("event_id", Integer, ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
    Column("location_id", Integer, ForeignKey("locations.id", ondelete="CASCADE"), primary_key=True),
)

organization_character = Table(
    "organization_character", Base.metadata,
    Column("organization_id", Integer, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True),
    Column("character_id", Integer, ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True),
)

organization_item = Table(
    "organization_item", Base.metadata,
    Column("organization_id", Integer, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True),
    Column("item_id", Integer, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
)

organization_location = Table(
    "organization_location", Base.metadata,
    Column("organization_id", Integer, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True),
    Column("location_id", Integer, ForeignKey("locations.id", ondelete="CASCADE"), primary_key=True),
)

character_item = Table(
    "character_item", Base.metadata,
    Column("character_id", Integer, ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True),
    Column("item_id", Integer, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
)

character_location = Table(
    "character_location", Base.metadata,
    Column("character_id", Integer, ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True),
    Column("location_id", Integer, ForeignKey("locations.id", ondelete="CASCADE"), primary_key=True),
)

character_rating = Table(
    "character_rating", Base.metadata,
    Column("character_id", Integer, ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True),
    Column("rating_id", Integer, ForeignKey("ratings.id", ondelete="CASCADE"), primary_key=True),
)

item_location = Table(
    "item_location", Base.metadata,
    Column("item_id", Integer, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
    Column("location_id", Integer, ForeignKey("locations.id", ondelete="CASCADE"), primary_key=True),
)

item_rating = Table(
    "item_rating", Base.metadata,
    Column("item_id", Integer, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
    Column("rating_id", Integer, ForeignKey("ratings.id", ondelete="CASCADE"), primary_key=True),
)

location_rating = Table(
    "location_rating", Base.metadata,
    Column("location_id", Integer, ForeignKey("locations.id", ondelete="CASCADE"), primary_key=True),
    Column("rating_id", Integer, ForeignKey("ratings.id", ondelete="CASCADE"), primary_key=True),
)


# ── ORM Models ────────────────────────────────────────────────────────────

class DescriptionModel(Base):
    __tablename__ = "descriptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    characteristics: Mapped[str | None] = mapped_column(Text, default=None)
    backstory: Mapped[str | None] = mapped_column(Text, default=None)


class ImageModel(Base):
    """Metadata for a file-backed image (see app/infrastructure/images).

    Pixels live on disk, addressed by ``sha256``; this row only records
    enough to dedup, resolve paths, and display without decoding the file.
    """
    __tablename__ = "images"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    ext: Mapped[str] = mapped_column(String(16), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class EventModel(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description_id: Mapped[int | None] = mapped_column(ForeignKey("descriptions.id"))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    description: Mapped[DescriptionModel | None] = relationship(lazy="selectin")
    organizations: Mapped[list[OrganizationModel]] = relationship(
        secondary=event_organization, back_populates="events", lazy="selectin",
    )
    characters: Mapped[list[CharacterModel]] = relationship(
        secondary=event_character, back_populates="events", lazy="selectin",
    )
    items: Mapped[list[ItemModel]] = relationship(
        secondary=event_item, back_populates="events", lazy="selectin",
    )
    locations: Mapped[list[LocationModel]] = relationship(
        secondary=event_location, back_populates="events", lazy="selectin",
    )


class OrganizationModel(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description_id: Mapped[int | None] = mapped_column(ForeignKey("descriptions.id"))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    tasks: Mapped[str | None] = mapped_column(Text, default=None)
    music_url: Mapped[str | None] = mapped_column(Text, default=None)
    image: Mapped[str | None] = mapped_column(Text, default=None)  # legacy base64; NULL after migration
    image_id: Mapped[int | None] = mapped_column(
        ForeignKey("images.id", ondelete="SET NULL"), default=None,
    )
    rating: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    description: Mapped[DescriptionModel | None] = relationship(lazy="selectin")
    # Eager-loaded so presentation/utils/image_utils can resolve a display
    # path synchronously (sha256+ext), without the view ever querying itself.
    image_ref: Mapped[ImageModel | None] = relationship(lazy="selectin")
    events: Mapped[list[EventModel]] = relationship(
        secondary=event_organization, back_populates="organizations", lazy="selectin",
    )
    characters: Mapped[list[CharacterModel]] = relationship(
        secondary=organization_character, back_populates="organizations", lazy="selectin",
    )
    items: Mapped[list[ItemModel]] = relationship(
        secondary=organization_item, back_populates="organizations", lazy="selectin",
    )
    locations: Mapped[list[LocationModel]] = relationship(
        secondary=organization_location, back_populates="organizations", lazy="selectin",
    )


class CharacterModel(Base):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description_id: Mapped[int | None] = mapped_column(ForeignKey("descriptions.id"))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    tasks: Mapped[str | None] = mapped_column(Text, default=None)
    personality: Mapped[str | None] = mapped_column(Text, default=None)
    image: Mapped[str | None] = mapped_column(Text, default=None)  # legacy base64; NULL after migration
    image_id: Mapped[int | None] = mapped_column(
        ForeignKey("images.id", ondelete="SET NULL"), default=None,
    )
    music_url: Mapped[str | None] = mapped_column(Text, default=None)
    rating: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    description: Mapped[DescriptionModel | None] = relationship(lazy="selectin")
    image_ref: Mapped[ImageModel | None] = relationship(lazy="selectin")
    events: Mapped[list[EventModel]] = relationship(
        secondary=event_character, back_populates="characters", lazy="selectin",
    )
    organizations: Mapped[list[OrganizationModel]] = relationship(
        secondary=organization_character, back_populates="characters", lazy="selectin",
    )
    items: Mapped[list[ItemModel]] = relationship(
        secondary=character_item, back_populates="characters", lazy="selectin",
    )
    locations: Mapped[list[LocationModel]] = relationship(
        secondary=character_location, back_populates="characters", lazy="selectin",
    )
    ratings: Mapped[list[RatingModel]] = relationship(
        secondary=character_rating, back_populates="characters", lazy="selectin",
    )


class ItemModel(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description_id: Mapped[int | None] = mapped_column(ForeignKey("descriptions.id"))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    rating: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    music_url: Mapped[str | None] = mapped_column(Text, default=None)

    description: Mapped[DescriptionModel | None] = relationship(lazy="selectin")
    events: Mapped[list[EventModel]] = relationship(
        secondary=event_item, back_populates="items", lazy="selectin",
    )
    organizations: Mapped[list[OrganizationModel]] = relationship(
        secondary=organization_item, back_populates="items", lazy="selectin",
    )
    characters: Mapped[list[CharacterModel]] = relationship(
        secondary=character_item, back_populates="items", lazy="selectin",
    )
    locations: Mapped[list[LocationModel]] = relationship(
        secondary=item_location, back_populates="items", lazy="selectin",
    )
    ratings: Mapped[list[RatingModel]] = relationship(
        secondary=item_rating, back_populates="items", lazy="selectin",
    )


class LocationModel(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description_id: Mapped[int | None] = mapped_column(ForeignKey("descriptions.id"))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    tasks: Mapped[str | None] = mapped_column(Text, default=None)
    image: Mapped[str | None] = mapped_column(Text, default=None)  # legacy base64; NULL after migration
    image_id: Mapped[int | None] = mapped_column(
        ForeignKey("images.id", ondelete="SET NULL"), default=None,
    )
    music_url: Mapped[str | None] = mapped_column(Text, default=None)
    rating: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    description: Mapped[DescriptionModel | None] = relationship(lazy="selectin")
    image_ref: Mapped[ImageModel | None] = relationship(lazy="selectin")
    events: Mapped[list[EventModel]] = relationship(
        secondary=event_location, back_populates="locations", lazy="selectin",
    )
    organizations: Mapped[list[OrganizationModel]] = relationship(
        secondary=organization_location, back_populates="locations", lazy="selectin",
    )
    characters: Mapped[list[CharacterModel]] = relationship(
        secondary=character_location, back_populates="locations", lazy="selectin",
    )
    items: Mapped[list[ItemModel]] = relationship(
        secondary=item_location, back_populates="locations", lazy="selectin",
    )
    ratings: Mapped[list[RatingModel]] = relationship(
        secondary=location_rating, back_populates="locations", lazy="selectin",
    )


class CharacterSheetModel(Base):
    """Character sheet template (design D1): one row per template.

    ``pages`` holds the whole page/field tree as a JSON string (the domain
    ``SheetTemplate.to_dict()``); the document is read/written in one piece.
    """
    __tablename__ = "character_sheets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    orientation: Mapped[str] = mapped_column(String(16), nullable=False)
    pages: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class GameSettingsModel(Base):
    __tablename__ = "game_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")


class RatingModel(Base):
    __tablename__ = "ratings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    description_id: Mapped[int | None] = mapped_column(ForeignKey("descriptions.id"))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False)

    description: Mapped[DescriptionModel | None] = relationship(lazy="selectin")
    characters: Mapped[list[CharacterModel]] = relationship(
        secondary=character_rating, back_populates="ratings", lazy="selectin",
    )
    items: Mapped[list[ItemModel]] = relationship(
        secondary=item_rating, back_populates="ratings", lazy="selectin",
    )
    locations: Mapped[list[LocationModel]] = relationship(
        secondary=location_rating, back_populates="ratings", lazy="selectin",
    )
