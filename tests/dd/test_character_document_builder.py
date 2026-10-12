"""Сборщик «карточка → character.json» (add-dnd-lss-generation, task 5.1;
spec dnd-character-export «Сборка документа из текущего состояния карточки»).

Два слоя проверки:

* чистый сборщик — конверт, границы уровня, правила раздела ``info``
  (подключённая ссылка / неразрешимый снимок / отсутствие), пустые поля,
  слаги заклинаний;
* служба над настоящей базой — импортированный, рукотворный и частично
  заполненный персонажи собираются в документ, который проходит
  ``CharacterValidatorService`` без ошибок (spec: все три наравне); документ
  следует за карточкой, а не за сохранённым сырым файлом; снятый датасет не
  калечит сборку; ``export_document`` пишет ровно тот текст, что принимает
  валидатор.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from app.application.services.entity_service import EntityService
from app.dd.application.character_document_builder import (
    CharacterDocumentBuilder,
    build_character_document,
)
from app.dd.application.character_import_service import CharacterImportService
from app.dd.application.character_validator_service import CharacterValidatorService
from app.dd.application.dataset_index_service import DatasetEntry, IndexSnapshot
from app.dd.application.dnd_character_extension_service import (
    DndCharacterExtensionService,
)
from app.dd.domain.character import DdSpellLink, ReferenceLink, empty_ext
from app.dd.domain.character_editor import editor_doc_to_text
from app.dd.infrastructure.db.dd_models import encode_text_blocks
from app.dd.infrastructure.db.dd_schema import ensure_dd_tables
from app.dd.infrastructure.repositories.dd_character_repository import (
    DdCharacterRepository,
    ext_to_domain,
)
from app.domain.entity_registry import EntityType
from app.infrastructure.db.models import CharacterModel, DescriptionModel
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.character_repository import CharacterRepository

D1 = date(1300, 1, 1)

_EMPTY_SNAP = IndexSnapshot(ids=(), titles={}, sections={}, slugs={})
_CONNECTED_SNAP = IndexSnapshot(
    ids=("srd",),
    titles={"srd": "SRD-5.1"},
    sections={"races": {"srd": (DatasetEntry("srd", "orc", "Орк", {}),)}},
    slugs={},
)


def _pure(**over):
    """Сборка чистого конверта из пустого лица с переопределениями."""
    kwargs = dict(
        name="Грог",
        level=None,
        links=empty_ext().links,
        blocks={},
        spell_links=(),
        snapshot=_CONNECTED_SNAP,
    )
    kwargs.update(over)
    return build_character_document(**kwargs)


def _data_of(envelope: dict) -> dict:
    assert envelope["jsonType"] == "character"
    assert envelope["version"] == "2"
    assert isinstance(envelope["data"], str)
    return json.loads(envelope["data"])


# ── чистый сборщик: конверт и границы полей ─────────────────────────────────


def test_envelope_is_the_format_identity():
    envelope = _pure()
    assert _data_of(envelope) == {"name": "Грог"}


def test_name_is_trimmed_once_and_alone():
    data = _data_of(_pure(name="  Мира  "))
    assert data == {"name": "Мира"}


def test_level_bounds_gate_the_key():
    assert _data_of(_pure(level=5))["level"] == 5
    assert _data_of(_pure(level=1))["level"] == 1
    assert _data_of(_pure(level=20))["level"] == 20
    # аномалия хранилища старше гейта — не выдумываем и не пишем
    assert "level" not in _data_of(_pure(level=0))
    assert "level" not in _data_of(_pure(level=21))
    assert "level" not in _data_of(_pure(level=None))


def test_unset_links_write_no_info_at_all():
    assert "info" not in _data_of(_pure())


def test_connected_link_is_pair_disconnected_key_is_omitted():
    """Неразрешимая привязка — единственная форма: ключ опускается, снимок
    имени остаётся в карточке (spec «Снятый датасет не калечит документ»,
    fix-dnd-followups Д5; второго вида «помеченная привязка» нет)."""
    links = empty_ext().links
    links = {
        **links,
        "race": ReferenceLink("srd", "orc", "Орк"),
        "class": ReferenceLink("gone", "wizard", "Волшебник"),
    }
    data = _data_of(_pure(links=links))
    assert data["info"]["race"] == {"id": "orc", "name": "Орк"}
    assert "charClass" not in data["info"]
    # остальные три слота не заданы — ключей нет вовсе
    assert set(data["info"]) == {"race"}
    # и снятая привязка остаётся снимком в самой карточке
    assert links["class"] == ReferenceLink("gone", "wizard", "Волшебник")


def test_snapshot_without_a_name_says_nothing():
    links = {
        **empty_ext().links,
        "race": ReferenceLink("srd", "orc", ""),
        "background": ReferenceLink("gone", "hermit", ""),
    }
    data = _data_of(_pure(links=links))
    # подключённая ссылка без снимка имени — честный id без имени…
    assert data["info"]["race"] == {"id": "orc"}
    # …неразрешимая без имени не говорит ничего и не пишется
    assert set(data["info"]) == {"race"}
    # тот же закон без подключённости: пустой id без имени — не привязка
    offline = _data_of(_pure(links=links, snapshot=_EMPTY_SNAP))
    assert "race" not in offline.get("info", {})


def test_empty_blocks_are_not_written():
    data = _data_of(
        _pure(blocks={"Биография": "текст", "  ": "пробел-имя", "Пусто": "   ", "Дыра": ""})
    )
    assert set(data["blocks"]) == {"Биография"}


def test_spell_slugs_keep_order_and_drop_duplicates_and_blanks():
    links = (
        DdSpellLink("srd", "fireball", "Огненный шар"),
        DdSpellLink("grim", "mending", "Починка"),
        DdSpellLink("other", "fireball", "Огненный шар снова"),
        DdSpellLink("grim", "", "Пустышка"),
    )
    data = _data_of(_pure(spell_links=links))
    assert data["spells"] == {"list": ["fireball", "mending"]}
    assert _data_of(_pure(spell_links=())).get("spells") is None


def test_blocks_carry_editor_nodes_with_formulas():
    data = _data_of(_pure(blocks={"Броня": "КД = [AC] + [DEX]"}))
    doc = data["blocks"]["Броня"]
    assert doc["type"] == "doc"
    read, issues = editor_doc_to_text(doc)
    assert issues == []
    assert read == "КД = [AC] + [DEX]"


# ── служба над базой: три персонажа наравне проходят валидатор ──────────────


class _StubIndex:
    def __init__(self, snap: IndexSnapshot) -> None:
        self._snap = snap

    async def snapshot(self):
        return self._snap


def _entity_services(uow) -> dict:
    return {
        EntityType.CHARACTER.value: EntityService(
            CharacterRepository(uow.session),
            BaseRepository(uow.session, DescriptionModel),
        )
    }


async def _make_character(uow, name: str) -> int:
    row = CharacterModel(name=name, start_date=D1)
    uow.session.add(row)
    await uow.session.commit()
    return row.id


def _builder(uow, snap: IndexSnapshot = _CONNECTED_SNAP) -> CharacterDocumentBuilder:
    return CharacterDocumentBuilder(
        uow=uow, entity_services=lambda: _entity_services(uow), dataset_index=_StubIndex(snap)
    )


async def _collect_and_validate(builder, character_id: int) -> dict:
    """Собрать текст, прогнать настоящим валидатором, вернуть разобранный data.
    Ошибки валидатора — провал теста (spec: «без ошибок»)."""
    text = await builder.build(character_id)
    report, parsed = CharacterValidatorService().validate(text)
    assert [f"{i.path}: {i.message}" for i in report.errors] == []
    assert parsed is not None
    return parsed


async def test_partially_filled_character_validates(uow):
    """Рукотворная карточка без единого D&D-поля: только имя — и файл проходит."""
    await ensure_dd_tables(uow)
    char_id = await _make_character(uow, "Неведомый")
    data = await _collect_and_validate(_builder(uow), char_id)
    assert data == {"name": "Неведомый"}


async def test_handcrafted_character_validates_with_every_face(uow):
    await ensure_dd_tables(uow)
    char_id = await _make_character(uow, "Мира")
    ext_service = DndCharacterExtensionService(uow)
    await ext_service.set_reference_link(char_id, "race", ReferenceLink("srd", "orc", "Орк"))
    await ext_service.set_reference_link(
        char_id, "class", ReferenceLink("gone", "wizard", "Волшебник")
    )
    await ext_service.set_level(char_id, 4)
    await ext_service.add_spell_link(char_id, DdSpellLink("srd", "fireball", "Огненный шар"))
    await ext_service.add_spell_link(char_id, DdSpellLink("grim", "mending", "Починка"))
    repo = DdCharacterRepository(uow.session)
    row = await repo.get_ext(char_id)
    row.text_blocks = encode_text_blocks(
        {"Внешность": "Шрам над бровью.\nБроня: [AC] крепка."}
    )
    await uow.session.commit()

    data = await _collect_and_validate(_builder(uow), char_id)
    assert data["name"] == "Мира"
    assert data["level"] == 4
    assert data["info"]["race"] == {"id": "orc", "name": "Орк"}
    # снятый источник: ключ привязки опущен (единственная форма), снимок
    # имени остался в карточке, валидатор ошибок не показал (spec)
    assert "charClass" not in data["info"]
    assert set(data["info"]) == {"race"}
    card = ext_to_domain(await DdCharacterRepository(uow.session).get_ext(char_id))
    assert card.links["class"] == ReferenceLink("gone", "wizard", "Волшебник")
    read, issues = editor_doc_to_text(data["blocks"]["Внешность"])
    assert issues == []
    assert read == "Шрам над бровью.\nБроня: [AC] крепка."
    assert data["spells"] == {"list": ["fireball", "mending"]}


async def test_imported_character_validates(uow, tmp_path):
    """Импортированный персонаж собирается наравне: его блоки — текст из
    файла, привязки — тройки из документа."""
    await ensure_dd_tables(uow)
    entity_services = _entity_services(uow)
    service = CharacterImportService(
        uow=uow,
        entity_services=lambda: entity_services,
        image_store=None,
        dataset_index=_StubIndex(_CONNECTED_SNAP),
        now=lambda: D1,
    )
    content = json.dumps(
        {
            "jsonType": "character",
            "version": "2",
            "data": {
                "name": "Грог",
                "level": 3,
                "info": {
                    "race": {"id": "orc", "name": "Полуорк"},
                    "charClass": {"id": "barbarian", "name": "Варвар"},
                },
                "blocks": {"Биография": "Родился в степи."},
            },
        },
        ensure_ascii=False,
    )
    outcome = await service.import_character(content)
    assert outcome.character_id is not None

    data = await _collect_and_validate(_builder(uow), outcome.character_id)
    assert data["name"] == "Грог"
    assert data["level"] == 3
    # карточка после импорта держит живое имя найденной записи (импорт берёт
    # его из индекса) — документ читает карточку, потому имя из индекса
    assert data["info"]["race"] == {"id": "orc", "name": "Орк"}
    # запись, которой нет в подключённом наборе, импорт хранит снимком файла;
    # без подтверждённого источника её ключ в документ не попадает, а снимок
    # остаётся в карточке (fix-dnd-followups Д5)
    assert "charClass" not in data["info"]
    card = ext_to_domain(await DdCharacterRepository(uow.session).get_ext(outcome.character_id))
    assert card.links["class"] == ReferenceLink("", "barbarian", "Варвар")
    read, _issues = editor_doc_to_text(data["blocks"]["Биография"])
    assert read == "Родился в степи."


async def test_document_follows_the_card_not_the_raw_file(uow):
    """Spec scenario «Документ следует за карточкой»: после импорта мастер
    сменил уровень и текст блока, переименовал персонажа — документ отражает
    правки, сырой файл остаётся прежним."""
    await ensure_dd_tables(uow)
    entity_services = _entity_services(uow)
    service = CharacterImportService(
        uow=uow,
        entity_services=lambda: entity_services,
        image_store=None,
        dataset_index=_StubIndex(_CONNECTED_SNAP),
        now=lambda: D1,
    )
    content = json.dumps(
        {
            "jsonType": "character",
            "version": "2",
            "data": {"name": "Грог", "level": 3, "blocks": {"Биография": "Родился в степи."}},
        },
        ensure_ascii=False,
    )
    outcome = await service.import_character(content)
    char_id = outcome.character_id

    await DndCharacterExtensionService(uow).set_level(char_id, 5)
    await entity_services[EntityType.CHARACTER.value].update_entity(char_id, name="Грог Второй")
    repo = DdCharacterRepository(uow.session)
    row = await repo.get_ext(char_id)
    row.text_blocks = encode_text_blocks({"Биография": "Ушёл в горы."})
    await uow.session.commit()

    data = await _collect_and_validate(_builder(uow), char_id)
    assert data["name"] == "Грог Второй"
    assert data["level"] == 5
    read, _issues = editor_doc_to_text(data["blocks"]["Биография"])
    assert read == "Ушёл в горы."
    # сырой файл-снимок не тронут правками карточки — в нём прежний уровень
    row = await repo.get_ext(char_id)
    assert '"level": 3' in row.raw_document
    assert "Ушёл в горы" not in row.raw_document


async def test_export_document_writes_the_validated_text(uow, tmp_path):
    await ensure_dd_tables(uow)
    char_id = await _make_character(uow, "Грог")
    path = tmp_path / "character.json"
    builder = _builder(uow)
    await builder.export_document(char_id, str(path))
    written = path.read_text(encoding="utf-8")
    assert written == await builder.build(char_id)
    report, parsed = CharacterValidatorService().validate(written)
    assert report.errors == ()
    assert parsed is not None and parsed["name"] == "Грог"


# ── честные отказы дверей сборки ─────────────────────────────────────────────


async def test_missing_character_is_refused_in_words(uow):
    await ensure_dd_tables(uow)
    with pytest.raises(RuntimeError, match="не найден"):
        await _builder(uow).collect(4242)


async def test_catalog_without_characters_is_refused_in_words(uow):
    await ensure_dd_tables(uow)
    char_id = await _make_character(uow, "Грог")
    builder = CharacterDocumentBuilder(
        uow=uow, entity_services=lambda: {}, dataset_index=_StubIndex(_EMPTY_SNAP)
    )
    with pytest.raises(RuntimeError, match="персонаж"):
        await builder.collect(char_id)


# ── снимок подключённости решает исход привязки ───────────────────────────────


async def test_same_link_is_unresolvable_when_source_leaves(uow):
    """Spec scenario «Снятый датасет не калечит документ»: та же карточка
    собирается при снятом источнике — сборка не падает, слаговый ключ
    привязки в документе отсутствует, валидатор ошибок не показывает,
    снимок имени сохранён в карточке."""
    await ensure_dd_tables(uow)
    char_id = await _make_character(uow, "Мира")
    await DndCharacterExtensionService(uow).set_reference_link(
        char_id, "race", ReferenceLink("srd", "orc", "Орк")
    )
    live = _data_of(await _builder(uow, _CONNECTED_SNAP).collect(char_id))
    # снятая подключённость — обычная сборка настоящим валидатором (без ошибок)
    offline = await _collect_and_validate(_builder(uow, _EMPTY_SNAP), char_id)
    assert live["info"]["race"] == {"id": "orc", "name": "Орк"}
    assert "race" not in offline.get("info", {})
    card = ext_to_domain(await DdCharacterRepository(uow.session).get_ext(char_id))
    assert card.links["race"] == ReferenceLink("srd", "orc", "Орк")
