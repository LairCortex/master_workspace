"""Канал заклинаний: конверты Foundry Item и принятие (add-dnd-lss-generation,
tasks 4.1–4.2).

Поза тестов канала датасетов: содержательные части из ответа модели
оборачиваются приложением (``type``, ``flags.lss.slug`` — служебные поля
конверта), служебные значения модели (``_id`` и пр.) в файл не попадают,
файл проходит ЖИВУЮ импортную проверку гримуаров. Гейт отчёта — три класса:
структурные ошибки парсера блокируют круг и принятие, семантика (пустой
текст, неизвестные уровень/школа) и «слаг вне SRD» — предупреждения, не
блокирующие ни круг, ни принятие. Принятие — только существующая дверь
``GrimoireImportService`` на настоящей полке ``tmp_path``: новый файл,
прежние байты целы, повтор — вопрос о замене своей полки.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.dd.application.generation_loop import run_rounds
from app.dd.application.grimoire_import_service import (
    ANONYMOUS_GRIMOIRES_PREFIX,
    GrimoireImportService,
    GrimoireImportStatus,
)
from app.dd.application.prompt_composer import PromptComposer, SlugVocabularyEntry
from app.dd.application.spellbook_channel import (
    CODE_SPELL_LEVEL_UNKNOWN,
    CODE_SPELL_SCHOOL_UNKNOWN,
    CODE_SPELL_TEXT_EMPTY,
    DEFAULT_SPELLBOOK_NAME,
    SPELL_DEFAULT_COUNT,
    SPELL_SCHOOL_CHOICES,
    SpellbookAcceptanceService,
    SpellbookChannel,
    SpellbookContext,
)
from app.dd.domain.grimoire import (
    CODE_GRIMOIRE_EMPTY,
    CODE_GRIMOIRE_SLUG_IN_SRD,
)
from app.dd.domain.lss_checks import CODE_SPELL_SLUG_NOT_SRD
from app.dd.infrastructure.grimoire_storage import GrimoireStorage

GENERATION_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "app" / "dd" / "resources" / "generation"
)


def _fewshot_spells() -> list[dict]:
    path = GENERATION_DIR / "fewshot" / "spellbook.json"
    return json.loads(path.read_text(encoding="utf-8"))["samples"]


class _ScriptedAsk:
    """Стаб-ответ канала той же формы, что у группы 1."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.users: list[str] = []

    async def __call__(self, system_prompt, user_prompt, on_phase=None):
        self.users.append(user_prompt)
        return self.answers.pop(0)


def _storage(tmp_path) -> GrimoireStorage:
    return GrimoireStorage(tmp_path / "grimoires")


def _acceptance(tmp_path) -> tuple[GrimoireStorage, SpellbookAcceptanceService]:
    storage = _storage(tmp_path)
    return storage, SpellbookAcceptanceService(GrimoireImportService(storage))


def _shelves_bytes(tmp_path) -> dict[str, bytes]:
    root = tmp_path / "grimoires"
    if not root.is_dir():
        return {}
    return {p.name: p.read_bytes() for p in sorted(root.glob("*"))}


# ── task 4.1: промт канала = слои Д3 + число заклинаний поверх ─────────────────


def test_prompt_appends_count_over_composer_layers():
    composer = PromptComposer()
    channel = SpellbookChannel()
    vocabulary = (
        SlugVocabularyEntry(source="srd51", slug="fire-ball", name="Fireball"),
    )
    context = SpellbookContext(world="Мир", idea="Идея", count=3, vocabulary=vocabulary)

    system, user = channel.build_prompt(context)

    base_system, base_user = composer.compose_spellbook("Мир", "Идея", vocabulary)
    assert system == base_system
    assert user == base_user + (
        "\n\nЗаклинаний в файле: 3 — выдай ровно столько заклинаний."
    )
    # дефолт числа — 5 (open question дизайна решён в пользу позы секций)
    _, default_user = channel.build_prompt(SpellbookContext())
    assert SPELL_DEFAULT_COUNT == 5
    assert default_user.endswith(
        "Заклинаний в файле: 5 — выдай ровно столько заклинаний."
    )


def test_count_outside_one_to_ten_is_refused():
    for bad in (0, 11):
        with pytest.raises(ValueError, match="число заклинаний в файле"):
            SpellbookContext(count=bad)


# ── task 4.1: конверт Foundry Item достраивает приложение ─────────────────────


def test_envelope_is_completed_by_the_app_and_passes_the_structural_gate():
    """Массив содержательных частей из ответа → файл заклинаний: конверты
    достроены приложением и проходят живую проверку гримуаров без ошибок
    (класс отчёта «чистые»)."""
    channel = SpellbookChannel()
    samples = _fewshot_spells()

    document = channel.parse(json.dumps(samples, ensure_ascii=False))

    parsed = json.loads(document)
    assert list(parsed) == ["name", "items"]
    assert parsed["name"] == DEFAULT_SPELLBOOK_NAME
    assert len(parsed["items"]) == 2
    first, second = parsed["items"]
    # ключи конверта — приложение: name/type/flags/system в фиксированном порядке
    assert list(first) == ["name", "type", "flags", "system"]
    assert (first["name"], first["type"]) == ("Искра праотца", "spell")
    assert first["flags"] == {"lss": {"slug": "ember-of-forebears"}}
    # содержательная часть модели живёт в system как есть
    assert first["system"]["level"] == 0
    assert first["system"]["school"] == "evocation"
    assert second["system"]["higherLevel"]["available"] is True
    # класс «чистые»: словарь не передан, семантика цела — вопросов нет
    report = channel.validate(document, SpellbookContext())
    assert report.issues == ()


def test_model_service_fields_never_reach_the_file():
    """Служебные поля конверта — правила приложения: протащила модель
    ``_id`` внутрь и снаружи, чужие ключи в ``system`` — в файл не попадают;
    массив, обёртки ``items``/``spells`` и одиночный предмет собирают один
    и тот же файл."""
    channel = SpellbookChannel()
    entry = {
        "_id": "Evil00000000001",
        "name": "Проверенный знак",
        "slug": "proven-sign",
        "type": "spell",
        "system": {
            "level": 2,
            "school": "abjuration",
            "description": {"value": "<p>Знак держится час.</p>"},
            "_id": "inner-junk",
            "flags": "junk",
        },
    }

    plain = channel.parse(json.dumps([entry], ensure_ascii=False))
    wrapped = channel.parse(json.dumps({"items": [entry]}, ensure_ascii=False))
    spells_key = channel.parse(json.dumps({"spells": [entry]}, ensure_ascii=False))
    single = channel.parse(json.dumps(entry, ensure_ascii=False))

    assert plain == wrapped == spells_key == single
    item = json.loads(plain)["items"][0]
    assert "_id" not in item  # служебное поле модели отброшено
    assert "_id" not in item["system"] and "flags" not in item["system"]
    assert item["flags"] == {"lss": {"slug": "proven-sign"}}


def test_answer_without_spell_array_is_a_russian_round_error():
    """Не-JSON и объект без списка заклинаний — обычные ValueError круга:
    раннер превращает их в ошибку и ведёт в обратную связь."""
    channel = SpellbookChannel()
    with pytest.raises(ValueError, match="не содержит JSON-документа"):
        channel.parse("извините, я не умею JSON")
    with pytest.raises(ValueError, match="массива заклинаний"):
        channel.parse(json.dumps({"classes": []}))


def test_unspellable_entries_are_dropped_and_parts_are_normalized():
    """Записи, которыми не может быть заклинание (не-словарь, чужой ``type``,
    имя-пустышка), в файл не пишутся; слаг нормализуется (нелатиница —
    честное «слога нет»); описание-строка получает форму ``{value}``,
    мусорное описание теряется (семантика честно скажет «пустой текст»);
    содержимое без блока ``system`` подбирается с верхнего уровня."""
    channel = SpellbookChannel()
    document = channel.parse(
        json.dumps(
            [
                "не словарь",
                {"type": "feat", "name": "Бдительность"},
                {"slug": "nameless", "system": {"level": 1}},
                {"name": "  Обрезка  ", "slug": "Moon Pet!", "system": {"level": 1}},
                {"name": "Кириллица", "slug": "Лунный", "system": {"level": 2}},
                {
                    "name": "Через флаг",
                    "flags": {"lss": {"slug": "Flag-Slug"}},
                    "system": {"level": 3},
                },
                {
                    "name": "Через flags.slug",
                    "flags": {"slug": "plain-flag"},
                    "system": {"level": 4},
                },
                {"name": "Флаг-мусор", "flags": 42, "system": {"level": 5}},
                {"name": "Описание-строка", "system": {"description": "Текст без HTML."}},
                {"name": "Мусор-описание", "system": {"description": 42}},
                {"name": "Без системы", "level": 6, "school": "illusion"},
            ],
            ensure_ascii=False,
        )
    )

    items = json.loads(document)["items"]
    assert [item["name"] for item in items] == [
        "Обрезка",
        "Кириллица",
        "Через флаг",
        "Через flags.slug",
        "Флаг-мусор",
        "Описание-строка",
        "Мусор-описание",
        "Без системы",
    ]
    flags = [item.get("flags") for item in items]
    assert flags == [
        {"lss": {"slug": "moon-pet"}},  # «Moon Pet!» → канонический слаг
        None,  # кириллический слаг не становится слагом тихо
        {"lss": {"slug": "flag-slug"}},
        {"lss": {"slug": "plain-flag"}},
        None,  # flags=42 — не слаг
        None,
        None,
        None,
    ]
    assert items[5]["system"]["description"] == {"value": "Текст без HTML."}
    assert "description" not in items[6]["system"]  # мусор ключа описания потерян
    assert items[7]["system"] == {"level": 6, "school": "illusion"}  # подбор с верхнего уровня


# ── task 4.1: три класса отчёта ───────────────────────────────────────────────


def test_semantic_mismatches_are_warnings_not_errors():
    """Семантика — предупреждения (класс «предупреждения»): пустой текст,
    неизвестные уровень/школа не блокируют ни круг, ни принятие."""
    channel = SpellbookChannel()
    document = channel.parse(
        json.dumps(
            [
                {"name": "Пустышка", "slug": "dud"},
                {
                    "name": "Числа",
                    "slug": "numbers",
                    "system": {"level": True, "school": 2, "description": {"chat": ""}},
                },
            ],
            ensure_ascii=False,
        )
    )

    report = channel.validate(document, SpellbookContext())

    assert report.errors == ()
    assert report.import_allowed  # предупреждения принятие не блокируют
    by_path = {i.path: i.code for i in report.warnings}
    assert by_path == {
        "spells[dud].level": CODE_SPELL_LEVEL_UNKNOWN,
        "spells[dud].school": CODE_SPELL_SCHOOL_UNKNOWN,
        "spells[dud]": CODE_SPELL_TEXT_EMPTY,
        "spells[numbers].level": CODE_SPELL_LEVEL_UNKNOWN,  # bool — не уровень
        "spells[numbers].school": CODE_SPELL_SCHOOL_UNKNOWN,  # число — не школа
        "spells[numbers]": CODE_SPELL_TEXT_EMPTY,
    }


def test_school_vocabulary_is_the_skeleton_eight():
    assert SPELL_SCHOOL_CHOICES == (
        "abjuration",
        "conjuration",
        "divination",
        "enchantment",
        "evocation",
        "illusion",
        "necromancy",
        "transmutation",
    )


def test_slug_outside_srd_is_a_conscious_warning():
    """Спека «Слаг вне SRD принимается осознанно»: словарь игры отмечает
    чужой слаг предупреждением, известный — молчит, словарь не передан —
    проверка молчит (поза tolerance LSS)."""
    channel = SpellbookChannel()
    document = channel.parse(json.dumps(_fewshot_spells(), ensure_ascii=False))

    partial = channel.validate(
        document, SpellbookContext(srd_slugs=("ember-of-forebears",))
    )
    assert partial.errors == ()
    assert [(i.code, i.path) for i in partial.warnings] == [
        (CODE_SPELL_SLUG_NOT_SRD, "spells[shield-of-loyalty].slug")
    ]

    known = channel.validate(
        document,
        SpellbookContext(srd_slugs=("ember-of-forebears", "shield-of-loyalty")),
    )
    assert known.issues == ()

    silent = channel.validate(document, SpellbookContext(srd_slugs=None))
    assert silent.issues == ()


def test_structural_errors_are_the_gate():
    """Класс «ошибки»: structural gate = ошибки импортной проверки гримуаров
    (битая структура, пустой список заклинаний); поверх них семантика — шум,
    возвращается ровно структурный отчёт."""
    channel = SpellbookChannel()
    empty = channel.parse("[]")  # модель ответила пустым массивом
    only_feats = channel.parse(
        json.dumps([{"type": "feat", "name": "Бдительность"}], ensure_ascii=False)
    )

    for document in (empty, only_feats):
        report = channel.validate(document, SpellbookContext())
        assert [i.code for i in report.errors] == [CODE_GRIMOIRE_EMPTY]
        assert not report.import_allowed

    broken = channel.validate("это не json", SpellbookContext())
    assert not broken.import_allowed


# ── task 4.1: круг поверх канала (ошибки — в фидбек, предупреждения — нет) ─────


async def test_warnings_do_not_trigger_a_round():
    """Спека «Предупреждения не запускают круг»: файл с предупреждениями
    (пустой текст) принят кругом с первого ответа."""
    channel = SpellbookChannel()
    answer = json.dumps(
        [{"name": "Знак без текста", "slug": "blank-sign"}], ensure_ascii=False
    )
    ask = _ScriptedAsk([answer])

    result = await run_rounds(channel, SpellbookContext(), ask)

    assert result.ok and result.attempts == 1
    # отчёт отсортирован канонически: сначала путь заклинания, затем поля
    assert [i.code for i in result.report.warnings] == [
        CODE_SPELL_TEXT_EMPTY,
        CODE_SPELL_LEVEL_UNKNOWN,
        CODE_SPELL_SCHOOL_UNKNOWN,
    ]


async def test_structural_error_enters_round_feedback_and_second_round_fixes_it():
    """Спека «Структурная ошибка блокирует принятие … ошибки уходят в круг
    перегенерации» на живом парсере: безымянные записи → пустой файл →
    GRIMOIRE_EMPTY в обратной связи, второй ответ (few-shot в fence) —
    достроенный валидный файл."""
    channel = SpellbookChannel()
    nameless = json.dumps(
        [{"slug": "no-name", "system": {"level": 1}}], ensure_ascii=False
    )
    ask = _ScriptedAsk(
        [nameless, "```json\n" + json.dumps(_fewshot_spells(), ensure_ascii=False) + "\n```"]
    )

    result = await run_rounds(channel, SpellbookContext(), ask)

    assert result.ok and result.attempts == 2
    assert result.report.errors == ()
    assert "GRIMOIRE_EMPTY" in ask.users[1]  # ошибка ушла в обратную связь круга
    assert json.loads(result.document)["name"] == DEFAULT_SPELLBOOK_NAME


def test_validate_survives_a_foreign_item_shape():
    """Публичный validate не падает на инородной форме файлов (парсер её
    принимает — семантика идёт по своим записям, не-записи пропускает)."""
    channel = SpellbookChannel()
    document = json.dumps(
        {"name": "Чужая выгрузка", "items": [{"name": "Тихий знак"}, "строка"]},
        ensure_ascii=False,
    )

    report = channel.validate(document, SpellbookContext())

    assert report.errors == ()
    assert {i.path for i in report.warnings} == {
        "spells[Тихий знак].level",
        "spells[Тихий знак].school",
        "spells[Тихий знак]",
    }


# ── task 4.2: принятие новым хоумбрю-гримуаром через существующую дверь ────────


def test_accept_adds_a_file_and_previous_shelves_are_bit_identical(tmp_path):
    """Спека «Файл принят новым гримуаром»: в хранилище появился новый файл
    (полка по содержимому — документ сам себя для хранилища не называет),
    прежние файлы целы бит-в-бит."""
    storage, acceptance = _acceptance(tmp_path)
    storage.save("old-a", json.dumps({"name": "Старый А", "items": []}))
    storage.save("old-b", json.dumps({"name": "Старый Б", "items": []}))
    before = _shelves_bytes(tmp_path)
    document = SpellbookChannel().parse(
        json.dumps(_fewshot_spells(), ensure_ascii=False)
    )

    outcome = acceptance.accept(document)

    assert outcome.status is GrimoireImportStatus.STORED
    assert outcome.grimoire_id.startswith(ANONYMOUS_GRIMOIRES_PREFIX)
    assert outcome.title == DEFAULT_SPELLBOOK_NAME
    assert outcome.spell_count == 2
    assert not outcome.replaced
    assert storage.load_content(outcome.grimoire_id) == document
    after = _shelves_bytes(tmp_path)
    for name, payload in before.items():
        assert after[name] == payload  # прежние файлы бит-в-бит целы
    assert set(after) == set(before) | {f"{outcome.grimoire_id}.json"}


def test_accept_honours_the_custom_book_name(tmp_path):
    storage, acceptance = _acceptance(tmp_path)
    document = SpellbookChannel(name="Гримуар забытых звёзд").parse(
        json.dumps(_fewshot_spells(), ensure_ascii=False)
    )

    outcome = acceptance.accept(document)

    assert outcome.status is GrimoireImportStatus.STORED
    assert outcome.title == "Гримуар забытых звёзд"


def test_warnings_do_not_block_acceptance_errors_do(tmp_path):
    """Спека «Слаг вне SRD принимается осознанно» + «Структурная ошибка
    блокирует принятие»: предупреждения (семантика канала и пересечение SRD
    на двери) едут с принятием, структурная ошибка отказывает — полки нет."""
    storage, acceptance = _acceptance(tmp_path)
    warning_document = SpellbookChannel().parse(
        json.dumps(
            [
                {"name": "Знак без текста", "slug": "blank-sign"},
                {"name": "Копия шара", "slug": "fire-ball",
                 "system": {"level": 3, "school": "evocation",
                            "description": {"value": "<p>Свой текст мастера.</p>"}}},
            ],
            ensure_ascii=False,
        )
    )

    outcome = acceptance.accept(warning_document, srd_slugs=("fire-ball",))

    assert outcome.status is GrimoireImportStatus.STORED
    assert outcome.report is not None and outcome.report.import_allowed
    assert CODE_GRIMOIRE_SLUG_IN_SRD in {i.code for i in outcome.report.issues}

    before = _shelves_bytes(tmp_path)
    blocked = acceptance.accept(SpellbookChannel().parse("[]"))

    assert blocked.status is GrimoireImportStatus.BLOCKED
    assert [i.code for i in blocked.report.errors] == [CODE_GRIMOIRE_EMPTY]  # type: ignore[union-attr]
    assert _shelves_bytes(tmp_path) == before  # под порогом хранилище не тронуто


def test_accept_of_the_same_document_asks_then_confirms(tmp_path):
    """Повтор тех же байт — штатный вопрос двери о замене своей же
    content-addressed полки; без подтверждения старые байты целы."""
    storage, acceptance = _acceptance(tmp_path)
    document = SpellbookChannel().parse(
        json.dumps(_fewshot_spells(), ensure_ascii=False)
    )
    first = acceptance.accept(document)
    grimoire_id = first.grimoire_id

    ask = acceptance.accept(document)

    assert ask.status is GrimoireImportStatus.NEEDS_CONFIRMATION
    assert storage.load_content(grimoire_id) == document

    done = acceptance.accept(document, confirmed=True)
    assert done.status is GrimoireImportStatus.STORED
    assert done.replaced
