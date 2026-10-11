"""The module's settings service — the flag's only writer (task 2.1, design Д1/Д3).

``ModuleSettingsService`` owns the read/write of the game's ``dnd_module``
flag: the enable flow (the kernel menu entry, composed by ``main.py`` with
this very service) and the disable flow (the module's own menu entry) both
finish through here, and every write is one ``GameSessionUoW.transaction()``
— the single transaction finish point holds (design Д1: «запись признака —
обычная операция записи настроек с единой точкой транзакции»).

The reading rules are the kernel codec's (the key, the version constant and
the JSON shape live in ``game_settings_repository`` — one knowledge, one
place); this service adds no interpretation of its own: an unreadable value
loads as ``None`` with the codec's journal entry, and only an explicit
:meth:`enable` / :meth:`disable` rewrites the row (never a background repair).

Same discipline as the kernel's ``CurrentDateService``: no Qt, no commits
outside the unit of work, no ORM models — the repository is built over
``uow.session`` per operation.
"""
from __future__ import annotations

from app.dd.infrastructure.db.dd_schema import create_dd_tables, ensure_dd_tables
from app.infrastructure.db.uow import GameSessionUoW
from app.infrastructure.repositories.game_settings_repository import (
    DND_MODULE_DATA_VERSION,
    DND_MODULE_KEY,
    DndModuleFlag,
    GameSettingsRepository,
    decode_dnd_module_flag,
    encode_dnd_module_flag,
)


class ModuleSettingsService:
    """Reads and writes the game's D&D-module flag on the game's unit."""

    def __init__(self, uow: GameSessionUoW) -> None:
        self._uow = uow

    async def load(self) -> DndModuleFlag | None:
        """The stored flag, or ``None`` for «absent or unreadable».

        A damaged row reads as ``None`` with the codec's warning already in
        the journal (spec «Испорченный признак открывает игру как обычную»);
        the row itself is left byte-identical for the next explicit write.
        The version travels as stored — higher or lower than this build
        supports: deciding what an ahead version means is the composition's
        rule (spec «Версия модуля и совместимость версий приложения»), not
        this service's.
        """
        raw = await GameSettingsRepository(self._uow.session).get(DND_MODULE_KEY)
        if raw is None:
            return None
        return decode_dnd_module_flag(raw)

    async def enable(self, version: int = DND_MODULE_DATA_VERSION) -> None:
        """Write the flag as «on, version ``version``» and create the
        module's tables (add-dnd-game-face task 8.1, design Д6; spec
        «Включение модуля на открытой игре»).

        One transaction around both halves: the settings-row upsert and the
        additive ``create_all`` of the module subset ride the SAME finish —
        a failure rolls back the flag and the DDL together (no half-enabled
        game). ``checkfirst`` keeps this safe over a file whose tables a
        previous enable already created (re-enable returns the data, spec
        «Выключили и снова включили»), and no existing table or row of the
        game is modified (spec «Включение НЕ SHALL изменять какие-либо
        существующие таблицы и строки игры»). An absent, disabled, or even
        damaged flag is overwritten here: this is the user's explicit write
        the absence rule always reserved."""
        async with self._uow.transaction():
            await GameSettingsRepository(self._uow.session).upsert(
                DND_MODULE_KEY, encode_dnd_module_flag(True, version)
            )
            await self._uow.session.run_sync(create_dd_tables)

    async def ensure_schema(self) -> None:
        """The game-open bootstrap (design Д6 «bootstrap при старте
        D&D-игры»): an existing D&D game created before the module owned
        tables gains them additively, its rows untouched. Its own
        transaction — callers are outside any unit when the composition
        bootstraps (``ensure_dd_tables`` owns the finish; enable stays on
        its own path)."""
        await ensure_dd_tables(self._uow)

    async def disable(self) -> None:
        """Write the flag as «off», keeping the stored version (task 2.3).

        «Выключение SHALL снять признак, сохранив все таблицы и данные модуля
        нетронутыми» — only the ``dnd_module`` row changes; the version the
        data carries survives (a game written by module v7 stays a v7 game
        while switched off, so a re-enable returns it under its own version).
        A row that no longer decodes leaves its version unknowable — the
        current format version is written, exactly what an enable from this
        build would claim."""
        stored = await self.load()
        version = stored.version if stored is not None else DND_MODULE_DATA_VERSION
        async with self._uow.transaction():
            await GameSettingsRepository(self._uow.session).upsert(
                DND_MODULE_KEY, encode_dnd_module_flag(False, version)
            )
