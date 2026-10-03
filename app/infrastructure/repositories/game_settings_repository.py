"""Infrastructure access to the per-game ``game_settings`` key/value table.

Single place where this table is touched (audit B2, task 6.2): both the
calendar settings service and the LLM prompts used to hand-roll the same
``select``-then-insert/update dance — the duplication is collapsed here so
every key goes through one get/upsert/delete trio.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.game_calendar import GameCoord, current_calendar
from app.infrastructure.calendar_storage import (
    CoordCorrupted,
    decode_coord,
    encode_coord,
)
from app.infrastructure.db.models import GameSettingsModel

_LOGGER = logging.getLogger(__name__)

# ── ``game_settings`` storage keys (roadmap pieces C2/C4, designs D1/D6) ──

#: Key under which the game's active calendar setting lives in the per-game
#: ``game_settings`` key/value table.
CALENDAR_SETTINGS_KEY = "game_calendar"

#: Key under which the calendar wizard keeps its work-in-progress draft
#: (piece C4, design D6): the same versioned spec body as the main key, lined
#: with a stage marker.  Never consulted on game open — a draft warms the
#: wizard flow only, never the active calendar (spec «Черновик мастера
#: календаря»).
CALENDAR_DRAFT_KEY = "game_calendar_draft"

#: Key of the binary «wizard seen» flag (C4): a game created by this version
#: is seeded with :data:`CALENDAR_WIZARD_SEEN_NO`, a keyless game reads as an
#: old one that never sees the wizard automatically, and the flag influences
#: nothing but the wizard's auto-show (spec «Флаг просмотра мастера
#: календаря»).
CALENDAR_WIZARD_SEEN_KEY = "calendar_wizard_seen"

#: The two stored texts of the flag.
CALENDAR_WIZARD_SEEN_NO = "0"
CALENDAR_WIZARD_SEEN_YES = "1"

#: Key of the game's «now» date (NRI-0021, design Д1): the coordinate of the
#: active calendar with its era flag, stored as JSON ``{"coord": <encoded
#: coordinate>, "bc": 0|1}`` through the :mod:`app.infrastructure.calendar_storage`
#: codec.  Since NRI-0023 (task 2.3) the same JSON carries the optional hour
#: key ``"h"`` — an integer of the active calendar's day; the key is written
#: only when a hour is set, so pre-0023 values stay byte-identical and stay
#: readable ("no key = no hour").  The key is seeded nowhere — its absence is
#: the rule "real today translated into the active calendar", the first
#: explicit edit is the first write (spec «Игровая «сейчас» хранится одна на
#: игру»).
CURRENT_DATE_KEY = "current_date"

#: Key of the preview column's pinned cards (NRI-0025, design Д3): a JSON
#: array ``[{"t": <type>, "i": <id>}]`` whose order IS the pin order, read
#: and written through :class:`PreviewPinsRepository`.  The key is seeded
#: nowhere — its absence is the normal «nothing pinned yet» state, a damaged
#: value reads as the empty list with a journal entry, and an unavailable
#: pair is dropped silently at restore by the connector (spec «Закрепления
#: хранятся в настройках игры и переживают перезапуск»).
PREVIEW_PINS_KEY = "preview_pins"


class GameSettingsRepository:
    """Key/value CRUD over ``game_settings`` for one bound session.

    Deliberately uncommitted: the repository never commits or rolls back —
    the caller owns the transaction (services via their own discipline or
    the game's unit of work).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key: str) -> str | None:
        """Stored text for ``key``, or ``None`` when the key is absent."""
        result = await self._session.execute(
            select(GameSettingsModel).where(GameSettingsModel.key == key)
        )
        row = result.scalars().first()
        return row.value if row is not None else None

    async def upsert(self, key: str, value: str) -> None:
        """Store ``value`` under ``key``, overwriting an existing row in place."""
        result = await self._session.execute(
            select(GameSettingsModel).where(GameSettingsModel.key == key)
        )
        row = result.scalars().first()
        if row is None:
            self._session.add(GameSettingsModel(key=key, value=value))
        else:
            row.value = value

    async def delete(self, key: str) -> None:
        """Delete ``key`` when present; an absent key is a silent no-op."""
        result = await self._session.execute(
            select(GameSettingsModel).where(GameSettingsModel.key == key)
        )
        row = result.scalars().first()
        if row is not None:
            await self._session.delete(row)


# ── Typed «now» storage (NRI-0021 task 2.1, design Д1) ─────────────────────


@dataclass(frozen=True)
class CurrentDateValue:
    """The decoded stored «now»: a coordinate of the active calendar, the era
    flag and the optional hour — the value design Д2 names for the service to
    hold, the hour added by NRI-0023 (task 2.3, spec «Игровая «сейчас»
    хранится одна на игру»).  ``hour=None`` means «час не выставлен» — the
    state every pre-0023 value and every fresh seed carries.  Pure data;
    every reading rule ("absent", "corrupted", "out-of-range hour") lives in
    :class:`CurrentDateRepository`."""

    coord: GameCoord
    is_bc: bool
    hour: int | None = None


def _current_date_corrupt(reason: str, raw: str) -> None:
    """Log one corruption the way the calendar key already phrases it (design
    Д1: «поведение как у „Повреждённое значение календарь-ключа“» — a warning
    and life by the absence rule; the damaged row is left untouched)."""
    _LOGGER.warning(
        "Ignoring corrupted %s setting (%s): %r", CURRENT_DATE_KEY, reason, raw
    )


def _encode_current_date(
    coord: GameCoord, is_bc: bool, hour: int | None = None
) -> str:
    """JSON body of design Д1: ``{"coord": <encode_coord text>, "bc": 0|1}``,
    NRI-0023 extended with ``"h": <int>`` only when a hour is set — a value
    without an hour stays byte-identical to the pre-0023 format, so writing
    never strands an older app on an unreadable key (v1-compatible codec).
    The coordinate codec owns the coordinate text and refuses non-coordinates
    itself (``TypeError``) — this wrapper never invents a stored date."""
    body: dict = {"coord": encode_coord(coord), "bc": 1 if is_bc else 0}
    if hour is not None:
        body["h"] = hour
    return json.dumps(body, ensure_ascii=False)


def _decode_current_date(raw: str) -> CurrentDateValue | None:
    """Read the stored JSON back, ``None`` for anything unreadable.

    Every rejection (unparseable JSON, a foreign shape, a missing or non
    ``0|1`` ``bc``, an off-type ``h``, a coordinate text the codec itself
    refuses) logs the one warning naming the reason and answers ``None`` —
    the caller then lives by the absence rule; the row is never rewritten
    here (same discipline as :meth:`CalendarSettingsService.load_and_apply`).
    The NRI-0023 hour: an absent key means "not set"; a stored hour the
    *active* calendar no longer has (a narrowed day after a calendar switch)
    reads silently as "not set" — the signature loses its hour without any
    write (design Д5, spec «Сужение суток чистит недоступный час»), while the
    date itself keeps serving."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        _current_date_corrupt("not parseable JSON", raw)
        return None
    if not isinstance(data, dict):
        _current_date_corrupt(
            f"must be a JSON object, got {type(data).__name__}", raw
        )
        return None
    bc_raw = data.get("bc")
    if isinstance(bc_raw, bool) or bc_raw not in (0, 1):
        _current_date_corrupt(f"era flag {bc_raw!r} is neither 0 nor 1", raw)
        return None
    hour: int | None = None
    if "h" in data:
        h_raw = data["h"]
        if isinstance(h_raw, bool) or not isinstance(h_raw, int):
            _current_date_corrupt(f"hour {h_raw!r} is not an integer", raw)
            return None
        if 0 <= h_raw < current_calendar().day_hours:
            hour = h_raw
    decoded = decode_coord(data.get("coord"))
    if isinstance(decoded, CoordCorrupted):
        _current_date_corrupt(
            "; ".join(f"{p.code}: {p.message}" for p in decoded.reasons), raw
        )
        return None
    return CurrentDateValue(coord=decoded.coord, is_bc=bc_raw == 1, hour=hour)


class CurrentDateRepository:
    """Typed storage access for the per-game ``current_date`` key.

    The same typed-wrapper pattern as :class:`LlmSettingsRepository`: a thin
    face over the shared :class:`GameSettingsRepository` trio, owning the
    JSON ``{"coord", "bc"}`` format on top of the coordinate codec.  Reads
    that find an unreadable value (unparsable body, malformed coordinate, or
    a coordinate the *active* calendar cannot host — a calendar switch may
    leave it out of range, design Д1/Риск) log and answer ``None``, leaving
    the row byte-identical for the first explicit edit to overwrite.  Like
    the trio below, this repository never commits — the caller owns the
    transaction (the service's unit of work).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._settings = GameSettingsRepository(session)

    async def load(self) -> CurrentDateValue | None:
        """The stored «now», or ``None`` for "absent or unreadable"."""
        raw = await self._settings.get(CURRENT_DATE_KEY)
        if raw is None:
            return None
        value = _decode_current_date(raw)
        if value is None:
            return None
        if not current_calendar().is_valid(value.coord):
            _current_date_corrupt(
                f"coordinate {encode_coord(value.coord)} does not exist in the "
                "active calendar",
                raw,
            )
            return None
        return value

    async def save(
        self, coord: GameCoord, is_bc: bool, hour: int | None = None
    ) -> None:
        """Store ``coord``/``is_bc`` (and the optional ``hour``) as the game's
        «now», overwriting any previous (even corrupted) value — «Перезапись
        вместо ремонта».          ``hour=None`` writes no ``h`` key at all, keeping
        the value in the pre-0023 shape (v1-compatible codec)."""
        await self._settings.upsert(
            CURRENT_DATE_KEY, _encode_current_date(coord, is_bc, hour)
        )


# ── Typed preview-pins storage (NRI-0025 task 1.1, design Д3) ───────────────


def _preview_pins_corrupt(reason: str, raw: str) -> None:
    """Log one corruption the way the other typed keys phrase it: a damaged
    pins list reads as empty with a journal entry and life by the absence
    rule (task 1.1); the row itself is left untouched — the next explicit
    pin/unpin rewrites a clean list (design Д3: no background repair write)."""
    _LOGGER.warning(
        "Ignoring corrupted %s setting (%s): %r", PREVIEW_PINS_KEY, reason, raw
    )


def _encode_preview_pins(pins: Sequence[tuple[str, int]]) -> str:
    """JSON body of design Д3: ``[{"t": <type>, "i": <id>}]`` — the array
    order IS the pin order (spec «порядок сохраняется»).  The pairs arrive
    from the connector, whose types are entity strings by construction; the
    encoder never re-validates them (same division of labour as
    :func:`_encode_current_date` — no stored pair is invented here)."""
    return json.dumps([{"t": t, "i": i} for t, i in pins], ensure_ascii=False)


def _decode_preview_pins(raw: str) -> list[tuple[str, int]]:
    """Read the stored array back, pair order preserved.

    All-or-nothing like the «now» codec: anything unreadable — unparsable
    JSON, a non-array body, an entry that is not an object, a ``t`` that is
    not text or an ``i`` that is not an integer — logs the one warning naming
    the reason and answers the EMPTY list (task 1.1: «битый JSON читается как
    пустой список с записью в журнал»); the damaged row is never rewritten
    here.  Whether a structurally fine pair still names an existing entity is
    the connector's restore rule (design Д3: unavailable pairs are dropped at
    read of the game open), not the codec's — a foreign type text reads back
    exactly as stored.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        _preview_pins_corrupt("not parseable JSON", raw)
        return []
    if not isinstance(data, list):
        _preview_pins_corrupt(
            f"must be a JSON array, got {type(data).__name__}", raw
        )
        return []
    pins: list[tuple[str, int]] = []
    for entry in data:
        if not isinstance(entry, dict):
            _preview_pins_corrupt(f"entry {entry!r} is not a JSON object", raw)
            return []
        type_raw = entry.get("t")
        if not isinstance(type_raw, str):
            _preview_pins_corrupt(f"type {type_raw!r} is not text", raw)
            return []
        id_raw = entry.get("i")
        if isinstance(id_raw, bool) or not isinstance(id_raw, int):
            _preview_pins_corrupt(f"id {id_raw!r} is not an integer", raw)
            return []
        pins.append((type_raw, id_raw))
    return pins


class PreviewPinsRepository:
    """Typed storage access for the per-game ``preview_pins`` key.

    The same typed-wrapper pattern as :class:`CurrentDateRepository`: a thin
    face over the shared :class:`GameSettingsRepository` trio, owning the
    JSON ``[{"t", "i"}]`` format on top of it.  An absent key is the normal
    empty state and reads as the empty list WITHOUT a warning; a damaged
    value reads as the empty list WITH the one journal entry the codec logs,
    the row staying byte-identical for the next explicit pin/unpin to
    overwrite (design Д3: «молчаливое излечение хранилища» happens through
    the user's next write, never as a background rewrite).  Like the trio,
    this repository never commits — the caller owns the transaction (the
    service's unit of work).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._settings = GameSettingsRepository(session)

    async def load(self) -> list[tuple[str, int]]:
        """The stored pins in pin order — empty for "absent or unreadable"."""
        raw = await self._settings.get(PREVIEW_PINS_KEY)
        if raw is None:
            return []
        return _decode_preview_pins(raw)

    async def save(self, pins: Sequence[tuple[str, int]]) -> None:
        """Store the full list as the game's pins, overwriting any previous
        (even corrupted) value; the array order carries the pin order."""
        await self._settings.upsert(PREVIEW_PINS_KEY, _encode_preview_pins(pins))
