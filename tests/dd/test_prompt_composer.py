"""Промтостроение и ресурсы генерации (add-dnd-lss-generation, tasks 2.1–2.2).

Ресурсы (``app/dd/resources/generation/``) фиксированы и детерминированы:
состав файлов, их содержимое (контрольные суммы) и форма few-shot-записей
проверяются на живых валидаторах модуля — образцы обязаны быть валидными
записями формата LSS, иначе круг генерации учился бы на мусоре. Сборка
``PromptComposer`` пинится golden-проверкой на фиксированных входах (design Д3),
а тест слоя словаря закрепляет спеку «Промт не зависит от подключенного
датасета»: подключение разных наборов меняет только слой словаря.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from app.dd.application.character_validator_service import CharacterValidatorService
from app.dd.application.dataset_validator_service import DatasetValidatorService
from app.dd.application.prompt_composer import (
    FEWSHOT_KEYS,
    GENERATION_RESOURCE_DIR,
    SKELETON_FILES,
    PromptComposer,
    SlugVocabularyEntry,
    generation_resource_dir,
)
from app.dd.domain.dataset import DatasetSource
from app.dd.domain.grimoire import parse_grimoire
from app.dd.domain.lss_checks import SECTIONS
from app.dd.infrastructure.lss_schemas import CHARACTER_FORMAT_VERSION

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GENERATION_DIR = REPO_ROOT / "app" / "dd" / "resources" / "generation"
SPEC_PATH = REPO_ROOT / "nri_manager.spec"

# ── фиксированные входы golden-сборки (design Д3) ────────────────────────────

WORLD = "Пограничье Серой долины: руины старой империи, страх перед магией."
IDEA = "Процветавший до Катаклизма орден, чьи остатки живут в страхе."

VOCABULARY = (
    SlugVocabularyEntry(source="srd51", slug="Elf", name="Эльф"),
    SlugVocabularyEntry(source="srd51", slug="HighElf", name="Высший эльф"),
    SlugVocabularyEntry(source="my-pack", slug="Alert", name="Бдительность"),
    SlugVocabularyEntry(source="srd51", slug="mage-hand", name="mage-hand"),
)

VOCABULARY_HEADER = (
    "Словарь идентификаторов подключённых источников — единственная область "
    "ссылок (id/slug/featId/classId/raceId берутся только отсюда); формат "
    "строки: slug — «снимок имени»."
)

# Контрольные суммы ресурсов: любое содержательное изменение скелета или
# few-shot-набора — явная смена промта, а не случайный дрейф (golden-поза).
RESOURCE_DIGESTS: dict[str, str] = {
    "skeletons/dataset-section.txt": "a7a57844b0b0b580ae3b47da79eaf0459c33ab05434291e5811497a1cf36bf68",
    "skeletons/spellbook.txt": "c682c95045c29a9be9eafd25b6c5ad59bab1a542f592175e6a557b67653e5985",
    "skeletons/character.txt": "04257b38d4ae3ee778f1635b0d2f06b087c4d3e2e23e4a5d0fa00a96259636af",
    "fewshot/classes.json": "3f4133c817131fed4758caeaf36e76af049f9159d8574faab1df5a03c10fc967",
    "fewshot/subclasses.json": "027291c7aafbad73c1f32f33ea84738148906018b2be814b3942b47917000085",
    "fewshot/races.json": "0c15d88c6cda15c0aa4dabd867b0295d9bb5983a2916b6ee4e54fb7c126230a8",
    "fewshot/subraces.json": "3c1f8fe211f1cf7b064486766d94fe42fd8533f92e7ab82542e31f8993bde424",
    "fewshot/backgrounds.json": "57453646052696532404f2b56334f7467d631137d0e550a7b867f9ab5a43d8a2",
    "fewshot/feats.json": "b28f3ebc78d1f8e93d4356833738cd7213b2080dbd84345508ccb2b8599f037d",
    "fewshot/spellbook.json": "099f8834314b487068e013b54558e888869c2e4bb364d2869efb4a3c63badbe7",
    "fewshot/character.json": "3e80346ebea63de7e523a97bdad28525b30c7e4ed9430af5cd08319ef2336f34",
}


def _fewshot(key: str) -> dict:
    path = GENERATION_DIR / "fewshot" / f"{key}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _skeleton(channel: str) -> str:
    path = GENERATION_DIR / "skeletons" / SKELETON_FILES[channel]
    return path.read_text(encoding="utf-8").strip()


# ── task 2.1: ресурсы на месте и детерминированы ─────────────────────────────


def test_skeleton_files_exist_for_every_channel():
    for channel, name in SKELETON_FILES.items():
        path = GENERATION_DIR / "skeletons" / name
        assert path.is_file(), f"нет скелета системного промта для канала {channel}"
        text = path.read_text(encoding="utf-8")
        # директива «содержимое по-русски, протокол латиницей» — в каждом скелете
        assert "по-русски" in text, f"скелет {channel} потерял языковую директиву"
        assert "латиниц" in text, f"скелет {channel} потерял директиву протокола"


def test_fewshot_resources_exist_for_every_section_and_channel():
    expected = {f"fewshot/{key}.json" for key in SECTIONS + ("spellbook", "character")}
    assert set(FEWSHOT_KEYS) == set(SECTIONS) | {"spellbook", "character"}
    for key in FEWSHOT_KEYS:
        path = GENERATION_DIR / "fewshot" / f"{key}.json"
        assert path.is_file(), f"нет few-shot-набора {key}"
    on_disk = {
        str(p.relative_to(GENERATION_DIR))
        for p in (GENERATION_DIR / "fewshot").glob("*.json")
    }
    assert on_disk == expected


def test_fewshot_shapes_are_fixed():
    """Каждый набор — «label» (RU-подпись секции/канала) + непустой массив
    «samples» записей; ключи порядка фиксированы JSON-файлом."""
    for key in FEWSHOT_KEYS:
        document = _fewshot(key)
        assert set(document) == {"label", "samples"}, f"fewshot/{key}: чужие ключи"
        assert isinstance(document["label"], str) and document["label"], key
        assert isinstance(document["samples"], list) and document["samples"], key
        assert all(isinstance(sample, dict) and sample for sample in document["samples"])


def test_resource_content_is_digest_pinned():
    """Golden для ресурсов: побайтовое содержимое фиксировано суммой."""
    assert set(RESOURCE_DIGESTS) == {
        f"skeletons/{name}" for name in SKELETON_FILES.values()
    } | {f"fewshot/{key}.json" for key in FEWSHOT_KEYS}
    for relative, digest in RESOURCE_DIGESTS.items():
        path = GENERATION_DIR / relative
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == digest, f"содержимое ресурса {relative} изменилось — сверь golden"


# ── разрешение каталога ресурсов (та же поза, что у бандла схем) ─────────────


def test_generation_resource_dir_default_is_package_directory():
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        assert generation_resource_dir() == GENERATION_RESOURCE_DIR
    finally:
        monkeypatch.undo()


def test_generation_resource_dir_frozen_override(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert generation_resource_dir() == (
        tmp_path / "app" / "dd" / "resources" / "generation"
    )


def test_composer_accepts_explicit_resource_dir():
    composer = PromptComposer(resource_dir=GENERATION_DIR)
    system, user = composer.compose_spellbook(WORLD, IDEA, VOCABULARY)
    default = PromptComposer()
    assert (system, user) == default.compose_spellbook(WORLD, IDEA, VOCABULARY)


# ── task 2.2: golden-сборка PromptComposer ───────────────────────────────────


def test_dataset_section_prompt_golden_feats():
    """Полный golden секционного промта на фиксированных входах: системная
    часть = скелет + строка секции + фиксированные образцы; пользовательская
    = мир → идея мастера → слой словаря."""
    composer = PromptComposer()
    system, user = composer.compose_dataset_section("feats", WORLD, IDEA, VOCABULARY)

    expected_system = "\n\n".join(
        [
            _skeleton("dataset-section"),
            "Секция: feats («Черты»).",
            "Образцы записей секции — повторяй их формат точно, содержимое пиши своё:\n"
            + json.dumps(_fewshot("feats")["samples"], ensure_ascii=False, indent=2),
        ]
    )
    assert system == expected_system
    assert user == (
        f"Описание мира:\n{WORLD}\n\n"
        f"Идея мастера:\n{IDEA}\n\n"
        f"{VOCABULARY_HEADER}\n"
        "[srd51]\n"
        "- Elf — «Эльф»\n"
        "- HighElf — «Высший эльф»\n"
        "- mage-hand\n"
        "[my-pack]\n"
        "- Alert — «Бдительность»"
    )


@pytest.mark.parametrize("channel", ["spellbook", "character"])
def test_channel_system_prompt_golden(channel):
    composer = PromptComposer()
    compose = getattr(composer, f"compose_{channel}")
    system, user = compose(WORLD, IDEA, VOCABULARY)
    header = {
        "spellbook": "Образец заклинания — повторяй его формат точно, содержимое пиши своё:",
        "character": (
            "Образцы фрагментов документов персонажей — повторяй их формат точно, "
            "содержимое пиши своё:"
        ),
    }[channel]
    assert system == "\n\n".join(
        [
            _skeleton(channel),
            header
            + "\n"
            + json.dumps(_fewshot(channel)["samples"], ensure_ascii=False, indent=2),
        ]
    )


@pytest.mark.parametrize("section", SECTIONS)
def test_section_prompt_assembly_contract(section):
    """Для всех шести секций: скелет общий, секция названа протокольным ключом
    и RU-подписью, образцы — ровно из файла секции, порядок побайтовый."""
    composer = PromptComposer()
    system, user = composer.compose_dataset_section(section)
    assert system.startswith(_skeleton("dataset-section") + "\n\n")
    label = _fewshot(section)["label"]
    assert f"\nСекция: {section} («{label}»).\n" in system
    assert json.dumps(
        _fewshot(section)["samples"], ensure_ascii=False, indent=2
    ) in system
    # пустые мир и идея не печатаются, словарь-по-умолчанию пуст и честен
    assert user == (
        f"{VOCABULARY_HEADER}\n(пусто — ссылаться ни на какие идентификаторы нельзя)"
    )


def test_assembly_is_byte_deterministic():
    composer = PromptComposer()
    first = composer.compose_dataset_section("races", WORLD, IDEA, VOCABULARY)
    second = composer.compose_dataset_section("races", WORLD, IDEA, VOCABULARY)
    assert first == second
    other = PromptComposer()
    assert other.compose_character(WORLD, IDEA, VOCABULARY) == (
        composer.compose_character(WORLD, IDEA, VOCABULARY)
    )


def test_unknown_section_is_russian_value_error():
    composer = PromptComposer()
    with pytest.raises(ValueError, match="неизвестная секция датасета: 'monsters'"):
        composer.compose_dataset_section("monsters", WORLD, IDEA, VOCABULARY)


# ── слой словаря: источник + slug + снимок; единственный меняющийся слой ─────


def test_connected_datasets_change_only_the_vocabulary_layer():
    """Спека «Промт не зависит от подключенного датасета»: наборы примеров
    идентичны, различается только слой словаря идентификаторов."""
    composer = PromptComposer()
    other_vocabulary = VOCABULARY + (
        SlugVocabularyEntry(source="home-pack", slug="SwiftDuelist", name="Стремительный дуэлянт"),
    )
    for compose in (
        lambda vocab: composer.compose_dataset_section("feats", WORLD, IDEA, vocab),
        lambda vocab: composer.compose_spellbook(WORLD, IDEA, vocab),
        lambda vocab: composer.compose_character(WORLD, IDEA, vocab),
    ):
        first_system, first_user = compose(VOCABULARY)
        second_system, second_user = compose(other_vocabulary)
        # наборы примеров идентичны…
        assert first_system == second_system
        # …и за границами слоя словаря промты байт-в-байт равны
        assert first_user.count(VOCABULARY_HEADER) == 1
        assert second_user.count(VOCABULARY_HEADER) == 1
        head, own_tail = first_user.split(VOCABULARY_HEADER, 1)
        other_head, other_tail = second_user.split(VOCABULARY_HEADER, 1)
        assert head == other_head
        assert own_tail != other_tail
        # отличается ровно словарь: новый источник виден только во втором
        assert "[home-pack]" in other_tail and "[home-pack]" not in own_tail
        assert "- SwiftDuelist — «Стремительный дуэлянт»" in other_tail
        assert "- Elf — «Эльф»" in own_tail and "- Elf — «Эльф»" in other_tail


def test_world_and_idea_are_separate_layers():
    composer = PromptComposer()
    _, user = composer.compose_character("", IDEA, ())
    assert "Описание мира" not in user
    assert user == (
        f"Идея мастера:\n{IDEA}\n\n"
        f"{VOCABULARY_HEADER}\n(пусто — ссылаться ни на какие идентификаторы нельзя)"
    )
    _, world_only = composer.compose_character(f"  {WORLD}  ", "   ", ())
    assert world_only == (
        f"Описание мира:\n{WORLD}\n\n{VOCABULARY_HEADER}\n"
        "(пусто — ссылаться ни на какие идентификаторы нельзя)"
    )


def test_vocabulary_groups_by_source_in_entry_order():
    composer = PromptComposer()
    entries = (
        SlugVocabularyEntry(source="beta", slug="b1", name="Бета"),
        SlugVocabularyEntry(source="alpha", slug="a1", name="Альфа"),
        SlugVocabularyEntry(source="beta", slug="b2", name=""),
        SlugVocabularyEntry(source="alpha", slug="a2", name="a2"),
    )
    _, user = composer.compose_spellbook(vocabulary=entries)
    vocabulary_block = user.split(VOCABULARY_HEADER + "\n", 1)[1]
    assert vocabulary_block == (
        "[beta]\n- b1 — «Бета»\n- b2\n[alpha]\n- a1 — «Альфа»\n- a2"
    )


# ── few-shot-записи — валидные записи формата (живые валидаторы модуля) ───────


def test_dataset_fewshot_samples_pass_the_live_validator():
    """Все секционные образцы вместе — консистентный мини-датасет: конверт
    достраивается как в канале, валидатор без подключённых источников и без
    словаря слагов не находит ошибок (перекрёстные id разрешаются внутри
    файла: BattleMaster→Fighter, HighElf→Elf, featId Alert)."""
    document = {
        "id": "fewshot-sample",
        "name": "Образцы few-shot",
        "system": "dnd_5",
        "edition": "2024",
        "author": "Master Workspace",
        "license": "CC-BY-4.0",
    }
    for section in SECTIONS:
        document[section] = _fewshot(section)["samples"]
    report = DatasetValidatorService().validate(
        json.dumps(document, ensure_ascii=False),
        connected=(),
        spell_slugs=None,
        source=DatasetSource.HOMEBREW,
    )
    assert report.errors == ()


@pytest.mark.parametrize("index", range(3))
def test_character_fragments_pass_the_live_validator(index):
    fragment = _fewshot("character")["samples"][index]
    envelope = {
        "jsonType": "character",
        "version": CHARACTER_FORMAT_VERSION,
        "data": json.dumps(fragment, ensure_ascii=False),
    }
    report, _ = CharacterValidatorService().validate(
        json.dumps(envelope, ensure_ascii=False)
    )
    assert report.errors == ()


def test_spell_template_parses_as_spells():
    """Шаблон заклинания читается существующим парсером гримуаров: имя, слаг и
    текст доходят, структурных ошибок нет."""
    content = json.dumps(_fewshot("spellbook")["samples"], ensure_ascii=False)
    parsed = parse_grimoire(content)
    assert parsed.report.errors == ()
    by_slug = {spell.slug: spell for spell in parsed.spells}
    assert by_slug["ember-of-forebears"].name == "Искра праотца"
    assert "1d10" in by_slug["ember-of-forebears"].description
    assert by_slug["shield-of-loyalty"].name == "Щит верности"


# ── замороженная сборка носит ресурсы с собой (та же охранка, что у схем) ────


def test_spec_datas_ship_the_generation_directory():
    datas = SPEC_PATH.read_text(encoding="utf-8").split("datas=[", 1)[1].rsplit("]", 1)[0]
    assert '("app/dd/resources/generation", "app/dd/resources/generation")' in datas, (
        "nri_manager.spec datas must ship app/dd/resources/generation — "
        "без ресурсов генерации замороженная сборка теряет скелеты и few-shot"
    )
