"""Generic entity service for CRUD on any entity type."""
from __future__ import annotations

from datetime import date
from typing import Any, Sequence

from app.infrastructure.repositories.base_repository import BaseRepository


class EntityService:
    def __init__(self, repo: BaseRepository, description_repo: BaseRepository) -> None:
        self._repo = repo
        self._desc_repo = description_repo

    async def create_entity(
        self,
        name: str,
        characteristics: str,
        backstory: str,
        start_date: date,
        end_date: date,
        **extra: Any,
    ):
        desc = await self._desc_repo.create(characteristics=characteristics, backstory=backstory)
        return await self._repo.create(
            name=name,
            description_id=desc.id,
            start_date=start_date,
            end_date=end_date,
            **extra,
        )

    async def get_entity(self, entity_id: int):
        return await self._repo.get_by_id(entity_id)

    async def get_all(self) -> Sequence:
        return await self._repo.get_all()

    async def update_entity(self, entity_id: int, **kwargs: Any):
        return await self._repo.update(entity_id, **kwargs)

    async def delete_entity(self, entity_id: int) -> bool:
        return await self._repo.delete(entity_id)
