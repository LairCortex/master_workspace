from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.entities.character import Character
    from app.domain.entities.item import Item
    from app.domain.entities.location import Location
    from app.domain.entities.organization import Organization

from app.domain.entities.description import Description


def _validate_base(name: str, description: Description | None, start_date: date | None, end_date: date | None) -> None:
    if not name:
        raise ValueError("name is required")
    if description is None:
        raise ValueError("description is required")
    if start_date is None:
        raise ValueError("start_date is required")
    if end_date is not None and end_date < start_date:
        raise ValueError("end_date must not be before start_date")


@dataclass
class Event:
    name: str
    description: Description
    start_date: date
    end_date: date | None = None
    id: int | None = None
    organizations: list[Organization] = field(default_factory=list)
    characters: list[Character] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)

    def __post_init__(self) -> None:
        _validate_base(self.name, self.description, self.start_date, self.end_date)
