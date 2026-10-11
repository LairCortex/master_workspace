"""``ModuleSettingsService`` — единственный писатель признака модуля
(add-dnd-module-foundation, task 2.1/2.3; spec dnd-module-lifecycle
«Включение модуля на открытой игре», «Выключение модуля с сохранением
данных», «Версия модуля и совместимость версий приложения»).

Юнит-контур на in-memory aiosqlite (штатные фикстуры ``uow``/``async_session``):
каждая операция — ровно одна транзакция юнита, читает сервис то, что записал
кодек ядра, и не додумывает ничего сверху. Правило версии — не здесь: сервис
отдаёт хранящуюся версию как есть, решает состав (main-фабрика).
"""
from __future__ import annotations

import json

import pytest

from app.dd.application.module_settings_service import ModuleSettingsService
from app.infrastructure.db.models import GameSettingsModel
from app.infrastructure.repositories.game_settings_repository import (
    DND_MODULE_DATA_VERSION,
    DND_MODULE_KEY,
)


async def _raw(uow) -> str | None:
    """Rows bypass the service here on purpose: the tests must see the exact
    stored body, not the service's own reading of it."""
    from sqlalchemy import select

    session = uow.session
    row = (
        await session.execute(
            select(GameSettingsModel).where(
                GameSettingsModel.key == DND_MODULE_KEY
            )
        )
    ).scalar_one_or_none()
    return row.value if row is not None else None


async def test_load_absent_is_none(uow):
    service = ModuleSettingsService(uow)
    assert await service.load() is None


async def test_enable_writes_the_current_version_body(uow):
    service = ModuleSettingsService(uow)
    await service.enable()
    flag = await service.load()
    assert flag is not None and flag.enabled is True
    assert flag.version == DND_MODULE_DATA_VERSION
    assert json.loads(await _raw(uow)) == {
        "enabled": True,
        "version": DND_MODULE_DATA_VERSION,
    }


async def test_enable_accepts_an_explicit_version(uow):
    # The launcher-creation path and a future format bump name the version
    # explicitly; the service stores what it is told (spec «при создании …
    # признак … с текущей версией формата данных модуля» — caller owns «текущая»).
    service = ModuleSettingsService(uow)
    await service.enable(version=7)
    flag = await service.load()
    assert flag.version == 7


async def test_enable_is_idempotent_single_row(uow):
    service = ModuleSettingsService(uow)
    await service.enable()
    await service.enable()
    assert await _raw(uow) == json.dumps(
        {"enabled": True, "version": DND_MODULE_DATA_VERSION}
    )


async def test_disable_switches_off_keeping_the_stored_version(uow):
    # Spec «Выключение SHALL снять признак, сохранив … данные»: the only
    # change is ``enabled``; the version the data carries survives so a
    # re-enable returns the game under its own version (scenario
    # «Выключили и снова включили»).
    service = ModuleSettingsService(uow)
    await service.enable(version=7)
    await service.disable()
    flag = await service.load()
    assert flag is not None and flag.enabled is False and flag.version == 7
    body = json.loads(await _raw(uow))
    assert body == {"enabled": False, "version": 7}


async def test_disable_repair_claim_uses_the_current_version_when_unreadable(uow):
    # A row that no longer decodes has no knowable version; the «off» write
    # claims what an enable from THIS build would claim (service docstring).
    service = ModuleSettingsService(uow)
    from app.infrastructure.repositories.game_settings_repository import (
        GameSettingsRepository,
    )

    async with uow.transaction():
        await GameSettingsRepository(uow.session).upsert(DND_MODULE_KEY, "не JSON")
    assert await service.load() is None  # corrupt reads as absent
    await service.disable()
    body = json.loads(await _raw(uow))
    assert body == {"enabled": False, "version": DND_MODULE_DATA_VERSION}


async def test_disable_on_an_ordinary_game_writes_the_row(uow):
    # The disable entry only exists while the module is attached, so this is
    # a defensive contract, not a UI route: «off» is written for the absent
    # flag too — the flag is the fact, and writing it is the operation.
    service = ModuleSettingsService(uow)
    await service.disable()
    body = json.loads(await _raw(uow))
    assert body["enabled"] is False


async def test_enable_then_disable_then_enable_roundtrip(uow):
    service = ModuleSettingsService(uow)
    await service.enable(version=3)
    await service.disable()
    await service.enable(version=3)
    flag = await service.load()
    assert flag.enabled is True and flag.version == 3


@pytest.mark.parametrize("bad", ['{"enabled": true}', '{"enabled": 1, "version": 2}'])
async def test_load_reads_damaged_value_as_none_without_rewriting(uow, bad, caplog):
    # Reading never repairs (the absence rule) and the codec logs the reason.
    service = ModuleSettingsService(uow)
    from app.infrastructure.repositories.game_settings_repository import (
        GameSettingsRepository,
    )

    async with uow.transaction():
        await GameSettingsRepository(uow.session).upsert(DND_MODULE_KEY, bad)
    assert await service.load() is None
    assert await _raw(uow) == bad  # byte-identical after the read
