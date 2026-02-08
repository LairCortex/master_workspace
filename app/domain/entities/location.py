from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.entities.character import Character
    from app.domain.entities.organization import Organization
    from app.domain.entities.rating import Rating

from app.domain.entities.description import Description
from app.domain.entities.event import _validate_base


@dataclass
class Location:
    name: str
    description: Description
    start_date: date
    end_date: date
    id: int | None = None
    tasks: str | None = None
    image: str | None = None
    characters: list[Character] = field(default_factory=list)
    organizations: list[Organization] = field(default_factory=list)
    ratings: list[Rating] = field(default_factory=list)

    def __post_init__(self) -> None:
        _validate_base(self.name, self.description, self.start_date, self.end_date)
