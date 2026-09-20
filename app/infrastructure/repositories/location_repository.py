"""Location repository."""
from __future__ import annotations


from app.infrastructure.db.models import LocationModel
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.coord_mapping import CoordMappingMixin


class LocationRepository(CoordMappingMixin, BaseRepository[LocationModel]):
    """Dated table: dates map through the coordinate resolver (C3a, D3)."""

    def __init__(self, session) -> None:
        super().__init__(session, LocationModel)
