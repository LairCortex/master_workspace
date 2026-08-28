"""Character sheet instance repository."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import CharacterSheetInstanceModel
from app.infrastructure.repositories.base_repository import BaseRepository


class CharacterSheetInstanceRepository(BaseRepository[CharacterSheetInstanceModel]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CharacterSheetInstanceModel)

    async def get_by_name(self, name: str) -> CharacterSheetInstanceModel | None:
        """Exact-match lookup by name (name is unique per game DB)."""
        result = await self._session.execute(
            select(CharacterSheetInstanceModel).where(
                CharacterSheetInstanceModel.name == name
            )
        )
        return result.scalars().first()

    async def get_by_character_id(
        self, character_id: int
    ) -> CharacterSheetInstanceModel | None:
        result = await self._session.execute(
            select(CharacterSheetInstanceModel).where(
                CharacterSheetInstanceModel.character_id == character_id
            )
        )
        return result.scalars().first()

    async def count_by_template(self, template_id: int) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(CharacterSheetInstanceModel)
            .where(CharacterSheetInstanceModel.template_id == template_id)
        )
        return int(result.scalar() or 0)
