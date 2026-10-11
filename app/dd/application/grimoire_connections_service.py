"""Grimoires a game connects to (add-dnd-game-face, task 4.2; design Д6;
spec dnd-grimoire-import «Игра подключает гримуары списком, отключение
обратимо»).

A game owns exactly one thing about the global grimoire library: the ordered
list of grimoire ids in its ``game_settings`` (the key the kernel registry
declares, ``dnd_grimoires``). This service is that list's writer through the
game's unit of work — one ``transaction()`` per connect/disconnect (coding
principle 3) — and the merger of the list with the storage shelf for the
screens:

* connecting adds an id (idempotent — the list is a set in an ordered list),
* disconnecting removes ONLY the link: the file stays in the global storage
  and may serve other games, and stays connectable again (spec scenario
  «Отключил — файл жив»),
* an id whose file left the storage reads as ``present=False`` and is never
  silently removed from the game's list (spec «Пропавший файл помечен»).

The same shape as :class:`app.dd.application.dataset_connections_service.
DatasetConnectionsService`, deliberately: a master meets one behaviour for
both halves of the module's global library. This service never touches files
and never re-validates grammar — the list is a reference, the storage owns the
referent.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.dd.infrastructure.grimoire_storage import GrimoireStorage
from app.infrastructure.db.uow import GameSessionUoW
from app.infrastructure.repositories.game_settings_repository import (
    DndGrimoiresRepository,
)


@dataclass(frozen=True)
class GrimoireConnection:
    """One row of the game's connected-grimoires view: the id as stored, the
    display title (the storage title while the file is there, the id itself
    once it is not) and ``present`` — False marks the vanished file the screen
    flags and the list still keeps."""

    grimoire_id: str
    title: str
    present: bool


class GrimoireConnectionsService:
    """Reads and writes one game's grimoire connections on its unit."""

    def __init__(self, uow: GameSessionUoW, storage: GrimoireStorage) -> None:
        self._uow = uow
        self._storage = storage

    async def connections(self) -> list[str]:
        """The connected ids in stored order («absent or unreadable» reads as
        the empty list, the row untouched — the next explicit write cleans
        it, the absent-value discipline of the typed keys)."""
        return await DndGrimoiresRepository(self._uow.session).load()

    async def connect(self, grimoire_id: str) -> None:
        """Add the id, keeping order; connecting an id that is already
        connected is a no-op without a write."""
        ids = await self.connections()
        if grimoire_id in ids:
            return
        ids.append(grimoire_id)
        async with self._uow.transaction():
            await DndGrimoiresRepository(self._uow.session).save(ids)

    async def disconnect(self, grimoire_id: str) -> None:
        """Remove the link only — the file is not this game's to touch (spec
        scenario «Отключил — файл жив»); an id that is not connected is a
        no-op without a write."""
        ids = await self.connections()
        if grimoire_id not in ids:
            return
        remaining = [known for known in ids if known != grimoire_id]
        async with self._uow.transaction():
            await DndGrimoiresRepository(self._uow.session).save(remaining)

    async def statuses(self) -> list[GrimoireConnection]:
        """Every stored id with its storage state, list order kept — a
        vanished file reads as ``present=False`` under its id and STAYS in the
        game's list (no silent cleanup write)."""
        titles = {
            entry.grimoire_id: entry.title
            for entry in self._storage.list_grimoires()
        }
        return [
            GrimoireConnection(
                grimoire_id=grimoire_id,
                title=titles.get(grimoire_id, grimoire_id),
                present=grimoire_id in titles,
            )
            for grimoire_id in await self.connections()
        ]
