from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.domain.entities.base import BaseEntity
from app.domain.time_of_day import TimeOfDay

if TYPE_CHECKING:
    from app.domain.entities.character import Character
    from app.domain.entities.event_type import EventType
    from app.domain.entities.item import Item
    from app.domain.entities.location import Location
    from app.domain.entities.organization import Organization


@dataclass
class Event(BaseEntity):
    organizations: list[Organization] = field(default_factory=list)
    characters: list[Character] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)
    event_type: EventType | None = None
    # NRI-0023 (task 1.3, design Д2): optional wall-clock start time in the
    # active game calendar; None means «весь день, с утра» and is never
    # defaulted into 00:00.  Only the start carries a time — the end stays a
    # day (or absent) as before.
    start_time: TimeOfDay | None = None
