"""Organization repository."""
from __future__ import annotations


from app.infrastructure.db.models import OrganizationModel
from app.infrastructure.repositories.base_repository import BaseRepository


class OrganizationRepository(BaseRepository[OrganizationModel]):
    def __init__(self, session) -> None:
        super().__init__(session, OrganizationModel)
