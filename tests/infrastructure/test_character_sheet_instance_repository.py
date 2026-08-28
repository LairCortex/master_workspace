"""Tests for CharacterSheetInstanceRepository — TDD: red first.

Covers task 3.1: get_all / get_by_id / get_by_name / get_by_character_id /
count_by_template / create / update / delete.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.character_sheet import EMPTY_PAGES_JSON
from app.infrastructure.repositories.character_repository import CharacterRepository
from app.infrastructure.repositories.character_sheet_instance_repository import (
    CharacterSheetInstanceRepository,
)
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)


async def _template(session: AsyncSession, name: str = "T") -> int:
    repo = CharacterSheetRepository(session)
    row = await repo.create(name=name, pages=EMPTY_PAGES_JSON, schema_version=2)
    return row.id


async def _character(session: AsyncSession, name: str = "C") -> int:
    repo = CharacterRepository(session)
    row = await repo.create(name=name, start_date=date(1300, 1, 1))
    return row.id


class TestCharacterSheetInstanceRepository:
    async def test_create_and_get_by_id(self, async_session: AsyncSession):
        tid = await _template(async_session)
        repo = CharacterSheetInstanceRepository(async_session)
        obj = await repo.create(
            name="Лист", template_id=tid, values='{"a": "1"}'
        )
        assert obj.id is not None
        result = await repo.get_by_id(obj.id)
        assert result.name == "Лист"
        assert result.template_id == tid
        assert result.values == '{"a": "1"}'
        assert result.character_id is None
        assert result.created_at is not None
        assert result.updated_at is not None

    async def test_get_all(self, async_session: AsyncSession):
        tid = await _template(async_session)
        repo = CharacterSheetInstanceRepository(async_session)
        await repo.create(name="A", template_id=tid, values="{}")
        await repo.create(name="B", template_id=tid, values="{}")
        items = await repo.get_all()
        assert {i.name for i in items} == {"A", "B"}

    async def test_get_by_id_not_found(self, async_session: AsyncSession):
        repo = CharacterSheetInstanceRepository(async_session)
        assert await repo.get_by_id(999) is None

    async def test_get_by_name_exact(self, async_session: AsyncSession):
        tid = await _template(async_session)
        repo = CharacterSheetInstanceRepository(async_session)
        await repo.create(name="Hero", template_id=tid, values="{}")
        await repo.create(name="Hero (v2)", template_id=tid, values="{}")
        found = await repo.get_by_name("Hero")
        assert found is not None
        assert found.name == "Hero"

    async def test_get_by_name_not_found(self, async_session: AsyncSession):
        repo = CharacterSheetInstanceRepository(async_session)
        assert await repo.get_by_name("Nobody") is None

    async def test_get_by_character_id(self, async_session: AsyncSession):
        tid = await _template(async_session)
        cid = await _character(async_session)
        repo = CharacterSheetInstanceRepository(async_session)
        await repo.create(name="Unbound", template_id=tid, values="{}")
        bound = await repo.create(
            name="Bound", template_id=tid, character_id=cid, values="{}"
        )
        found = await repo.get_by_character_id(cid)
        assert found is not None
        assert found.id == bound.id

    async def test_get_by_character_id_not_found(self, async_session: AsyncSession):
        repo = CharacterSheetInstanceRepository(async_session)
        assert await repo.get_by_character_id(999) is None

    async def test_count_by_template(self, async_session: AsyncSession):
        t1 = await _template(async_session, "T1")
        t2 = await _template(async_session, "T2")
        repo = CharacterSheetInstanceRepository(async_session)
        await repo.create(name="A", template_id=t1, values="{}")
        await repo.create(name="B", template_id=t1, values="{}")
        await repo.create(name="C", template_id=t2, values="{}")
        assert await repo.count_by_template(t1) == 2
        assert await repo.count_by_template(t2) == 1
        assert await repo.count_by_template(999) == 0

    async def test_update_changes_name_and_values(self, async_session: AsyncSession):
        tid = await _template(async_session)
        repo = CharacterSheetInstanceRepository(async_session)
        obj = await repo.create(name="Old", template_id=tid, values="{}")
        updated = await repo.update(obj.id, name="New", values='{"x": 1}')
        assert updated.name == "New"
        assert updated.values == '{"x": 1}'
        assert updated.template_id == tid

    async def test_update_not_found(self, async_session: AsyncSession):
        repo = CharacterSheetInstanceRepository(async_session)
        assert await repo.update(999, name="X") is None

    async def test_delete(self, async_session: AsyncSession):
        tid = await _template(async_session)
        repo = CharacterSheetInstanceRepository(async_session)
        obj = await repo.create(name="Del", template_id=tid, values="{}")
        assert await repo.delete(obj.id) is True
        assert await repo.get_by_id(obj.id) is None

    async def test_delete_not_found(self, async_session: AsyncSession):
        repo = CharacterSheetInstanceRepository(async_session)
        assert await repo.delete(999) is False
