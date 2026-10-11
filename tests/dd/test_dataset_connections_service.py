"""Связи игры с глобальной библиотекой датасетов (add-dnd-module-foundation,
task 3.4; spec dnd-dataset-library «Игра подключает наборы», «Пропавший набор
помечен»).

DB-контур на штатных фикстурах ``uow``/``async_session`` (in-memory aiosqlite):
одна транзакция единицы работы на connect/disconnect (принцип 3), отключение
убирает ТОЛЬКО ссылку, пропавшая полка остаётся в списке с пометкой и без
санитарной записи.
"""
from __future__ import annotations

import json

from app.dd.application.dataset_connections_service import (
    DatasetConnectionsService,
)
from app.dd.domain.dataset import DatasetMeta, DatasetSource
from app.dd.infrastructure.dataset_storage import DatasetStorage
from app.infrastructure.repositories.game_settings_repository import (
    DND_DATASETS_KEY,
    DndDatasetsRepository,
    GameSettingsRepository,
)


def _storage(tmp_path) -> DatasetStorage:
    storage = DatasetStorage(tmp_path / "datasets")
    for dataset_id, title in (("srd51", "SRD 5.1 (2014)"), ("my-pack", "Мой набор")):
        storage.save(
            dataset_id,
            json.dumps({"id": dataset_id, "title": title}),
            DatasetMeta(
                source=DatasetSource.SRD if dataset_id == "srd51" else DatasetSource.HOMEBREW,
                imported_at="2026-10-09",
                sha256="0" * 64,
            ),
        )
    return storage


async def test_absent_key_reads_empty_no_row(uow):
    service = DatasetConnectionsService(uow, None)  # type: ignore[arg-type]
    assert await service.connections() == []


async def test_connect_appends_in_order_idempotent(uow, tmp_path):
    service = DatasetConnectionsService(uow, _storage(tmp_path))
    await service.connect("srd51")
    await service.connect("my-pack")
    await service.connect("srd51")  # уже подключён — без второй записи и без дубля
    assert await service.connections() == ["srd51", "my-pack"]


async def test_disconnect_keeps_the_file_and_the_others(uow, tmp_path):
    """Спека «Подключили и отключили»: связь убрана, файл набора жив — он
    может служить другим играм."""
    storage = _storage(tmp_path)
    service = DatasetConnectionsService(uow, storage)
    await service.connect("srd51")
    await service.connect("my-pack")
    await service.disconnect("srd51")
    assert await service.connections() == ["my-pack"]
    assert storage.load_content("srd51") is not None  # файл не тронут
    await service.disconnect("ghost")  # не подключён — no-op без записи


async def test_statuses_merge_storage_and_flag_missing(uow, tmp_path):
    """Спека «Пропавший набор помечен»: id без файла читается present=False
    под своим id, остаётся в списке, санитарной записи нет."""
    storage = _storage(tmp_path)
    service = DatasetConnectionsService(uow, storage)
    await DndDatasetsRepository(uow.session).save(["my-pack", "srd51", "vanished"])
    rows = await service.statuses()
    assert [(r.dataset_id, r.title, r.present) for r in rows] == [
        ("my-pack", "Мой набор", True),
        ("srd51", "SRD 5.1 (2014)", True),
        ("vanished", "vanished", False),
    ]
    # список игры не изменился — никакого тихого ремонта
    assert await DndDatasetsRepository(uow.session).load() == [
        "my-pack",
        "srd51",
        "vanished",
    ]


async def test_corrupt_value_reads_empty_but_stays_for_explicit_write(uow, tmp_path):
    """Испорченное значение ключа — пустой список с записью в журнал; строка
    остаётся байт-в-байт до явной записи (дисциплина остальных типизированных
    ключей), а первый connect перезаписывает её чистым списком."""
    async with uow.transaction():
        await GameSettingsRepository(uow.session).upsert(DND_DATASETS_KEY, "{не json")
    service = DatasetConnectionsService(uow, _storage(tmp_path))
    assert await service.connections() == []
    await service.connect("srd51")
    assert await service.connections() == ["srd51"]
