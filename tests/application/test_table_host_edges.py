"""Edge coverage for table-host HTTP, service coerce, LAN, panel."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer
from PySide6.QtWidgets import QApplication, QMessageBox
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
    PortBusyError,
    TableHostService,
    _coerce_value,
    _new_pin,
)
from app.domain.entities.character_sheet import FieldType, place_field
from app.infrastructure.repositories.character_sheet_instance_repository import (
    CharacterSheetInstanceRepository,
)
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)
from app.infrastructure.table_host.http import create_table_host_app
from app.infrastructure.table_host.lan import local_ipv4_addresses
from app.presentation.views.table_host.panel import TableHostPanel, host_urls, qr_pixmap


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


async def _host(session: AsyncSession, types=None):
    sheet_repo = CharacterSheetRepository(session)
    inst_repo = CharacterSheetInstanceRepository(session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    host = TableHostService(inst_svc, sheet_svc)
    row = await sheet_svc.create("Шаблон")
    template = await sheet_svc.load(row.id)
    fields = {}
    for ftype in types or (FieldType.TEXT,):
        f = template.add_field(ftype, (10.0, 10.0 + 40 * len(fields)))
        if ftype is FieldType.DROPDOWN:
            f.options = ["а", "б"]
        if ftype is FieldType.NUMBER:
            f.min_value = 0.0
            f.max_value = 10.0
        fields[ftype] = f
    await sheet_svc.update_pages(row.id, template)
    inst = await inst_svc.create("Лист", row.id)
    host.seat(inst.id)
    await host.start()
    return host, inst, fields, sheet_svc, inst_svc


async def test_http_503_when_closed():
    app = create_table_host_app(None)
    async with TestClient(TestServer(app)) as client:
        assert (await client.post("/api/join", json={"pin": "1", "name": "a", "instance_id": 1})).status == 503
        assert (await client.get("/api/seats?pin=0000")).status == 503
        assert (await client.get("/api/sheet")).status == 503
        assert (await client.post("/api/field", json={"field_id": "x", "value": 1})).status == 503
        assert (await client.post("/api/image", data=b"", headers={"Content-Type": "text/plain"})).status == 503
        assert (await client.get("/api/image/1")).status == 503
        assert (await client.post("/api/leave")).status == 503
        with pytest.raises(Exception):
            await client.ws_connect("/ws")


async def test_join_seats_sheet_field_http(async_session: AsyncSession):
    host, inst, fields, *_ = await _host(async_session)
    text = fields[FieldType.TEXT]
    app = create_table_host_app(host)
    async with TestClient(TestServer(app)) as client:
        bad = await client.post("/api/join", json={"pin": "nope", "name": "Вася"})
        assert bad.status == 400
        wrong = await client.post(
            "/api/join", json={"pin": "0000", "name": "Вася", "instance_id": inst.id}
        )
        assert wrong.status == 403
        seats = await client.get(f"/api/seats?pin={host.pin}")
        assert seats.status == 200
        body = await seats.json()
        assert body["seats"][0]["instance_id"] == inst.id
        join = await client.post(
            "/api/join",
            json={"pin": host.pin, "name": "Вася", "instance_id": inst.id},
        )
        token = (await join.json())["token"]
        sheet = await client.get("/api/sheet", headers={"Authorization": f"Bearer {token}"})
        assert sheet.status == 200
        data = await sheet.json()
        assert data["instance_id"] == inst.id
        field = await client.post(
            "/api/field",
            json={"field_id": text.id, "value": "ok"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert field.status == 200
        empty_img = await client.post(
            "/api/image",
            data=b"",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain"},
        )
        assert empty_img.status == 400
        missing = await client.get(
            "/api/image/999", headers={"Authorization": f"Bearer {token}"}
        )
        assert missing.status == 404
        ws = await client.ws_connect("/ws", params={"token": "bad"})
        kicked = await ws.receive_json()
        assert kicked["type"] == "kicked"
        await ws.close()


async def test_coerce_and_commit_types(async_session: AsyncSession):
    host, inst, fields, _sheet, inst_svc = await _host(
        async_session,
        types=(FieldType.TEXT, FieldType.CHECKBOX, FieldType.NUMBER, FieldType.DROPDOWN, FieldType.IMAGE),
    )
    token = await host.join(host.pin, "Вася", inst.id)
    await host.commit_field(token, fields[FieldType.CHECKBOX].id, "да")
    await host.commit_field(token, fields[FieldType.NUMBER].id, "3,5")
    await host.commit_field(token, fields[FieldType.DROPDOWN].id, "б")
    await host.commit_field(token, fields[FieldType.IMAGE].id, None)
    with pytest.raises(FieldCommitError):
        await host.commit_field(token, fields[FieldType.IMAGE].id, 1)
    with pytest.raises(FieldCommitError):
        await host.commit_field(token, fields[FieldType.NUMBER].id, "abc")
    with pytest.raises(FieldCommitError):
        await host.commit_field(token, fields[FieldType.NUMBER].id, "99")
    with pytest.raises(FieldCommitError):
        await host.commit_field(token, fields[FieldType.NUMBER].id, "nan")
    with pytest.raises(FieldCommitError):
        await host.commit_field(token, fields[FieldType.NUMBER].id, "inf")
    with pytest.raises(FieldCommitError):
        _coerce_value(place_field(FieldType.NUMBER, (0, 0)), "nan")
    with pytest.raises(FieldCommitError):
        await host.commit_field(token, fields[FieldType.DROPDOWN].id, "нет")
    with pytest.raises(FieldCommitError):
        await host.join(host.pin, "  ", inst.id)
    num = place_field(FieldType.NUMBER, (0, 0))
    num.min_value = 1
    with pytest.raises(FieldCommitError):
        _coerce_value(num, "0")
    assert _coerce_value(place_field(FieldType.CHECKBOX, (0, 0)), True) is True
    assert _coerce_value(place_field(FieldType.TEXT, (0, 0)), None) == ""
    label = place_field(FieldType.LABEL, (0, 0))
    with pytest.raises(FieldCommitError):
        _coerce_value(label, "x")
    img = place_field(FieldType.IMAGE, (0, 0))
    with pytest.raises(FieldCommitError):
        _coerce_value(img, True)
    host.unseat(inst.id)
    host.seat(inst.id)
    await host.kick(inst.id)
    assert host.players() == []
    seen = []
    host.subscribe_values(lambda *a: seen.append(a))
    token2 = await host.join(host.pin, "Петя", inst.id)
    await host.commit_field(token2, fields[FieldType.TEXT].id, "ж")
    assert seen
    assert host.valuesChanged is host._on_values_changed
    with pytest.raises(FieldCommitError):
        await host.store_image(token2, fields[FieldType.IMAGE].id, b"x")
    assert await host.preview_path(token2, 1) is None
    with pytest.raises(InvalidPinError):
        await host.list_seats("0000")
    seats = await host.list_seats(host.pin)
    assert seats
    with pytest.raises(FieldCommitError):
        await host.join(host.pin, "Коля", 999999)
    with pytest.raises(FieldCommitError):
        await host.commit_field(token2, "missing", "x")
    with pytest.raises(InvalidTokenError):
        await host.attach_ws("bad", object())

    class DummyWs:
        async def send_json(self, payload):
            pass

        async def close(self):
            pass

    dummy = DummyWs()
    await host.attach_ws(token2, dummy)
    host.detach_ws(token2, dummy)
    await host.broadcast_layout(-1)
    await host.kick(999999)
    assert _coerce_value(place_field(FieldType.NUMBER, (0, 0)), "") == ""
    assert _coerce_value(place_field(FieldType.NUMBER, (0, 0)), None) == ""


async def test_port_busy(async_session: AsyncSession):
    class Busy:
        async def start(self, **kwargs):
            raise OSError("busy")

        async def stop(self):
            pass

    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    host = TableHostService(inst_svc, sheet_svc, http=Busy())
    row = await sheet_svc.create("Шаблон")
    inst = await inst_svc.create("Лист", row.id)
    host.seat(inst.id)
    with pytest.raises(PortBusyError):
        await host.start(7845)


def test_lan_and_qr(qtbot, monkeypatch):
    ips = local_ipv4_addresses()
    assert isinstance(ips, list)
    urls = host_urls(7845, ["10.0.0.1", "127.0.0.1"])
    assert urls[0] == "http://10.0.0.1:7845/"
    assert urls[-1].startswith("http://127.0.0.1:")
    pix = qr_pixmap(urls[0])
    assert not pix.isNull()
    host = TableHostService(MagicMock(), MagicMock())
    panel = TableHostPanel(host, list_ipv4=lambda: ["10.0.0.8"])
    qtbot.addWidget(panel)
    panel.set_instances([(1, "Лист")])
    assert panel.checked_seat_ids() == []
    from PySide6.QtCore import Qt
    panel.seat_list.item(0).setCheckState(Qt.CheckState.Checked)
    assert panel.checked_seat_ids() == [1]
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    panel.show_start_error(EmptySeatingError())
    panel.show_start_error(RuntimeError("x"))


def test_lan_partial_sources(monkeypatch):
    monkeypatch.setattr(
        "app.infrastructure.table_host.lan.socket.gethostbyname_ex",
        lambda *a, **k: (_ for _ in ()).throw(OSError("x")),
    )
    monkeypatch.setattr(
        "app.infrastructure.table_host.lan.socket.getaddrinfo",
        lambda host, *a, **k: (
            (_ for _ in ()).throw(OSError("x"))
            if host == "lo0"
            else [(None, None, None, None, ("10.1.2.3", 0))]
        ),
    )

    class OkSock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def settimeout(self, t):
            pass

        def connect(self, addr):
            pass

        def getsockname(self):
            return ("10.9.8.7", 0)

    monkeypatch.setattr(
        "app.infrastructure.table_host.lan.socket.socket",
        lambda *a, **k: OkSock(),
    )
    monkeypatch.setattr(
        "app.infrastructure.table_host.lan.socket.if_nameindex",
        lambda: [(1, "lo0"), (2, "en0")],
    )
    ips = local_ipv4_addresses()
    assert "10.1.2.3" in ips
    assert "10.9.8.7" in ips


def test_lan_if_nameindex_missing(monkeypatch):
    monkeypatch.setattr(
        "app.infrastructure.table_host.lan.socket.gethostbyname_ex",
        lambda *a, **k: ("h", [], ["192.168.0.5"]),
    )
    monkeypatch.setattr(
        "app.infrastructure.table_host.lan.socket.getaddrinfo",
        lambda *a, **k: (_ for _ in ()).throw(OSError("x")),
    )

    class BoomSock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def settimeout(self, t):
            pass

        def connect(self, addr):
            raise OSError("x")

    monkeypatch.setattr(
        "app.infrastructure.table_host.lan.socket.socket",
        lambda *a, **k: BoomSock(),
    )
    monkeypatch.setattr(
        "app.infrastructure.table_host.lan.socket.if_nameindex",
        lambda: (_ for _ in ()).throw(AttributeError("x")),
    )
    assert local_ipv4_addresses() == ["192.168.0.5"]


async def test_ws_send_failure_is_swallowed(async_session: AsyncSession):
    host, inst, fields, *_ = await _host(async_session)

    class Boom:
        async def send_json(self, payload):
            raise RuntimeError("gone")

        async def close(self):
            raise RuntimeError("gone")

    token = await host.join(host.pin, "Вася", inst.id)
    await host.attach_ws(token, Boom())
    await host.commit_field(token, fields[FieldType.TEXT].id, "x")
    await host.kick(inst.id)
    host.detach_ws("missing", Boom())
    await host.broadcast_layout(999999)

    class CloseBoom:
        async def send_json(self, payload):
            pass

        async def close(self):
            raise RuntimeError("gone")

    token3 = await host.join(host.pin, "Вася", inst.id)
    await host.attach_ws(token3, CloseBoom())
    await host.attach_ws(token3, Boom())
    await host.kick(inst.id)
    token4 = await host.join(host.pin, "Вася", inst.id)
    await host.attach_ws(token4, CloseBoom())
    await host.kick(inst.id)


def test_new_pin_retries_collision(monkeypatch):
    values = iter([1, 1, 2])
    monkeypatch.setattr(
        "app.application.services.table_host_service.secrets.randbelow",
        lambda n: next(values),
    )
    assert _new_pin("0001") == "0002"


def test_lan_oserror(monkeypatch):
    monkeypatch.setattr(
        "app.infrastructure.table_host.lan.socket.gethostname",
        lambda: (_ for _ in ()).throw(OSError("x")),
    )
    monkeypatch.setattr(
        "app.infrastructure.table_host.lan.socket.getaddrinfo",
        lambda *a, **k: (_ for _ in ()).throw(OSError("x")),
    )
    monkeypatch.setattr(
        "app.infrastructure.table_host.lan.socket.gethostbyname_ex",
        lambda *a, **k: (_ for _ in ()).throw(OSError("x")),
    )

    class BoomSock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def settimeout(self, t):
            pass

        def connect(self, addr):
            raise OSError("x")

    monkeypatch.setattr(
        "app.infrastructure.table_host.lan.socket.socket",
        lambda *a, **k: BoomSock(),
    )
    monkeypatch.setattr(
        "app.infrastructure.table_host.lan.socket.if_nameindex",
        lambda: (_ for _ in ()).throw(OSError("x")),
    )
    assert local_ipv4_addresses() == []


async def test_stop_calls_http(async_session: AsyncSession):
    class FakeHttp:
        def __init__(self):
            self.stopped = False

        async def start(self, **kwargs):
            pass

        async def stop(self):
            self.stopped = True

    http = FakeHttp()
    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    host = TableHostService(inst_svc, sheet_svc, http=http)
    row = await sheet_svc.create("Шаблон")
    inst = await inst_svc.create("Лист", row.id)
    host.seat(inst.id)
    await host.start(7845)
    await host.stop()
    assert http.stopped


async def test_http_unexpected_errors_and_table_host_status(async_session: AsyncSession):
    host, inst, fields, *_ = await _host(async_session)
    app = create_table_host_app(host)
    async with TestClient(TestServer(app)) as client:
        empty = await client.post(
            "/api/join",
            json={"pin": host.pin, "name": "  ", "instance_id": inst.id},
        )
        assert empty.status == 400
        taken = await client.post(
            "/api/join",
            json={"pin": host.pin, "name": "Вася", "instance_id": inst.id},
        )
        token = (await taken.json())["token"]
        again = await client.post(
            "/api/join",
            json={"pin": host.pin, "name": "Петя", "instance_id": inst.id},
        )
        assert again.status == 409
        sheet_bad = await client.get("/api/sheet")
        assert sheet_bad.status == 409
        field_bad = await client.post(
            "/api/field",
            json={"field_id": "x", "value": 1},
            headers={"Authorization": "Bearer nope"},
        )
        assert field_bad.status == 409
        img_bad = await client.post(
            "/api/image",
            data=b"--x\r\nContent-Disposition: form-data; name=\"field_id\"\r\n\r\nf\r\n--x--\r\n",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "multipart/form-data; boundary=x",
            },
        )
        assert img_bad.status in (400, 200)
        img_token = await client.post(
            "/api/image",
            data=b"--x\r\nContent-Disposition: form-data; name=\"field_id\"\r\n\r\nf\r\n--x\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.png\"\r\nContent-Type: image/png\r\n\r\nnotimg\r\n--x--\r\n",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "multipart/form-data; boundary=x",
            },
        )
        assert img_token.status in (400, 409)
        get_bad_id = await client.get(
            "/api/image/x", headers={"Authorization": f"Bearer {token}"}
        )
        assert get_bad_id.status == 400
        get_token = await client.get(
            "/api/image/1", headers={"Authorization": "Bearer nope"}
        )
        assert get_token.status == 409
        from aiohttp import FormData as _Form
        no_store = _Form()
        no_store.add_field("field_id", fields[FieldType.TEXT].id)
        no_store.add_field("file", b"abc", filename="a.png", content_type="image/png")
        stored_err = await client.post(
            "/api/image",
            data=no_store,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert stored_err.status == 400
        seats_pin = await client.get("/api/seats?pin=0000")
        assert seats_pin.status == 403
        sheet_q = await client.get(f"/api/sheet?token={token}")
        assert sheet_q.status == 200

    class Exploding:
        async def join(self, *a, **k):
            raise RuntimeError("x")

        async def list_seats(self, *a, **k):
            raise RuntimeError("x")

        async def get_sheet(self, *a, **k):
            raise RuntimeError("x")

        async def commit_field(self, *a, **k):
            raise RuntimeError("x")

        async def store_image(self, *a, **k):
            raise RuntimeError("x")

        async def preview_path(self, *a, **k):
            raise RuntimeError("x")

        async def leave(self, *a, **k):
            raise RuntimeError("x")

        def attach_ws(self, *a, **k):
            raise RuntimeError("x")

        def detach_ws(self, *a, **k):
            pass

    boom_app = create_table_host_app(Exploding())
    async with TestClient(TestServer(boom_app)) as client:
        join = await client.post(
            "/api/join", json={"pin": "1", "name": "a", "instance_id": 1}
        )
        assert join.status == 500
        seats = await client.get("/api/seats?pin=1")
        assert seats.status == 500
        sheet = await client.get("/api/sheet")
        assert sheet.status == 500
        field = await client.post("/api/field", json={"field_id": "x", "value": 1})
        assert field.status == 500
        from aiohttp import FormData
        form = FormData()
        form.add_field("field_id", "f")
        form.add_field("file", b"abc", filename="a.png", content_type="image/png")
        image = await client.post("/api/image", data=form)
        assert image.status == 500
        preview = await client.get("/api/image/1")
        assert preview.status == 400
        leave = await client.post("/api/leave")
        assert leave.status == 500
        try:
            ws = await client.ws_connect("/ws")
            await ws.close()
        except Exception:
            pass


async def test_http_never_started_stop():
    from app.infrastructure.table_host.http import TableHostHttp

    http = TableHostHttp()
    await http.stop()
    assert http.runner is None


async def test_start_oserror_cleans_runner():
    import socket as _socket

    from app.infrastructure.table_host.http import TableHostHttp

    occupier = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    occupier.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
    occupier.bind(("127.0.0.1", 0))
    occupier.listen(1)
    port = occupier.getsockname()[1]
    http = TableHostHttp()
    try:
        with pytest.raises(OSError):
            await http.start(host="127.0.0.1", port=port)
        assert http.runner is None
    finally:
        occupier.close()
        if http.runner is not None:
            await http.stop()


async def test_multipart_read_error(monkeypatch, async_session: AsyncSession):
    import app.infrastructure.table_host.http as http_mod

    async def boom(_request):
        raise RuntimeError("bad")

    monkeypatch.setattr(http_mod, "_read_multipart_image", boom)
    host, inst, fields, *_ = await _host(async_session)
    token = await host.join(host.pin, "Вася", inst.id)
    app = create_table_host_app(host)
    async with TestClient(TestServer(app)) as client:
        from aiohttp import FormData
        form = FormData()
        form.add_field("field_id", "f")
        form.add_field("file", b"abc", filename="a.png", content_type="image/png")
        resp = await client.post(
            "/api/image",
            data=form,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status == 400


async def test_multipart_too_large(monkeypatch, async_session: AsyncSession):
    import app.infrastructure.table_host.http as http_mod
    from aiohttp.web_exceptions import HTTPRequestEntityTooLarge

    async def boom(_request):
        raise HTTPRequestEntityTooLarge(max_size=1, actual_size=2)

    monkeypatch.setattr(http_mod, "_read_multipart_image", boom)
    host, inst, fields, *_ = await _host(async_session)
    token = await host.join(host.pin, "Вася", inst.id)
    app = create_table_host_app(host)
    async with TestClient(TestServer(app)) as client:
        from aiohttp import FormData
        form = FormData()
        form.add_field("field_id", "f")
        form.add_field("file", b"abc", filename="a.png", content_type="image/png")
        resp = await client.post(
            "/api/image",
            data=form,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status == 413
        body = await resp.json()
        assert "больш" in body["error"].lower()
