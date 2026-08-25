"""Character sheet repository."""
from __future__ import annotations

from sqlalchemy import select

from app.infrastructure.db.models import CharacterSheetModel
from app.infrastructure.repositories.base_repository import BaseRepository


class CharacterSheetRepository(BaseRepository[CharacterSheetModel]):
    def __init__(self, session) -> None:
        super().__init__(session, CharacterSheetModel)

    async def get_by_name(self, name: str) -> CharacterSheetModel | None:
        stmt = select(self._model).where(self._model.name == name)
        result = await self._session.execute(stmt)
        return result.scalars().first()
