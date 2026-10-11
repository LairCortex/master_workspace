"""Datasets a game connects to (add-dnd-module-foundation, task 3.4).

A game owns exactly one thing about the global library: the ordered list of
dataset ids in its ``game_settings`` (the key the kernel registry declares).
This service is the list's writer through the game's unit of work — one
``transaction()`` per connect/disconnect (coding principle 3) — and the
merger of the list with the storage shelf for the screens:

* connecting adds an id (idempotent — the list is a set in an ordered list),
* disconnecting removes ONLY the link: the dataset file stays in the global
  storage, it may serve other games (spec scenario «Подключили и отключили»),
* an id whose file left the storage reads as MISSING and is never silently
  removed from the game's list (spec «Пропавший набор помечен»).

The ids themselves are storage names the library validated on import; this
service never touches files and never re-validates grammar — the list is a
reference, the storage owns the referent.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.dd.infrastructure.dataset_storage import DatasetStorage
from app.infrastructure.db.uow import GameSessionUoW
from app.infrastructure.repositories.game_settings_repository import (
    DndDatasetsRepository,
)


@dataclass(frozen=True)
class DatasetConnection:
    """One row of the game's connected-sets view: the id as stored, the
    display title (the storage title while the file is there, the id itself
    once it is not), and ``present`` — False marks the missing shelf the
    screen flags and the list still keeps."""

    dataset_id: str
    title: str
    present: bool


class DatasetConnectionsService:
    """Reads and writes one game's dataset connections on its unit."""

    def __init__(self, uow: GameSessionUoW, storage: DatasetStorage) -> None:
        self._uow = uow
        self._storage = storage

    async def connections(self) -> list[str]:
        """The connected ids in stored order («absent or unreadable» reads as
        the empty list, the row untouched — the next explicit write cleans
        it, same absence discipline as every typed key)."""
        return await DndDatasetsRepository(self._uow.session).load()

    async def connect(self, dataset_id: str) -> None:
        """Add the id, keeping order; connecting an id that is already
        connected is a no-op without a write."""
        ids = await self.connections()
        if dataset_id in ids:
            return
        ids.append(dataset_id)
        async with self._uow.transaction():
            await DndDatasetsRepository(self._uow.session).save(ids)

    async def disconnect(self, dataset_id: str) -> None:
        """Remove the link only — the storage file is not this game's to
        touch (spec: «отключение SHALL убирать только связь, не трогая файл
        датасета»); an id that is not connected is a no-op without a write."""
        ids = await self.connections()
        if dataset_id not in ids:
            return
        remaining = [known for known in ids if known != dataset_id]
        async with self._uow.transaction():
            await DndDatasetsRepository(self._uow.session).save(remaining)

    async def statuses(self) -> list[DatasetConnection]:
        """Every stored id with its storage state, list order kept — a
        missing shelf reads as ``present=False`` under its id and STAYS in
        the game's list (no silent cleanup write)."""
        titles = {
            entry.dataset_id: entry.title
            for entry in self._storage.list_datasets()
        }
        return [
            DatasetConnection(
                dataset_id=dataset_id,
                title=titles.get(dataset_id, dataset_id),
                present=dataset_id in titles,
            )
            for dataset_id in await self.connections()
        ]
