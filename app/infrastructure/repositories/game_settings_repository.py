"""Infrastructure access to the per-game ``game_settings`` key/value table.

Single place where this table is touched (audit B2, task 6.2): both the
calendar settings service and the LLM prompts used to hand-roll the same
``select``-then-insert/update dance — the duplication is collapsed here so
every key goes through one get/upsert/delete trio.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import GameSettingsModel

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
