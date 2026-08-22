"""Base entity dataclass — common fields and validation shared by all entities."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.domain.entities.description import Description
from app.domain.entities.rating import Rating


def _validate_base(
    name: str,
    description: Description | None,
    start_date: date | None,
    end_date: date | None,
) -> None:
    if not name:
        raise ValueError("name is required")
    if description is None:
        raise ValueError("description is required")
    if start_date is None:
        raise ValueError("start_date is required")
    if end_date is not None and end_date < start_date:
        raise ValueError("end_date must not be before start_date")


@dataclass
class BaseEntity:
    name: str
    description: Description
    start_date: date
    end_date: date | None = None
    id: int | None = None
    music_url: str | None = None
    ratings: list[Rating] = field(default_factory=list)

    def __post_init__(self) -> None:
        _validate_base(self.name, self.description, self.start_date, self.end_date)
