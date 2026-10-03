"""Game-bound preview-pins storage service (NRI-0025 task 1.2, design Д3).

The thin settings face design Д3 names for the preview column's pins: the
connector owns the slot rules (limit, order, live pointer) and this service
is the only path the ``preview_pins`` key travels — one instance per opened
game, composed in the root right next to the other game-bound services.

* :meth:`PreviewPinsService.get_pins` reads the stored list as-is (a plain
  read, no transaction — the same discipline as :meth:`CurrentDateService.load`):
  order preserved, an absent key serving the empty list, a damaged value
  already read as empty by the storage wrapper with its journal entry there.
  Whether every pair still resolves to an entity is the connector's restore
  rule (design Д3), not this service's.
* :meth:`PreviewPinsService.save_pins` writes the full list back in exactly
  one ``GameSessionUoW.transaction()`` (the repository itself never commits),
  so every pin/unpin persists through the game's single finish point and a
  failed write leaves no partial list behind.
"""
from __future__ import annotations

from collections.abc import Sequence

from app.infrastructure.db.uow import GameSessionUoW
from app.infrastructure.repositories.game_settings_repository import (
    PreviewPinsRepository,
)


class PreviewPinsService:
    """Get/save face over ``game_settings.preview_pins``, one transaction
    per write."""

    def __init__(self, uow: GameSessionUoW) -> None:
        self._uow = uow

    async def get_pins(self) -> list[tuple[str, int]]:
        """The saved pins in pin order — empty when nothing is pinned yet."""
        return await PreviewPinsRepository(self._uow.session).load()

    async def save_pins(self, pins: Sequence[tuple[str, int]]) -> None:
        """Persist the full pin list: one transaction, one upsert (Д3).

        Any error rolls the write back and re-raises — a connector state
        that moved ahead of an uncommitted list is caught by the next read,
        never by a half-written key."""
        async with self._uow.transaction():
            await PreviewPinsRepository(self._uow.session).save(pins)
