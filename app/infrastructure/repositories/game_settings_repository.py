"""Infrastructure access to the per-game ``game_settings`` key/value table.

Single place where this table is touched (audit B2, task 6.2): both the
calendar settings service and the LLM prompts used to hand-roll the same
``select``-then-insert/update dance — the duplication is collapsed here so
every key goes through one get/upsert/delete trio.
"""
from __future__ import annotations

import json
import logging
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
#: codec.  The key is seeded nowhere — its absence is the rule "real today
#: translated into the active calendar", the first explicit edit is the first
#: write (spec «Игровая «сейчас» хранится одна на игру»).
CURRENT_DATE_KEY = "current_date"


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
    """The decoded stored «now»: a coordinate of the active calendar and the
    era flag — the two fields design Д2 names as the value the service holds.
    Pure data; every reading rule ("absent", "corrupted") lives in
    :class:`CurrentDateRepository`."""

    coord: GameCoord
    is_bc: bool


def _current_date_corrupt(reason: str, raw: str) -> None:
    """Log one corruption the way the calendar key already phrases it (design
    Д1: «поведение как у „Повреждённое значение календарь-ключа“» — a warning
    and life by the absence rule; the damaged row is left untouched)."""
    _LOGGER.warning(
        "Ignoring corrupted %s setting (%s): %r", CURRENT_DATE_KEY, reason, raw
    )


def _encode_current_date(coord: GameCoord, is_bc: bool) -> str:
    """JSON body of design Д1: ``{"coord": <encode_coord text>, "bc": 0|1}``.
    The coordinate codec owns the coordinate text and refuses non-coordinates
    itself (``TypeError``) — this wrapper never invents a stored date."""
    return json.dumps(
        {"coord": encode_coord(coord), "bc": 1 if is_bc else 0},
        ensure_ascii=False,
    )


def _decode_current_date(raw: str) -> CurrentDateValue | None:
    """Read the stored JSON back, ``None`` for anything unreadable.

    Every rejection (unparseable JSON, a foreign shape, a missing or non
    ``0|1`` ``bc``, a coordinate text the codec itself refuses) logs the one
    warning naming the reason and answers ``None`` — the caller then lives by
    the absence rule; the row is never rewritten here (same discipline as
    :meth:`CalendarSettingsService.load_and_apply`)."""
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
    decoded = decode_coord(data.get("coord"))
    if isinstance(decoded, CoordCorrupted):
        _current_date_corrupt(
            "; ".join(f"{p.code}: {p.message}" for p in decoded.reasons), raw
        )
        return None
    return CurrentDateValue(coord=decoded.coord, is_bc=bc_raw == 1)


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

    async def save(self, coord: GameCoord, is_bc: bool) -> None:
        """Store ``coord``/``is_bc`` as the game's «now», overwriting any
        previous (even corrupted) value — «Перезапись вместо ремонта»."""
        await self._settings.upsert(CURRENT_DATE_KEY, _encode_current_date(coord, is_bc))
