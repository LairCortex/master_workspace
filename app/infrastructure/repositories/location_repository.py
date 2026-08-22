"""Location repository."""
from __future__ import annotations

from sqlalchemy import select

from app.infrastructure.db.models import LocationModel
from app.infrastructure.repositories.base_repository import BaseRepository


class LocationRepository(BaseRepository[LocationModel]):
    def __init__(self, session) -> None:
        super().__init__(session, LocationModel)
