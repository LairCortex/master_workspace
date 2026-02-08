"""Event application service."""
from __future__ import annotations

from datetime import date
from typing import Any, Sequence

from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.event_repository import EventRepository


class EventService:
    def __init__(self, event_repo: EventRepository, description_repo: BaseRepository) -> None:
        self._event_repo = event_repo
        self._desc_repo = description_repo

    async def create_event(
        self,
        name: str,
        characteristics: str,
        backstory: str,
        start_date: date,
        end_date: date,
        **extra: Any,
    ):
        desc = await self._desc_repo.create(characteristics=characteristics, backstory=backstory)
        return await self._event_repo.create(
            name=name,
            description_id=desc.id,
            start_date=start_date,
            end_date=end_date,
            **extra,
        )

    async def get_event(self, event_id: int):
        return await self._event_repo.get_by_id(event_id)

    async def get_all_events(self) -> Sequence:
        return await self._event_repo.get_all_ordered()

    async def update_event(self, event_id: int, **kwargs: Any):
        return await self._event_repo.update(event_id, **kwargs)

    async def delete_event(self, event_id: int) -> bool:
        return await self._event_repo.delete(event_id)

    async def get_events_at_date(self, target_date: date) -> Sequence:
        return await self._event_repo.get_events_at_date(target_date)
