"""aiohttp app for the table host (design D1).

``AppRunner`` + ``TCPSite`` on the already-running qasync loop — never
``web.run_app``. Tests use ``aiohttp.TestClient`` / ``TestServer``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from aiohttp import web
from aiohttp.web_exceptions import HTTPRequestEntityTooLarge

DEFAULT_PORT = 7845
MAX_UPLOAD_BYTES = 16 * 1024 * 1024


def web_static_dir() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "presentation"
        / "views"
        / "table_host"
        / "web"
    )


TABLE_HOST_KEY = web.AppKey("table_host", object)


async def handle_index(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(web_static_dir() / "index.html")


def _service(request: web.Request):
    return request.app[TABLE_HOST_KEY]


def _token_of(request: web.Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return str(request.query.get("token") or "")


def _error_response(exc: Exception) -> web.Response:
    from app.application.services.table_host_service import (
        InvalidPinError,
        InvalidTokenError,
        NameTakenError,
        SeatTakenError,
        TableHostError,
    )

    status = 400
    if isinstance(exc, InvalidPinError):
        status = 403
    elif isinstance(exc, (NameTakenError, SeatTakenError, InvalidTokenError)):
        status = 409
    elif isinstance(exc, TableHostError):
        status = 400
    return web.json_response({"error": str(exc)}, status=status)


async def handle_join(request: web.Request) -> web.Response:
    service = _service(request)
    if service is None:
        return web.json_response({"error": "Стол закрыт"}, status=503)
    body: dict[str, Any] = await request.json()
    try:
        token = await service.join(
            str(body.get("pin", "")),
            str(body.get("name", "")),
            int(body["instance_id"]),
        )
    except (KeyError, TypeError, ValueError):
        return web.json_response({"error": "Некорректный запрос"}, status=400)
    except Exception as exc:
        from app.application.services.table_host_service import TableHostError
        if isinstance(exc, TableHostError):
            return _error_response(exc)
        raise
    return web.json_response({"token": token})


async def handle_seats(request: web.Request) -> web.Response:
    service = _service(request)
    if service is None:
        return web.json_response({"error": "Стол закрыт"}, status=503)
    pin = str(request.query.get("pin") or "")
    try:
        seats = await service.list_seats(pin)
    except Exception as exc:
        from app.application.services.table_host_service import TableHostError
        if isinstance(exc, TableHostError):
            return _error_response(exc)
        raise
    return web.json_response({"seats": seats})


async def handle_sheet(request: web.Request) -> web.Response:
    service = _service(request)
    if service is None:
        return web.json_response({"error": "Стол закрыт"}, status=503)
    try:
        sheet = await service.get_sheet(_token_of(request))
    except Exception as exc:
        from app.application.services.table_host_service import TableHostError
        if isinstance(exc, TableHostError):
            return _error_response(exc)
        raise
    return web.json_response(sheet)


async def handle_field(request: web.Request) -> web.Response:
    service = _service(request)
    if service is None:
        return web.json_response({"error": "Стол закрыт"}, status=503)
    body: dict[str, Any] = await request.json()
    try:
        value = await service.commit_field(
            _token_of(request),
            str(body.get("field_id", "")),
            body.get("value"),
        )
    except Exception as exc:
        from app.application.services.table_host_service import TableHostError
        if isinstance(exc, TableHostError):
            return _error_response(exc)
        raise
    return web.json_response({"ok": True, "value": value})


async def handle_leave(request: web.Request) -> web.Response:
    service = _service(request)
    if service is None:
        return web.json_response({"error": "Стол закрыт"}, status=503)
    await service.leave(_token_of(request))
    return web.json_response({"ok": True})

async def _read_multipart_image(request: web.Request) -> tuple[str, bytes]:
    reader = await request.multipart()
    field_id = ""
    data = b""
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "field_id":
            field_id = (await part.read()).decode("utf-8", errors="replace")
        elif part.name in ("file", "image"):
            data = await part.read()
    return field_id, data


async def handle_image_post(request: web.Request) -> web.Response:
    service = _service(request)
    if service is None:
        return web.json_response({"error": "Стол закрыт"}, status=503)
    if "multipart" not in (request.content_type or ""):
        return web.json_response({"error": "Нет файла"}, status=400)
    try:
        field_id, data = await _read_multipart_image(request)
    except HTTPRequestEntityTooLarge:
        return web.json_response({"error": "Файл слишком большой"}, status=413)
    except Exception:
        return web.json_response({"error": "Нет файла"}, status=400)
    if not field_id or not data:
        return web.json_response({"error": "Нет файла"}, status=400)
    try:
        image_id = await service.store_image(_token_of(request), field_id, data)
    except Exception as exc:
        from app.application.services.table_host_service import TableHostError
        if isinstance(exc, TableHostError):
            return _error_response(exc)
        raise
    return web.json_response({"image_id": image_id})


async def handle_image_get(request: web.Request) -> web.StreamResponse:
    service = _service(request)
    if service is None:
        return web.json_response({"error": "Стол закрыт"}, status=503)
    try:
        image_id = int(request.match_info["id"])
        path = await service.preview_path(_token_of(request), image_id)
    except Exception as exc:
        from app.application.services.table_host_service import TableHostError
        if isinstance(exc, TableHostError):
            return _error_response(exc)
        return web.json_response({"error": "Некорректный запрос"}, status=400)
    if path is None or not path.exists():
        return web.json_response({"error": "Нет изображения"}, status=404)
    return web.FileResponse(path)


async def handle_ws(request: web.Request) -> web.StreamResponse:
    service = _service(request)
    if service is None:
        return web.json_response({"error": "Стол закрыт"}, status=503)
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    token = _token_of(request)
    try:
        await service.attach_ws(token, ws)
    except Exception as exc:
        from app.application.services.table_host_service import TableHostError
        if isinstance(exc, TableHostError):
            await ws.send_json({"type": "kicked"})
            await ws.close()
            return ws
        raise
    try:
        async for _msg in ws:
            pass
    finally:
        service.detach_ws(token, ws)
    return ws


@web.middleware
async def _max_size_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except HTTPRequestEntityTooLarge:
        return web.json_response({"error": "Файл слишком большой"}, status=413)


def create_table_host_app(
    service=None, *, client_max_size: int = MAX_UPLOAD_BYTES
) -> web.Application:
    app = web.Application(
        client_max_size=client_max_size,
        middlewares=[_max_size_middleware],
    )
    app[TABLE_HOST_KEY] = service
    static = web_static_dir()
    app.router.add_get("/", handle_index)
    app.router.add_post("/api/join", handle_join)
    app.router.add_get("/api/seats", handle_seats)
    app.router.add_get("/api/sheet", handle_sheet)
    app.router.add_post("/api/field", handle_field)
    app.router.add_post("/api/leave", handle_leave)
    app.router.add_post("/api/image", handle_image_post)
    app.router.add_get("/api/image/{id}", handle_image_get)
    app.router.add_get("/ws", handle_ws)
    if static.is_dir():
        app.router.add_static("/static", static, name="static")
    return app


class TableHostHttp:
    """Lifecycle wrapper: ``start`` / ``stop`` around AppRunner + TCPSite."""

    def __init__(self, app: web.Application | None = None) -> None:
        self._app = app if app is not None else create_table_host_app()
        self.runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    async def start(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        runner = web.AppRunner(self._app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        try:
            await site.start()
        except OSError:
            await runner.cleanup()
            raise
        self.runner = runner
        self._site = site

    async def stop(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()
        self.runner = None
        self._site = None
