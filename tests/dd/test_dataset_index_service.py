"""Индекс подключённых датасетов (add-dnd-game-face, task 3.1; design Д5;
spec dnd-reference-records «шесть справочных типов с парным идентификатором»).

DB-контур на штатной фикстуре ``uow`` + настоящий ``DatasetStorage`` на
``tmp_path`` (тот же дуэт, что у тестов связей). Покрыты: пустые подключения
— пустой индекс и ноль затрат; коллизии одноимённых id из разных наборов —
две разные записи, не слитые; правка файла на лету — видна со следующего
чтения (инвалидация по sha256 содержимого, не по sidecar); нерасбираемый
файл — пусто без голоса; слаги заклинаний двух редакций — две пары, живая
перезапись списка; синхронная дверь ``snapshot_now`` до первого чтения —
честная пустота.
"""
from __future__ import annotations

import json

from app.dd.application.dataset_connections_service import (
    DatasetConnectionsService,
)
from app.dd.application.dataset_index_service import (
    DatasetIndexService,
    parse_dataset,
)
from app.dd.domain.dataset import DatasetMeta, DatasetSource
from app.dd.infrastructure.dataset_storage import DatasetStorage


def _meta(source: DatasetSource = DatasetSource.SRD) -> DatasetMeta:
    return DatasetMeta(source=source, imported_at="2026-10-09", sha256="0" * 64)


def _storage(tmp_path) -> DatasetStorage:
    """Две полки: SRD-2014 с ``cleric``/``fire-ball`` записями и домашний
    набор со СВОИМ ``cleric`` (специальный сценарий спеки) и своей чертой."""
    storage = DatasetStorage(tmp_path / "datasets")
    storage.save(
        "srd51",
        json.dumps(
            {
                "id": "srd51",
                "title": "SRD 5.1 (2014)",
                "classes": [
                    {"id": "cleric", "label": "Клейрик"},
                    {"id": "wizard", "label": "Волшебник"},
                ],
                "feats": [{"id": "alert", "label": "Бдительность"}],
            },
            ensure_ascii=False,
        ),
        _meta(),
    )
    storage.save(
        "my-pack",
        json.dumps(
            {
                "id": "my-pack",
                "title": "Мой набор",
                "classes": [{"id": "cleric", "label": "Клейрик мой"}],
                "feats": [{"id": "lucky", "label": "Везучесть", "desc": "Текст черте"}],
                "subraces": [{"id": "high-elf"}],  # без label — имя = id
            },
            ensure_ascii=False,
        ),
        _meta(DatasetSource.HOMEBREW),
    )
    return storage


def _index(uow, tmp_path) -> tuple[DatasetIndexService, DatasetConnectionsService]:
    storage = _storage(tmp_path)
    connections = DatasetConnectionsService(uow, storage)
    return DatasetIndexService(connections, storage), connections


async def test_empty_connections_empty_index(uow, tmp_path):
    """Спека/Д5: пустой список подключений — пустой индекс, ноль затрат."""
    index, _ = _index(uow, tmp_path)
    snap = await index.snapshot()
    assert snap.ids == ()
    assert snap.sections == {}
    assert snap.slugs == {}
    assert await index.entries("classes") == ()
    assert await index.spell_slugs() == ()


async def test_same_slug_two_sets_stays_two_records(uow, tmp_path):
    """Спека «Одноимённые слаги из разных наборов не сливаются»: пара
    «датасет + id» — идентичность, два ``cleric`` читаются двумя записями
    каждый со своим именем и порядком подключений."""
    index, connections = _index(uow, tmp_path)
    await connections.connect("srd51")
    await connections.connect("my-pack")
    classes = await index.entries("classes")
    assert [(e.dataset_id, e.entry_id, e.name) for e in classes] == [
        ("srd51", "cleric", "Клейрик"),
        ("srd51", "wizard", "Волшебник"),
        ("my-pack", "cleric", "Клейрик мой"),
    ]
    snap = await index.snapshot()
    assert snap.entry("classes", "my-pack", "cleric") is not None
    assert snap.entry("classes", "srd51", "cleric") is not None
    assert snap.entry("classes", "ghost", "cleric") is None
    assert snap.entry("feats", "srd51", "missing") is None
    # без label имя — сам id (честное имя вместо выдуманного)
    subrace = await index.entries("subraces")
    assert [(e.name, e.entry_id) for e in subrace] == [("high-elf", "high-elf")]


async def test_reconnect_and_disconnect_reindex_without_restart(uow, tmp_path):
    """Список подключений — тоже часть сверки: подключили между чтениями —
    записи появились, отключили — ушли, файл на полке не тронут."""
    index, connections = _index(uow, tmp_path)
    await connections.connect("srd51")
    assert len(await index.entries("classes")) == 2
    await connections.connect("my-pack")
    assert len(await index.entries("classes")) == 3
    await connections.disconnect("srd51")
    snap = await index.snapshot()
    assert snap.ids == ("my-pack",)
    assert len(await index.entries("classes")) == 1
    # заголовок отключённого набора уходит из снимка вместе с записями
    assert snap.titles == {"my-pack": "Мой набор"}


async def test_live_file_edit_is_visible_next_read(uow, tmp_path):
    """Инвалидация по sha256 файла: правка между чтениями («правка файла на
    лету») видна со следующего чтения; не изменившийся файл повторно НЕ
    разбирается (тот же объект разбора в кэше — пин дисциплины digest)."""
    storage = _storage(tmp_path)
    connections = DatasetConnectionsService(uow, storage)
    await connections.connect("srd51")
    index = DatasetIndexService(connections, storage)
    first = await index.entries("classes")
    assert len(first) == 2
    cached = index._cache["srd51"]
    assert await index.entries("classes") and index._cache["srd51"] is cached
    # правка теми же глазами storage.save (свежий sha сайдкар не обманешь —
    # индекс хэширует САМИ байты документа)
    storage.save(
        "srd51",
        json.dumps({"classes": [{"id": "warlock", "label": "Чернокнижник"}]}),
        _meta(),
    )
    edited = await index.entries("classes")
    assert [(e.entry_id, e.name) for e in edited] == [("warlock", "Чернокнижник")]
    assert index._cache["srd51"] is not cached


async def test_unparsable_file_indexes_empty_quietly(uow, tmp_path):
    """Байты, которые не разбираются, индексируются пустотой — голос у
    валидатора, не у индекса; остальные наборы читаются как ни в чём не
    бывало."""
    storage = _storage(tmp_path)
    connections = DatasetConnectionsService(uow, storage)
    storage.save("broken", "[не объект json", _meta(DatasetSource.HOMEBREW))
    await connections.connect("broken")
    await connections.connect("srd51")
    index = DatasetIndexService(connections, storage)
    assert await index.entries("classes") and len(await index.entries("classes")) == 2


async def test_vanished_file_drops_out_of_snapshot(uow, tmp_path):
    """Связь осталась, файл исчез — набор без записей и без заголовка;
    вернулся — читается снова (сверка на каждом чтении)."""
    storage = _storage(tmp_path)
    connections = DatasetConnectionsService(uow, storage)
    await connections.connect("srd51")
    index = DatasetIndexService(connections, storage)
    assert (await index.snapshot()).titles == {"srd51": "SRD 5.1 (2014)"}
    storage.document_path("srd51").unlink()
    snap = await index.snapshot()
    assert snap.ids == ()
    assert snap.titles == {}
    assert await index.entries("classes") == ()


async def test_spell_slugs_two_editions_and_lifecycle(uow, tmp_path):
    """Контракт «призрак в двух SRD — две сущности»: слаги читаются
    парами (набор, слаг) по каждому подключённому набору со своим списком;
    правка списка видна, отключение убирает пары, набор без файла — без
    пар."""
    storage = _storage(tmp_path)
    connections = DatasetConnectionsService(uow, storage)
    storage.save_spell_slugs("srd51", ("fire-ball", "mage-hand"))
    storage.save_spell_slugs("my-pack", ("my-hex",))
    await connections.connect("srd51")
    await connections.connect("my-pack")
    index = DatasetIndexService(connections, storage)
    assert await index.spell_slugs() == (
        ("srd51", "fire-ball"),
        ("srd51", "mage-hand"),
        ("my-pack", "my-hex"),
    )
    storage.save_spell_slugs("srd51", ("fire-ball",))
    assert await index.spell_slugs() == (
        ("srd51", "fire-ball"),
        ("my-pack", "my-hex"),
    )
    await connections.disconnect("srd51")
    assert await index.spell_slugs() == (("my-pack", "my-hex"),)


async def test_snapshot_now_before_first_read_is_empty(uow, tmp_path):
    """Синхронная дверь протокола до первого async-чтения отвечает честной
    пустотой — ни одного обращения к диску в sync-вызове."""
    index, connections = _index(uow, tmp_path)
    await connections.connect("srd51")  # connection без чтения индекса
    snap = index.snapshot_now()
    assert snap.ids == ()
    assert snap.entry("classes", "srd51", "cleric") is None
    # после async-чтения та же дверь отвечает снимком
    await index.entries("classes")
    assert index.snapshot_now().entry("classes", "srd51", "cleric") is not None


def test_parse_dataset_tolerant_branches():
    """Чистый разбор: не-JSON и не-объект — пусто; секция не список, запись
    не объект и запись без строкового id пропускаются по одной, здоровые
    записи того же файла индексируются."""
    empty = {section: () for section in ("classes", "subclasses", "races", "subraces", "backgrounds", "feats")}
    assert parse_dataset("{ не json", "x") == empty
    assert parse_dataset("[1, 2]", "x") == empty
    parsed = parse_dataset(
        json.dumps(
            {
                "classes": [
                    {"id": "ok", "label": "OK"},
                    {"id": "", "label": "пустой id"},
                    {"label": "без id"},
                    "не объект",
                ],
                "feats": "не список",
            }
        ),
        "x",
    )
    assert [(e.entry_id, e.name, e.dataset_id) for e in parsed["classes"]] == [
        ("ok", "OK", "x")
    ]
    assert parsed["feats"] == ()


async def test_unsafe_stored_id_reads_as_vanished(uow, tmp_path):
    """Связь, сохранённая не-безопасным id (битая/ручная строка настроек):
    файл под таким именем существовать не может — id читается как пропавший
    набор без единогоraise (тёплый прокол реставрации пинов не должен будить
    молчание источника ошибкой, protocol warm)."""
    index, connections = _index(uow, tmp_path)
    await connections.connect("srd51")
    await connections.connect("хом-пак")

    snap = await index.snapshot()
    assert snap.ids == ("srd51",)
    # живой набор служит как служил (его записи — на месте)
    assert snap.entries("classes", "srd51")
