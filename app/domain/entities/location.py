from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.domain.entities.base import BaseEntity

if TYPE_CHECKING:
    from app.domain.entities.character import Character
    from app.domain.entities.organization import Organization


@dataclass
class Location(BaseEntity):
    tasks: str | None = None
    image: str | None = None
    characters: list[Character] = field(default_factory=list)
    organizations: list[Organization] = field(default_factory=list)
