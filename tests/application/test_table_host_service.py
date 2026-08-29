"""Tests for TableHostService (tasks 2.1 / 2.2): seating, PIN, join, field, stop."""
from __future__ import annotations

import base64
import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.character_sheet_instance_service import (
    CharacterSheetInstanceService,
)
from app.application.services.character_sheet_service import CharacterSheetService
from app.application.services.table_host_service import (
    EmptySeatingError,
    FieldCommitError,
    InvalidPinError,
    InvalidTokenError,
    NameTakenError,
    SeatTakenError,
    TableHostService,
)
from app.domain.entities.character_sheet import FieldType
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
    host = TableHostService(inst_svc, sheet_svc)
    return sheet_svc, inst_svc, host


async def _seed(sheet_svc, inst_svc, n_instances: int = 2):
    row = await sheet_svc.create("Шаблон")
    template = await sheet_svc.load(row.id)
    text_f = template.add_field(FieldType.TEXT, (10.0, 10.0))
    text_f.content = "было"
    await sheet_svc.update_pages(row.id, template)
    instances = []
    for i in range(n_instances):
        instances.append(await inst_svc.create(f"Лист {i + 1}", row.id))
    return row.id, text_f.id, instances


class TestStart:
    async def test_start_without_seating_is_rejected(self, async_session: AsyncSession):
        _sheet, _inst, host = await _services(async_session)
        with pytest.raises(EmptySeatingError):
            await host.start()
        assert not host.is_running

    async def test_pin_is_four_digits_and_changes_on_restart(
        self, async_session: AsyncSession
    ):
        sheet_svc, inst_svc, host = await _services(async_session)
        _tid, _fid, instances = await _seed(sheet_svc, inst_svc, 1)
        host.seat(instances[0].id)
        await host.start()
        pin1 = host.pin
        assert pin1 is not None and len(pin1) == 4 and pin1.isdigit()
        await host.stop()
        await host.start()
        pin2 = host.pin
        assert pin2 is not None and len(pin2) == 4 and pin2.isdigit()
        assert pin2 != pin1

    async def test_restart_replaces_seating_not_accumulates(
        self, async_session: AsyncSession
    ):
        from app.application.services.character_sheet_instance_service import (
            SeatedInstanceError,
        )

        sheet_svc, inst_svc, host = await _services(async_session)
        inst_svc.set_seating_guard(host.is_seated)
        _tid, _fid, instances = await _seed(sheet_svc, inst_svc, 2)
        a, b = instances[0].id, instances[1].id
        host.set_seating([a, b])
        await host.start()
        await host.stop()
        host.set_seating([a])
        await host.start()
        assert a in host.seated_ids
        assert b not in host.seated_ids
        seats = await host.list_seats(host.pin)
        assert [s["instance_id"] for s in seats] == [a]
        await inst_svc.delete(b)
        with pytest.raises(SeatedInstanceError):
            await inst_svc.delete(a)


class TestJoin:
    async def test_wrong_pin_rejected(self, async_session: AsyncSession):
        sheet_svc, inst_svc, host = await _services(async_session)
        _tid, _fid, instances = await _seed(sheet_svc, inst_svc, 1)
        host.seat(instances[0].id)
        await host.start()
        with pytest.raises(InvalidPinError):
            await host.join("0000" if host.pin != "0000" else "1111", "Вася", instances[0].id)
        row = await inst_svc.get(instances[0].id)
        stored = json.loads(row.values)
        assert stored[_fid] == "было"

    async def test_name_unique_across_table(self, async_session: AsyncSession):
        sheet_svc, inst_svc, host = await _services(async_session)
        _tid, _fid, instances = await _seed(sheet_svc, inst_svc, 2)
        host.seat(instances[0].id)
        host.seat(instances[1].id)
        await host.start()
        await host.join(host.pin, "Вася", instances[0].id)
        with pytest.raises(NameTakenError):
            await host.join(host.pin, "Вася", instances[1].id)

    async def test_free_sheet_ok(self, async_session: AsyncSession):
        sheet_svc, inst_svc, host = await _services(async_session)
        _tid, fid, instances = await _seed(sheet_svc, inst_svc, 1)
        host.seat(instances[0].id)
        await host.start()
        token = await host.join(host.pin, "Вася", instances[0].id)
        assert token
        sheet = await host.get_sheet(token)
        assert fid in sheet["values"]
        assert sheet["instance_id"] == instances[0].id

    async def test_occupied_other_name_conflict(self, async_session: AsyncSession):
        sheet_svc, inst_svc, host = await _services(async_session)
        _tid, _fid, instances = await _seed(sheet_svc, inst_svc, 1)
        host.seat(instances[0].id)
        await host.start()
        await host.join(host.pin, "Вася", instances[0].id)
        with pytest.raises(SeatTakenError):
            await host.join(host.pin, "Петя", instances[0].id)

    async def test_same_name_evicts_previous_tab(self, async_session: AsyncSession):
        sheet_svc, inst_svc, host = await _services(async_session)
        _tid, fid, instances = await _seed(sheet_svc, inst_svc, 1)
        host.seat(instances[0].id)
        await host.start()
        t1 = await host.join(host.pin, "Вася", instances[0].id)
        t2 = await host.join(host.pin, "Вася", instances[0].id)
        assert t1 != t2
        with pytest.raises(InvalidTokenError):
            await host.commit_field(t1, fid, "старый")
        await host.commit_field(t2, fid, "новый")
        row = await inst_svc.get(instances[0].id)
        assert json.loads(row.values)[fid] == "новый"


class TestFieldAndStop:
    async def test_field_commit_writes_values(self, async_session: AsyncSession):
        sheet_svc, inst_svc, host = await _services(async_session)
        _tid, fid, instances = await _seed(sheet_svc, inst_svc, 1)
        host.seat(instances[0].id)
        await host.start()
        token = await host.join(host.pin, "Вася", instances[0].id)
        await host.commit_field(token, fid, "с веба")
        row = await inst_svc.get(instances[0].id)
        assert json.loads(row.values)[fid] == "с веба"

    async def test_stop_invalidates_token(self, async_session: AsyncSession):
        sheet_svc, inst_svc, host = await _services(async_session)
        _tid, fid, instances = await _seed(sheet_svc, inst_svc, 1)
        host.seat(instances[0].id)
        await host.start()
        token = await host.join(host.pin, "Вася", instances[0].id)
        await host.commit_field(token, fid, "останется")
        await host.stop()
        assert not host.is_running
        with pytest.raises(InvalidTokenError):
            await host.commit_field(token, fid, "после стопа")
        row = await inst_svc.get(instances[0].id)
        assert json.loads(row.values)[fid] == "останется"

    async def test_leave_frees_seat(self, async_session: AsyncSession):
        sheet_svc, inst_svc, host = await _services(async_session)
        _tid, fid, instances = await _seed(sheet_svc, inst_svc, 1)
        host.seat(instances[0].id)
        await host.start()
        token = await host.join(host.pin, "Вася", instances[0].id)
        await host.leave(token)
        assert host.occupancy == {}
        await host.leave(token)
        token2 = await host.join(host.pin, "Петя", instances[0].id)
        await host.commit_field(token2, fid, "после выхода")
        with pytest.raises(InvalidTokenError):
            await host.commit_field(token, fid, "нет")


_PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class _FakeWs:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.closed = False

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)

    async def close(self) -> None:
        self.closed = True


class TestImageAndLayout:
    async def test_readable_image_goes_through_image_store(
        self, async_session: AsyncSession, tmp_path, qapp
    ):
        from app.infrastructure.images.store import ImageStore

        sheet_svc, inst_svc, _host = await _services(async_session)
        store = ImageStore(async_session, tmp_path / "images")
        inst_svc._image_store = store
        host = TableHostService(inst_svc, sheet_svc, image_store=store)
        row = await sheet_svc.create("Шаблон")
        template = await sheet_svc.load(row.id)
        img = template.add_field(FieldType.IMAGE, (10.0, 10.0))
        await sheet_svc.update_pages(row.id, template)
        inst = await inst_svc.create("Лист", row.id)
        before = json.loads((await inst_svc.get(inst.id)).values)
        host.seat(inst.id)
        await host.start()
        token = await host.join(host.pin, "Вася", inst.id)
        image_id = await host.store_image(token, img.id, _PNG_1PX)
        stored = json.loads((await inst_svc.get(inst.id)).values)
        assert stored[img.id] == image_id
        assert image_id != before.get(img.id)
        path = await host.preview_path(token, image_id)
        assert path is not None and path.exists()

    async def test_store_image_rejects_non_image_field(
        self, async_session: AsyncSession, tmp_path, qapp
    ):
        from app.infrastructure.images.store import ImageStore

        sheet_svc, inst_svc, _host = await _services(async_session)
        store = ImageStore(async_session, tmp_path / "images")
        host = TableHostService(inst_svc, sheet_svc, image_store=store)
        row = await sheet_svc.create("Шаблон")
        template = await sheet_svc.load(row.id)
        text_f = template.add_field(FieldType.TEXT, (10.0, 10.0))
        await sheet_svc.update_pages(row.id, template)
        inst = await inst_svc.create("Лист", row.id)
        host.seat(inst.id)
        await host.start()
        token = await host.join(host.pin, "Вася", inst.id)
        with pytest.raises(FieldCommitError):
            await host.store_image(token, text_f.id, _PNG_1PX)
        stored = json.loads((await inst_svc.get(inst.id)).values)
        assert stored[text_f.id] != 1
        with pytest.raises(FieldCommitError):
            await host.store_image(token, "missing-field", _PNG_1PX)

    async def test_image_field_rejects_missing_id(
        self, async_session: AsyncSession, tmp_path, qapp
    ):
        from app.infrastructure.images.store import ImageStore

        sheet_svc, inst_svc, _host = await _services(async_session)
        store = ImageStore(async_session, tmp_path / "images")
        host = TableHostService(inst_svc, sheet_svc, image_store=store)
        row = await sheet_svc.create("Шаблон")
        template = await sheet_svc.load(row.id)
        img = template.add_field(FieldType.IMAGE, (10.0, 10.0))
        await sheet_svc.update_pages(row.id, template)
        inst = await inst_svc.create("Лист", row.id)
        host.seat(inst.id)
        await host.start()
        token = await host.join(host.pin, "Вася", inst.id)
        with pytest.raises(FieldCommitError):
            await host.commit_field(token, img.id, 999999)
        stored = json.loads((await inst_svc.get(inst.id)).values)
        assert stored.get(img.id) != 999999

    async def test_preview_path_is_scoped_to_session_sheet(
        self, async_session: AsyncSession, tmp_path, qapp
    ):
        from app.infrastructure.images.store import ImageStore

        sheet_svc, inst_svc, _host = await _services(async_session)
        store = ImageStore(async_session, tmp_path / "images")
        inst_svc._image_store = store
        host = TableHostService(inst_svc, sheet_svc, image_store=store)
        row = await sheet_svc.create("Шаблон")
        template = await sheet_svc.load(row.id)
        img = template.add_field(FieldType.IMAGE, (10.0, 10.0))
        await sheet_svc.update_pages(row.id, template)
        a = await inst_svc.create("Лист A", row.id)
        b = await inst_svc.create("Лист B", row.id)
        host.set_seating([a.id, b.id])
        await host.start()
        ta = await host.join(host.pin, "Вася", a.id)
        tb = await host.join(host.pin, "Петя", b.id)
        id_a = await host.store_image(ta, img.id, _PNG_1PX)
        assert await host.preview_path(ta, id_a) is not None
        assert await host.preview_path(tb, id_a) is None

    async def test_attach_ws_closes_previous_socket(self, async_session: AsyncSession):
        sheet_svc, inst_svc, host = await _services(async_session)
        tid, _fid, instances = await _seed(sheet_svc, inst_svc, 1)
        host.seat(instances[0].id)
        await host.start()
        token = await host.join(host.pin, "Вася", instances[0].id)
        old = _FakeWs()
        new = _FakeWs()
        await host.attach_ws(token, old)
        await host.attach_ws(token, new)
        assert old.closed
        await host.broadcast_layout(tid)
        assert any(m.get("type") == "layout" for m in new.messages)
        assert not any(m.get("type") == "layout" for m in old.messages)

    async def test_unreadable_image_does_not_write_values(
        self, async_session: AsyncSession, tmp_path, qapp
    ):
        from app.infrastructure.images.store import ImageStore

        sheet_svc, inst_svc, _host = await _services(async_session)
        store = ImageStore(async_session, tmp_path / "images")
        host = TableHostService(inst_svc, sheet_svc, image_store=store)
        row = await sheet_svc.create("Шаблон")
        template = await sheet_svc.load(row.id)
        img = template.add_field(FieldType.IMAGE, (10.0, 10.0))
        await sheet_svc.update_pages(row.id, template)
        inst = await inst_svc.create("Лист", row.id)
        before = json.loads((await inst_svc.get(inst.id)).values)
        host.seat(inst.id)
        await host.start()
        token = await host.join(host.pin, "Вася", inst.id)
        with pytest.raises(FieldCommitError):
            await host.store_image(token, img.id, b"not-an-image")
        after = json.loads((await inst_svc.get(inst.id)).values)
        assert after == before

    async def test_broadcast_layout_sends_to_client(self, async_session: AsyncSession):
        sheet_svc, inst_svc, host = await _services(async_session)
        tid, _fid, instances = await _seed(sheet_svc, inst_svc, 1)
        host.seat(instances[0].id)
        await host.start()
        token = await host.join(host.pin, "Вася", instances[0].id)
        ws = _FakeWs()
        await host.attach_ws(token, ws)
        await host.broadcast_layout(tid)
        assert any(m.get("type") == "layout" for m in ws.messages)
        assert host._layout_version >= 1

    async def test_template_image_default_is_served_without_instance_key(
        self, async_session: AsyncSession, tmp_path, qapp
    ):
        """A field added to the template after the sheet was created has no key
        in the map: the web Fill must inherit the template's own picture."""
        from app.infrastructure.images.store import ImageStore

        sheet_svc, inst_svc, _host = await _services(async_session)
        store = ImageStore(async_session, tmp_path / "images")
        inst_svc._image_store = store
        host = TableHostService(inst_svc, sheet_svc, image_store=store)
        row = await sheet_svc.create("Шаблон")
        inst = await inst_svc.create("Лист", row.id)
        image_id = await store.store(_PNG_1PX)
        template = await sheet_svc.load(row.id)
        img = template.add_field(FieldType.IMAGE, (10.0, 10.0))
        img.image_id = image_id
        await sheet_svc.update_pages(row.id, template)
        host.seat(inst.id)
        await host.start()
        token = await host.join(host.pin, "Вася", inst.id)

        sheet = await host.get_sheet(token)
        assert img.id not in sheet["values"]
        by_id = {
            item["id"]: item
            for page in sheet["layout"]["pages"]
            for item in page["fields"]
        }
        assert by_id[img.id]["image_id"] == image_id
        path = await host.preview_path(token, image_id)
        assert path is not None and path.exists()

    async def test_preview_path_refuses_foreign_template_image(
        self, async_session: AsyncSession, tmp_path, qapp
    ):
        from app.infrastructure.images.store import ImageStore

        sheet_svc, inst_svc, _host = await _services(async_session)
        store = ImageStore(async_session, tmp_path / "images")
        host = TableHostService(inst_svc, sheet_svc, image_store=store)
        mine = await sheet_svc.create("Мой")
        other = await sheet_svc.create("Чужой")
        foreign_id = await store.store(_PNG_1PX)
        other_template = await sheet_svc.load(other.id)
        foreign = other_template.add_field(FieldType.IMAGE, (10.0, 10.0))
        foreign.image_id = foreign_id
        await sheet_svc.update_pages(other.id, other_template)
        inst = await inst_svc.create("Лист", mine.id)
        host.seat(inst.id)
        await host.start()
        token = await host.join(host.pin, "Вася", inst.id)

        assert await host.preview_path(token, foreign_id) is None


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
