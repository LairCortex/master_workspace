"""Base entity dataclass — common fields and validation shared by all entities.

Since piece C3a (design D4) the date fields store game-calendar coordinates:
the field names stay exactly as they were, their type is now ``GameCoord``
(and ``GameCoord | None`` where an absent date was allowed), and a plain
``datetime.date`` is still accepted on input — ``__post_init__`` coerces it
to the equal ``MonthDay`` (design D4), so pre-C3a call sites keep their
numbers.  Validation keeps working through the same helpers: «end ≥ start»
is decided by ``cmp_era_dates`` on the coordinates across the era border,
and a coordinate the active calendar does not contain is refused by the
``era_key`` dispatcher with ``InvalidGameDateError`` — no silent
normalization (C0 design D6).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.date_era import cmp_era_dates, era_key
from app.domain.entities.description import Description
from app.domain.entities.rating import Rating
from app.domain.game_calendar import GameCoord, as_game_coord


def _validate_base(
    name: str,
    description: Description | None,
    start_date: GameCoord | None,
    end_date: GameCoord | None,
    start_bc: bool = False,
    end_bc: bool = False,
) -> None:
    if not name:
        raise ValueError("name is required")
    if description is None:
        raise ValueError("description is required")
    if start_date is None:
        raise ValueError("start_date is required")
    # The start coordinate must exist in the active calendar: era_key answers
    # with the distinguishable InvalidGameDateError, never a normalization
    # (spec «Дня не существует в активном календаре», designs D4/D6).
    era_key(start_date, start_bc)
    if end_date is not None and cmp_era_dates(
        (end_date, end_bc), (start_date, start_bc)
    ) < 0:
        raise ValueError("end_date must not be before start_date")


@dataclass
class BaseEntity:
    name: str
    description: Description
    start_date: GameCoord
    end_date: GameCoord | None = None
    id: int | None = None
    music_url: str | None = None
    ratings: list[Rating] = field(default_factory=list)
    start_bc: bool = False
    end_bc: bool = False

    def __post_init__(self) -> None:
        # D4: «дата = координата» — an input datetime.date arrives as the
        # MonthDay of the same numbers, a coordinate passes through untouched.
        self.start_date = as_game_coord(self.start_date)
        self.end_date = as_game_coord(self.end_date)
        _validate_base(
            self.name,
            self.description,
            self.start_date,
            self.end_date,
            self.start_bc,
            self.end_bc,
        )
