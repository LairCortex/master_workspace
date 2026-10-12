"""Сборщик контекстов генерации (add-dnd-lss-generation, task 7.1, design Д3).

Контексты собираются из ЖИВОГО состояния игры: словарь — снимок индекса
подключённых полок, корпус и словарь слагов — публичные двери проверки
импорта (тот же рецепт, что у проверки файла — одно знание, одно место).
Здесь — Qt-free контур на штатной ``uow`` и ``tmp_path``-хранилищах; листы
проверяются своими offscreen-тестами.
"""
from __future__ import annotations

import json

from app.dd.application.dataset_connections_service import (
    DatasetConnectionsService,
)
from app.dd.application.dataset_import_service import DatasetImportService
from app.dd.application.dataset_index_service import DatasetIndexService
from app.dd.application.dataset_library_service import DatasetLibraryService
from app.dd.application.dataset_section_channel import DatasetSectionChannel
from app.dd.application.dataset_validator_service import DatasetValidatorService
from app.dd.application.generation_inputs import GenerationInputs
from app.dd.application.grimoire_connections_service import (
    GrimoireConnectionsService,
)
from app.dd.application.grimoire_index_service import GrimoireIndexService
from app.dd.domain.dataset import DatasetMeta, DatasetSource
from app.dd.infrastructure.dataset_storage import DatasetStorage
from app.dd.infrastructure.grimoire_storage import GrimoireStorage
from tests.dd.lss_check_fixtures import base_dataset, class_with


def _harness(uow, tmp_path):
    storage = DatasetStorage(tmp_path / "datasets")
    connections = DatasetConnectionsService(uow, storage)
    library = DatasetLibraryService(storage, object())
    grimoire_storage = GrimoireStorage(tmp_path / "grimoires")
    grimoire_connections = GrimoireConnectionsService(uow, grimoire_storage)
    grimoire_index = GrimoireIndexService(grimoire_connections, grimoire_storage)
    importer = DatasetImportService(
        library, connections, DatasetValidatorService(), storage, grimoire_index
    )
    index = DatasetIndexService(connections, storage)
    inputs = GenerationInputs(
        index=index, importer=importer, grimoire_index=grimoire_index
    )
    return storage, connections, importer, index, inputs


async def test_section_entries_lists_one_section_of_connected_shelves(uow, tmp_path):
    # Пары «источник/запись» секции — источник пре-выборов листа персонажа:
    # порядок подключений, пустая секция/несуществующая — пустой ответ.
    storage, connections, _importer, _index, inputs = _harness(uow, tmp_path)
    storage.save(
        "srd51",
        json.dumps(
            base_dataset(id="srd51", classes=[class_with()]), ensure_ascii=False
        ),
        DatasetMeta(
            source=DatasetSource.SRD, imported_at="2026-10-01", sha256="0" * 64
        ),
    )
    await connections.connect("srd51")

    entries = await inputs.section_entries("classes")
    assert entries and all(
        entry.source == "srd51" and entry.slug and entry.name for entry in entries
    )
    # Секция, которой на полке нет (и выдуманная) — пустой кортеж, не отказ.
    assert await inputs.section_entries("races") == ()
    assert await inputs.section_entries("несуществующая") == ()


async def test_contexts_carry_vocabulary_corpus_and_slugs(uow, tmp_path):
    storage, connections, _importer, _index, inputs = _harness(uow, tmp_path)
    storage.save(
        "srd51",
        json.dumps(
            base_dataset(id="srd51", classes=[class_with()]), ensure_ascii=False
        ),
        DatasetMeta(
            source=DatasetSource.SRD, imported_at="2026-10-01", sha256="0" * 64
        ),
    )
    await connections.connect("srd51")

    context = await inputs.dataset_section_context(
        "classes", "hb-gen-classes", world="Мир", idea="Идея", count=4
    )

    assert context.world == "Мир" and context.idea == "Идея" and context.count == 4
    # Словарь — записи подключённой полки (парный ключ источник/запись).
    assert any(
        entry.source == "srd51" and entry.slug for entry in context.vocabulary
    )
    # Корпус — тот же рецепт, что у проверки импорта: полка внутри.
    assert [c.dataset_id for c in context.connected] == ["srd51"]
    # Без загруженных SRD-списков словарь молчит (None — проверка пропускает).
    assert context.spell_slugs is None

    spellbook = await inputs.spellbook_context(world="Мир", idea="Идея", count=3)
    assert spellbook.count == 3 and spellbook.srd_slugs is None

    character = await inputs.character_context(
        world="Мир", concept="Концепция", level=3
    )
    assert character.level == 3 and character.current_document is None
    # Разрешающее поле персонажа — все id подключённых записей.
    assert "wizard" in character.record_ids


async def test_dataset_context_excludes_own_shelf_from_corpus(uow, tmp_path):
    storage, connections, _importer, _index, inputs = _harness(uow, tmp_path)
    storage.save(
        "hb-gen-feats",
        json.dumps(base_dataset(id="hb-gen-feats"), ensure_ascii=False),
        DatasetMeta(
            source=DatasetSource.HOMEBREW,
            imported_at="2026-10-02",
            sha256="1" * 64,
        ),
    )
    await connections.connect("hb-gen-feats")

    context = await inputs.dataset_section_context(
        "feats", "hb-gen-feats", world="", idea="", count=1
    )

    # Полка самой генерируемой секции — не корпус (поза повторной проверки).
    assert context.connected == ()


async def test_character_top_up_context_reuses_current_document(uow, tmp_path):
    _storage, _connections, _importer, _index, inputs = _harness(uow, tmp_path)
    current = json.dumps(
        {
            "jsonType": "character",
            "version": 1,
            "data": json.dumps(
                {"name": "Готов", "blocks": {"Внешность": {"text": "целое"}}},
                ensure_ascii=False,
            ),
        },
        ensure_ascii=False,
    )

    context = await inputs.character_context(
        world="Мир", concept="", current_document=current
    )

    assert context.is_top_up
    # Дозаполнение везёт текущий документ канала как есть; отказ «пусто
    # дозаполнять» — право конструктора контекста (пин grouped-тестов канала).
    fillable = json.dumps(
        {
            "jsonType": "character",
            "version": 1,
            "data": json.dumps({"name": "Половина"}, ensure_ascii=False),
        },
        ensure_ascii=False,
    )
    second = await inputs.character_context(
        world="", concept="", current_document=fillable
    )
    assert second.is_top_up


def test_dataset_channel_accepts_generated_shelf_id():
    # Адрес полки из generation_dataset_id проходит грамматику хранилища
    # (отказ пришёл бы до первого запроса — проверяем на конструкторе канала).
    from app.dd.presentation.generation.dataset_task_sheet import (
        generation_dataset_id,
    )

    for section in ("classes", "feats", "backgrounds"):
        DatasetSectionChannel(section, generation_dataset_id(section))
