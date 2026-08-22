"""Item repository."""
from __future__ import annotations

from sqlalchemy import select

from app.infrastructure.db.models import ItemModel
from app.infrastructure.repositories.base_repository import BaseRepository


class ItemRepository(BaseRepository[ItemModel]):
    def __init__(self, session) -> None:
        super().__init__(session, ItemModel)
