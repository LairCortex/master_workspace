"""Канал датасетов: конверт и принятие (add-dnd-lss-generation, tasks 3.1–3.2).

Секционный канал проверяется с ЖИВЫМ ``DatasetValidatorService``: конверт
достраивается приложением (версия формата, id, холостая лицензия) и проходит
схему; служебные значения — включая числа — из ответа модели не берутся
(даже когда модель обернула массив в объект со своими «version»/«id»);
корпус линков и словарь SRD-слагов доходят до валидатора, неразрешимая
ссылка становится ошибкой круга и уходит в обратную связь. Принятие идёт
только через существующую дверь импорта + ``DatasetConnectionsService`` на
настоящей полке ``tmp_path`` и in-memory ``uow``: лицензия в файле,
автоподключение, отказ при ошибках и вопрос о замене.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.dd.application.dataset_connections_service import (
    DatasetConnectionsService,
)
from app.dd.application.dataset_import_service import (
    DatasetImportService,
    DatasetImportStatus,
)
from app.dd.application.dataset_library_service import DatasetLibraryService
from app.dd.application.dataset_section_channel import (
    DATASET_EDITION,
    DATASET_LICENSE_CHOICES,
    DATASET_SYSTEM,
    DEFAULT_DATASET_LICENSE,
    DatasetAcceptanceOutcome,
    DatasetSectionAcceptanceService,
    DatasetSectionChannel,
    DatasetSectionContext,
    insert_dataset_license,
)
from app.dd.application.dataset_validator_service import DatasetValidatorService
from app.dd.application.generation_loop import run_rounds
from app.dd.application.prompt_composer import PromptComposer, SlugVocabularyEntry
from app.dd.domain.dataset import DatasetSource
from app.dd.domain.lss_checks import SECTIONS, ConnectedDataset
from app.dd.infrastructure.dataset_storage import DatasetStorage
from app.dd.infrastructure.lss_schemas import FORMAT_VERSION, SCHEMA_URL_TEMPLATE

GENERATION_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "app" / "dd" / "resources" / "generation"
)


def _fewshot(section: str) -> list[dict]:
    path = GENERATION_DIR / "fewshot" / f"{section}.json"
    return json.loads(path.read_text(encoding="utf-8"))["samples"]


class _NoNetworkClient:
    async def fetch_srd_2014(self):
        raise AssertionError("network in an acceptance unit test")

    async def fetch_srd_2024(self):
        raise AssertionError("network in an acceptance unit test")


class _ScriptedAsk:
    """Стаб-ответ канала той же формы, что у группы 1."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.users: list[str] = []

    async def __call__(self, system_prompt, user_prompt, on_phase=None):
        self.users.append(user_prompt)
        return self.answers.pop(0)


def _channel(section: str = "feats", dataset_id: str = "hb-gen-feats-1", **kwargs):
    return DatasetSectionChannel(section, dataset_id, **kwargs)


def _acceptance_stack(tmp_path, uow):
    """Настоящая дверь: хранилище + библиотека + связи + импорт на tmp-корне
    (поза tests/dd/test_dataset_import_service.py)."""
    storage = DatasetStorage(tmp_path / "datasets")
    library = DatasetLibraryService(storage, _NoNetworkClient())  # type: ignore[arg-type]
    connections = DatasetConnectionsService(uow, storage)
    importer = DatasetImportService(
        library, connections, DatasetValidatorService(), storage
    )
    return storage, connections, DatasetSectionAcceptanceService(importer, connections)


# ── task 3.1: конверт достроен, схема проходит ───────────────────────────────


def test_envelope_is_completed_by_the_app_and_passes_the_live_validator():
    """Массив few-shot-записей из ответа → файл dataset-<тип>: конверт
    достроен приложением и проходит живую схему без ошибок."""
    channel = _channel()
    entries = _fewshot("feats")

    document = channel.parse(json.dumps(entries, ensure_ascii=False))

    envelope = json.loads(document)
    assert envelope[
        "$schema"
    ] == SCHEMA_URL_TEMPLATE.format(version=FORMAT_VERSION)  # версия формата — приложение
    assert envelope["id"] == "hb-gen-feats-1"  # id — из задачи, не из ответа
    assert envelope["name"] == "Хоумбрю: Черты"  # RU-подпись секции
    assert (envelope["system"], envelope["edition"]) == (DATASET_SYSTEM, DATASET_EDITION)
    # лицензия — холостая (единственное поле принятия, подставится при записи)
    assert envelope["license"] == DEFAULT_DATASET_LICENSE
    assert envelope["feats"] == entries
    report = channel.validate(document, DatasetSectionContext())
    assert report.errors == ()


def test_model_service_fields_never_reach_the_envelope():
    """«Числа модели в конверт не попадают»: обернула ли модель массив в
    объект со своими «version», «$schema» и «id» — служебные поля конверта
    остаются правилами приложения, а голый массив даёт тот же файл."""
    channel = _channel()
    smuggled = {
        "$schema": "https://longstoryshort.app/schema/v99/wizard-dataset.json",
        "version": "99",
        "id": "srd51",
        "name": "Набор из ответа модели",
        "license": "Public Domain",
        "feats": _fewshot("feats"),
    }

    wrapped = json.loads(channel.parse(json.dumps(smuggled, ensure_ascii=False)))
    plain = json.loads(channel.parse(json.dumps(_fewshot("feats"), ensure_ascii=False)))

    assert wrapped["$schema"] == SCHEMA_URL_TEMPLATE.format(version=FORMAT_VERSION)
    assert wrapped["id"] == "hb-gen-feats-1"
    assert wrapped["name"] == "Хоумбрю: Черты"
    assert wrapped["license"] == DEFAULT_DATASET_LICENSE
    assert "version" not in wrapped  # число модели отброшено вместе с id
    assert wrapped == plain  # обе формы ответа собирают один и тот же файл


def test_answer_without_section_array_is_a_russian_round_error():
    """Не-JSON и объект без запрошенной секции — обычные ValueError круга:
    раннер превращает их в ошибку «не JSON»/сообщение и ведёт в фидбек."""
    channel = _channel(section="feats")
    with pytest.raises(ValueError, match="не содержит JSON-документа"):
        channel.parse("извините, я не умею JSON")
    with pytest.raises(ValueError, match="секции «feats»"):
        channel.parse(json.dumps({"classes": _fewshot("classes")}))


def test_channel_guards_section_and_dataset_id_up_front():
    with pytest.raises(ValueError, match="неизвестная секция датасета: 'monsters'"):
        _channel(section="monsters")
    with pytest.raises(ValueError, match="не может именем файла"):
        _channel(dataset_id="HB Sett!")


def test_section_label_layer_is_single_sourced():
    """Подпись конверта — из few-shot-ресурса (одна правда): чужая секция —
    тот же русский ValueError, что у сборки промта."""
    assert PromptComposer().section_label("races") == "Виды"
    with pytest.raises(ValueError, match="неизвестная секция датасета: 'monsters'"):
        PromptComposer().section_label("monsters")


# ── task 3.1: промт канала = слои Д3 + число сущностей поверх ─────────────────


def test_prompt_appends_count_over_composer_layers():
    composer = PromptComposer()
    channel = _channel()
    vocabulary = (SlugVocabularyEntry(source="srd51", slug="Alert", name="Бдительность"),)
    context = DatasetSectionContext(
        world="Мир", idea="Идея", count=4, vocabulary=vocabulary
    )

    system, user = channel.build_prompt(context)

    base_system, base_user = composer.compose_dataset_section(
        "feats", "Мир", "Идея", vocabulary
    )
    assert system == base_system
    assert user == base_user + "\n\nСущностей в секции: 4 — выдай ровно столько записей."
    # дефолт числа — 5 (spec: «по умолчанию 5»)
    _, default_user = channel.build_prompt(DatasetSectionContext())
    assert default_user.endswith("Сущностей в секции: 5 — выдай ровно столько записей.")


def test_count_outside_one_to_ten_is_refused():
    for bad in (0, 11):
        with pytest.raises(ValueError, match="число сущностей в секции"):
            DatasetSectionContext(count=bad)


# ── task 3.1: валидация существующим сервисом с корпусом и слагами ────────────


def _feat_reference_channel():
    """Канал предысторий: запись-предыстория few-shot ссылается featId
    на «Alert» — ссылка решается только через подключённый корпус."""
    channel = _channel(
        section="backgrounds", dataset_id="hb-gen-backgrounds-1"
    )
    return channel, json.dumps(_fewshot("backgrounds"), ensure_ascii=False)


def _alert_corpus() -> tuple[ConnectedDataset, ...]:
    return (
        ConnectedDataset(
            dataset_id="ref-set",
            source=DatasetSource.SRD,
            document={"feats": [{"id": "Alert", "label": "Alert", "grants": []}]},
        ),
    )


def test_link_resolution_reads_connected_datasets():
    channel, answer = _feat_reference_channel()
    document = channel.parse(answer)

    lonely = channel.validate(document, DatasetSectionContext())
    assert [i.code for i in lonely.errors] == ["LINK_FEAT"]

    connected = channel.validate(
        document, DatasetSectionContext(connected=_alert_corpus())
    )
    assert connected.errors == ()


def test_spell_slugs_dictionary_reaches_the_validator():
    """Словарь SRD-слагов доходит до валидатора: unknown slug — предупреждение
    (не ошибка!), None — проверка слогов молчит (предписание LSS)."""
    channel = _channel(section="classes", dataset_id="hb-gen-classes-1")
    entries = json.loads(json.dumps(_fewshot("classes")))
    entries[0]["grants"].append({"type": "spell-fixed", "slug": "frost-bite"})
    document = channel.parse(json.dumps(entries, ensure_ascii=False))

    unknown = channel.validate(
        document, DatasetSectionContext(spell_slugs=("magic-missile",))
    )
    assert [i.code for i in unknown.warnings] == ["SPELL_SLUG_NOT_SRD"]
    assert unknown.errors == ()

    known = channel.validate(
        document, DatasetSectionContext(spell_slugs=("frost-bite",))
    )
    assert known.issues == ()

    silent = channel.validate(document, DatasetSectionContext(spell_slugs=None))
    assert [i for i in silent.issues if i.code == "SPELL_SLUG_NOT_SRD"] == []


async def test_unresolvable_link_enters_round_feedback_and_second_round_fixes_it():
    """Спека «Неразрешимая ссылка — ошибка круга» на живом валидаторе: первый
    ответ ссылается на несуществующий фит, круг возвращает ошибку, второй
    ответ с решаемой ссылкой проходит, документ — достроенный конверт."""
    channel = _channel(section="backgrounds", dataset_id="hb-gen-backgrounds-1")
    broken = json.loads(json.dumps(_fewshot("backgrounds")))
    broken[0]["grants"][-1]["featId"] = "GhostFeat"
    ask = _ScriptedAsk(
        [
            json.dumps(broken, ensure_ascii=False),
            "```json\n" + json.dumps(_fewshot("backgrounds"), ensure_ascii=False) + "\n```",
        ]
    )
    context = DatasetSectionContext(connected=_alert_corpus())

    result = await run_rounds(channel, context, ask)

    assert result.ok and result.attempts == 2
    assert result.report.errors == ()
    assert "LINK_FEAT" in ask.users[1]  # ошибка ушла в обратную связь круга
    assert json.loads(result.document)["id"] == "hb-gen-backgrounds-1"


# ── task 3.2: принятие через дверь импорта + автоподключение ──────────────────


def test_license_vocabulary_is_the_allowed_trio():
    assert DATASET_LICENSE_CHOICES == ("CC0", "CC-BY-4.0", "CC-BY-SA-4.0")
    assert DEFAULT_DATASET_LICENSE == "CC-BY-4.0"


def test_insert_license_keeps_the_envelope_and_replaces_only_the_license():
    channel = _channel()
    document = channel.parse(json.dumps(_fewshot("feats"), ensure_ascii=False))

    content = insert_dataset_license(document, "CC0")

    envelope = json.loads(content)
    assert envelope["license"] == "CC0"
    assert envelope["feats"] == _fewshot("feats")
    assert envelope["id"] == "hb-gen-feats-1"


def test_insert_license_refuses_foreign_license_and_junk_document():
    for foreign in ("CC-BY", "Public Domain", ""):
        with pytest.raises(ValueError, match="вне разрешённого выбора"):
            insert_dataset_license('{"id": "x"}', foreign)
    with pytest.raises(ValueError, match="не является корректным JSON"):
        insert_dataset_license("{битый", "CC0")
    with pytest.raises(ValueError, match="не является JSON-объектом"):
        insert_dataset_license("[1, 2]", "CC0")


async def test_accept_writes_homebrew_with_license_and_connects(uow, tmp_path):
    """Спека «Принятие подключает датасет»: файл в глобальном хранилище,
    лицензия в файле, набор отмечен подключённым."""
    storage, connections, acceptance = _acceptance_stack(tmp_path, uow)
    document = _channel().parse(json.dumps(_fewshot("feats"), ensure_ascii=False))

    outcome = await acceptance.accept(document)

    assert outcome.accepted and outcome.connected
    assert outcome.import_outcome.status is DatasetImportStatus.STORED
    assert outcome.import_outcome.report is not None
    assert outcome.import_outcome.report.import_allowed
    stored = json.loads(storage.load_content("hb-gen-feats-1"))
    assert stored["license"] == "CC-BY-4.0"  # дефолтная лицензия — в файле
    meta = storage.load_meta("hb-gen-feats-1")
    assert meta is not None and meta.source is DatasetSource.HOMEBREW
    assert await connections.connections() == ["hb-gen-feats-1"]


async def test_accept_records_the_chosen_license(uow, tmp_path):
    storage, _, acceptance = _acceptance_stack(tmp_path, uow)
    document = _channel().parse(json.dumps(_fewshot("feats"), ensure_ascii=False))

    outcome = await acceptance.accept(document, "CC0")

    assert outcome.accepted
    assert json.loads(storage.load_content("hb-gen-feats-1"))["license"] == "CC0"


async def test_document_with_errors_is_not_accepted(uow, tmp_path):
    """Спека «Документ с ошибками не принимается»: дверь отказывает до
    хранилища — полка пуста, игра ничего не подключила."""
    storage, connections, acceptance = _acceptance_stack(tmp_path, uow)
    document = _channel(
        section="backgrounds", dataset_id="hb-gen-backgrounds-1"
    ).parse(json.dumps(_fewshot("backgrounds"), ensure_ascii=False))
    # без подключённого «Alert» ссылка LINK_FEAT — ошибка валидатора

    outcome = await acceptance.accept(document)

    assert not outcome.accepted and not outcome.connected
    assert outcome.import_outcome.status is DatasetImportStatus.BLOCKED
    assert [i.code for i in outcome.import_outcome.report.errors] == ["LINK_FEAT"]  # type: ignore[union-attr]
    assert storage.list_datasets() == []
    assert await connections.connections() == []


async def test_foreign_license_refuses_before_the_door(uow, tmp_path):
    storage, connections, acceptance = _acceptance_stack(tmp_path, uow)
    document = _channel().parse(json.dumps(_fewshot("feats"), ensure_ascii=False))

    with pytest.raises(ValueError, match="вне разрешённого выбора"):
        await acceptance.accept(document, "CC-BY")

    assert storage.list_datasets() == []
    assert await connections.connections() == []


async def test_accept_asks_about_replacement_then_confirms(uow, tmp_path):
    """Замена существующей полки — вопрос двери и повтор с подтверждением;
    неподтверждённый ответ ничего не подключает."""
    storage, connections, acceptance = _acceptance_stack(tmp_path, uow)
    first = _channel().parse(json.dumps(_fewshot("feats"), ensure_ascii=False))
    await acceptance.accept(first)
    entries = _fewshot("feats")
    entries[0]["label"] = "Бдительность, переиздание"
    second = _channel().parse(json.dumps(entries, ensure_ascii=False))

    ask = await acceptance.accept(second)
    assert not ask.accepted and not ask.connected
    assert ask.import_outcome.status is DatasetImportStatus.NEEDS_CONFIRMATION
    assert storage.load_content("hb-gen-feats-1") == first

    done = await acceptance.accept(second, confirmed=True)
    assert done.accepted and done.connected
    assert isinstance(done, DatasetAcceptanceOutcome)
    assert json.loads(storage.load_content("hb-gen-feats-1"))["feats"][0]["label"] == (
        "Бдительность, переиздание"
    )


# ── охранка: канал живёт в Qt-free application-слое, секции закрыты ───────────


def test_channel_sections_match_the_lss_section_list():
    """Канал знает ровно шесть секций LSS; для каждой — свой файл-конверт."""
    for section in SECTIONS:
        channel = DatasetSectionChannel(section, f"hb-gen-{section}")
        document = json.loads(
            channel.parse(json.dumps(_fewshot(section), ensure_ascii=False))
        )
        assert list(document) == [
            "$schema",
            "id",
            "name",
            "system",
            "edition",
            "author",
            "license",
            section,
        ]
