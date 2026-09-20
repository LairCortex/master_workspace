"""Rating — a dated, leveled annotation (design D4 since piece C3a).

Like every dated domain type the rating's dates are game-calendar
coordinates: field names unchanged, a plain ``datetime.date`` is coerced to
the equal ``MonthDay`` on input, «end ≥ start» runs through ``cmp_era_dates``
on the coordinates, and the start coordinate must exist in the active
calendar (the ``era_key`` dispatcher's ``InvalidGameDateError``, no silent
normalization).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.date_era import cmp_era_dates, era_key
from app.domain.entities.description import Description
from app.domain.game_calendar import GameCoord, as_game_coord


@dataclass
class Rating:
    description: Description
    start_date: GameCoord
    end_date: GameCoord | None = None
    level: int = 1
    id: int | None = None
    start_bc: bool = False
    end_bc: bool = False

    def __post_init__(self) -> None:
        if self.description is None:
            raise ValueError("description is required")
        # D4: the input date is the MonthDay of the same numbers.
        self.start_date = as_game_coord(self.start_date)
        self.end_date = as_game_coord(self.end_date)
        if self.start_date is None:
            raise ValueError("start_date is required")
        if self.level is None:
            raise ValueError("level is required")
        # The start coordinate must exist in the active calendar (D4/D6).
        era_key(self.start_date, self.start_bc)
        if self.end_date is not None and cmp_era_dates(
            (self.end_date, self.end_bc), (self.start_date, self.start_bc)
        ) < 0:
            raise ValueError("end_date must not be before start_date")
