from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.domain.entities.base import BaseEntity

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
