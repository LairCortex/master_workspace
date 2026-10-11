"""The game's «показывать справочные записи в поиске» switch (task 3.3).

One boolean, stored per game under the kernel-registered ``dnd_search_show_reference``
key (spec dnd-reference-records «Справочные сущности участвуют в поиске под
одним переключателем»): the state survives restarts because the row survives
them (task 3.3's «перезапуск сохраняет» is the settings table's own promise —
this service only reads and writes it). Absent reads as the spec default
«показывать»; a damaged row reads as the same default through the typed
codec's journal entry.

The service is the state's single holder in the live session: the reference
source asks :attr:`visible` before every surface read (protocol Д1 — the
kernel never learns that a toggle exists), the datasets sheet's checkbox
mirrors the value and writes the master's click through :meth:`set_visible`
(one unit-of-work transaction, coding principle 3). ``load`` is the open-
game read the composition performs once, before the first window shows; a
source composed without a prior load answers the same default, so no surface
can surface reference rows from a half-initialised holder.
"""
from __future__ import annotations

from app.infrastructure.db.uow import GameSessionUoW
from app.infrastructure.repositories.game_settings_repository import (
    DndSearchShowReferenceRepository,
)


class ReferenceVisibilityService:
    """Reads and writes one game's reference-search toggle on its unit."""

    def __init__(self, uow: GameSessionUoW) -> None:
        self._uow = uow
        # The spec default stands until the row is read (the module's source
        # is composed before the composition's await-point on some test
        # contours; answering «show» is the row's absence answer anyway).
        self._visible = True

    @property
    def visible(self) -> bool:
        """The current toggle state — what the external source reports as
        its protocol ``visible``."""
        return self._visible

    async def load(self) -> bool:
        """Read the stored state into the holder (the open-game read) and
        return it."""
        self._visible = await DndSearchShowReferenceRepository(
            self._uow.session
        ).load()
        return self._visible

    async def set_visible(self, enabled: bool) -> None:
        """Store the master's answer — one transaction per click, the value
        flips in the holder only after the write committed (a failed write
        leaves source and row exactly as they were)."""
        async with self._uow.transaction():
            await DndSearchShowReferenceRepository(self._uow.session).save(enabled)
        self._visible = bool(enabled)
