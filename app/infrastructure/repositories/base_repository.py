"""Generic base repository with CRUD operations."""
from __future__ import annotations

from typing import Any, Generic, Sequence, Type, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    def __init__(self, session: AsyncSession, model: Type[T]) -> None:
        self._session = session
        self._model = model

    async def get_by_id(self, entity_id: int) -> T | None:
        stmt = select(self._model).where(self._model.id == entity_id)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def get_all(self) -> Sequence[T]:
        result = await self._session.execute(select(self._model))
        return result.scalars().all()

    async def create(self, **kwargs: Any) -> T:
        obj = self._model(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def update(self, entity_id: int, **kwargs: Any) -> T | None:
        obj = await self.get_by_id(entity_id)
        if obj is None:
            return None
        for key, value in kwargs.items():
            setattr(obj, key, value)
        await self._session.flush()
        return obj

    async def delete(self, entity_id: int) -> bool:
        obj = await self.get_by_id(entity_id)
        if obj is None:
            return False
        await self._session.delete(obj)
        await self._session.flush()
        return True
