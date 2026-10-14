"""Сборщик «карточка → character.json» (add-dnd-lss-generation, task 5.1;
design Д4; spec dnd-character-export «Сборка документа из текущего состояния
карточки»).

Qt-free ядро экспорта: текущее состояние карточки — имя ядра, лицо модуля
(``DdCharacterExt``: пять привязок, уровень), структурированные механики
(dd-card-redesign task 6.2: шесть значений, разрешение владения спасбросками
по Д8, владения навыками, скорость, мировоззрение, сетка ячеек) и привязки
заклинаний и черт — собирается в конверт формата ``jsonType: "character"``,
``version: "2"`` с ``data`` — JSON-строкой по схеме формата. Собранная форма
проходит
:class:`app.dd.application.character_validator_service.CharacterValidatorService`
без ошибок: форматное обещание spec «Совместимость экспорта с приёмом LSS».

Правила сборки (spec-сценарии):

- **пустые поля не выдумываются** — имя без значения не бывает (схема требует
  непустого), а всё прочее (уровень, привязки, блоки, заклинания и любая
  механика — характеристики, спасброски, навыки, скорость, мировоззрение,
  ячейки, черты) пишется только когда задано; числами-механиками из воздуха
  документ не разрастается;
- **снят датасет — документ не калечится** — привязка чья ссылка не
  подключена (:class:`IndexSnapshot` её не знает), принимает единственную
  форму: в документ она НЕ попадает, ключ раздела ``info`` опускается
  (fix-dnd-followups, design Д5); снимок имени сохраняется в карточке и в
  текстовых частях документа, помеченной привязки ``{"id": "", …}``` сборщик
  не печатает; то же правило для черт: неподключённая черта в ``feats`` не
  попадает, её снимок живёт в карточке;
- **документ следует за карточкой** — имя, привязки, уровень, механики и
  блоки читаются из хранилища в момент сборки, сохранённый сырой файл в
  сборке не участвует (spec scenario «Документ следует за карточкой»);
- владение спасбросками пишется разрешённым по Д8 набором (класс из
  подключённого датасета владеет своими, иначе — ручная роспись мастера):
  ``stats.<stat>.save = true`` ровно у владеемых, у прочих ключ ``save``
  опускается — так же выглядит живой файл;
- текстовые блоки — узлы форматированного редактора (:func:`text_to_editor_doc`,
  общий построитель с каналом персонажа), формулы — латиницей заглавными.

Слой application: чтение — через репозиторий модуля и службы сущностей ядра
(двери composition root), финал транзакции — за ``GameSessionUoW``; сборщик
только читает и пишет файл по указанному мастеру пути.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.dd.domain.character import (
    INFO_KEYS,
    LEVEL_MAX,
    LEVEL_MIN,
    LINK_SLOTS,
    DdFeatLink,
    DdSpellLink,
    ReferenceLink,
)
from app.dd.domain.character_blocks import text_to_editor_doc
from app.dd.domain.character_mechanics import (
    ABILITY_KEYS,
    ABILITY_TO_LSS_STAT,
    SKILL_ABILITIES,
    CharacterMechanics,
    class_record_saving_throws,
    resolve_saving_throw_profs,
)
from app.dd.infrastructure.db.dd_models import decode_text_blocks
from app.dd.infrastructure.lss_schemas import (
    CHARACTER_FORMAT_VERSION,
    CHARACTER_JSON_TYPE,
)
from app.dd.infrastructure.repositories.dd_character_repository import (
    DdCharacterRepository,
    ext_to_domain,
    mechanics_from_row,
)
from app.domain.entity_registry import EntityType
from app.infrastructure.db.uow import GameSessionUoW

if TYPE_CHECKING:
    from app.application.services.entity_service import EntityService
    from app.dd.application.dataset_index_service import DatasetIndexService, IndexSnapshot

#: Ключ раздела заклинаний собранного документа: слаги привязанных заклинаний
#: (spec: «привязки заклинаний слагами»). Схема ``SpellsSection`` закрывает
#: ``slots`` и не запрещает прочего — слаг-список живёт своим ключом.
SPELLS_LIST_KEY = "list"


def _info_value(link: ReferenceLink, snapshot: "IndexSnapshot | None") -> dict[str, str] | None:
    """Одна привязка → значение раздела ``info`` (или ``None`` — писать нечего).

    Подключённая ссылка уходит парой ``id`` + снимок имени. Неразрешимая
    привязка (источник снят) принимает единственную форму — ключ слагового
    раздела просто не пишется (fix-dnd-followups, design Д5; spec
    «Снятый датасет не калечит документ»): снимок имени сохраняется в
    карточке и в текстовых частях документа, второго вида «помеченная
    привязка» ``{"id": "", "name": …}``` сборщик не печатает."""
    if not link.is_set:
        return None
    if not _is_connected(link.source_key, snapshot):
        return None
    value: dict[str, str] = {"id": link.ref_id}
    if link.snapshot_name:
        value["name"] = link.snapshot_name
    return value


def _spell_slugs(spell_links: Sequence[DdSpellLink]) -> list[str]:
    """Слаги привязок в порядке привязки, без повторов (один слаг — одно
    имя в списке; порядок строк таблицы и есть порядок мастера)."""
    slugs: list[str] = []
    seen: set[str] = set()
    for link in spell_links:
        if link.slug and link.slug not in seen:
            seen.add(link.slug)
            slugs.append(link.slug)
    return slugs


def _is_connected(source_key: str, snapshot: "IndexSnapshot | None") -> bool:
    return (
        snapshot is not None and bool(source_key) and source_key in snapshot.ids
    )


def _stats_section(
    mechanics: CharacterMechanics | None, saving_throw_profs: frozenset[str]
) -> dict[str, Any]:
    """Раздел ``stats`` из текущего состояния: значения — где заданы (полный
    набор или ничего — гейт хранилища), ``save: true`` — у владеемых
    спасброском по разрешённому Д8 набору; у прочих ключ опускается, как в
    живом файле. Пустое не выдумывается: ни значений, ни владений — ключа
    ``stats`` в документе нет."""
    scores = mechanics.scores if mechanics is not None else None
    section: dict[str, Any] = {}
    for ability in ABILITY_KEYS:
        entry: dict[str, Any] = {}
        if scores is not None:
            entry["value"] = scores[ability]
        if ability in saving_throw_profs:
            entry["save"] = True
        if entry:
            section[ABILITY_TO_LSS_STAT[ability]] = entry
    return section


def _skills_section(mechanics: CharacterMechanics | None) -> dict[str, Any]:
    """Владения навыками — штатным порядком (документ детерминирован для
    одного состояния); незаданное владение ключа не получает («профилей из
    воздуха нет») — сет-card читает отсутствующий флаг как «не владеет»."""
    if mechanics is None or not mechanics.skill_proficiencies:
        return {}
    return {
        key: {"proficient": True}
        for key in SKILL_ABILITIES
        if key in mechanics.skill_proficiencies
    }


def _slots_entries(mechanics: CharacterMechanics | None) -> list[dict[str, int]]:
    """Сетка ячеек в раздел ``spells.slots``: ``max`` — целое число ячеек
    уровня (то, что хранит сетка), ``value`` — то же (лист носит так
    неизрасходованную половину; живая форма привычнее обоим ключам)."""
    if mechanics is None or not mechanics.spell_slots:
        return []
    return [
        {"level": level, "value": count, "max": count}
        for level, count in sorted(mechanics.spell_slots.items())
    ]


def _feats_section(
    feat_links: Sequence[DdFeatLink], snapshot: "IndexSnapshot | None"
) -> list[dict[str, str]]:
    """Черты — те же правила, что у пяти привязок ``info``: подключённая
    уходит парой ``id`` + снимок имени, неподключённая в документ не
    попадает (снимок сохраняется в карточке, spec «Снятый датасет не
    калечит документ»)."""
    feats: list[dict[str, str]] = []
    for link in feat_links:
        if not link.ref_id or not _is_connected(link.source_key, snapshot):
            continue
        value: dict[str, str] = {"id": link.ref_id}
        if link.snapshot_name:
            value["name"] = link.snapshot_name
        feats.append(value)
    return feats


def build_character_document(
    *,
    name: str,
    level: int | None,
    links: Mapping[str, ReferenceLink],
    blocks: Mapping[str, str],
    spell_links: Sequence[DdSpellLink],
    snapshot: "IndexSnapshot | None",
    mechanics: CharacterMechanics | None = None,
    saving_throw_profs: frozenset[str] = frozenset(),
    feat_links: Sequence[DdFeatLink] = (),
) -> dict[str, Any]:
    """Чистый сборщик: состояние карточки → конверт документа.

    ``name`` — имя ядра (пишется с обрезкой пробелов — так же его читает
    импорт); ``blocks`` — сохранённые текстовые блоки (имя → plain-текст);
    ``snapshot`` — текущий снимок индекса (дверь подключённости источников);
    ``mechanics``/``saving_throw_profs``/``feat_links`` — механики из
    dd-card-redesign task 6.2 (спасброски передаются РАЗРЕШЁННЫМ по Д8
    набором — класс из подключённого датасета владеет своими). Пустые поля
    не пишутся; уровень вне 1…20 (аномалия хранилища старше гейта) — тоже."""
    data: dict[str, Any] = {"name": name.strip()}
    if level is not None and LEVEL_MIN <= level <= LEVEL_MAX:
        data["level"] = level
    info: dict[str, Any] = {}
    for slot, _section, _type_key in LINK_SLOTS:
        value = _info_value(links.get(slot, ReferenceLink("", "", "")), snapshot)
        if value is not None:
            info[INFO_KEYS[slot]] = value
    if info:
        data["info"] = info
    stats = _stats_section(mechanics, saving_throw_profs)
    if stats:
        data["stats"] = stats
    skills = _skills_section(mechanics)
    if skills:
        data["skills"] = skills
    if mechanics is not None and mechanics.speed is not None:
        data["speed"] = mechanics.speed
    if mechanics is not None and mechanics.alignment:
        data["alignment"] = mechanics.alignment
    editor_blocks = {
        block_name: text_to_editor_doc(text)
        for block_name, text in blocks.items()
        if block_name.strip() and text.strip()
    }
    if editor_blocks:
        data["blocks"] = editor_blocks
    spells: dict[str, Any] = {}
    slugs = _spell_slugs(spell_links)
    if slugs:
        spells[SPELLS_LIST_KEY] = slugs
    slots = _slots_entries(mechanics)
    if slots:
        spells["slots"] = slots
    if spells:
        data["spells"] = spells
    feats = _feats_section(feat_links, snapshot)
    if feats:
        data["feats"] = feats
    return {
        "jsonType": CHARACTER_JSON_TYPE,
        "version": CHARACTER_FORMAT_VERSION,
        # живой экспорт носит data JSON-строкой (гейт CHAR_DATA разбирает её)
        "data": json.dumps(data, ensure_ascii=False),
    }


class CharacterDocumentBuilder:
    """Дверь сбора документа: читает карточку по её id и собирает конверт
    (design Д4). Файловая половина — :meth:`export_document`: записать
    собранный текст по указанному мастеру пути; карточку и сырой файл экспорт
    не трогает (spec scenario «Сохранение отменено» — отмена вообще ничего
    не меняет, эта дверь тогда просто не вызывается)."""

    def __init__(
        self,
        *,
        uow: GameSessionUoW,
        entity_services: Callable[[], Mapping[str, "EntityService"]],
        dataset_index: "DatasetIndexService",
    ) -> None:
        self._uow = uow
        self._entity_services = entity_services
        self._index = dataset_index

    async def collect(self, character_id: int) -> dict[str, Any]:
        """Полный снимок карточки → конверт документа (имя ядра + лицо
        модуля + механики + привязки заклинаний и черт + текущая
        подключённость источников). Владение спасбросками пишется
        разрешённым по Д8 набором — тем же чтó рисует карточка: класс из
        подключённого датасета владеет своими, иначе ручная роспись."""
        name = await self._character_name(character_id)
        repo = DdCharacterRepository(self._uow.session)
        row = await repo.get_ext(character_id)
        ext = ext_to_domain(row)
        mechanics = mechanics_from_row(row)
        blocks = decode_text_blocks(row.text_blocks if row is not None else None)
        spell_links = await repo.list_spell_links(character_id)
        feat_links = await repo.list_feat_links(character_id)
        snapshot = await self._index.snapshot()
        saving_throw_profs = resolve_saving_throw_profs(
            class_record_saving_throws(ext, snapshot),
            mechanics.manual_saving_throws,
        )
        return build_character_document(
            name=name,
            level=ext.level,
            links=ext.links,
            blocks=blocks,
            spell_links=spell_links,
            snapshot=snapshot,
            mechanics=mechanics,
            saving_throw_profs=saving_throw_profs,
            feat_links=feat_links,
        )

    async def build(self, character_id: int) -> str:
        """Собранный конверт текстом файла (тот же текст принимает валидатор)."""
        return json.dumps(await self.collect(character_id), ensure_ascii=False)

    async def export_document(self, character_id: int, path: str) -> None:
        """Собрать и записать документ в выбранный мастером файл. Сбой записи
        — обычное исключение: рамка таба показывает русское окно и журнал,
        карточка от сбоя не меняется."""
        Path(path).write_text(await self.build(character_id), encoding="utf-8")

    async def _character_name(self, character_id: int) -> str:
        """Имя — поле ядра: служба персонажей composition root'а, той же
        дверью его читает и импорт."""
        entity_service = self._entity_services().get(EntityType.CHARACTER.value)
        if entity_service is None:
            raise RuntimeError("каталог служб сущностей не знает персонажей")
        row = await entity_service.get_entity(character_id)
        if row is None:
            raise RuntimeError("персонаж для экспорта не найден в игре")
        return str(row.name)
