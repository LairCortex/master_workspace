from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.entities.item import Item
    from app.domain.entities.location import Location
    from app.domain.entities.rating import Rating

from app.domain.entities.description import Description
from app.domain.entities.event import _validate_base


@dataclass
class Character:
    name: str
    description: Description
    start_date: date
    end_date: date
    id: int | None = None
    tasks: str | None = None
    personality: str | None = None
    image: str | None = None
    items: list[Item] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)
    ratings: list[Rating] = field(default_factory=list)

    def __post_init__(self) -> None:
        _validate_base(self.name, self.description, self.start_date, self.end_date)
