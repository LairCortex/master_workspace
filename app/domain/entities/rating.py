from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.domain.date_era import cmp_era_dates
from app.domain.entities.description import Description


@dataclass
class Rating:
    description: Description
    start_date: date
    end_date: date | None = None
    level: int = 1
    id: int | None = None
    start_bc: bool = False
    end_bc: bool = False

    def __post_init__(self) -> None:
        if self.description is None:
            raise ValueError("description is required")
        if self.start_date is None:
            raise ValueError("start_date is required")
        if self.level is None:
            raise ValueError("level is required")
        if self.end_date is not None and cmp_era_dates(
            (self.end_date, self.end_bc), (self.start_date, self.start_bc)
        ) < 0:
            raise ValueError("end_date must not be before start_date")
