"""SQLAlchemy ORM models for NRI scenario manager."""
from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.domain.date_era import era_key
from app.domain.game_calendar import (
    DateField,
    GameCoord,
    InvalidGameDateError,
    MonthDay,
    StandardCalendar,
    as_game_coord,
    current_calendar,
)
from app.infrastructure.calendar_storage import (
    CoordDecoded,
    decode_coord,
    encode_coord,
)


class Base(DeclarativeBase):
    pass


# ── Era-aware date columns (add-era-aware-dates, design D3) ───────────────
# Every dated table carries the era flags (INTEGER 0/1, DEFAULT 0 so
# pre-era rows and old-version INSERTs mean «н.э.») plus nullable derived
# keys. Keys stay NULLable on purpose: an old app version INSERTs without
# them (compatibility requirement), and the python key reconcile run from
# ``Application.start()`` recomputes them on the next open (C2, design D5).
# The hooks below keep keys in sync on every write the new version itself
# performs.
#
# Piece C3a (design D1) adds the nullable ``start_coord``/``end_coord`` TEXT
# slots beside the date columns: filled, the coordinate column IS the truth
# (spec «Истина следует за заполненностью»); empty, the date columns are
# read exactly as before, so a standard game never notices the new columns.

_coord_logger = logging.getLogger(__name__)

#: Accepted spellings of a date slot in the resolver calls: the domain
#: ``DateField`` enum (report/service side) or the plain storage prefix.
_DATE_SLOTS = {DateField.START: "start", DateField.END: "end", "start": "start", "end": "end"}


def _date_slot(field: DateField | str) -> str:
    """Normalize a date-slot reference to its column-name prefix."""
    try:
        return _DATE_SLOTS[field]
    except KeyError:
        raise ValueError(f"unknown date slot {field!r} (expected DateField or 'start'/'end')") from None


def _slot_value(row, slot: str):
    """The row's own reading branch (C3a design D3) — side-effect free.

    Returns ``(value, corrupted_reasons)``: a decodable coordinate column
    answers with its coordinate, an empty one with the stored ``date`` slot,
    and an unreadable text with the date fallback *plus* the codec's reasons
    (the repair itself belongs to :func:`resolve_coord`, the only caller
    allowed to clear and log — reading must stay safe inside flush hooks).
    """
    coord_column, date_column = f"{slot}_coord", f"{slot}_date_raw"
    raw = getattr(row, coord_column)
    if raw:
        decoded = decode_coord(raw)
        if isinstance(decoded, CoordDecoded):
            return decoded.coord, None
        return getattr(row, date_column), decoded.reasons
    return getattr(row, date_column), None


def resolve_coord(row, field: DateField | str) -> GameCoord | None:
    """Storage resolver, read direction for the services (C3a design D3).

    One branch for every reader above: a filled coordinate column wins —
    decoded through the domain codec; unreadable text is *repaired* the way
    spec «Повреждённая координатная колонка» demands (the row falls back to
    its date columns, the column is cleared, the table+id go to the log);
    an empty column means «the date lives in the date columns», with the
    stored ``date`` read as the ``MonthDay`` of its own numbers.  ``None``
    only when the fallback slot holds no date at all.  Row attributes are
    read through :func:`_slot_value`, the same branch the ``start_date``/
    ``end_date`` properties hand to every other consumer (design D3: the
    layers above never learn the two storages exist).
    """
    slot = _date_slot(field)
    value, corrupted = _slot_value(row, slot)
    if corrupted is not None:
        table = getattr(type(row), "__tablename__", type(row).__name__)
        _coord_logger.warning(
            "Corrupted %s coordinate in %s (id=%s): %s — coordinate column cleared",
            slot,
            table,
            getattr(row, "id", None),
            "; ".join(f"{p.code}: {p.message}" for p in corrupted),
        )
        setattr(row, f"{slot}_coord", None)
    return as_game_coord(value)


def assign_coord(row, field: DateField | str, coord: GameCoord | date | None) -> None:
    """Storage resolver, write direction (C3a design D3).

    The routing branch lives nowhere else: the row's coordinate column
    already filled → the coordinate stays there (its truth must not split
    across storages); else the active calendar is the «Стандартный» preset →
    the legacy date columns (a standard game keeps living in them, the
    coordinate columns stay empty); else an active custom calendar → the
    coordinate columns, while the date columns are *never* updated
    («мёртвое наследие, не зеркало» — design D1).  A plain ``datetime.date``
    is the ``MonthDay`` of its numbers on the way in (D4); a coordinate the
    Gregorian date columns cannot physically hold (an intercalary day, an
    absent month or day) refuses with the core's ``InvalidGameDateError`` —
    the standard route stores real dates only, no normalization (D6).
    """
    coord = as_game_coord(coord)
    slot = _date_slot(field)
    coord_column, date_column = f"{slot}_coord", f"{slot}_date_raw"
    use_coord = bool(getattr(row, coord_column)) or not isinstance(
        current_calendar(), StandardCalendar
    )
    if use_coord:
        setattr(row, coord_column, None if coord is None else encode_coord(coord))
        return
    if coord is None:
        setattr(row, date_column, None)
        return
    if isinstance(coord, MonthDay):
        try:
            setattr(row, date_column, date(coord.year, coord.month, coord.day))
            return
        except ValueError:
            pass  # not representable as a Gregorian date — refused below
    raise InvalidGameDateError(
        f"coordinate {coord!r} cannot be stored in the standard calendar's "
        f"{date_column} column (no such date exists in it)"
    )


class CoordDateSlots:
    """The date attributes ARE the storage branch (C3a, designs D1/D3).

    Every layer above the repositories — timeline rows, dialogs, search,
    the snapshot, ``getattr(row, "start_date")`` anywhere — reads and writes
    dates under these names, so the «coord column filled ⇒ the truth is in
    it» law of spec «Координаты в записях датированных таблиц» must live
    exactly here, on the attribute itself.  Reading is the pure
    :func:`_slot_value` branch (no clearing, no logging — those belong to
    :func:`resolve_coord` on the repair paths): a row whose coordinate
    column holds the truth hands up the game coordinate and never re-reads
    its dead date columns, while every other row answers its stored ``date``
    exactly as before (a standard game notices nothing).  Writing a plain
    ``date`` or ``None`` touches the legacy date column directly — the byte
    route of every pre-C3a call site and construction (seeding a row that
    way leaves its coordinate columns empty, i.e. «the date lives in the
    date columns», which is exactly what the storage law prescribes) —
    while writing a :data:`GameCoord` hands over to the one routed
    :func:`assign_coord`: a coordinate physically cannot live anywhere else
    than where the route sends it.
    """

    start_date = property(
        lambda self: _slot_value(self, "start")[0],
        lambda self, value: _set_slot(self, "start", value),
        doc="Game-calendar coordinate or (standard games) the stored date.",
    )
    end_date = property(
        lambda self: _slot_value(self, "end")[0],
        lambda self, value: _set_slot(self, "end", value),
        doc="Game-calendar coordinate or (standard games) the stored date.",
    )


def _set_slot(row, slot: str, value: GameCoord | date | None) -> None:
    """One attribute-write branch (design D3): a game coordinate takes the
    routed :func:`assign_coord` (there is no other place it can live), a
    plain ``date``/``None`` keeps the direct legacy-column write of every
    pre-C3a construction and mutation site."""
    if value is None or isinstance(value, date):
        setattr(row, f"{slot}_date_raw", value)
        return
    assign_coord(row, slot, value)


def _sync_era_keys(mapper, connection, target) -> None:
    """Derive start_key/end_key from the resolved (coordinate, era) pairs.

    Runs in before_insert/before_update for the six dated tables, so every
    new-version write lands with keys equal to the app-side ``era_key`` (and
    to the startup key reconcile of design D5). Since C3a (design D3) the
    keyed truth per slot is whatever ``resolve_coord`` reads — the
    coordinate column when filled, the date columns otherwise — so a record
    carrying a game coordinate is ordered by it, while standard rows keep
    their bit-identical numbers. An era flag not yet set on a new
    instance reads as «н.э.» — exactly how ``DEFAULT 0`` reads pre-era and
    old-version rows; repositories load full rows before mutating, so the
    date/era attributes are always present on update.
    """
    start = resolve_coord(target, DateField.START)
    if start is not None:
        target.start_key = era_key(start, bool(target.start_bc))
    end = resolve_coord(target, DateField.END)
    if end is not None:
        target.end_key = era_key(end, bool(target.end_bc))
    else:
        target.end_key = None


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


class EventTypeModel(Base):
    """A per-game event type (W4).

    ``color_index`` targets a ``color.chart.{1..8}`` token (1-based);
    ``sort_order`` is the user-editable display order. Rows reach existing
    game DBs via ``create_all`` in ``init_db()``, which also seeds the six
    NRI defaults once the table is created empty.
    """

    __tablename__ = "event_types"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    color_index: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class EventModel(CoordDateSlots, Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description_id: Mapped[int | None] = mapped_column(ForeignKey("descriptions.id"))
    # The ORM attributes carry the storage name plus ``_raw`` (C3a, D3): the
    # public ``start_date``/``end_date`` names are the coord-first properties
    # of CoordDateSlots; ``mapped_column`` keeps the legacy column names.
    start_date_raw: Mapped[date] = mapped_column("start_date", Date, nullable=False)
    end_date_raw: Mapped[date | None] = mapped_column("end_date", Date, nullable=True)
    # Era flags (0 = н.э.) + derived chronological keys (design D3); the keys
    # are re-synced by the _sync_era_keys hooks below on every new-version write.
    start_bc: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    end_bc: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    start_key: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    end_key: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # Game-coordinate storage slots (C3a, design D1): NULL means «the date
    # lives in the date columns», an unparseable text is repaired by the
    # resolver below; the writing route decides which slot a value enters.
    start_coord: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    end_coord: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # Optional type (W4); deleting a type unlinks events (SET NULL).
    event_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("event_types.id", ondelete="SET NULL"), nullable=True, default=None,
    )

    description: Mapped[DescriptionModel | None] = relationship(lazy="selectin")
    event_type: Mapped[EventTypeModel | None] = relationship(lazy="selectin")
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


class OrganizationModel(CoordDateSlots, Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description_id: Mapped[int | None] = mapped_column(ForeignKey("descriptions.id"))
    # The ORM attributes carry the storage name plus ``_raw`` (C3a, D3): the
    # public ``start_date``/``end_date`` names are the coord-first properties
    # of CoordDateSlots; ``mapped_column`` keeps the legacy column names.
    start_date_raw: Mapped[date] = mapped_column("start_date", Date, nullable=False)
    end_date_raw: Mapped[date | None] = mapped_column("end_date", Date, nullable=True)
    # Era flags (0 = н.э.) + derived chronological keys (design D3); the keys
    # are re-synced by the _sync_era_keys hooks below on every new-version write.
    start_bc: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    end_bc: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    start_key: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    end_key: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # Game-coordinate storage slots (C3a, design D1): NULL means «the date
    # lives in the date columns», an unparseable text is repaired by the
    # resolver below; the writing route decides which slot a value enters.
    start_coord: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    end_coord: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
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


class CharacterModel(CoordDateSlots, Base):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description_id: Mapped[int | None] = mapped_column(ForeignKey("descriptions.id"))
    # The ORM attributes carry the storage name plus ``_raw`` (C3a, D3): the
    # public ``start_date``/``end_date`` names are the coord-first properties
    # of CoordDateSlots; ``mapped_column`` keeps the legacy column names.
    start_date_raw: Mapped[date] = mapped_column("start_date", Date, nullable=False)
    end_date_raw: Mapped[date | None] = mapped_column("end_date", Date, nullable=True)
    # Era flags (0 = н.э.) + derived chronological keys (design D3); the keys
    # are re-synced by the _sync_era_keys hooks below on every new-version write.
    start_bc: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    end_bc: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    start_key: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    end_key: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # Game-coordinate storage slots (C3a, design D1): NULL means «the date
    # lives in the date columns», an unparseable text is repaired by the
    # resolver below; the writing route decides which slot a value enters.
    start_coord: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    end_coord: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
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


class ItemModel(CoordDateSlots, Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description_id: Mapped[int | None] = mapped_column(ForeignKey("descriptions.id"))
    # The ORM attributes carry the storage name plus ``_raw`` (C3a, D3): the
    # public ``start_date``/``end_date`` names are the coord-first properties
    # of CoordDateSlots; ``mapped_column`` keeps the legacy column names.
    start_date_raw: Mapped[date] = mapped_column("start_date", Date, nullable=False)
    end_date_raw: Mapped[date | None] = mapped_column("end_date", Date, nullable=True)
    # Era flags (0 = н.э.) + derived chronological keys (design D3); the keys
    # are re-synced by the _sync_era_keys hooks below on every new-version write.
    start_bc: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    end_bc: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    start_key: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    end_key: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # Game-coordinate storage slots (C3a, design D1): NULL means «the date
    # lives in the date columns», an unparseable text is repaired by the
    # resolver below; the writing route decides which slot a value enters.
    start_coord: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    end_coord: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
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


class LocationModel(CoordDateSlots, Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description_id: Mapped[int | None] = mapped_column(ForeignKey("descriptions.id"))
    # The ORM attributes carry the storage name plus ``_raw`` (C3a, D3): the
    # public ``start_date``/``end_date`` names are the coord-first properties
    # of CoordDateSlots; ``mapped_column`` keeps the legacy column names.
    start_date_raw: Mapped[date] = mapped_column("start_date", Date, nullable=False)
    end_date_raw: Mapped[date | None] = mapped_column("end_date", Date, nullable=True)
    # Era flags (0 = н.э.) + derived chronological keys (design D3); the keys
    # are re-synced by the _sync_era_keys hooks below on every new-version write.
    start_bc: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    end_bc: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    start_key: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    end_key: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # Game-coordinate storage slots (C3a, design D1): NULL means «the date
    # lives in the date columns», an unparseable text is repaired by the
    # resolver below; the writing route decides which slot a value enters.
    start_coord: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    end_coord: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
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


class GameSettingsModel(Base):
    __tablename__ = "game_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")


class RatingModel(CoordDateSlots, Base):
    __tablename__ = "ratings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    description_id: Mapped[int | None] = mapped_column(ForeignKey("descriptions.id"))
    # The ORM attributes carry the storage name plus ``_raw`` (C3a, D3): the
    # public ``start_date``/``end_date`` names are the coord-first properties
    # of CoordDateSlots; ``mapped_column`` keeps the legacy column names.
    start_date_raw: Mapped[date] = mapped_column("start_date", Date, nullable=False)
    end_date_raw: Mapped[date | None] = mapped_column("end_date", Date, nullable=True)
    # Era flags (0 = н.э.) + derived chronological keys (design D3); the keys
    # are re-synced by the _sync_era_keys hooks below on every new-version write.
    start_bc: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    end_bc: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    start_key: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    end_key: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # Game-coordinate storage slots (C3a, design D1): NULL means «the date
    # lives in the date columns», an unparseable text is repaired by the
    # resolver below; the writing route decides which slot a value enters.
    start_coord: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    end_coord: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
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


class CharacterSheetModel(Base):
    """A character-sheet template (epic A1).

    One row per sheet. ``name`` is unique per game DB. ``pages`` holds the
    single-page layout as a JSON array (``[{"fields": [...]}]``) — see the
    domain ``SheetTemplate`` for the shape. New tables reach existing DBs via
    ``create_all`` in ``init_db()`` (no ALTER of existing tables required).
    """

    __tablename__ = "character_sheets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    orientation: Mapped[str] = mapped_column(String(16), nullable=False, default="portrait", server_default="portrait")
    pages: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class CharacterSheetInstanceModel(Base):
    """A filled character-sheet instance of the current game (epic B).

    ``name`` is unique per game DB. ``template_id`` is immutable after create
    (ON DELETE RESTRICT: a template with instances cannot be dropped).
    ``character_id`` is optional and unique among non-NULL values; SQLite
    allows several NULLs so unbound sheets do not collide. ``values`` is the
    JSON object ``{field_id: value}``.
    """

    __tablename__ = "character_sheet_instances"
    __table_args__ = (UniqueConstraint("character_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("character_sheets.id", ondelete="RESTRICT"), nullable=False
    )
    character_id: Mapped[int | None] = mapped_column(
        ForeignKey("characters.id", ondelete="SET NULL"), nullable=True, default=None
    )
    values: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


# ── Era-key sync hooks (design D2/D3) ─────────────────────────────────────
# Keep the derived chronological keys of every new-version write consistent
# with its (date, era) pair: inserts and date/era edits land with correct
# keys, so ORDER BY/FILTER on start_key/end_key never depends on the
# startup key reconcile having seen the row yet.
for _dated_model in (
    EventModel,
    OrganizationModel,
    CharacterModel,
    ItemModel,
    LocationModel,
    RatingModel,
):
    sqlalchemy_event.listen(_dated_model, "before_insert", _sync_era_keys)
    sqlalchemy_event.listen(_dated_model, "before_update", _sync_era_keys)
