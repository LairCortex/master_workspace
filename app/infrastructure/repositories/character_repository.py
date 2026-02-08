"""Character repository."""
from __future__ import annotations

from typing import Sequence

from sqlalchemy import func, or_, select

from app.infrastructure.db.models import CharacterModel, DescriptionModel
from app.infrastructure.repositories.base_repository import BaseRepository


class CharacterRepository(BaseRepository[CharacterModel]):
    def __init__(self, session) -> None:
        super().__init__(session, CharacterModel)

    async def search(self, query: str) -> Sequence[CharacterModel]:
        stmt = (
            select(self._model)
            .outerjoin(DescriptionModel, self._model.description_id == DescriptionModel.id)
            .where(
                or_(
                    func.lower(self._model.name).contains(query.lower()),
                    func.lower(DescriptionModel.characteristics).contains(query.lower()),
                    func.lower(DescriptionModel.backstory).contains(query.lower()),
                )
            )
        )
        result = await self._session.execute(stmt)
        return result.scalars().unique().all()
