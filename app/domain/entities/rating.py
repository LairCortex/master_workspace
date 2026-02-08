from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.domain.entities.description import Description


@dataclass
class Rating:
    description: Description
    start_date: date
    end_date: date | None = None
    level: int = 1
    id: int | None = None

    def __post_init__(self) -> None:
        if self.description is None:
            raise ValueError("description is required")
        if self.start_date is None:
            raise ValueError("start_date is required")
        if self.level is None:
            raise ValueError("level is required")
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
