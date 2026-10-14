"""Приёмка QA-фикстур из ``docs/qa/fixtures/dnd/`` (fix-dnd-followups, задачи 5.1/5.2).

Фикстуры собраны руками по бандл-схемам (design Д6) и живут в репозитории —
значит их приёмка двойная: этот оффскрин-тест прогоняет файлы через настоящие
конвейеры, а живой прогон (группа 7) импортирует те же байты через файловый
диалог. Тест читает сами файлы репозитория — не реплики: поправить фикстуру,
не замеченную конвейером, нельзя.

Что пинится здесь (верификации задач):

* 5.1 — импорт обеих фикстур проходит: снимок (``raw_document`` побайтово равен
  файлу), привязки (триплеты пяти слотов: живая пара+имя для подключённой
  записи, снимок из файла для отсутствующей — Д7), уровень, блоки (структурный
  рендер + конвертация форматного документа с нотацией ``[STR]``), аватар
  прошёл дверь ImageStore; при подтверждённой перезаписи поля и снимок
  заменены, а id листа LSS — не выводимый из файла — остался на месте;
* 5.2 — импортёр гримуаров принимает Foundry-фикстуру с ожидаемым отчётом
  (ни ошибок, ни предупреждений), кладёт на полку под своим id и считает три
  заклинания; повторный импорт того же файла — ветка подтверждения замены.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.entity_service import EntityService
from app.dd.application.character_import_service import (
    BLOCK_AVATAR,
    CharacterImportService,
    CharacterImportStatus,
)
from app.dd.application.dataset_index_service import DatasetEntry, IndexSnapshot
from app.dd.application.grimoire_import_service import (
    GrimoireImportService,
    GrimoireImportStatus,
)
from app.dd.domain.character_checks import (
    CODE_CHAR_DEPRECATED_BONUSES,
    CODE_CHAR_SERVICE_KEYS,
)
from app.dd.domain.grimoire import parse_grimoire
from app.dd.infrastructure.db.dd_models import decode_text_blocks
from app.dd.infrastructure.db.dd_schema import ensure_dd_tables
from app.dd.infrastructure.grimoire_storage import GrimoireStorage
from app.dd.infrastructure.repositories.dd_character_repository import (
    DdCharacterRepository,
    mechanics_from_row,
)
from app.domain.entity_registry import EntityType
from app.infrastructure.db.models import CharacterModel, DescriptionModel
from app.infrastructure.images.store import ImageStore
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.character_repository import CharacterRepository

#: Фикстуры лежат в репозитории рядом с procedures 13/14/15 — тест читает их,
#: а не копирует: приёмка именно тех байтов, которые выберет живой прогон.
FIXTURES_DIR = Path(__file__).resolve().parents[2] / "docs" / "qa" / "fixtures" / "dnd"
CHARACTER_INITIAL = FIXTURES_DIR / "character-import-initial.json"
CHARACTER_UPDATED = FIXTURES_DIR / "character-import-updated.json"
CHARACTER_FULL = FIXTURES_DIR / "character-import-full.json"
GRIMOIRE_SAMPLE = FIXTURES_DIR / "grimoire-foundry-sample.json"

D1 = date(1300, 1, 1)
SHEET_ID = "qa-lss-sheet-042"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class _StubIndex:
    def __init__(self, snap: IndexSnapshot) -> None:
        self._snap = snap

    async def snapshot(self):
        return self._snap


def _fixture_index() -> IndexSnapshot:
    """Индекс как на живом прогоне с подключёнными SRD: часть записей фикса-
    документов подключена (живая пара + живое имя), подвид/подклассы — нет
    (снимок имени из файла, Д7). Имена записей нарочно НЕ равны снимкам из
    файла: так тест различает, чьё имя попало в триплет."""
    return IndexSnapshot(
        ids=("srd",),
        titles={"srd": "SRD-5.1"},
        sections={
            "races": {"srd": (DatasetEntry("srd", "dwarf", "Дварф набора", {}),)},
            "classes": {"srd": (DatasetEntry("srd", "fighter", "Воин набора", {}),)},
            "backgrounds": {
                "srd": (
                    DatasetEntry("srd", "soldier", "Солдат набора", {}),
                    DatasetEntry("srd", "outlander", "Чужеземец набора", {}),
                )
            },
            # dd-card-redesign task 6.1: «alert» подключён (живая пара+имя),
            # «lucky» — нет (снимок имени из файла, Д7 для черты).
            "feats": {
                "srd": (DatasetEntry("srd", "alert", "Наблюдательность набора", {}),)
            },
        },
        slugs={},
    )


async def _make_service(uow, images_dir: Path) -> CharacterImportService:
    """Тот же пол real-кatalogа, что у тестов сервисного контура: write-path
    идёт через службу персонажей, ImageStore — настоящая дверь картинок."""
    await ensure_dd_tables(uow)
    desc_repo = BaseRepository(uow.session, DescriptionModel)
    catalog = {
        EntityType.CHARACTER.value: EntityService(CharacterRepository(uow.session), desc_repo)
    }
    return CharacterImportService(
        uow=uow,
        entity_services=lambda: catalog,
        image_store=ImageStore(uow.session, images_dir),
        dataset_index=_StubIndex(_fixture_index()),
        now=lambda: D1,
    )


async def _ext_row(session: AsyncSession, character_id: int):
    return await DdCharacterRepository(session).get_ext(character_id)


# ── 5.1: character-import-initial.json ──────────────────────────────────────


async def test_initial_fixture_creates_a_character_with_everything_laid_out(
    uow, tmp_path
):
    content = _read(CHARACTER_INITIAL)
    service = await _make_service(uow, tmp_path)

    outcome = await service.import_character(content)

    assert outcome.status is CharacterImportStatus.CREATED
    assert outcome.name == "Грог Железный Кулак"
    report = outcome.report
    assert report is not None and report.import_allowed
    codes = {issue.code for issue in report.issues}
    # Живая форма экспорта: устаревшие каналы бонусов и служебные ключи —
    # предупреждения, не блок (spec «Живой экспорт проходит с предупреждениями»).
    assert codes == {CODE_CHAR_DEPRECATED_BONUSES, CODE_CHAR_SERVICE_KEYS}

    row = await uow.session.get(CharacterModel, outcome.character_id)
    assert row is not None
    assert row.name == "Грог Железный Кулак"
    assert row.image_id is not None  # PNG-аватар фикстуры прошёл QImageReader

    ext = await _ext_row(uow.session, outcome.character_id)
    assert ext.raw_document == content  # снимок побайтово равен файлу
    assert ext.level == 3
    # Подключённые записи: живая пара + живое имя индекса; отсутствующие —
    # снимок имени из файла с пустым источником.
    assert (ext.race_source_key, ext.race_ref_id, ext.race_snapshot_name) == (
        "srd",
        "dwarf",
        "Дварф набора",
    )
    assert (ext.subrace_source_key, ext.subrace_ref_id, ext.subrace_snapshot_name) == (
        "",
        "mountain-dwarf",
        "Горный дварф",
    )
    assert (ext.class_source_key, ext.class_ref_id, ext.class_snapshot_name) == (
        "srd",
        "fighter",
        "Воин набора",
    )
    assert (ext.subclass_source_key, ext.subclass_ref_id, ext.subclass_snapshot_name) == (
        "",
        "champion",
        "Чемпион",
    )
    assert (ext.background_source_key, ext.background_ref_id, ext.background_snapshot_name) == (
        "srd",
        "soldier",
        "Солдат набора",
    )

    blocks = decode_text_blocks(ext.text_blocks)
    # dd-card-redesign task 6.1: six whole values, boolean saves and
    # proficiencies FIT the intake — they arrive as structured fields, not
    # as blocks («значения стоят в структурированных полях карточки, а не
    # только текстом»).
    mechanics = mechanics_from_row(ext)
    assert mechanics.scores == {
        "strength": 17,
        "dexterity": 12,
        "constitution": 15,
        "intelligence": 10,
        "wisdom": 11,
        "charisma": 8,
    }
    assert mechanics.manual_saving_throws == frozenset({"strength", "constitution"})
    assert mechanics.skill_proficiencies == frozenset({"athletics", "perception"})
    assert "Характеристики" not in blocks and "Спасброски" not in blocks
    assert "Навыки" not in blocks
    # What did not fit still prints readable (spec « STRUCTURE читается без
    # LSS»): coins and the converted formatted-editor block included.
    assert blocks["Монеты"] == "gp: 45\nsp: 12\ncp: 7"
    # Форматный документ блока «Черты» сконвертирован, формулы — нотацией.
    assert "Атаки в ближнем бою идут с бонусом [STR] + [PROF]." in blocks["Черты"]
    assert "- Стойкость дварфов" in blocks["Черты"]
    # Готовый текст блока «Заметки» доехал как есть.
    assert blocks["Заметки"] == (
        "Зимой уходит в горы Ордейрина, весной возвращается с караваном."
    )
    # data-URI аватара — картинка, а не текст: блока «Аватар» нет.
    assert BLOCK_AVATAR not in blocks


# ── 5.1: character-import-updated.json (перезапись, id листа цел) ───────────


async def test_updated_fixture_overwrites_fields_snapshot_and_keeps_sheet_id(
    uow, tmp_path
):
    initial = _read(CHARACTER_INITIAL)
    updated = _read(CHARACTER_UPDATED)
    assert initial != updated  # самодостаточность фикстур: второй файл иной

    service = await _make_service(uow, tmp_path)
    created = await service.import_character(initial)
    assert created.status is CharacterImportStatus.CREATED
    character_id = created.character_id
    first_image_id = (await uow.session.get(CharacterModel, character_id)).image_id

    # Живой порядок: после импорта мастер вписал id листа LSS в таб (импорт
    # его не выводит и вывести не может — spec «экспорт LSS не содержит
    # идентификатора»).
    ext = await _ext_row(uow.session, character_id)
    ext.lss_sheet_id = SHEET_ID
    await uow.session.commit()

    unconfirmed = await service.import_character(updated, character_id=character_id)
    assert unconfirmed.status is CharacterImportStatus.NEEDS_CONFIRMATION
    untouched = await _ext_row(uow.session, character_id)
    assert untouched.raw_document == initial  # без «да» — ни поля, ни снимок

    outcome = await service.import_character(
        updated, character_id=character_id, confirmed=True
    )
    assert outcome.status is CharacterImportStatus.OVERWRITTEN
    assert outcome.name == "Грог Железный Топор"

    row = await uow.session.get(CharacterModel, character_id)
    assert row is not None and row.name == "Грог Железный Топор"
    assert row.image_id is not None and row.image_id != first_image_id  # новый аватар

    ext = await _ext_row(uow.session, character_id)
    assert ext.raw_document == updated  # снимок заменён новым файлом
    assert ext.level == 5
    # Привязки следуют второму файлу: сменились подкласс (снимок из файла) и
    # предыстория (живая запись), целые пары остались целыми.
    assert (ext.subclass_source_key, ext.subclass_ref_id, ext.subclass_snapshot_name) == (
        "",
        "battle-master",
        "Мастер боя",
    )
    assert (ext.background_source_key, ext.background_ref_id, ext.background_snapshot_name) == (
        "srd",
        "outlander",
        "Чужеземец набора",
    )
    assert ext.race_ref_id == "dwarf" and ext.race_source_key == "srd"
    # Id листа LSS импортом не выводится — он обязан остаться на месте.
    assert ext.lss_sheet_id == SHEET_ID

    blocks = decode_text_blocks(ext.text_blocks)
    assert blocks["Заметки"] == (
        "После боя при Ордрейрине взял топор вождя; "
        "гильдия наёмников зовёт его Железным Топором."
    )
    assert "Боевое преимущество: урон добивания растёт с [DEX] + [PROF]." in blocks["Черты"]
    # Второй файл тоже ложится структурой: шесть значений, спасброски и
    # владения — поля карточки, блоков этих семейств нет.
    mechanics = mechanics_from_row(ext)
    assert mechanics.scores is not None and mechanics.scores["strength"] == 18
    assert mechanics.manual_saving_throws == frozenset(
        {"strength", "dexterity", "constitution"}
    )
    assert mechanics.skill_proficiencies == frozenset(
        {"athletics", "intimidation", "perception"}
    )
    assert "Характеристики" not in blocks and "Спасброски" not in blocks
    assert "Навыки" not in blocks


# ── 5.2: grimoire-foundry-sample.json ───────────────────────────────────────


def _grimoire_service(tmp_path) -> GrimoireImportService:
    return GrimoireImportService(GrimoireStorage(tmp_path / "grimoires"))


def test_grimoire_sample_fixture_is_accepted_with_the_expected_report(tmp_path):
    content = _read(GRIMOIRE_SAMPLE)
    service = _grimoire_service(tmp_path)

    outcome = service.import_grimoire(content)

    assert outcome.status is GrimoireImportStatus.STORED
    assert outcome.grimoire_id == "qa-sample-grimoire"  # id самого файла
    assert outcome.title == "Гримуар QA-образца"
    assert outcome.spell_count == 3
    assert not outcome.replaced
    assert outcome.report is not None and outcome.report.import_allowed
    assert outcome.report.issues == ()  # ожидаемый отчёт: чистый
    shelf = service._storage.document_path("qa-sample-grimoire")
    assert shelf.read_text(encoding="utf-8") == content
    # Слаги — ровно те, что ждёт словарь валидатора (флаг LSS каждого предмета).
    parse = parse_grimoire(content)
    assert tuple(spell.slug for spell in parse.spells) == (
        "ember-spark",
        "ash-veil",
        "whispering-snare",
    )


def test_grimoire_sample_fixture_reimport_walks_the_replacement_branch(tmp_path):
    """Тот же файл второй раз — ветка подтверждения замены (ожидание живого
    прогона: тексты подтверждения закреплены пином test_dd_fixed_texts)."""
    content = _read(GRIMOIRE_SAMPLE)
    service = _grimoire_service(tmp_path)
    assert service.import_grimoire(content).status is GrimoireImportStatus.STORED

    again = service.import_grimoire(content)
    assert again.status is GrimoireImportStatus.NEEDS_CONFIRMATION

    confirmed = service.import_grimoire(content, confirmed=True)
    assert confirmed.status is GrimoireImportStatus.STORED
    assert confirmed.replaced


def test_character_fixtures_are_standalone_bundle_documents():
    """Самодостаточность для живого выбора через файловый диалог: конверт
    читается как JSON-объект с гейтами формата, data — JSON-строка."""
    for path in (CHARACTER_INITIAL, CHARACTER_UPDATED, CHARACTER_FULL):
        envelope = json.loads(_read(path))
        assert envelope["jsonType"] == "character"
        assert envelope["version"] == "2"
        assert isinstance(envelope["data"], str)
        document = json.loads(envelope["data"])
        assert document["name"]
        assert document["info"]["charClass"]["id"]


# ── dd-card-redesign 6.1: character-import-full.json (все разделы) ───────────


async def test_full_fixture_lays_every_mechanics_family_structured(
    uow, tmp_path
):
    """Фикстура «всё сразу»: каждое семейство механик ложится полем карточки,
    его читаемый блок не рисуется, не-механические разделы печатаются как
    прежде, неизвестный раздел приходит под исходным именем, сырой файл
    цел побайтово (spec «Раскладывание полное», «Механики легли структурой»)."""
    content = _read(CHARACTER_FULL)
    service = await _make_service(uow, tmp_path)

    outcome = await service.import_character(content)
    assert outcome.status is CharacterImportStatus.CREATED
    assert outcome.name == "Грог Полного Профиля"
    codes = {issue.code for issue in outcome.report.issues}
    assert codes == {CODE_CHAR_DEPRECATED_BONUSES, CODE_CHAR_SERVICE_KEYS}

    ext = await _ext_row(uow.session, outcome.character_id)
    assert ext.raw_document == content  # побайтово — источник правды цел
    assert ext.level == 5

    mechanics = mechanics_from_row(ext)
    assert mechanics.scores == {
        "strength": 18,
        "dexterity": 14,
        "constitution": 16,
        "intelligence": 10,
        "wisdom": 12,
        "charisma": 8,
    }
    assert mechanics.manual_saving_throws == frozenset({"strength", "constitution"})
    assert mechanics.skill_proficiencies == frozenset(
        {"athletics", "perception", "survival"}
    )
    assert mechanics.speed == 25
    assert mechanics.alignment == "хаотично-добрый"
    assert mechanics.spell_slots == {1: 4, 2: 3}

    links = await DdCharacterRepository(uow.session).list_feat_links(
        outcome.character_id
    )
    assert [(lnk.source_key, lnk.ref_id, lnk.snapshot_name) for lnk in links] == [
        ("srd", "alert", "Наблюдательность набора"),  # живая запись — живое имя
        ("", "lucky", "Везунчик"),  # записи нет — снимок из файла, Д7
    ]

    blocks = decode_text_blocks(ext.text_blocks)
    for fitted in (
        "Характеристики",
        "Спасброски",
        "Навыки",
        "Ячейки заклинаний",
        "Скорость",
        "Мировоззрение",
    ):
        assert fitted not in blocks  # легшее структурой не дублируется текстом
    assert blocks["Монеты"] == "gp: 120\nsp: 3"
    assert "Атаки в ближнем бою идут с бонусом [STR] + [PROF]." in blocks["Черты"]
    # Поля «Личности» — обычные именованные блоки, доехали как есть.
    assert blocks["Внешность"] == "Плетёная борода с медными кольцами, шрам через бровь."
    assert blocks["Предыстория персонажа"] == (
        "Служил в городском ополчении, ушёл в вольные наёмники."
    )
    # Неизвестный раздел — блок с исходным именем (spec про молчание).
    assert blocks["hobby"] == "Режет фигурки из мыльного камня."
    # Слаг-список раздела spells — не дверь импорта: привязок не выросло.
    assert await DdCharacterRepository(uow.session).list_spell_links(
        outcome.character_id
    ) == []
