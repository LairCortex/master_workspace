from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.domain.entities.base import BaseEntity

if TYPE_CHECKING:
    from app.domain.entities.character import Character
    from app.domain.entities.item import Item
    from app.domain.entities.location import Location


@dataclass
class Organization(BaseEntity):
    tasks: str | None = None
    image: str | None = None
    characters: list[Character] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)
