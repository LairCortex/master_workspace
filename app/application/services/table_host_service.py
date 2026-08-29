"""Table-host session: seating, PIN, join, field commit (design D2, D3)."""
from __future__ import annotations

import json
import math
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from app.application.services.character_sheet_instance_service import (
    CharacterSheetInstanceService,
)
from app.application.services.character_sheet_service import CharacterSheetService
from app.domain.entities.character_sheet import SheetField
from app.domain.entities.character_sheet_instance import (
    FILLABLE_TYPES,
    iter_instance_image_ids,
)
from app.domain.entities.sheet_html_layout import html_layout
from app.domain.enums.field_type import FieldType
from app.infrastructure.images.store import ImageStore
from app.infrastructure.table_host.http import DEFAULT_PORT

if TYPE_CHECKING:
    from app.infrastructure.table_host.http import TableHostHttp


class TableHostError(Exception):
    """Base error for the table-host session."""


class EmptySeatingError(TableHostError):
    def __init__(self) -> None:
        super().__init__("Нет посадки")


class PortBusyError(TableHostError):
    def __init__(self, port: int) -> None:
        super().__init__(f"Порт {port} занят")
        self.port = port


class InvalidPinError(TableHostError):
    def __init__(self) -> None:
        super().__init__("Неверный PIN")


class NameTakenError(TableHostError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Имя «{name}» уже за столом")
        self.name = name


class SeatTakenError(TableHostError):
    def __init__(self, instance_id: int) -> None:
        super().__init__("Лист занят")
        self.instance_id = instance_id


class InvalidTokenError(TableHostError):
    def __init__(self) -> None:
        super().__init__("Сессия недействительна")


class FieldCommitError(TableHostError):
    def __init__(self, message: str = "Нельзя записать поле") -> None:
        super().__init__(message)


@dataclass
class Occupancy:
    name: str
    token: str
    ws: Any = None


def _new_pin(previous: str | None) -> str:
    pin = f"{secrets.randbelow(10000):04d}"
    while pin == previous:
        pin = f"{secrets.randbelow(10000):04d}"
    return pin


class TableHostService:
    def __init__(
        self,
        instance_service: CharacterSheetInstanceService,
        sheet_service: CharacterSheetService,
        image_store: ImageStore | None = None,
        http: TableHostHttp | None = None,
    ) -> None:
        self._instance_service = instance_service
        self._sheet_service = sheet_service
        self._image_store = image_store
        self._http = http
        self._seated_ids: set[int] = set()
        self._occupancy: dict[int, Occupancy] = {}
        self._tokens: dict[str, int] = {}
        self._pin: str | None = None
        self._running = False
        self._port = DEFAULT_PORT
        self._on_values_changed: list[Callable[[int, str, Any], None]] = []
        self._on_occupancy_changed: list[Callable[[], None]] = []
        self._layout_version: int = 0

    def set_http(self, http: TableHostHttp | None) -> None:
        self._http = http

    # -- observers (D5) -----------------------------------------------------

    def subscribe_values(self, callback: Callable[[int, str, Any], None]) -> None:
        self._on_values_changed.append(callback)

    def subscribe_occupancy(self, callback: Callable[[], None]) -> None:
        self._on_occupancy_changed.append(callback)

    @property
    def valuesChanged(self) -> list[Callable[[int, str, Any], None]]:
        return self._on_values_changed

    # -- state --------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def pin(self) -> str | None:
        return self._pin

    @property
    def port(self) -> int:
        return self._port

    @property
    def seated_ids(self) -> set[int]:
        return set(self._seated_ids)

    @property
    def occupancy(self) -> dict[int, Occupancy]:
        return dict(self._occupancy)

    def is_seated(self, instance_id: int) -> bool:
        return self._running and instance_id in self._seated_ids

    def seat(self, instance_id: int) -> None:
        self._seated_ids.add(instance_id)
        self._notify_occupancy()

    def set_seating(self, instance_ids: Iterable[int]) -> None:
        self._seated_ids = {int(i) for i in instance_ids}
        self._notify_occupancy()

    def unseat(self, instance_id: int) -> None:
        self._seated_ids.discard(instance_id)
        self._notify_occupancy()

    def players(self) -> list[tuple[int, str]]:
        return [(iid, occ.name) for iid, occ in self._occupancy.items()]

    # -- lifecycle ----------------------------------------------------------

    async def start(self, port: int = DEFAULT_PORT) -> None:
        if not self._seated_ids:
            raise EmptySeatingError()
        if self._http is not None:
            try:
                await self._http.start(host="0.0.0.0", port=port)
            except OSError as exc:
                raise PortBusyError(port) from exc
        self._pin = _new_pin(self._pin)
        self._port = port
        self._running = True
        self._occupancy.clear()
        self._tokens.clear()

    async def stop(self) -> None:
        for occ in list(self._occupancy.values()):
            await self._close_ws(occ, {"type": "stopped"})
        self._occupancy.clear()
        self._tokens.clear()
        self._running = False
        if self._http is not None:
            await self._http.stop()
        self._notify_occupancy()

    # -- join / sheet / field -----------------------------------------------

    async def join(self, pin: str, name: str, instance_id: int) -> str:
        if not self._running or pin != self._pin:
            raise InvalidPinError()
        name = (name or "").strip()
        if not name:
            raise FieldCommitError("Имя не может быть пустым")
        if instance_id not in self._seated_ids:
            raise FieldCommitError("Лист не в посадке")

        occupied_by_name = next(
            (iid for iid, occ in self._occupancy.items() if occ.name == name),
            None,
        )
        if occupied_by_name is not None:
            if occupied_by_name != instance_id:
                raise NameTakenError(name)
            await self._evict(occupied_by_name)
        elif instance_id in self._occupancy:
            raise SeatTakenError(instance_id)

        token = secrets.token_urlsafe(32)
        self._occupancy[instance_id] = Occupancy(name=name, token=token)
        self._tokens[token] = instance_id
        self._notify_occupancy()
        return token

    async def get_sheet(self, token: str) -> dict[str, Any]:
        instance_id = self._require_token(token)
        row = await self._instance_service.get(instance_id)
        template = await self._sheet_service.load(row.template_id)
        return {
            "instance_id": instance_id,
            "template_id": row.template_id,
            "values": json.loads(row.values),
            "layout": html_layout(template),
            "orientation": template.orientation,
            "name": row.name,
        }

    async def list_seats(self, pin: str) -> list[dict[str, Any]]:
        if not self._running or pin != self._pin:
            raise InvalidPinError()
        out: list[dict[str, Any]] = []
        for instance_id in sorted(self._seated_ids):
            row = await self._instance_service.get(instance_id)
            occ = self._occupancy.get(instance_id)
            out.append({
                "instance_id": instance_id,
                "sheet_name": row.name,
                "occupied_by": None if occ is None else occ.name,
            })
        return out

    async def commit_field(self, token: str, field_id: str, value: Any) -> Any:
        instance_id = self._require_token(token)
        row = await self._instance_service.get(instance_id)
        template = await self._sheet_service.load(row.template_id)
        field_obj = template.get_field(field_id)
        if field_obj is None or field_obj.type not in FILLABLE_TYPES:
            raise FieldCommitError()
        coerced = _coerce_value(field_obj, value)
        if field_obj.type is FieldType.IMAGE and coerced is not None:
            if self._image_store is None:
                raise FieldCommitError("Нет изображения")
            path = await self._image_store.preview_file_path(int(coerced))
            if path is None or not path.exists():
                raise FieldCommitError("Нет изображения")
        values = json.loads(row.values)
        values[field_id] = coerced
        await self._instance_service.update_values(instance_id, values)
        await self._broadcast(instance_id, {
            "type": "value",
            "instance_id": instance_id,
            "field_id": field_id,
            "value": coerced,
        })
        for callback in list(self._on_values_changed):
            callback(instance_id, field_id, coerced)
        return coerced

    async def kick(self, instance_id: int) -> None:
        await self._evict(instance_id)
        self._notify_occupancy()

    async def leave(self, token: str) -> None:
        instance_id = self._tokens.get(token)
        if instance_id is None:
            return
        await self._evict(instance_id)
        self._notify_occupancy()

    async def drop_seat(self, instance_id: int) -> None:
        await self._evict(instance_id)
        self._seated_ids.discard(instance_id)
        self._notify_occupancy()

    async def attach_ws(self, token: str, ws: Any) -> int:
        instance_id = self._require_token(token)
        occ = self._occupancy[instance_id]
        old = occ.ws
        occ.ws = ws
        if old is not None and old is not ws:
            try:
                await old.close()
            except Exception:
                pass
        return instance_id

    def detach_ws(self, token: str, ws: Any) -> None:
        instance_id = self._tokens.get(token)
        if instance_id is None:
            return
        occ = self._occupancy.get(instance_id)
        if occ is not None and occ.ws is ws:
            occ.ws = None

    async def broadcast_layout(self, template_id: int) -> None:
        self._layout_version += 1
        for instance_id, occ in list(self._occupancy.items()):
            row = await self._instance_service.get(instance_id)
            if row.template_id != template_id:
                continue
            await self._send_ws(occ, {"type": "layout", "template_id": template_id})

    async def store_image(self, token: str, field_id: str, data: bytes) -> int:
        instance_id = self._require_token(token)
        row = await self._instance_service.get(instance_id)
        template = await self._sheet_service.load(row.template_id)
        field_obj = template.get_field(field_id)
        if field_obj is None or field_obj.type is not FieldType.IMAGE:
            raise FieldCommitError()
        if self._image_store is None:
            raise FieldCommitError("Хранилище изображений недоступно")
        try:
            image_id = await self._image_store.store(data)
        except ValueError as exc:
            raise FieldCommitError("Файл повреждён или не является изображением") from exc
        await self.commit_field(token, field_id, image_id)
        return image_id

    async def preview_path(self, token: str, image_id: int):
        instance_id = self._require_token(token)
        if self._image_store is None:
            return None
        row = await self._instance_service.get(instance_id)
        if image_id not in iter_instance_image_ids(row.values):
            # a picture the map does not carry may still be the template's own
            # default (a field added after the sheet was created): the web Fill
            # inherits it, so its preview must be reachable — and nothing else.
            template = await self._sheet_service.load(row.template_id)
            if image_id not in _template_image_ids(template):
                return None
        return await self._image_store.preview_file_path(image_id)

    # -- internals ----------------------------------------------------------

    def _require_token(self, token: str) -> int:
        if not self._running:
            raise InvalidTokenError()
        instance_id = self._tokens.get(token)
        if instance_id is None:
            raise InvalidTokenError()
        return instance_id

    async def _evict(self, instance_id: int) -> None:
        occ = self._occupancy.pop(instance_id, None)
        if occ is None:
            return
        self._tokens.pop(occ.token, None)
        await self._close_ws(occ, {"type": "kicked"})

    async def _broadcast(self, instance_id: int, payload: dict[str, Any]) -> None:
        occ = self._occupancy.get(instance_id)
        if occ is not None:
            await self._send_ws(occ, payload)

    async def _send_ws(self, occ: Occupancy, payload: dict[str, Any]) -> None:
        ws = occ.ws
        if ws is None:
            return
        try:
            await ws.send_json(payload)
        except Exception:
            occ.ws = None

    async def _close_ws(self, occ: Occupancy, payload: dict[str, Any]) -> None:
        await self._send_ws(occ, payload)
        ws = occ.ws
        occ.ws = None
        if ws is None:
            return
        try:
            await ws.close()
        except Exception:
            pass

    def _notify_occupancy(self) -> None:
        for callback in list(self._on_occupancy_changed):
            callback()


def _template_image_ids(template) -> set[int]:
    return {
        field.image_id
        for page in template.pages
        for field in page.fields
        if field.type is FieldType.IMAGE and field.image_id is not None
    }


def _coerce_value(field: SheetField, value: Any) -> Any:
    if field.type in (FieldType.TEXT, FieldType.TEXTAREA):
        return "" if value is None else str(value)
    if field.type is FieldType.CHECKBOX:
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "on", "yes", "да")
        return bool(value)
    if field.type is FieldType.NUMBER:
        text = "" if value is None else str(value).strip().replace(",", ".")
        if not text:
            return ""
        try:
            number = float(text)
        except ValueError as exc:
            raise FieldCommitError("Не число") from exc
        if not math.isfinite(number):
            raise FieldCommitError("Не число")
        if field.min_value is not None and number < field.min_value:
            raise FieldCommitError("Число меньше минимума")
        if field.max_value is not None and number > field.max_value:
            raise FieldCommitError("Число больше максимума")
        return text
    if field.type is FieldType.DROPDOWN:
        option = "" if value is None else str(value)
        if option not in field.options:
            raise FieldCommitError("Нет такой опции")
        return option
    if field.type is FieldType.IMAGE:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise FieldCommitError("image_id должен быть числом")
        return value
    raise FieldCommitError()
