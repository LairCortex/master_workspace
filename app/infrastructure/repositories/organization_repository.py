"""Organization repository."""
from __future__ import annotations


from app.infrastructure.db.models import OrganizationModel
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.coord_mapping import CoordMappingMixin


class OrganizationRepository(CoordMappingMixin, BaseRepository[OrganizationModel]):
    """Dated table: dates map through the coordinate resolver (C3a, D3)."""

    def __init__(self, session) -> None:
        super().__init__(session, OrganizationModel)
