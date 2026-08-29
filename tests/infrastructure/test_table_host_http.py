"""Tests for the table-host HTTP skeleton (tasks 1.2 / 1.3).

In-process aiohttp TestClient / TestServer — no external network.
"""
from __future__ import annotations

from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from app.infrastructure.table_host.http import (
    TableHostHttp,
    create_table_host_app,
    web_static_dir,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SPEC_PATH = REPO_ROOT / "nri_manager.spec"
WEB_SRC = "app/presentation/views/table_host/web"


async def test_get_root_returns_html():
    app = create_table_host_app()
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/")
        assert resp.status == 200
        ctype = resp.headers.get("Content-Type", "")
        text = await resp.text()
        assert "html" in ctype.lower() or "<html" in text.lower()
        assert "PIN" in text or "пин" in text.lower() or "Пин" in text or "код" in text.lower()


async def test_runner_start_and_stop():
    http = TableHostHttp()
    await http.start(host="127.0.0.1", port=0)
    try:
        assert http.runner is not None
    finally:
        await http.stop()
    assert http.runner is None


def test_spec_datas_contains_web_static():
    text = SPEC_PATH.read_text(encoding="utf-8")
    datas = text.split("datas=[", 1)[1].rsplit("]", 1)[0]
    assert WEB_SRC in datas
    assert (REPO_ROOT / WEB_SRC / "index.html").is_file()
    assert web_static_dir().is_dir()


async def test_post_image_multipart_returns_image_id(async_session, tmp_path, qapp):
    import json

    from aiohttp import FormData
    from aiohttp.test_utils import TestClient, TestServer

    from app.application.services.character_sheet_instance_service import (
        CharacterSheetInstanceService,
    )
    from app.application.services.character_sheet_service import CharacterSheetService
    from app.application.services.table_host_service import TableHostService
    from app.domain.enums.field_type import FieldType
    from app.infrastructure.images.store import ImageStore
    from app.infrastructure.repositories.character_sheet_instance_repository import (
        CharacterSheetInstanceRepository,
    )
    from app.infrastructure.repositories.character_sheet_repository import (
        CharacterSheetRepository,
    )
    from tests.application.test_table_host_service import _PNG_1PX as PNG

    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    store = ImageStore(async_session, tmp_path / "images")
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc, image_store=store)
    host = TableHostService(inst_svc, sheet_svc, image_store=store)
    row = await sheet_svc.create("Шаблон")
    template = await sheet_svc.load(row.id)
    img = template.add_field(FieldType.IMAGE, (10.0, 10.0))
    await sheet_svc.update_pages(row.id, template)
    inst = await inst_svc.create("Лист", row.id)
    host.seat(inst.id)
    await host.start()
    token = await host.join(host.pin, "Вася", inst.id)
    app = create_table_host_app(host)
    async with TestClient(TestServer(app)) as client:
        form = FormData()
        form.add_field("field_id", img.id)
        form.add_field("file", PNG, filename="p.png", content_type="image/png")
        resp = await client.post(
            "/api/image", data=form, headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status == 200
        body = await resp.json()
        assert "image_id" in body
        stored = json.loads((await inst_svc.get(inst.id)).values)
        assert stored[img.id] == body["image_id"]
        preview = await client.get(
            f"/api/image/{body['image_id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert preview.status == 200
        static = await client.get("/static/app.js")
        assert static.status == 200


async def test_ws_value_kicked_stopped(async_session):
    from aiohttp.test_utils import TestClient, TestServer

    from app.application.services.character_sheet_instance_service import (
        CharacterSheetInstanceService,
    )
    from app.application.services.character_sheet_service import CharacterSheetService
    from app.application.services.table_host_service import TableHostService
    from app.domain.enums.field_type import FieldType
    from app.infrastructure.repositories.character_sheet_instance_repository import (
        CharacterSheetInstanceRepository,
    )
    from app.infrastructure.repositories.character_sheet_repository import (
        CharacterSheetRepository,
    )

    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    host = TableHostService(inst_svc, sheet_svc)
    row = await sheet_svc.create("Шаблон")
    template = await sheet_svc.load(row.id)
    text_f = template.add_field(FieldType.TEXT, (10.0, 10.0))
    await sheet_svc.update_pages(row.id, template)
    inst = await inst_svc.create("Лист", row.id)
    host.seat(inst.id)
    await host.start()
    token = await host.join(host.pin, "Вася", inst.id)
    app = create_table_host_app(host)
    async with TestClient(TestServer(app)) as client:
        ws = await client.ws_connect("/ws", params={"token": token})
        await ws.send_str("ping")
        await host.commit_field(token, text_f.id, "с сокета")
        msg = await ws.receive_json()
        assert msg["type"] == "value"
        assert msg["value"] == "с сокета"
        token2 = await host.join(host.pin, "Вася", inst.id)
        kicked = await ws.receive_json()
        assert kicked["type"] == "kicked"
        await ws.close()
        ws2 = await client.ws_connect("/ws", params={"token": token2})
        await host.stop()
        stopped = await ws2.receive_json()
        assert stopped["type"] == "stopped"
        await ws2.close()


async def test_ws_layout_via_test_client(async_session):
    from aiohttp.test_utils import TestClient, TestServer

    from app.application.services.character_sheet_instance_service import (
        CharacterSheetInstanceService,
    )
    from app.application.services.character_sheet_service import CharacterSheetService
    from app.application.services.table_host_service import TableHostService
    from app.domain.enums.field_type import FieldType
    from app.infrastructure.repositories.character_sheet_instance_repository import (
        CharacterSheetInstanceRepository,
    )
    from app.infrastructure.repositories.character_sheet_repository import (
        CharacterSheetRepository,
    )

    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    host = TableHostService(inst_svc, sheet_svc)
    row = await sheet_svc.create("Шаблон")
    template = await sheet_svc.load(row.id)
    template.add_field(FieldType.TEXT, (10.0, 10.0))
    await sheet_svc.update_pages(row.id, template)
    inst = await inst_svc.create("Лист", row.id)
    host.seat(inst.id)
    await host.start()
    token = await host.join(host.pin, "Вася", inst.id)
    app = create_table_host_app(host)
    async with TestClient(TestServer(app)) as client:
        ws = await client.ws_connect("/ws", params={"token": token})
        await host.broadcast_layout(row.id)
        msg = await ws.receive_json()
        assert msg["type"] == "layout"
        await ws.close()


async def test_leave_endpoint_frees_seat(async_session):
    from aiohttp.test_utils import TestClient, TestServer

    from app.application.services.character_sheet_instance_service import (
        CharacterSheetInstanceService,
    )
    from app.application.services.character_sheet_service import CharacterSheetService
    from app.application.services.table_host_service import TableHostService
    from app.domain.enums.field_type import FieldType
    from app.infrastructure.repositories.character_sheet_instance_repository import (
        CharacterSheetInstanceRepository,
    )
    from app.infrastructure.repositories.character_sheet_repository import (
        CharacterSheetRepository,
    )

    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    host = TableHostService(inst_svc, sheet_svc)
    row = await sheet_svc.create("Шаблон")
    template = await sheet_svc.load(row.id)
    template.add_field(FieldType.TEXT, (10.0, 10.0))
    await sheet_svc.update_pages(row.id, template)
    inst = await inst_svc.create("Лист", row.id)
    host.seat(inst.id)
    await host.start()
    token = await host.join(host.pin, "Вася", inst.id)
    app = create_table_host_app(host)
    async with TestClient(TestServer(app)) as client:
        resp = await client.post(
            "/api/leave", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status == 200
        assert host.occupancy == {}
        again = await client.post("/api/leave", params={"token": token})
        assert again.status == 200


async def test_post_image_over_1mb_reaches_store(async_session, tmp_path, qapp):
    from aiohttp import FormData
    from aiohttp.test_utils import TestClient, TestServer

    from app.application.services.character_sheet_instance_service import (
        CharacterSheetInstanceService,
    )
    from app.application.services.character_sheet_service import CharacterSheetService
    from app.application.services.table_host_service import TableHostService
    from app.domain.enums.field_type import FieldType
    from app.infrastructure.images.store import ImageStore
    from app.infrastructure.repositories.character_sheet_instance_repository import (
        CharacterSheetInstanceRepository,
    )
    from app.infrastructure.repositories.character_sheet_repository import (
        CharacterSheetRepository,
    )
    from tests.application.test_table_host_service import _PNG_1PX as PNG

    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    store = ImageStore(async_session, tmp_path / "images")
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc, image_store=store)
    host = TableHostService(inst_svc, sheet_svc, image_store=store)
    row = await sheet_svc.create("Шаблон")
    template = await sheet_svc.load(row.id)
    img = template.add_field(FieldType.IMAGE, (10.0, 10.0))
    await sheet_svc.update_pages(row.id, template)
    inst = await inst_svc.create("Лист", row.id)
    host.seat(inst.id)
    await host.start()
    token = await host.join(host.pin, "Вася", inst.id)
    app = create_table_host_app(host)
    async with TestClient(TestServer(app)) as client:
        form = FormData()
        form.add_field("field_id", img.id)
        form.add_field(
            "file",
            PNG + b"\x00" * (2 * 1024 * 1024),
            filename="big.png",
            content_type="image/png",
        )
        resp = await client.post(
            "/api/image", data=form, headers={"Authorization": f"Bearer {token}"}
        )
        body = await resp.json()
        assert body.get("error") != "Нет файла"
        assert resp.status in (200, 400)


async def test_max_size_middleware_returns_json():
    from aiohttp.web_exceptions import HTTPRequestEntityTooLarge

    from app.infrastructure.table_host.http import _max_size_middleware

    async def boom(_request):
        raise HTTPRequestEntityTooLarge(max_size=10, actual_size=99)

    resp = await _max_size_middleware(None, boom)
    assert resp.status == 413
    import json as _json
    body = _json.loads(resp.body.decode())
    assert "больш" in body["error"].lower()


async def test_handler_too_large_is_not_missing_file(monkeypatch, async_session):
    from aiohttp import FormData
    from aiohttp.test_utils import TestClient, TestServer

    from app.application.services.character_sheet_instance_service import (
        CharacterSheetInstanceService,
    )
    from app.application.services.character_sheet_service import CharacterSheetService
    from app.application.services.table_host_service import TableHostService
    from app.domain.enums.field_type import FieldType
    from app.infrastructure.repositories.character_sheet_instance_repository import (
        CharacterSheetInstanceRepository,
    )
    from app.infrastructure.repositories.character_sheet_repository import (
        CharacterSheetRepository,
    )
    from app.infrastructure.table_host.http import create_table_host_app as _create

    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    host = TableHostService(inst_svc, sheet_svc)
    row = await sheet_svc.create("Шаблон")
    template = await sheet_svc.load(row.id)
    img = template.add_field(FieldType.IMAGE, (10.0, 10.0))
    await sheet_svc.update_pages(row.id, template)
    inst = await inst_svc.create("Лист", row.id)
    host.seat(inst.id)
    await host.start()
    token = await host.join(host.pin, "Вася", inst.id)
    app = _create(host, client_max_size=1024)
    async with TestClient(TestServer(app)) as client:
        form = FormData()
        form.add_field("field_id", img.id)
        form.add_field(
            "file", b"x" * 4096, filename="big.bin", content_type="application/octet-stream"
        )
        resp = await client.post(
            "/api/image", data=form, headers={"Authorization": f"Bearer {token}"}
        )
        body = await resp.json()
        assert resp.status == 413
        assert "больш" in body.get("error", "").lower() or "файл" in body.get("error", "").lower()


def test_web_client_has_leave_clear_pinch_and_seat_poll():
    js = (web_static_dir() / "app.js").read_text(encoding="utf-8")
    html = (web_static_dir() / "index.html").read_text(encoding="utf-8")
    assert "Выйти" in html or "leave" in js
    assert "/api/leave" in js
    assert "Убрать" in js
    assert "touchstart" in js and "touchmove" in js
    assert "setInterval" in js
    assert "captureDrafts" in js or "draft" in js.lower()


