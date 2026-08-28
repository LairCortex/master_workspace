"""Character sheet template repository."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import CharacterSheetModel
from app.infrastructure.repositories.base_repository import BaseRepository


class CharacterSheetRepository(BaseRepository[CharacterSheetModel]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CharacterSheetModel)

    async def get_by_name(self, name: str) -> CharacterSheetModel | None:
        """Exact-match lookup by name (name is unique per game DB)."""
        result = await self._session.execute(
            select(CharacterSheetModel).where(CharacterSheetModel.name == name)
        )
        return result.scalars().first()
