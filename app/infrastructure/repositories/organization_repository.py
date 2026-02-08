"""Organization repository."""
from __future__ import annotations

from typing import Sequence

from sqlalchemy import or_, select

from app.infrastructure.db.models import DescriptionModel, OrganizationModel
from app.infrastructure.repositories.base_repository import BaseRepository


class OrganizationRepository(BaseRepository[OrganizationModel]):
    def __init__(self, session) -> None:
        super().__init__(session, OrganizationModel)

    async def search(self, query: str) -> Sequence[OrganizationModel]:
        stmt = (
            select(self._model)
            .outerjoin(DescriptionModel, self._model.description_id == DescriptionModel.id)
            .where(
                or_(
                    self._model.name.ilike(f"%{query}%"),
                    DescriptionModel.characteristics.ilike(f"%{query}%"),
                    DescriptionModel.backstory.ilike(f"%{query}%"),
                )
            )
        )
        result = await self._session.execute(stmt)
        return result.scalars().unique().all()
