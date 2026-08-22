from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.domain.entities.base import BaseEntity

if TYPE_CHECKING:
    from app.domain.entities.location import Location


@dataclass
class Item(BaseEntity):
    locations: list[Location] = field(default_factory=list)
