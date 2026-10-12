"""Сборщик «карточка → character.json» (add-dnd-lss-generation, task 5.1;
design Д4; spec dnd-character-export «Сборка документа из текущего состояния
карточки»).

Qt-free ядро экспорта: текущее состояние карточки — имя ядра, лицо модуля
(``DdCharacterExt``: пять привязок, уровень) и привязки заклинаний — собирается
в конверт формата ``jsonType: "character"``, ``version: "2"`` с ``data`` —
JSON-строкой по схеме формата. Собранная форма проходит
:class:`app.dd.application.character_validator_service.CharacterValidatorService`
без ошибок: форматное обещание spec «Совместимость экспорта с приёмом LSS».

Правила сборки (spec-сценарии):

- **пустые поля не выдумываются** — имя без значения не бывает (схема требует
  непустого), а всё прочее (уровень, привязки, блоки, заклинания) пишется
  только когда задано; числа-механики из воздуха не берутся;
- **снят датасет — документ не калечится** — привязка чья ссылка не
  подключена (:class:`IndexSnapshot` её не знает), уходит в документ как
  неразрешимая: ``{"id": "", "name": снимок}`` — законный по схеме CharacterRef
  честный ответ «имя помним, ссылку подтвердить нечем»; снимок без имени не
  говорит ничего и не пишется;
- **документ следует за карточкой** — имя, привязки, уровень и блоки читаются
  из хранилища в момент сборки, сохранённый сырой файл в сборке не участвует
  (spec scenario «Документ следует за карточкой»);
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
    DdSpellLink,
    ReferenceLink,
)
from app.dd.domain.character_blocks import text_to_editor_doc
from app.dd.infrastructure.db.dd_models import decode_text_blocks
from app.dd.infrastructure.lss_schemas import (
    CHARACTER_FORMAT_VERSION,
    CHARACTER_JSON_TYPE,
)
from app.dd.infrastructure.repositories.dd_character_repository import (
    DdCharacterRepository,
    ext_to_domain,
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

    Подключённая ссылка уходит парой ``id`` + снимок имени; снятый источник
    отвечает неразрешимым ``{"id": "", "name": снимок}`` (spec «Снятый датасет
    не калечит документ»: снимок сохранён, ссылку нечем подтвердить). Снимок
    без имени — при снятом источнике он не несёт знания, и ключ не пишется:
    пустой «id»: "" без имени был бы молчаливым шумом в документе."""
    if not link.is_set:
        return None
    connected = snapshot is not None and bool(link.source_key) and link.source_key in snapshot.ids
    if connected:
        value: dict[str, str] = {"id": link.ref_id}
        if link.snapshot_name:
            value["name"] = link.snapshot_name
        return value
    if not link.snapshot_name:
        return None
    return {"id": "", "name": link.snapshot_name}


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


def build_character_document(
    *,
    name: str,
    level: int | None,
    links: Mapping[str, ReferenceLink],
    blocks: Mapping[str, str],
    spell_links: Sequence[DdSpellLink],
    snapshot: "IndexSnapshot | None",
) -> dict[str, Any]:
    """Чистый сборщик: состояние карточки → конверт документа.

    ``name`` — имя ядра (пишется с обрезкой пробелов — так же его читает
    импорт); ``blocks`` — сохранённые текстовые блоки (имя → plain-текст);
    ``snapshot`` — текущий снимок индекса (дверь подключённости источников).
    Пустые поля не пишутся; уровень вне 1…20 (аномалия хранилища старше
    гейта) — тоже."""
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
    editor_blocks = {
        block_name: text_to_editor_doc(text)
        for block_name, text in blocks.items()
        if block_name.strip() and text.strip()
    }
    if editor_blocks:
        data["blocks"] = editor_blocks
    slugs = _spell_slugs(spell_links)
    if slugs:
        data["spells"] = {SPELLS_LIST_KEY: slugs}
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
        модуля + привязки заклинаний + текущая подключённость источников)."""
        name = await self._character_name(character_id)
        repo = DdCharacterRepository(self._uow.session)
        row = await repo.get_ext(character_id)
        ext = ext_to_domain(row)
        blocks = decode_text_blocks(row.text_blocks if row is not None else None)
        spell_links = await repo.list_spell_links(character_id)
        snapshot = await self._index.snapshot()
        return build_character_document(
            name=name,
            level=ext.level,
            links=ext.links,
            blocks=blocks,
            spell_links=spell_links,
            snapshot=snapshot,
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
