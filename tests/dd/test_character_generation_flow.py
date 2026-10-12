"""Сквозные сценарии генерации персонажа (add-dnd-lss-generation, tasks
6.2–6.3; spec dnd-generation «Генерация персонажа с нуля», «Дозаполнение
персонажа»).

Оба сценария идут через существующие двери, без mocks самих себя:

- **с нуля**: концепция → :class:`CharacterChannel` → круг группы 1 (стаб-канал)
  → :class:`CharacterImportService` → персонаж в игре с ядром-строкой,
  живым лицом D&D-таба и сохранённым сырым документом (spec: результат
  принимается существующим импортом — второго входа нет);
- **дозаполнение**: сборщик группы 5 отвечает текущим документом, круг
  дозаполняет пустое, подтверждённая перезапись тем же документом обновляет
  карточку и заменяет сырой файл — написанное мастером остаётся целым.

Гейт «пусто дозаполнять» проверяется на реальной полностью заполненной
карточке: сборщик отдаёт документ без пустых полей, контекст отказывает до
единственного запроса к каналу.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from app.application.services.entity_service import EntityService
from app.dd.application.character_channel import (
    TOP_UP_NOTHING_REFUSAL,
    CharacterChannel,
    CharacterContext,
    top_up_missing_fields,
)
from app.dd.application.character_document_builder import CharacterDocumentBuilder
from app.dd.application.character_import_service import (
    CharacterImportService,
    CharacterImportStatus,
)
from app.dd.application.dataset_index_service import DatasetEntry, IndexSnapshot
from app.dd.application.generation_loop import run_rounds
from app.dd.application.prompt_composer import SlugVocabularyEntry
from app.dd.domain.character_editor import editor_doc_to_text
from app.dd.infrastructure.db.dd_models import decode_text_blocks
from app.dd.infrastructure.db.dd_schema import ensure_dd_tables
from app.dd.infrastructure.repositories.dd_character_repository import (
    DdCharacterRepository,
)
from app.domain.entity_registry import EntityType
from app.infrastructure.db.models import CharacterModel, DescriptionModel
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.character_repository import CharacterRepository

D1 = date(1300, 1, 1)

_VOCABULARY = (
    SlugVocabularyEntry("srd", "Elf", "Эльф"),
    SlugVocabularyEntry("srd", "HighElf", "Высший эльф"),
    SlugVocabularyEntry("srd", "Fighter", "Воин"),
    SlugVocabularyEntry("srd", "BattleMaster", "Боевой мастер"),
    SlugVocabularyEntry("srd", "GuildArtisan", "Гильдейский ремесленник"),
)
_RECORD_IDS = tuple(entry.slug for entry in _VOCABULARY)
_SPELL_SLUGS = ("fire-ball", "mending")


def _entry(slug: str, name: str) -> DatasetEntry:
    return DatasetEntry("srd", slug, name, {})


_INDEX = IndexSnapshot(
    ids=("srd",),
    titles={"srd": "SRD-5.1"},
    sections={
        "races": {"srd": (_entry("Elf", "Эльф"),)},
        "subraces": {"srd": (_entry("HighElf", "Высший эльф"),)},
        "classes": {"srd": (_entry("Fighter", "Воин"),)},
        "subclasses": {"srd": (_entry("BattleMaster", "Боевой мастер"),)},
        "backgrounds": {"srd": (_entry("GuildArtisan", "Гильдейский ремесленник"),)},
    },
    slugs={},
)


class _StubIndex:
    def __init__(self, snap: IndexSnapshot) -> None:
        self._snap = snap

    async def snapshot(self):
        return self._snap


class _ScriptedAsk:
    def __init__(self, answers: list[str]):
        self.answers = list(answers)
        self.users: list[str] = []

    async def __call__(self, system_prompt, user_prompt, on_phase=None):
        self.users.append(user_prompt)
        return self.answers.pop(0)


def _catalog(uow) -> dict:
    return {
        EntityType.CHARACTER.value: EntityService(
            CharacterRepository(uow.session),
            BaseRepository(uow.session, DescriptionModel),
        )
    }


def _import_service(uow) -> CharacterImportService:
    return CharacterImportService(
        uow=uow,
        entity_services=lambda: _catalog(uow),
        dataset_index=_StubIndex(_INDEX),
        now=lambda: D1,
    )


def _builder(uow) -> CharacterDocumentBuilder:
    return CharacterDocumentBuilder(
        uow=uow,
        entity_services=lambda: _catalog(uow),
        dataset_index=_StubIndex(_INDEX),
    )


async def _round(answer: str, **over):
    """Круг генерации на стаб-канале: контекст + один scripted-ответ."""
    kwargs: dict = dict(
        world="Мир пепла и ветров",
        concept="следопыт-разведчик гильдии",
        vocabulary=_VOCABULARY,
        record_ids=_RECORD_IDS,
        spell_slugs=_SPELL_SLUGS,
    )
    kwargs.update(over)
    context = CharacterContext(**kwargs)
    ask = _ScriptedAsk([answer])
    result = await run_rounds(CharacterChannel(context), context, ask)
    return context, ask, result


def _data_of(document: str) -> dict:
    return json.loads(json.loads(document)["data"])


# ── task 6.2: концепция → персонаж в игре (существующий импорт) ───────────────


async def test_concept_becomes_a_character_in_the_game(uow):
    await ensure_dd_tables(uow)
    answer = json.dumps(
        {
            "name": "Мариссель Тал",
            "level": 3,
            "info": {
                "race": {"id": "Elf", "name": "Эльф"},
                "charClass": {"id": "Fighter", "name": "Воин"},
            },
            "blocks": {"Внешность": "Прямая спина, седина рано тронула виски."},
            "spells": {"list": ["fire-ball"]},
        },
        ensure_ascii=False,
    )
    _context, ask, result = await _round(answer)
    assert ask.users and "следопыт-разведчик гильдии" in ask.users[0]
    assert result.ok, result.report.errors

    outcome = await _import_service(uow).import_character(result.document)
    assert outcome.status is CharacterImportStatus.CREATED
    assert outcome.name == "Мариссель Тал"
    character_id = outcome.character_id

    row = await uow.session.get(CharacterModel, character_id)
    assert row.name == "Мариссель Тал"  # ядро: персонаж появился в игре

    ext = await DdCharacterRepository(uow.session).get_ext(character_id)
    assert ext is not None  # лицо D&D-таба существует
    assert ext.raw_document == result.document  # сырой документ сохранён дословно
    assert ext.level == 3
    assert (ext.race_source_key, ext.race_ref_id, ext.race_snapshot_name) == (
        "srd",
        "Elf",
        "Эльф",
    )
    assert ext.class_ref_id == "Fighter"
    blocks = decode_text_blocks(ext.text_blocks)
    assert "Прямая спина" in blocks["Внешность"]
    # привязки заклинаний из файла НЕ выводятся — слаги живут в сыром документе
    assert await DdCharacterRepository(uow.session).list_spell_links(character_id) == []


async def test_preselects_survive_the_whole_way_into_the_card(uow):
    """Пре-выбор класса проходит весь путь: ответ модели перебит, импорт
    кладёт в карточку отмеченное мастером."""
    await ensure_dd_tables(uow)
    answer = json.dumps(
        {
            "name": "Безымянный",
            "info": {"charClass": {"id": "Wizard", "name": "Волшебник"}},
        },
        ensure_ascii=False,
    )
    _context, _ask, result = await _round(
        answer,
        level=5,
        char_class=_VOCABULARY[2],  # Fighter
    )
    assert result.ok, result.report.errors
    outcome = await _import_service(uow).import_character(result.document)
    assert outcome.status is CharacterImportStatus.CREATED
    ext = await DdCharacterRepository(uow.session).get_ext(outcome.character_id)
    assert ext.level == 5
    assert ext.class_ref_id == "Fighter"  # ответ Wizard перебит пре-выбором
    assert ext.class_snapshot_name == "Воин"


# ── task 6.3: дозаполнение — защита непустого и подтверждённая перезапись ─────


async def test_top_up_flow_fills_the_card_through_the_import_door(uow):
    await ensure_dd_tables(uow)
    # карточка мастера: имя, вид, класс, аватар-текст? — нет: только заполненное
    first = json.dumps(
        {
            "jsonType": "character",
            "version": "2",
            "data": {
                "name": "Грог",
                "info": {
                    "race": {"id": "Elf", "name": "Эльф"},
                    "charClass": {"id": "Fighter", "name": "Воин"},
                },
                "blocks": {"Предыстория": "Своими словами мастера."},
            },
        },
        ensure_ascii=False,
    )
    created = await _import_service(uow).import_character(first)
    assert created.status is CharacterImportStatus.CREATED
    character_id = created.character_id

    current = await _builder(uow).build(character_id)
    missing = top_up_missing_fields(current)
    assert "Уровень" in missing and "Заклинания" in missing
    assert "Имя" not in missing and "Вид" not in missing

    addition = json.dumps(
        {
            "name": "Переименованный",  # будет отвергнут склейкой
            "level": 4,
            "info": {
                "subrace": {"id": "HighElf", "name": "Высший эльф"},
                "subclass": {"id": "BattleMaster", "name": "Боевой мастер"},
            },
            "blocks": {
                "Предыстория": "выдуманная биография",  # будет отвергнут
                "Внешность": "Шрам над бровью.",
            },
            "spells": {"list": ["mending"]},
        },
        ensure_ascii=False,
    )
    _context, _ask, result = await _round(addition, current_document=current)
    assert result.ok, result.report.errors

    data = _data_of(result.document)
    assert data["name"] == "Грог"  # непустое защищено на уровне склейки
    assert editor_doc_to_text(data["blocks"]["Предыстория"])[0] == (
        "Своими словами мастера."
    )
    assert data["blocks"]["Внешность"] == "Шрам над бровью."

    outcome = await _import_service(uow).import_character(
        result.document, character_id=character_id, confirmed=True
    )
    assert outcome.status is CharacterImportStatus.OVERWRITTEN

    ext = await DdCharacterRepository(uow.session).get_ext(character_id)
    assert ext.raw_document == result.document  # сырой файл заменён документом круга
    assert ext.level == 4  # дозаполненное дошло до карточки
    assert (ext.subrace_source_key, ext.subrace_ref_id) == ("srd", "HighElf")
    assert (ext.subclass_ref_id, ext.subclass_snapshot_name) == (
        "BattleMaster",
        "Боевой мастер",
    )
    blocks = decode_text_blocks(ext.text_blocks)
    assert "Своими словами мастера." in blocks["Предыстория"]
    assert "выдуманная" not in blocks["Предыстория"]
    assert "Шрам над бровью." in blocks["Внешность"]
    row = await uow.session.get(CharacterModel, character_id)
    assert row.name == "Грог"  # карточка обновлена дозаполнением, а не переименована


async def test_full_card_leaves_nothing_to_fill(uow):
    """Гейт «Пусто дозаполнять — не запускается» на реальной карте: сборщик
    полностью заполненной карточки не оставляет пустых полей, и генерация
    отказывает до единого запроса к каналу."""
    await ensure_dd_tables(uow)
    full = json.dumps(
        {
            "jsonType": "character",
            "version": "2",
            "data": {
                "name": "Делла Кроу",
                "level": 7,
                "info": {
                    "race": {"id": "Elf", "name": "Эльф"},
                    "subrace": {"id": "HighElf", "name": "Высший эльф"},
                    "charClass": {"id": "Fighter", "name": "Воин"},
                    "subclass": {"id": "BattleMaster", "name": "Боевой мастер"},
                    "background": {
                        "id": "GuildArtisan",
                        "name": "Гильдейский ремесленник",
                    },
                },
                "blocks": {"Биография": "Мастер записал всё сам."},
            },
        },
        ensure_ascii=False,
    )
    created = await _import_service(uow).import_character(full)
    assert created.status is CharacterImportStatus.CREATED
    async with uow.transaction():
        await DdCharacterRepository(uow.session).insert_spell_link(
            created.character_id, "srd", "fire-ball", "Огненный снаряд"
        )

    current = await _builder(uow).build(created.character_id)
    assert top_up_missing_fields(current) == ()
    with pytest.raises(ValueError, match=TOP_UP_NOTHING_REFUSAL):
        await _round("недоходит", current_document=current)
