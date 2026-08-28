"""Tests for CharacterSheetRepository — TDD: red first.

Covers task 3.1: get_all / get_by_id / get_by_name / create / update / delete
on an in-memory session. ``get_by_name`` is an exact match (uniqueness key),
not the contains-style ``search_by_name`` from BaseRepository.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.character_sheet import EMPTY_PAGES_JSON
from app.infrastructure.repositories.character_sheet_repository import CharacterSheetRepository


def _pages() -> str:
    return EMPTY_PAGES_JSON


class TestCharacterSheetRepository:
    async def test_create_and_get_by_id(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        obj = await repo.create(name="Hero", pages=_pages())
        assert obj.id is not None
        result = await repo.get_by_id(obj.id)
        assert result.name == "Hero"
        assert result.pages == _pages()

    async def test_create_defaults(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        obj = await repo.create(name="S", pages=_pages())
        assert obj.schema_version == 1
        assert obj.orientation == "portrait"
        assert obj.created_at is not None
        assert obj.updated_at is not None

    async def test_get_all(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        await repo.create(name="A", pages=_pages())
        await repo.create(name="B", pages=_pages())
        items = await repo.get_all()
        assert {i.name for i in items} == {"A", "B"}

    async def test_get_by_id_not_found(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        assert await repo.get_by_id(999) is None

    async def test_get_by_name_exact(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        await repo.create(name="Hero", pages=_pages())
        await repo.create(name="Hero (v2)", pages=_pages())
        found = await repo.get_by_name("Hero")
        assert found is not None
        assert found.name == "Hero"

    async def test_get_by_name_not_substring(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        await repo.create(name="Hero", pages=_pages())
        assert await repo.get_by_name("H") is None
        assert await repo.get_by_name("ero") is None

    async def test_get_by_name_not_found(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        assert await repo.get_by_name("Nobody") is None

    async def test_update_changes_name_and_pages(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        obj = await repo.create(name="Old", pages=_pages())
        updated = await repo.update(obj.id, name="New", pages='[{"fields": [{"id": "x"}]}]')
        assert updated.name == "New"
        assert updated.pages == '[{"fields": [{"id": "x"}]}]'

    async def test_update_not_found(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        assert await repo.update(999, name="X") is None

    async def test_delete(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        obj = await repo.create(name="Del", pages=_pages())
        assert await repo.delete(obj.id) is True
        assert await repo.get_by_id(obj.id) is None

    async def test_delete_not_found(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        assert await repo.delete(999) is False
