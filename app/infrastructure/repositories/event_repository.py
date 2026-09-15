"""Event repository."""
from __future__ import annotations

from typing import Sequence

from sqlalchemy import or_, select

from app.infrastructure.db.models import EventModel
from app.infrastructure.repositories.base_repository import BaseRepository


class EventRepository(BaseRepository[EventModel]):
    """Events ordered/filtered by the era key (design D2/D4), never by raw
    ``start_date``/``end_date`` text — across the era border the lexicographic
    date order disagrees with chronology."""

    def __init__(self, session) -> None:
        super().__init__(session, EventModel)

    async def get_all_ordered(self) -> Sequence[EventModel]:
        stmt = select(self._model).order_by(
            self._model.start_key, self._model.id
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_events_at_date(self, target_key: int) -> Sequence[EventModel]:
        """Return events whose interval covers the target moment.

        ``target_key`` is the shared chronological key (:func:`era_key`) of
        the (date, era) pair — the window/query passes keys, not dates.
        Events with NULL end_key are treated as ongoing (infinite interval,
        covered by any window at/after the start).
        """
        stmt = (
            select(self._model)
            .where(self._model.start_key <= target_key)
            .where(
                or_(
                    self._model.end_key.is_(None),
                    self._model.end_key >= target_key,
                )
            )
            .order_by(self._model.start_key, self._model.id)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()
