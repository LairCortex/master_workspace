"""Связи игры с глобальной библиотекой гримуаров (add-dnd-game-face, task 4.2;
spec dnd-grimoire-import «Игра подключает гримуары списком, отключение
обратимо»).

DB-контур на штатных фикстурах ``uow``/``async_session`` (in-memory aiosqlite):
одна транзакция единицы работы на connect/disconnect (принцип 3), отключение
убирает ТОЛЬКО ссылку, пропавший файл остаётся в списке с пометкой и без
санитарной записи. Зеркало тестов датасетных связей — та же форма поведения для
обеих половин глобальной библиотеки модуля.
"""
from __future__ import annotations

import json

from app.dd.application.grimoire_connections_service import (
    GrimoireConnectionsService,
)
from app.dd.infrastructure.grimoire_storage import GrimoireStorage
from app.infrastructure.repositories.game_settings_repository import (
    DND_GRIMOIRES_KEY,
    DndGrimoiresRepository,
    GameSettingsRepository,
)


def _storage(tmp_path) -> GrimoireStorage:
    storage = GrimoireStorage(tmp_path / "grimoires")
    for grimoire_id, title in (
        ("tina-grimoire", "Гримуар Тины"),
        ("world-items", "Предметы мира"),
    ):
        storage.save(
            grimoire_id,
            json.dumps({"id": grimoire_id, "name": title}, ensure_ascii=False),
        )
    return storage


async def test_absent_key_reads_empty_no_row(uow):
    """Ни одного подключённого гримуара — нормальное состояние игры: пустой
    список и НИКАКОЙ строки в ``game_settings``."""
    service = GrimoireConnectionsService(uow, None)  # type: ignore[arg-type]
    assert await service.connections() == []
    assert await GameSettingsRepository(uow.session).get(DND_GRIMOIRES_KEY) is None


async def test_connect_appends_in_order_idempotent(uow, tmp_path):
    service = GrimoireConnectionsService(uow, _storage(tmp_path))
    await service.connect("tina-grimoire")
    await service.connect("world-items")
    await service.connect("tina-grimoire")  # уже подключён — без дубля и без записи
    assert await service.connections() == ["tina-grimoire", "world-items"]


async def test_disconnect_keeps_the_file_and_the_others(uow, tmp_path):
    """Спека «Подключил, отключил — файл жив»: убрана только ссылка этого
    файла, сам файл в глобальном хранилище не тронут и подключим снова."""
    storage = _storage(tmp_path)
    service = GrimoireConnectionsService(uow, storage)
    await service.connect("tina-grimoire")
    await service.connect("world-items")
    await service.disconnect("tina-grimoire")

    assert await service.connections() == ["world-items"]
    assert storage.load_content("tina-grimoire") is not None
    await service.connect("tina-grimoire")  # обратимо
    assert await service.connections() == ["world-items", "tina-grimoire"]


async def test_disconnect_of_unknown_id_writes_nothing(uow, tmp_path):
    """Отключение неподключённого id — no-op; пустой список остаётся отсутствием
    ключа, а не записанным ``[]``."""
    service = GrimoireConnectionsService(uow, _storage(tmp_path))
    await service.disconnect("ghost")
    assert await GameSettingsRepository(uow.session).get(DND_GRIMOIRES_KEY) is None


async def test_statuses_merge_storage_and_flag_missing(uow, tmp_path):
    """Спека «Пропавший файл помечен»: id без файла читается present=False под
    своим id, соседний файл остаётся с заголовком, санитарной записи нет."""
    storage = _storage(tmp_path)
    service = GrimoireConnectionsService(uow, storage)
    await service.connect("tina-grimoire")
    await service.connect("deleted-grimoire")

    statuses = await service.statuses()
    assert [(s.grimoire_id, s.title, s.present) for s in statuses] == [
        ("tina-grimoire", "Гримуар Тины", True),
        ("deleted-grimoire", "deleted-grimoire", False),
    ]
    # список игры не починен молча — та же пара id в той же записи
    assert await DndGrimoiresRepository(uow.session).load() == [
        "tina-grimoire",
        "deleted-grimoire",
    ]


async def test_corrupt_value_reads_empty_untouched_until_next_write(uow, tmp_path):
    """Битое значение ключа читается пустым (журнальная запись — у кодека), а
    первая явная запись чинит его чистой связкой (дисциплина_absent-value_)."""
    async with uow.transaction():
        await GameSettingsRepository(uow.session).upsert(DND_GRIMOIRES_KEY, "{битый")
    service = GrimoireConnectionsService(uow, _storage(tmp_path))
    assert await service.connections() == []
    await service.connect("tina-grimoire")
    assert await service.connections() == ["tina-grimoire"]
    async with uow.transaction():
        raw = await GameSettingsRepository(uow.session).get(DND_GRIMOIRES_KEY)
    assert json.loads(raw) == ["tina-grimoire"]
