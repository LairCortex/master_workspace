"""Rating repository."""
from __future__ import annotations

from app.infrastructure.db.models import RatingModel
from app.infrastructure.repositories.base_repository import BaseRepository


class RatingRepository(BaseRepository[RatingModel]):
    def __init__(self, session) -> None:
        super().__init__(session, RatingModel)
