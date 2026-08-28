"""Tests for CharacterSheetService — TDD: red first.

A1 part: create, name-conflict rejection, rename (name only, pages
untouched) + rename conflict, update_pages JSON round-trip, delete,
corrupt-JSON load error, stable field ids across update_pages.

A-playable part (task 2.1): create writes schema_version 2 and one page
«Страница 1»; a v1 row loads without loss; save writes v2; an unknown field
type is never handed out as a layout; page operations in the model
(add/remove/reorder/rename, the last page cannot be removed).
"""
from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

import pytest

from app.application.services.character_sheet_service import (
    CharacterSheetError,
    CharacterSheetService,
    CorruptSheetError,
    NameConflictError,
    SheetNotFoundError,
    UnknownFieldTypeError,
)
from app.domain.entities.character_sheet import (
    EMPTY_PAGES_JSON,
    FieldType,
    SheetTemplate,
)
from app.infrastructure.db.models import CharacterSheetModel
from app.infrastructure.repositories.character_sheet_repository import CharacterSheetRepository


class TestCreate:
    async def test_create_empty_page_schema_v2(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        row = await svc.create("My Sheet")
        assert row.id is not None
        assert row.name == "My Sheet"
        assert row.schema_version == 2
        stored = json.loads(row.pages)
        assert stored == [{"name": "Страница 1", "fields": []}]

        loaded = await svc.load(row.id)
        assert loaded.name == "My Sheet"
        assert loaded.schema_version == 2
        assert loaded.page.fields == []
        assert loaded.page.name == "Страница 1"

    async def test_create_name_conflict_rejected(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        await svc.create("A")
        with pytest.raises(NameConflictError):
            await svc.create("A")
        assert len(await svc.list_sheets()) == 1

    async def test_create_blank_name_rejected(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        with pytest.raises(ValueError):
            await svc.create("   ")
        assert len(await svc.list_sheets()) == 0


class TestRename:
    async def test_rename_changes_name_only(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        row = await svc.create("Before")
        t = SheetTemplate(name="Before")
        t.add_field(FieldType.TEXT, (10.0, 10.0)).content = "keep me"
        await svc.update_pages(row.id, t)

        pages_before = (await repo.get_by_id(row.id)).pages

        await svc.rename(row.id, "After")
        fetched = await repo.get_by_id(row.id)
        assert fetched.name == "After"
        assert fetched.pages == pages_before

    async def test_rename_conflict_rejected_keeps_old_name(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        await svc.create("A")
        row_b = await svc.create("B")
        with pytest.raises(NameConflictError):
            await svc.rename(row_b.id, "A")
        fetched = await repo.get_by_id(row_b.id)
        assert fetched.name == "B"

    async def test_rename_to_own_name_is_ok(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        row = await svc.create("A")
        await svc.rename(row.id, "A")  # reusing own name is not a conflict
        assert (await repo.get_by_id(row.id)).name == "A"


class TestUpdatePages:
    async def test_round_trip_json(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        row = await svc.create("RT")
        t = SheetTemplate(name="RT")
        fa = t.add_field(FieldType.LABEL, (10.0, 10.0))
        fa.content = "Имя"
        fb = t.add_field(FieldType.TEXTAREA, (40.0, 40.0))
        fb.font_size = 14.0
        ids = [fa.id, fb.id]

        await svc.update_pages(row.id, t)

        loaded = await svc.load(row.id)
        fields = loaded.page.fields
        assert [f.id for f in fields] == ids
        assert fields[0].content == "Имя"
        assert fields[0].type == FieldType.LABEL
        assert fields[1].font_size == 14.0

    async def test_field_id_is_uuid_and_stable(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        row = await svc.create("Stable")
        t = SheetTemplate(name="Stable")
        f = t.add_field(FieldType.TEXT, (5.0, 5.0))
        original_id = f.id
        assert original_id

        await svc.update_pages(row.id, t)
        first = await svc.load(row.id)
        assert first.page.fields[0].id == original_id

        # A second save must not regenerate the id.
        await svc.update_pages(row.id, first)
        second = await svc.load(row.id)
        assert second.page.fields[0].id == original_id


class TestDelete:
    async def test_delete_removes_row(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        row = await svc.create("Doomed")
        assert await svc.delete(row.id) is True
        assert await repo.get_by_id(row.id) is None
        assert await repo.get_by_name("Doomed") is None

    async def test_delete_missing_returns_false(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        assert await svc.delete(999) is False


class TestLoad:
    async def test_load_corrupt_json_raises_and_does_not_return(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        # A row whose pages JSON is malformed must fail on load, not open as a layout.
        row = await repo.create(name="Broken", pages="{ this is not json")
        await async_session.commit()
        with pytest.raises(CorruptSheetError):
            await svc.load(row.id)

    async def test_load_missing_id(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        with pytest.raises(CharacterSheetError):
            await svc.load(12345)


class TestList:
    async def test_list_sorted_by_name(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        await svc.create("Zebra")
        await svc.create("Alpha")
        names = [s.name for s in await svc.list_sheets()]
        assert names == ["Alpha", "Zebra"]


# ── error backstops (DB integrity, missing rows, empty names) ───────────────

class TestErrorBackstops:
    async def test_create_integrity_conflict_raises_name_conflict(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        await svc.create("Taken")
        # hide the row from the pre-check so the DB constraint is the decider
        async_session.add(CharacterSheetModel(name="Race", pages=EMPTY_PAGES_JSON))
        await async_session.commit()

        async def hidden(name):
            return None

        repo.get_by_name = hidden
        with pytest.raises(NameConflictError):
            await svc.create("Race")
        # the session must be usable after the rollback
        assert [r.name for r in await svc.list_sheets()] == ["Race", "Taken"] or \
            [r.name for r in await svc.list_sheets()] == ["Taken", "Race"]

    async def test_update_pages_missing_id_raises(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        template = SheetTemplate(name="Ghost")
        with pytest.raises(SheetNotFoundError):
            await svc.update_pages(999, template)

    async def test_rename_empty_name_raises_value_error(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        row = await svc.create("Целое")
        with pytest.raises(ValueError):
            await svc.rename(row.id, "   ")

    async def test_rename_missing_id_raises(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        with pytest.raises(SheetNotFoundError):
            await svc.rename(4242, "Любое")

    async def test_rename_integrity_conflict_raises_name_conflict(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        a = await svc.create("А")
        await svc.create("В")

        async def hidden(name):
            return None

        repo.get_by_name = hidden
        with pytest.raises(NameConflictError):
            await svc.rename(a.id, "В")

        rows = await svc.list_sheets()
        assert sorted(r.name for r in rows) == ["А", "В"]


# ── user-facing errors are Russian (str(exc) is shown in the UI) ───────────

class TestUserFacingMessages:
    async def test_name_conflict_message_is_russian(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        await svc.create("Двойник")
        with pytest.raises(NameConflictError) as ei:
            await svc.create("Двойник")
        assert "уже существует" in str(ei.value)

    async def test_not_found_message_is_russian(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        with pytest.raises(SheetNotFoundError) as ei:
            await svc.load(999)
        assert "не найден" in str(ei.value)

    async def test_corrupt_message_is_russian(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        row = await repo.create(name="Bit", pages="not json")
        await async_session.commit()
        with pytest.raises(CorruptSheetError) as ei:
            await svc.load(row.id)
        assert "поврежд" in str(ei.value)

    async def test_empty_name_message_is_russian(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        with pytest.raises(ValueError) as ei:
            await svc.create("   ")
        assert "пустым" in str(ei.value)


# ── A-playable: v1 read, save bumps to v2, unknown type, page model ────────

def _v1_pages(*fields: dict) -> str:
    return json.dumps([{"fields": list(fields)}])


def _a1_field(fid: str, ftype: str, **extra) -> dict:
    base = {
        "id": fid, "type": ftype, "x": 12.0, "y": 34.0,
        "w": 72.0, "h": 18.0, "font_size": 10.0, "content": "",
    }
    base.update(extra)
    return base


class TestLoadV1:
    async def test_load_v1_preserves_fields_without_loss(self, async_session: AsyncSession):
        """A schema_version 1 row loads with the same fields, ids and geometry."""
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        pages = _v1_pages(
            _a1_field("sig", "label", content="Имя"),
            _a1_field("in1", "text", x=40.0, y=60.0, font_size=12.5, content="Иван"),
        )
        row = await repo.create(name="Legacy", schema_version=1, pages=pages)
        await async_session.commit()

        template = await svc.load(row.id)

        assert template.schema_version == 1  # in memory until the next save
        assert len(template.pages) == 1
        assert template.pages[0].name == "Страница 1"
        assert template.orientation == "portrait"
        fields = template.pages[0].fields
        assert [(f.id, f.type, f.content, f.font_size) for f in fields] == [
            ("sig", FieldType.LABEL, "Имя", 10.0),
            ("in1", FieldType.TEXT, "Иван", 12.5),
        ]
        assert (fields[1].x, fields[1].y) == (40.0, 60.0)


class TestSaveBumpsVersion:
    async def test_saving_v1_template_writes_schema_version_2(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        pages = _v1_pages(_a1_field("sig", "label", content="Имя"))
        row = await repo.create(name="Old", schema_version=1, pages=pages)
        await async_session.commit()

        template = await svc.load(row.id)
        await svc.update_pages(row.id, template)  # untouched save

        fetched = await repo.get_by_id(row.id)
        assert fetched.schema_version == 2
        stored = json.loads(fetched.pages)
        assert len(stored) == 1 and stored[0]["name"] == "Страница 1"
        assert stored[0]["fields"][0]["id"] == "sig"

    async def test_saving_multi_page_template_round_trips(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        row = await svc.create("Два")
        template = await svc.load(row.id)
        template.add_page()
        first = template.add_field(FieldType.LABEL, (10.0, 10.0), page_index=0)
        second = template.add_field(FieldType.TEXT, (10.0, 10.0), page_index=1)
        await svc.update_pages(row.id, template)

        reloaded = await svc.load(row.id)
        assert len(reloaded.pages) == 2
        assert reloaded.pages[0].fields[0].id == first.id
        assert reloaded.pages[1].fields[0].id == second.id


class TestUnknownType:
    async def test_load_unknown_type_raises_and_does_not_return(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        pages = _v1_pages(_a1_field("x", "sparkles"))
        row = await repo.create(name="Magic", schema_version=1, pages=pages)
        await async_session.commit()

        with pytest.raises(UnknownFieldTypeError) as ei:
            await svc.load(row.id)
        assert isinstance(ei.value, CharacterSheetError)

        # the DB is untouched: the row and its layout are exactly as before
        fetched = await repo.get_by_id(row.id)
        assert fetched.name == "Magic"
        assert fetched.pages == pages


class TestPageModel:
    """Page operations live in the model (SheetTemplate); the service
    persists whatever the model holds."""

    def test_add_page_inserts_after_and_names_by_total_count(self):
        t = SheetTemplate(name="T")
        new = t.add_page(after_index=0)
        assert len(t.pages) == 2
        assert t.pages[1] is new
        assert new.name == "Страница 2"

    def test_add_page_at_end_when_no_index(self):
        t = SheetTemplate(name="T")
        t.add_page()
        t.add_page()
        assert [p.name for p in t.pages] == ["Страница 1", "Страница 2", "Страница 3"]

    def test_remove_page(self):
        t = SheetTemplate(name="T")
        t.add_page()
        f = t.add_field(FieldType.LABEL, (10.0, 10.0), page_index=1)
        t.remove_page(1)
        assert len(t.pages) == 1
        assert t.pages[0].fields == []  # the page's fields go with it
        assert t.get_field(f.id) is None

    def test_last_page_cannot_be_removed(self):
        t = SheetTemplate(name="T")
        with pytest.raises(ValueError):
            t.remove_page(0)
        assert len(t.pages) == 1

    def test_move_page_reorders(self):
        t = SheetTemplate(name="T")
        t.add_page()
        t.add_page()
        names = [p.name for p in t.pages]
        t.move_page(0, 2)
        assert [p.name for p in t.pages] == [names[1], names[2], names[0]]
        t.move_page(2, 0)
        assert [p.name for p in t.pages] == names  # moved back

    def test_move_page_self_or_out_of_range_is_noop(self):
        t = SheetTemplate(name="T")
        t.add_page()
        before = [p.name for p in t.pages]
        t.move_page(0, 0)
        t.move_page(0, 99)
        t.move_page(5, 0)
        assert [p.name for p in t.pages] == before

    def test_rename_page(self):
        t = SheetTemplate(name="T")
        t.add_page()
        t.rename_page(1, "Навыки")
        assert t.pages[1].name == "Навыки"

    def test_rename_page_empty_name_rejected(self):
        t = SheetTemplate(name="T")
        with pytest.raises(ValueError):
            t.rename_page(0, "   ")
        assert t.pages[0].name == "Страница 1"

    async def test_pages_are_persisted_and_reload(self, async_session: AsyncSession):
        repo = CharacterSheetRepository(async_session)
        svc = CharacterSheetService(repo)
        row = await svc.create("Порядок")
        template = await svc.load(row.id)
        template.add_page(after_index=0)
        template.rename_page(1, "Вторая")
        template.move_page(0, 1)  # «Вторая» becomes the first page
        await svc.update_pages(row.id, template)

        reloaded = await svc.load(row.id)
        assert [p.name for p in reloaded.pages] == ["Вторая", "Страница 1"]
