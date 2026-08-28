"""Filled character-sheet instance service: CRUD, bind, value map.

Create copies the template's current fillable defaults into the stored JSON
map and pins ``template_id`` (no setter afterwards). Name uniqueness and
the one-character-per-instance unique constraint are checked before insert
and again at the DB level (IntegrityError backstop).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy.exc import IntegrityError

from app.application.services.character_sheet_service import (
    CharacterSheetService,
    SheetNotFoundError,
)
from app.domain.entities.character_sheet_instance import defaults_map, iter_instance_image_ids
from app.infrastructure.db.models import CharacterSheetInstanceModel
from app.infrastructure.images.store import ImageStore
from app.infrastructure.repositories.character_sheet_instance_repository import (
    CharacterSheetInstanceRepository,
)


class CharacterSheetInstanceError(Exception):
    """Base error for filled-sheet operations."""


class InstanceNotFoundError(CharacterSheetInstanceError):
    def __init__(self, instance_id: int) -> None:
        super().__init__(f"Заполненный лист {instance_id} не найден")
        self.instance_id = instance_id


class InstanceNameConflictError(CharacterSheetInstanceError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Лист с именем «{name}» уже существует")
        self.name = name


class CharacterAlreadyBoundError(CharacterSheetInstanceError):
    def __init__(self, character_id: int) -> None:
        super().__init__(
            f"Персонаж {character_id} уже привязан к другому заполненному листу"
        )
        self.character_id = character_id


EMPTY_INSTANCE_NAME_ERROR: str = "Имя листа не может быть пустым"


class CharacterSheetInstanceService:
    def __init__(
        self,
        repo: CharacterSheetInstanceRepository,
        sheet_service: CharacterSheetService,
        image_store: ImageStore | None = None,
    ) -> None:
        self._repo = repo
        self._session = repo._session
        self._sheet_service = sheet_service
        self._image_store = image_store

    async def list_instances(self) -> Sequence[CharacterSheetInstanceModel]:
        rows = await self._repo.get_all()
        return sorted(rows, key=lambda r: r.name)

    async def create(self, name: str, template_id: int) -> CharacterSheetInstanceModel:
        name = name.strip()
        if not name:
            raise ValueError(EMPTY_INSTANCE_NAME_ERROR)
        if await self._repo.get_by_name(name) is not None:
            raise InstanceNameConflictError(name)
        template = await self._sheet_service.load(template_id)
        values_json = json.dumps(defaults_map(template), ensure_ascii=False)
        try:
            row = await self._repo.create(
                name=name,
                template_id=template_id,
                values=values_json,
            )
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            if await self._repo.get_by_name(name) is not None:
                raise InstanceNameConflictError(name) from None
            raise
        return row

    async def get(self, instance_id: int) -> CharacterSheetInstanceModel:
        row = await self._repo.get_by_id(instance_id)
        if row is None:
            raise InstanceNotFoundError(instance_id)
        return row

    async def rename(self, instance_id: int, new_name: str) -> CharacterSheetInstanceModel:
        new_name = new_name.strip()
        if not new_name:
            raise ValueError(EMPTY_INSTANCE_NAME_ERROR)
        row = await self.get(instance_id)
        existing = await self._repo.get_by_name(new_name)
        if existing is not None and existing.id != instance_id:
            raise InstanceNameConflictError(new_name)
        row.name = new_name
        row.updated_at = datetime.utcnow()
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            raise InstanceNameConflictError(new_name) from None
        return row

    async def update_values(
        self, instance_id: int, values: dict[str, Any]
    ) -> CharacterSheetInstanceModel:
        row = await self.get(instance_id)
        old_ids = set(iter_instance_image_ids(row.values))
        row.values = json.dumps(values, ensure_ascii=False)
        row.updated_at = datetime.utcnow()
        await self._session.commit()
        if self._image_store is not None:
            new_ids = set(iter_instance_image_ids(row.values))
            for image_id in old_ids - new_ids:
                await self._image_store.gc_after_commit(image_id)
        return row

    async def delete(self, instance_id: int) -> bool:
        row = await self._repo.get_by_id(instance_id)
        if row is None:
            return False
        image_ids = iter_instance_image_ids(row.values)
        deleted = await self._repo.delete(instance_id)
        if deleted:
            await self._session.commit()
            if self._image_store is not None:
                for image_id in set(image_ids):
                    await self._image_store.gc_after_commit(image_id)
        return deleted

    async def bind_character(
        self, instance_id: int, character_id: int
    ) -> CharacterSheetInstanceModel:
        row = await self.get(instance_id)
        taken = await self._repo.get_by_character_id(character_id)
        if taken is not None and taken.id != instance_id:
            raise CharacterAlreadyBoundError(character_id)
        row.character_id = character_id
        row.updated_at = datetime.utcnow()
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            taken = await self._repo.get_by_character_id(character_id)
            if taken is not None and taken.id != instance_id:
                raise CharacterAlreadyBoundError(character_id) from None
            raise
        return row

    async def unbind_character(self, instance_id: int) -> CharacterSheetInstanceModel:
        row = await self.get(instance_id)
        row.character_id = None
        row.updated_at = datetime.utcnow()
        await self._session.commit()
        return row

    async def get_by_character_id(
        self, character_id: int
    ) -> CharacterSheetInstanceModel | None:
        return await self._repo.get_by_character_id(character_id)
