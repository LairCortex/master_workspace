"""Event-type repository (per-game ordered set of event types)."""
from __future__ import annotations

from typing import Sequence

from sqlalchemy import func, select

from app.infrastructure.db.models import EventTypeModel
from app.infrastructure.repositories.base_repository import BaseRepository


class EventTypeRepository(BaseRepository[EventTypeModel]):
    def __init__(self, session) -> None:
        super().__init__(session, EventTypeModel)

    async def get_all_ordered(self) -> Sequence[EventTypeModel]:
        """Types in display order (``sort_order``, ties by id)."""
        stmt = select(self._model).order_by(self._model.sort_order, self._model.id)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def next_sort_order(self) -> int:
        """Append position: one past the current maximum (0 for an empty set)."""
        result = await self._session.execute(select(func.max(self._model.sort_order)))
        current = result.scalar()
        return 0 if current is None else current + 1
