"""Tests for CharacterSheetInstanceService — TDD: red first.

Covers task 3.3: create copies defaults and writes template_id; name conflict
rejected; two sheets on one template ok; rename immediately, conflict
rejected; no setter for template_id; delete; bind unique; unbind; delete
character leaves sheet with character_id NULL; delete template with
instances is rejected.
"""
from __future__ import annotations

import json
from datetime import date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.exc import IntegrityError

from app.application.services.character_sheet_instance_service import (
    CharacterAlreadyBoundError,
    CharacterSheetInstanceService,
    InstanceNameConflictError,
    SeatedInstanceError,
)
from app.application.services.character_sheet_service import (
    CharacterSheetService,
    TemplateHasInstancesError,
)
from app.domain.entities.character_sheet import FieldType, SheetTemplate
from app.domain.entities.character_sheet_instance import defaults_map
from app.infrastructure.repositories.character_repository import CharacterRepository
from app.infrastructure.repositories.character_sheet_instance_repository import (
    CharacterSheetInstanceRepository,
)
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)


async def _services(session: AsyncSession):
    sheet_repo = CharacterSheetRepository(session)
    inst_repo = CharacterSheetInstanceRepository(session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    return sheet_svc, inst_svc, inst_repo


async def _template_with_fields(sheet_svc: CharacterSheetService) -> tuple[int, SheetTemplate]:
    row = await sheet_svc.create("Шаблон")
    template = await sheet_svc.load(row.id)
    text_f = template.add_field(FieldType.TEXT, (10.0, 10.0))
    text_f.content = "Иван"
    chk = template.add_field(FieldType.CHECKBOX, (10.0, 40.0))
    chk.content = "true"
    img = template.add_field(FieldType.IMAGE, (10.0, 70.0))
    img.image_id = 5
    template.add_field(FieldType.LABEL, (10.0, 200.0))
    await sheet_svc.update_pages(row.id, template)
    return row.id, await sheet_svc.load(row.id)


class TestCreate:
    async def test_create_copies_defaults_and_template_id(self, async_session: AsyncSession):
        sheet_svc, inst_svc, repo = await _services(async_session)
        tid, template = await _template_with_fields(sheet_svc)
        row = await inst_svc.create("Лист 1", tid)
        assert row.id is not None
        assert row.name == "Лист 1"
        assert row.template_id == tid
        assert row.character_id is None
        stored = json.loads(row.values)
        assert stored == defaults_map(template)
        assert len(stored) == 3

    async def test_name_conflict_rejected(self, async_session: AsyncSession):
        sheet_svc, inst_svc, repo = await _services(async_session)
        tid, _ = await _template_with_fields(sheet_svc)
        await inst_svc.create("Лист", tid)
        with pytest.raises(InstanceNameConflictError):
            await inst_svc.create("Лист", tid)
        assert len(await inst_svc.list_instances()) == 1

    async def test_two_instances_on_one_template_ok(self, async_session: AsyncSession):
        sheet_svc, inst_svc, repo = await _services(async_session)
        tid, _ = await _template_with_fields(sheet_svc)
        a = await inst_svc.create("A", tid)
        b = await inst_svc.create("B", tid)
        assert a.template_id == b.template_id == tid
        assert {r.name for r in await inst_svc.list_instances()} == {"A", "B"}

    async def test_create_non_name_integrity_error_is_not_name_conflict(
        self, async_session: AsyncSession
    ):
        sheet_svc, inst_svc, repo = await _services(async_session)
        tid, _ = await _template_with_fields(sheet_svc)

        async def boom(**kwargs):
            raise IntegrityError("INSERT", {}, Exception("fk"))

        inst_svc._repo.create = boom  # type: ignore[method-assign]
        with pytest.raises(IntegrityError):
            await inst_svc.create("СвободноеИмя", tid)


class TestRename:
    async def test_rename_commits_immediately(self, async_session: AsyncSession):
        sheet_svc, inst_svc, repo = await _services(async_session)
        tid, _ = await _template_with_fields(sheet_svc)
        row = await inst_svc.create("До", tid)
        values_before = row.values
        row.updated_at = datetime(2000, 1, 1)
        await async_session.commit()
        await inst_svc.rename(row.id, "После")
        fetched = await repo.get_by_id(row.id)
        assert fetched.name == "После"
        assert fetched.values == values_before
        assert fetched.updated_at > datetime(2000, 1, 1)

    async def test_rename_conflict_rejected(self, async_session: AsyncSession):
        sheet_svc, inst_svc, repo = await _services(async_session)
        tid, _ = await _template_with_fields(sheet_svc)
        a = await inst_svc.create("A", tid)
        await inst_svc.create("B", tid)
        with pytest.raises(InstanceNameConflictError):
            await inst_svc.rename(a.id, "B")
        assert (await repo.get_by_id(a.id)).name == "A"


class TestNoTemplateSetter:
    def test_service_has_no_template_id_setter(self):
        public = [m for m in dir(CharacterSheetInstanceService) if not m.startswith("_")]
        forbidden = {m for m in public if "template" in m.lower()}
        assert forbidden == set()

    async def test_update_values_does_not_change_template_id(self, async_session: AsyncSession):
        sheet_svc, inst_svc, repo = await _services(async_session)
        tid, _ = await _template_with_fields(sheet_svc)
        other = await sheet_svc.create("Другой")
        row = await inst_svc.create("Лист", tid)
        await inst_svc.update_values(row.id, {"x": "1"})
        fetched = await repo.get_by_id(row.id)
        assert fetched.template_id == tid
        assert fetched.template_id != other.id


class TestDelete:
    async def test_delete_removes_row(self, async_session: AsyncSession):
        sheet_svc, inst_svc, repo = await _services(async_session)
        tid, _ = await _template_with_fields(sheet_svc)
        row = await inst_svc.create("Doomed", tid)
        assert await inst_svc.delete(row.id) is True
        assert await repo.get_by_id(row.id) is None

    async def test_delete_missing_returns_false(self, async_session: AsyncSession):
        _, inst_svc, _ = await _services(async_session)
        assert await inst_svc.delete(999) is False

    async def test_delete_seated_while_host_running_rejected(
        self, async_session: AsyncSession
    ):
        from app.application.services.table_host_service import TableHostService

        sheet_svc, inst_svc, repo = await _services(async_session)
        tid, _ = await _template_with_fields(sheet_svc)
        row = await inst_svc.create("За столом", tid)
        host = TableHostService(inst_svc, sheet_svc)
        inst_svc.set_seating_guard(host.is_seated)
        host.seat(row.id)
        await host.start()
        with pytest.raises(SeatedInstanceError):
            await inst_svc.delete(row.id)
        assert await repo.get_by_id(row.id) is not None
        await host.stop()
        assert await inst_svc.delete(row.id) is True
        assert await repo.get_by_id(row.id) is None


class TestBind:
    async def test_bind_unique_second_rejected(self, async_session: AsyncSession):
        sheet_svc, inst_svc, repo = await _services(async_session)
        tid, _ = await _template_with_fields(sheet_svc)
        a = await inst_svc.create("A", tid)
        b = await inst_svc.create("B", tid)
        char_repo = CharacterRepository(async_session)
        char = await char_repo.create(name="P", start_date=date(1300, 1, 1))
        await async_session.commit()

        before = (await repo.get_by_id(a.id)).updated_at
        await inst_svc.bind_character(a.id, char.id)
        bound = await repo.get_by_id(a.id)
        assert bound.updated_at >= before
        with pytest.raises(CharacterAlreadyBoundError):
            await inst_svc.bind_character(b.id, char.id)

        assert (await repo.get_by_id(a.id)).character_id == char.id
        assert (await repo.get_by_id(b.id)).character_id is None

    async def test_bind_integrity_error_reraise_when_character_free(
        self, async_session: AsyncSession
    ):
        sheet_svc, inst_svc, _repo = await _services(async_session)
        tid, _ = await _template_with_fields(sheet_svc)
        row = await inst_svc.create("A", tid)
        char_repo = CharacterRepository(async_session)
        char = await char_repo.create(name="P", start_date=date(1300, 1, 1))
        await async_session.commit()

        orig_commit = inst_svc._session.commit

        async def boom():
            raise IntegrityError("UPDATE", {}, Exception("fk"))

        inst_svc._session.commit = boom  # type: ignore[method-assign]
        try:
            with pytest.raises(IntegrityError):
                await inst_svc.bind_character(row.id, char.id)
        finally:
            inst_svc._session.commit = orig_commit  # type: ignore[method-assign]

    async def test_unbind(self, async_session: AsyncSession):
        sheet_svc, inst_svc, repo = await _services(async_session)
        tid, _ = await _template_with_fields(sheet_svc)
        a = await inst_svc.create("A", tid)
        char_repo = CharacterRepository(async_session)
        char = await char_repo.create(name="P", start_date=date(1300, 1, 1))
        await async_session.commit()
        await inst_svc.bind_character(a.id, char.id)
        await inst_svc.unbind_character(a.id)
        assert (await repo.get_by_id(a.id)).character_id is None

    async def test_delete_character_sets_null(self, async_session: AsyncSession):
        sheet_svc, inst_svc, repo = await _services(async_session)
        tid, _ = await _template_with_fields(sheet_svc)
        a = await inst_svc.create("A", tid)
        instance_id = a.id
        char_repo = CharacterRepository(async_session)
        char = await char_repo.create(name="P", start_date=date(1300, 1, 1))
        await async_session.commit()
        await inst_svc.bind_character(instance_id, char.id)

        await char_repo.delete(char.id)
        await async_session.commit()
        async_session.expunge_all()
        fetched = await repo.get_by_id(instance_id)
        assert fetched is not None
        assert fetched.character_id is None


class TestDeleteTemplateWithInstances:
    async def test_delete_template_with_instances_rejected(self, async_session: AsyncSession):
        sheet_svc, inst_svc, repo = await _services(async_session)
        tid, _ = await _template_with_fields(sheet_svc)
        await inst_svc.create("A", tid)
        with pytest.raises(TemplateHasInstancesError):
            await sheet_svc.delete(tid)
        assert await repo.count_by_template(tid) == 1
        assert await CharacterSheetRepository(async_session).get_by_id(tid) is not None

    async def test_delete_template_without_instances_ok(self, async_session: AsyncSession):
        sheet_svc, _, _ = await _services(async_session)
        tid, _ = await _template_with_fields(sheet_svc)
        assert await sheet_svc.delete(tid) is True
