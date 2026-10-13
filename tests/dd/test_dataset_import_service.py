"""Импорт датасета файлом и повторная проверка (add-dnd-module-foundation,
task 5.1; spec dnd-dataset-library «Импорт пользовательского датасета
файлом», dnd-dataset-validator «Порог импорта»).

Юнит-контур на штатной ``uow`` (in-memory) и ``tmp_path``-хранилище, все
сервисы настоящие: здесь проверяется ОДНО дерево решений сервиса — ошибки
отказывают без касания хранилища, предупреждения пропускают импорт, замена
только после подтверждения, SRD защищён, сайдкар получает свежий счётчик
ошибок, корпус линков читается по подключённым наборам с исключением
собственной полки.
"""
from __future__ import annotations

import json

from app.dd.application.dataset_connections_service import (
    DatasetConnectionsService,
)
from app.dd.application.dataset_import_service import (
    DatasetImportService,
    DatasetImportStatus,
)
from app.dd.application.dataset_library_service import DatasetLibraryService
from app.dd.application.dataset_validator_service import DatasetValidatorService
from app.dd.application.grimoire_connections_service import (
    GrimoireConnectionsService,
)
from app.dd.application.grimoire_index_service import GrimoireIndexService
from app.dd.domain.dataset import (
    SRD_2014_DATASET_ID,
    SRD_2024_DATASET_ID,
    DatasetMeta,
    DatasetSource,
)
from app.dd.infrastructure.dataset_storage import DatasetStorage
from app.dd.infrastructure.grimoire_storage import GrimoireStorage
from tests.dd.lss_check_fixtures import base_dataset, class_with


class _NoNetworkClient:
    """Клиент-пробка: эти тесты не ходят в сеть, а конструктор библиотеки
    требует клиента — пусть лучше заорёт, если что-то полезет качать."""

    async def fetch_srd_2014(self):
        raise AssertionError("network in an import unit test")

    async def fetch_srd_2024(self):
        raise AssertionError("network in an import unit test")


def _trio(tmp_path, uow):
    """Хранилище + библиотека + связи + сервис импорта на одном tmp-корне."""
    storage = DatasetStorage(tmp_path / "datasets")
    library = DatasetLibraryService(storage, _NoNetworkClient())  # type: ignore[arg-type]
    connections = DatasetConnectionsService(uow, storage)
    importer = DatasetImportService(
        library, connections, DatasetValidatorService(), storage
    )
    return storage, library, connections, importer


def _warned_content() -> str:
    """Чистый по форме и ошибкам документ с предупреждением ROLL_FORMULA
    (сценарий «Импорт с предупреждениями»): нераспознанная формула кости."""
    return json.dumps(
        base_dataset(
            classes=[class_with({"type": "gold-dice", "dice": "2d"})]
        ),
        ensure_ascii=False,
    )


async def test_clean_document_stored_sidecar_stamped(uow, tmp_path):
    storage, _, _, importer = _trio(tmp_path, uow)
    content = json.dumps(base_dataset(), ensure_ascii=False)

    outcome = await importer.import_dataset(content)

    assert outcome.status is DatasetImportStatus.STORED
    # Имя списка — текстовая подпись самого файла: живые датасеты LSS несут
    # её в ``name`` (таблица артефактов доков, 2026-10-12), читатель берёт его.
    assert (outcome.dataset_id, outcome.title) == ("hb-set", "Хоумбрю")
    assert not outcome.replaced
    assert outcome.report is not None and outcome.report.import_allowed
    assert storage.load_content("hb-set") == content
    meta = storage.load_meta("hb-set")
    assert meta is not None and meta.check_errors == 0
    # Импорт — всегда homebrew, чем бы ни притворялся файл.
    assert meta.source is DatasetSource.HOMEBREW


async def test_warnings_import_and_report_accompanies(uow, tmp_path):
    """Спека: предупреждения не блокируют, отчёт остаётся на экране."""
    storage, _, _, importer = _trio(tmp_path, uow)
    content = _warned_content()

    outcome = await importer.import_dataset(content)

    assert outcome.status is DatasetImportStatus.STORED
    assert outcome.report is not None
    assert not outcome.report.errors and outcome.report.warnings
    assert storage.load_content("hb-set") == content


async def test_errors_refuse_and_storage_untouched(uow, tmp_path):
    """Спека «Отказ с ошибками — хранилище не меняется»: лицензия вне
    белого списка — отказ ДО любого обращения к полке."""
    storage, library, _, importer = _trio(tmp_path, uow)
    content = json.dumps(base_dataset(license="Public Domain"))

    outcome = await importer.import_dataset(content)

    assert outcome.status is DatasetImportStatus.BLOCKED
    assert outcome.dataset_id == "hb-set"
    assert outcome.report is not None
    assert [issue.code for issue in outcome.report.errors] == ["LICENSE"]
    assert library.list_storage() == []
    assert storage.load_content("hb-set") is None


async def test_unparsable_file_blocked_with_invalid_json(uow, tmp_path):
    storage, library, _, importer = _trio(tmp_path, uow)

    outcome = await importer.import_dataset("{not json")

    assert outcome.status is DatasetImportStatus.BLOCKED
    assert outcome.dataset_id is None  # id прочесть нечем
    assert outcome.report is not None
    assert outcome.report.errors[0].code == "INVALID_JSON"
    assert library.list_storage() == []


async def test_non_object_root_blocked(uow, tmp_path):
    _, library, _, importer = _trio(tmp_path, uow)

    outcome = await importer.import_dataset("[1, 2]")

    assert outcome.status is DatasetImportStatus.BLOCKED
    assert outcome.dataset_id is None
    assert library.list_storage() == []


async def test_non_text_id_excludes_nothing_and_blocks(uow, tmp_path):
    """Документ со словарём, но без текстового id: свой id не прочтен —
    корпус не исключает ничего, вердикт отдаёт валидатор (форма/линки),
    хранилище не тронуто."""
    _, library, _, importer = _trio(tmp_path, uow)

    outcome = await importer.import_dataset('{"id": 5, "license": "CC-BY-4.0"}')

    assert outcome.status is DatasetImportStatus.BLOCKED
    assert outcome.dataset_id is None
    assert library.list_storage() == []


async def test_existing_id_asks_confirmation_then_replaces(uow, tmp_path):
    """Спека «заменять только после подтверждения»: первый ответ — вопрос,
    байты на полке те же; подтверждённый запрос меняет их и говорит «replaced»."""
    storage, _, _, importer = _trio(tmp_path, uow)
    first = json.dumps(base_dataset(), ensure_ascii=False)
    await importer.import_dataset(first)
    second = json.dumps(
        base_dataset(id="hb-set", author="другой"), ensure_ascii=False
    )

    ask = await importer.import_dataset(second)
    assert ask.status is DatasetImportStatus.NEEDS_CONFIRMATION
    assert ask.dataset_id == "hb-set" and ask.title == "Хоумбрю"
    assert ask.message  # русская фраза для экрана
    assert storage.load_content("hb-set") == first  # полка не тронута

    done = await importer.import_dataset(second, confirmed=True)
    assert done.status is DatasetImportStatus.STORED
    assert done.replaced
    assert storage.load_content("hb-set") == second


async def test_srd_shelf_refuses_replacement(uow, tmp_path):
    """Спека «SRD защищён от перезаписи»: ни один флаг подтверждения не
    покупает перезапись официальной полки — русская фраза и те же байты."""
    storage, _, _, importer = _trio(tmp_path, uow)
    official = json.dumps(base_dataset(id=SRD_2014_DATASET_ID), ensure_ascii=False)
    storage.save(
        SRD_2014_DATASET_ID,
        official,
        DatasetMeta(
            source=DatasetSource.SRD, imported_at="2026-10-01", sha256="0" * 64
        ),
    )
    homebrew = json.dumps(
        base_dataset(id=SRD_2014_DATASET_ID, name="Мой SRD"), ensure_ascii=False
    )

    blocked = await importer.import_dataset(homebrew)
    assert blocked.status is DatasetImportStatus.BLOCKED
    assert blocked.report is not None and blocked.report.import_allowed
    assert blocked.message  # фраза магазинных правил, не отчёт проверки

    also = await importer.import_dataset(homebrew, confirmed=True)
    assert also.status is DatasetImportStatus.BLOCKED
    assert storage.load_content(SRD_2014_DATASET_ID) == official


async def test_corpus_reads_connected_shelves_excluding_own(uow, tmp_path):
    """Корпус линков — по подключённым наборам (спека dnd-dataset-validator),
    собственная полка исключена (её старые байты — не сосед), мусор в
    соседях не мешает: битый JSON, не-объект и призрак пропускаются."""
    storage, _, connections, importer = _trio(tmp_path, uow)
    # Сосед-справочник с классом wizard (по образцу test_lss_checks_errors).
    storage.save(
        "ref-set",
        json.dumps(
            {
                "id": "ref-set",
                "name": "Справочник",
                "classes": [class_with(entity_id="wizard")],
            },
            ensure_ascii=False,
        ),
        DatasetMeta(
            source=DatasetSource.SRD, imported_at="2026-10-01", sha256="0" * 64
        ),
    )
    storage.save(
        "broken",
        "{битый",
        DatasetMeta(
            source=DatasetSource.HOMEBREW, imported_at="2026-10-01", sha256="0" * 64
        ),
    )
    storage.save(
        "not-object",
        "[1, 2]",
        DatasetMeta(
            source=DatasetSource.HOMEBREW, imported_at="2026-10-01", sha256="0" * 64
        ),
    )
    for dataset_id in ("ref-set", "broken", "not-object", "ghost"):
        await connections.connect(dataset_id)
    # Собственная полка уже лежит (будет исключена из корпуса по своему id)
    # и подключена — как в живой игре перед заменой.
    own = json.dumps(base_dataset(), ensure_ascii=False)
    storage.save(
        "hb-set",
        own,
        DatasetMeta(
            source=DatasetSource.HOMEBREW, imported_at="2026-10-01", sha256="0" * 64
        ),
    )
    await connections.connect("hb-set")
    # Подсобытие-ссылка решается только через соседа wizard; id тот же —
    # запрос замены подтверждённого ещё не видел.
    document = json.dumps(
        base_dataset(
            subclasses=[
                {"id": "school-hb", "classId": "wizard", "label": "HB", "grants": []}
            ]
        ),
        ensure_ascii=False,
    )

    outcome = await importer.import_dataset(document)
    assert outcome.status is DatasetImportStatus.NEEDS_CONFIRMATION
    # Отчёт подтверждённого вопроса чист по линкам — корпус читался, а
    # собственная старая полка (без wizard) в нём исключена.
    assert outcome.report is not None
    assert not [i for i in outcome.report.issues if i.code.startswith("LINK_")]

    done = await importer.import_dataset(document, confirmed=True)
    assert done.status is DatasetImportStatus.STORED
    # Тот же документ без справочника даёт LINK_CLASS — корпус реально
    # читался, а мусорные соседи (битый JSON, не-объект, призрак) линк
    # не закрыли: отключаем единственный валидный набор.
    await connections.disconnect("ref-set")
    lonely = await importer.import_dataset(
        json.dumps(
            base_dataset(
                id="hb-set-2",
                subclasses=[
                    {
                        "id": "school-hb",
                        "classId": "wizard",
                        "label": "HB",
                        "grants": [],
                    }
                ],
            ),
            ensure_ascii=False,
        )
    )
    assert lonely.status is DatasetImportStatus.BLOCKED
    assert any(i.code == "LINK_CLASS" for i in lonely.report.errors)  # type: ignore[union-attr]


async def test_spell_slugs_union_over_both_srd_lists(uow, tmp_path):
    """Списки слогов SRD 2014 И 2024 сливаются в один корпус проверки; без
    обоих списков проверка слогов молчит (предписание LSS)."""
    storage, _, _, importer = _trio(tmp_path, uow)
    spell = {"type": "spell-fixed", "slug": "shield"}
    document = json.dumps(
        base_dataset(classes=[class_with(spell)]), ensure_ascii=False
    )

    # Ни одного списка — проверка слогов пропущена.
    outcome = await importer.import_dataset(document)
    assert outcome.status is DatasetImportStatus.STORED
    assert outcome.report is not None
    assert not [i for i in outcome.report.issues if i.code == "SPELL_SLUG_NOT_SRD"]

    # Списки на двух полках — union: «shield» из 2024 чист, «fireball» — нет.
    storage.save_spell_slugs(SRD_2014_DATASET_ID, ("magic-missile",))
    storage.save_spell_slugs(SRD_2024_DATASET_ID, ("shield",))
    clean = await importer.import_dataset(
        json.dumps(
            base_dataset(id="hb-set-2", classes=[class_with(spell)]),
            ensure_ascii=False,
        )
    )
    assert clean.status is DatasetImportStatus.STORED
    assert clean.report is not None
    assert not [i for i in clean.report.issues if i.code == "SPELL_SLUG_NOT_SRD"]

    foreign = await importer.import_dataset(
        json.dumps(
            base_dataset(
                id="hb-set-3",
                classes=[class_with({"type": "spell-fixed", "slug": "fireball"})],
            ),
            ensure_ascii=False,
        )
    )
    assert foreign.status is DatasetImportStatus.STORED  # предупреждение не блок
    assert foreign.report is not None
    assert [i.code for i in foreign.report.warnings] == ["SPELL_SLUG_NOT_SRD"]


# ── словарь валидатора: SRD ∪ гримуары игры (add-dnd-game-face, task 4.3) ────


def _grimoire_stack(uow, tmp_path):
    """Гримуарная тройка той же игры на общем tmp-корне: полка, связи, дверь
    чтения — те же настоящие сервисы, что собирает composition root."""
    storage = GrimoireStorage(tmp_path / "grimoires")
    connections = GrimoireConnectionsService(uow, storage)
    return storage, connections, GrimoireIndexService(connections, storage)


def _importer_with_grimoires(library, connections, storage, grimoire_index):
    return DatasetImportService(
        library,
        connections,
        DatasetValidatorService(),
        storage,
        grimoire_index,
    )


async def test_connected_grimoire_silences_the_slug_outside_srd(uow, tmp_path):
    """Спека «Объявленное и загруженное — легально»: датасет ссылается на
    «moon-pet», в игру подключён гримуар с этим слогом — предупреждения нет;
    тот же датасет без подключённого гримуара его получает."""
    storage, library, connections, _ = _trio(tmp_path, uow)
    storage.save_spell_slugs(SRD_2024_DATASET_ID, ("shield",))
    grimoire_storage, grimoire_connections, grimoire_index = _grimoire_stack(
        uow, tmp_path
    )
    grimoire_storage.save(
        "tina-grimoire",
        json.dumps(
            [{"name": "Лунный питомец", "slug": "moon-pet"}], ensure_ascii=False
        ),
    )
    importer = _importer_with_grimoires(
        library, connections, storage, grimoire_index
    )
    spell = {"type": "spell-fixed", "slug": "moon-pet"}
    document = json.dumps(
        base_dataset(id="hb-moon", classes=[class_with(spell)]), ensure_ascii=False
    )

    # Гримуар ещё не подключён — словарь = SRD, слаг чужой.
    before = await importer.import_dataset(document)
    assert before.status is DatasetImportStatus.STORED
    assert [i.code for i in before.report.warnings] == ["SPELL_SLUG_NOT_SRD"]

    await grimoire_connections.connect("tina-grimoire")
    after = await importer.import_dataset(
        json.dumps(
            base_dataset(id="hb-moon-2", classes=[class_with(spell)]),
            ensure_ascii=False,
        )
    )
    assert after.status is DatasetImportStatus.STORED
    assert after.report is not None
    assert not [i for i in after.report.issues if i.code == "SPELL_SLUG_NOT_SRD"]


async def test_grimoire_slug_check_survives_without_srd_lists(uow, tmp_path):
    """SRD-списков нет, а гримуар подключён — словарь НЕ пуст: проверка слогов
    работает на одном гримуаре (неизвестный слаг помечен, объявленный — нет)."""
    storage, library, connections, _ = _trio(tmp_path, uow)
    grimoire_storage, grimoire_connections, grimoire_index = _grimoire_stack(
        uow, tmp_path
    )
    grimoire_storage.save(
        "tina-grimoire",
        json.dumps([{"name": "Лунный питомец", "id": "Moon Pet"}], ensure_ascii=False),
    )
    await grimoire_connections.connect("tina-grimoire")
    importer = _importer_with_grimoires(
        library, connections, storage, grimoire_index
    )

    known = await importer.import_dataset(
        json.dumps(
            base_dataset(
                id="hb-known", classes=[class_with({"type": "spell-fixed", "slug": "moon-pet"})]
            ),
            ensure_ascii=False,
        )
    )
    assert [i.code for i in known.report.issues if i.code == "SPELL_SLUG_NOT_SRD"] == []

    unknown = await importer.import_dataset(
        json.dumps(
            base_dataset(
                id="hb-unknown",
                classes=[class_with({"type": "spell-fixed", "slug": "far-out"})],
            ),
            ensure_ascii=False,
        )
    )
    assert [i.code for i in unknown.report.warnings] == ["SPELL_SLUG_NOT_SRD"]


async def test_recheck_reads_the_same_grimoire_dictionary(uow, tmp_path):
    """Повторная проверка того же файла идёт через тот же словарь: подключение
    гримуара меняет вердикт полки без пересохранения датасета."""
    storage, library, connections, _ = _trio(tmp_path, uow)
    storage.save_spell_slugs(SRD_2024_DATASET_ID, ("shield",))
    grimoire_storage, grimoire_connections, grimoire_index = _grimoire_stack(
        uow, tmp_path
    )
    grimoire_storage.save(
        "tina-grimoire",
        json.dumps([{"name": "Лунный питомец", "slug": "moon-pet"}], ensure_ascii=False),
    )
    importer = _importer_with_grimoires(
        library, connections, storage, grimoire_index
    )
    await importer.import_dataset(
        json.dumps(
            base_dataset(
                id="hb-moon",
                classes=[class_with({"type": "spell-fixed", "slug": "moon-pet"})],
            ),
            ensure_ascii=False,
        )
    )

    report = await importer.recheck("hb-moon")
    assert [i.code for i in report.warnings] == ["SPELL_SLUG_NOT_SRD"]

    await grimoire_connections.connect("tina-grimoire")
    again = await importer.recheck("hb-moon")
    assert again is not None and not again.warnings and not again.errors


async def test_recheck_stamps_clean_and_erroring_shelf(uow, tmp_path):
    """Повторная проверка перечитывает полку, печатает вердикт и шлёпает
    свежий счётчик в сайдкар — ошибки в частности."""
    storage, _, _, importer = _trio(tmp_path, uow)
    await importer.import_dataset(json.dumps(base_dataset(), ensure_ascii=False))

    report = await importer.recheck("hb-set")
    assert report is not None and not report.errors and not report.warnings
    assert storage.load_meta("hb-set").check_errors == 0  # type: ignore[union-attr]

    # Полка «испортилась» (лицензия уехала за белый список) — проверка
    # находит ошибку и обновляет сайдкар.
    storage.save(
        "hb-set",
        json.dumps(base_dataset(license="Public Domain")),
        DatasetMeta(
            source=DatasetSource.HOMEBREW, imported_at="2026-10-02", sha256="1" * 64
        ),
    )
    report = await importer.recheck("hb-set")
    assert report is not None
    assert [issue.code for issue in report.errors] == ["LICENSE"]
    assert storage.load_meta("hb-set").check_errors == 1  # type: ignore[union-attr]


async def test_recheck_checks_official_shelf_with_official_source(uow, tmp_path):
    """Сайдкар SRD проверяется как официальный (свои классы закрывают
    списки заклинаний, Д7) — и получает штамп, как любая полка."""
    storage, _, _, importer = _trio(tmp_path, uow)
    official = json.dumps(base_dataset(id=SRD_2014_DATASET_ID), ensure_ascii=False)
    storage.save(
        SRD_2014_DATASET_ID,
        official,
        DatasetMeta(
            source=DatasetSource.SRD, imported_at="2026-10-01", sha256="0" * 64
        ),
    )

    report = await importer.recheck(SRD_2014_DATASET_ID)

    assert report is not None and not report.errors
    assert storage.load_meta(SRD_2014_DATASET_ID).check_errors == 0  # type: ignore[union-attr]


async def test_recheck_missing_shelf_returns_none(uow, tmp_path):
    """Полка исчезла между списком и кликом — None, сайдкар-призрак не
    создаётся, список на экране обновит вызывающий."""
    storage, _, _, importer = _trio(tmp_path, uow)

    assert await importer.recheck("hb-set") is None
    assert storage.meta_path("hb-set").exists() is False


async def test_recheck_bare_document_without_sidecar_checks_unstamped(uow, tmp_path):
    """Разорванная запись прошлого (сначала документ, сайдкар потом): голый
    файл в списке есть — проверка честная, но штампу ставить некуда;
    хранилищная защита призраков не должна долетать до экрана."""
    storage, library, _, importer = _trio(tmp_path, uow)
    storage._ensure_root()
    storage.document_path("hb-set").write_text(
        json.dumps(base_dataset(), ensure_ascii=False), encoding="utf-8"
    )
    assert [s.dataset_id for s in library.list_storage()] == ["hb-set"]

    report = await importer.recheck("hb-set")

    assert report is not None and not report.errors
    assert storage.load_meta("hb-set") is None  # ничего не дописано
