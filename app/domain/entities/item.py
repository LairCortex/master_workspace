from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.domain.entities.base import BaseEntity

if TYPE_CHECKING:
    from app.domain.entities.location import Location


@dataclass
class Item(BaseEntity):
    #: reference to the ``images`` record of the item's picture (NRI-0022);
    #: the org/character/location dataclasses still carry the retired base64
    #: ``image`` string here — the item never had one, its slot is the link
    image_id: int | None = None
    locations: list[Location] = field(default_factory=list)
