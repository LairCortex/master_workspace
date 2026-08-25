"""Tests for CharacterSheetRepository (task 3.2)."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.infrastructure.db.models import CharacterSheetModel
from app.infrastructure.repositories.character_sheet_repository import CharacterSheetRepository

#: a minimal valid pages JSON (one page, no fields)
PAGES = '[{"name": "ОСН", "fields": []}]'


def _sheet_kwargs(name: str = "Лист", orientation: str = "portrait") -> dict:
    return {"name": name, "orientation": orientation, "pages": PAGES}


class TestCharacterSheetRepository:
    async def test_create_and_get_by_id(self, async_session):
        repo = CharacterSheetRepository(async_session)
        created = await repo.create(**_sheet_kwargs())
        assert created.id is not None
        fetched = await repo.get_by_id(created.id)
        assert fetched.name == "Лист"
        assert fetched.orientation == "portrait"
        assert fetched.pages == PAGES

    async def test_get_by_id_not_found(self, async_session):
        repo = CharacterSheetRepository(async_session)
        assert await repo.get_by_id(999) is None

    async def test_get_all(self, async_session):
        repo = CharacterSheetRepository(async_session)
        await repo.create(**_sheet_kwargs("А"))
        await repo.create(**_sheet_kwargs("Б"))
        assert len(await repo.get_all()) == 2

    async def test_update(self, async_session):
        repo = CharacterSheetRepository(async_session)
        created = await repo.create(**_sheet_kwargs())
        new_pages = '[{"name": "ОСН", "fields": []}, {"name": "ЗАП", "fields": []}]'
        updated = await repo.update(created.id, name="Лист 2", pages=new_pages)
        assert updated.name == "Лист 2"
        assert updated.pages == new_pages

    async def test_update_not_found(self, async_session):
        repo = CharacterSheetRepository(async_session)
        assert await repo.update(999, name="x") is None

    async def test_delete(self, async_session):
        repo = CharacterSheetRepository(async_session)
        created = await repo.create(**_sheet_kwargs())
        assert await repo.delete(created.id) is True
        assert await repo.get_by_id(created.id) is None

    async def test_delete_not_found(self, async_session):
        repo = CharacterSheetRepository(async_session)
        assert await repo.delete(999) is False

    async def test_get_by_name(self, async_session):
        repo = CharacterSheetRepository(async_session)
        await repo.create(**_sheet_kwargs("Персонаж"))
        await repo.create(**_sheet_kwargs("НПС"))
        found = await repo.get_by_name("НПС")
        assert found is not None and found.name == "НПС"
        assert await repo.get_by_name("Нема") is None

    async def test_duplicate_name_raises_integrity_error(self, async_session):
        repo = CharacterSheetRepository(async_session)
        await repo.create(**_sheet_kwargs())
        async_session.add(CharacterSheetModel(**_sheet_kwargs()))
        with pytest.raises(IntegrityError):
            await async_session.commit()
        await async_session.rollback()
