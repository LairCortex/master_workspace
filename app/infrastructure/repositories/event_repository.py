"""Event repository."""
from __future__ import annotations

from typing import Sequence

from sqlalchemy import or_, select

from app.infrastructure.db.models import DescriptionModel, EventModel
from app.infrastructure.repositories.base_repository import BaseRepository


class EventRepository(BaseRepository[EventModel]):
    def __init__(self, session) -> None:
        super().__init__(session, EventModel)

    async def search(self, query: str) -> Sequence[EventModel]:
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

    async def get_all_ordered(self) -> Sequence[EventModel]:
        stmt = select(self._model).order_by(self._model.start_date)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_events_at_date(self, target_date) -> Sequence[EventModel]:
        """Return events whose date range covers the target date."""
        stmt = (
            select(self._model)
            .where(self._model.start_date <= target_date)
            .where(self._model.end_date >= target_date)
            .order_by(self._model.start_date)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()
