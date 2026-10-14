"""Канал персонажа (add-dnd-lss-generation, tasks 6.1–6.3; design Д2/Д5;
spec dnd-generation «Генерация персонажа с нуля», «Дозаполнение персонажа»,
«Числовая механика остаётся LSS»).

Qt-free реализация протокола :class:`GenerationChannel
<app.dd.application.generation_loop.GenerationChannel>` поверх механизма
круга группы 1 (поза каналов датасетов и заклинаний): модель пишет ровно
содержательную часть ``data`` (имя, уровень, привязки, текстовые блоки,
слаги заклинаний), а приложение достраивает конверт ``character.json``
(``jsonType``/``version``/``data`` — JSON-строка, та же живая форма, что у
сборщика экспорта). Из ответа модели в документ не попадает ничего, кроме
содержательной части:

- **числовые механические ключи отбрасываются до валидации** — содержательная
  часть собирается whitelist'ом (spec: ``stats``/``skills``/``bonuses``/
  ``bonusesSkills``/``bonusesStats``/``weaponsList``/``resources``/``coins``
  не пишет ни один режим; ``:func:`app.dd.domain.character_render`` показывает,
  что это вотчина LSS-листа), вместе с ними отсекается и числовой счётчик
  ``spells.slots`` (директива скелета промпта); в разделе ``spells`` живёт
  только слаг-список ``list``;
- **пре-выборы соблюдает приложение** — отмеченные мастером уровень/вид/класс
  вписываются в документ поверх ответа модели (spec scenario «Пре-выбор класса
  соблюдён»), неразрешимый выбор — обычная ошибка разрешения ниже;
- **неразрешимый slug — ошибка круга** (ERROR, не предупреждение): словарь
  подключённых источников — единственная область ссылок (spec «Детерминированные
  примеры и словарь идентификаторов»); пустой ``id`` — законный честный ответ
  «имя помним, ссылку подтвердить нечем» (так приходят живые файлы LSS и
  ответы модели; сборщик экспорта такую форму с fix-dnd-followups не печатает),
  он не проверяется.

Дозаполнение (design Д5): вход — текущий документ из сборщика
(:class:`CharacterDocumentBuilder`), модель дозаполняет пустые содержательные
поля, а **защита непустого живёт на уровне склейки**: непустые значения
текущего документа (имя, уровень, привязки, блоки, слаг-список) не
перезаписываются никогда, чем бы ни ответил модель. Гейт «пусто дозаполнять —
не запускается» закрыт на уровне контекста: если пустых полей нет, конструктор
отказывает русским ``ValueError`` до всякого запроса.

Принятие — существующая дверь :class:`CharacterImportService` (design Д5:
с нуля — создание с сохранённым сырым файлом и D&D-табом; дозаполнение —
подтверждённая перезапись тем же документом, карточка обновляется, сырой
файл заменяется). Вторых дверей здесь нет.

Контекст канал носит с собой с конструктора: протокол круга доносит его до
``build_prompt``/``validate``, но не до ``parse``, а склейка дозаполнения
происходит именно там.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.dd.application.character_document_builder import SPELLS_LIST_KEY
from app.dd.application.character_validator_service import CharacterValidatorService
from app.dd.application.generation_loop import Prompt, extract_json_document
from app.dd.application.prompt_composer import PromptComposer, SlugVocabularyEntry
from app.dd.domain.character import INFO_KEYS, LEVEL_MAX, LEVEL_MIN, LINK_SLOTS, validate_level
from app.dd.domain.character_checks import parse_data
from app.dd.domain.character_editor import editor_doc_to_text
from app.dd.domain.validation_report import CheckIssue, Severity, ValidationReport
from app.dd.infrastructure.lss_schemas import CHARACTER_FORMAT_VERSION, CHARACTER_JSON_TYPE

#: Механические ключи документа, которые генерация не пишет никогда
#: (spec «Числовая механика остаётся LSS», дельта dd-card-redesign: к
#: числовым восьми добавлены ``speed``/``alignment``/``feats`` — механики
#: карточки, не содержательная часть генерации): содержательная часть
#: собирается whitelist'ом из :data:`_CONTENT_DATA`-полей, поэтому ни один
#: из этих ключей не доходит до валидатора — их добирает карточка/построитель.
MECHANIC_KEYS: tuple[str, ...] = (
    "stats",
    "skills",
    "bonuses",
    "bonusesSkills",
    "bonusesStats",
    "weaponsList",
    "resources",
    "coins",
    "speed",
    "alignment",
    "feats",
)

#: Коды разрешения ссылок канала (стабильный машинный контракт, поза кодов
#: Д8): ссылка вне словаря подключённых источников — ошибка круга.
CODE_CHAR_REF_UNRESOLVED = "CHAR_REF_UNRESOLVED"
CODE_CHAR_SPELL_SLUG_UNRESOLVED = "CHAR_SPELL_SLUG_UNRESOLVED"

#: Русские подписи содержательных полей для промпта и гейта дозаполнения.
#: Подписи вкладок таба живут в presentation (RECORD_TYPES); здесь — captions
#: слоя генерации (ядро модуля не заглядывает в свой UI, guard изоляции).
CAPTION_NAME = "Имя"
CAPTION_LEVEL = "Уровень"
CAPTION_SPELLS = "Заклинания"
SLOT_CAPTIONS: dict[str, str] = {
    "race": "Вид",
    "subrace": "Подвид",
    "class": "Класс",
    "subclass": "Подкласс",
    "background": "Предыстория",
}

#: Русский отказ гейта «пусто дозаполнять» (spec scenario «Пусто дозаполнять»:
#: генерация не запускается с пояснением). fix-dnd-followups (design Д4): the
#: norm fixed the whole sentence — the constant is the full capitalized text,
#: verbatim-pinned in ``tests/dd/test_dd_fixed_texts.py``.
TOP_UP_NOTHING_REFUSAL = (
    "Дозаполнять нечего: все содержательные поля карточки уже заполнены"
)

#: Строка формы заклинаний — обеим режимам (слаг-список живёт под тем же
#: ключом, что пишет сборщик: одна правда SPELLS_LIST_KEY).
_SPELLS_SHAPE_LINE = (
    'Заклинания — списком слагов: "spells": {"list": ["slug-1", "slug-2"]}; '
    "бери слаги только из словаря идентификаторов."
)

#: Обязанность имени (spec: «Обязательным остаётся только имя»).
_NAME_LINE = (
    "Имя персонажа обязательно. Все идентификаторы — только из словаря "
    "подключённых источников; нет нужного — не выдумывай, а не пиши привязку."
)


def _is_int(value: object) -> bool:
    """Целое без булева притворства (та же норма, что у импорта и сборщика)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _block_text(value: object) -> str:
    """Текст значения текстового блока: строка как есть, узлы редактора —
    через штатный конвертер (пустой блок — пустой текст)."""
    if isinstance(value, str):
        return value
    return editor_doc_to_text(value)[0]


def _document_spell_list(data: dict[str, Any]) -> list[str]:
    """Слаг-список заклинаний документа (терпимо к обеим формам раздела)."""
    raw = data.get("spells")
    if isinstance(raw, dict):
        raw = raw.get(SPELLS_LIST_KEY)
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, str) and item.strip()]


# ── содержательная часть ответа модели (whitelist = гарантия spec) ────────────


def _content_info(raw: object) -> dict[str, Any]:
    """Раздел ``info`` содержательной части: только пять известных слотов,
    только строковые id/name; строка вместо словаря — терпимость к слаг-
    дрейфу (поза канала заклинаний); пустые значения ключ не получают."""
    if not isinstance(raw, dict):
        return {}
    info: dict[str, Any] = {}
    for slot, _section, _type_key in LINK_SLOTS:
        ref: object = raw.get(INFO_KEYS[slot])
        if isinstance(ref, str) and ref.strip():
            ref = {"id": ref.strip()}
        if not isinstance(ref, dict):
            continue
        value: dict[str, str] = {}
        ref_id = ref.get("id")
        ref_name = ref.get("name")
        name_val = ref_name if isinstance(ref_name, str) and ref_name.strip() else None
        # пустой id с именем — законный неразрешимый снимок (схема требует
        # сам ключ id); совсем пустой ref ключа не получает
        if isinstance(ref_id, str) and (ref_id.strip() or name_val):
            value["id"] = ref_id
        if name_val:
            value["name"] = name_val
        if value:
            info[INFO_KEYS[slot]] = value
    return info


def _content_blocks(raw: object) -> dict[str, Any]:
    """Раздел ``blocks``: только именованные непустые значения; форма
    (строка или узлы редактора) проходит как есть — обе легальны схемой."""
    if not isinstance(raw, dict):
        return {}
    blocks: dict[str, Any] = {}
    for name, value in raw.items():
        # имя ключа после json.loads всегда строка — пустой имя не блок
        if not name.strip():
            continue
        if not isinstance(value, (str, dict, list)):
            continue
        if not _block_text(value).strip():
            continue
        blocks[name.strip()] = value
    return blocks


def _content_spell_slugs(raw: object) -> list[str]:
    """Слаг-список из ответа: раздел с ключом ``list`` или голый массив;
    непустые строки, порядок и уникальность — как в сборщике."""
    if isinstance(raw, list):
        candidates: list = raw
    elif isinstance(raw, dict):
        listed = raw.get(SPELLS_LIST_KEY)
        candidates = listed if isinstance(listed, list) else []
    else:
        candidates = []
    slugs: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        if not isinstance(item, str) or not item.strip():
            continue
        slug = item.strip()
        if slug not in seen:
            seen.add(slug)
            slugs.append(slug)
    return slugs


def _content_data(raw: object) -> dict[str, Any]:
    """Ответ модели → содержательная часть ``data``. Whitelist полей и есть
    гарантия «числа — LSS»: :data:`MECHANIC_KEYS` и служебные ключи живого
    экспорта в результат попасть не могут структурно, как и числовой счётчик
    ``spells.slots`` (из раздела заклинаний живёт только ``list``)."""
    if not isinstance(raw, dict):
        raise ValueError(
            "ответ модели не является JSON-объектом содержательной части — "
            "выдай только объект с полями name/level/info/blocks/spells"
        )
    data: dict[str, Any] = {}
    name = raw.get("name")
    if isinstance(name, str) and name.strip():
        data["name"] = name.strip()
    level = raw.get("level")
    if _is_int(level) and LEVEL_MIN <= level <= LEVEL_MAX:
        data["level"] = level
    avatar = raw.get("avatar")
    if isinstance(avatar, str) and avatar.strip():
        data["avatar"] = avatar
    info = _content_info(raw.get("info"))
    if info:
        data["info"] = info
    blocks = _content_blocks(raw.get("blocks"))
    if blocks:
        data["blocks"] = blocks
    slugs = _content_spell_slugs(raw.get("spells"))
    if slugs:
        data["spells"] = {SPELLS_LIST_KEY: slugs}
    return data


def _apply_preselects(data: dict[str, Any], context: "CharacterContext") -> None:
    """Пре-выборы мастера сильнее ответа модели (spec scenario «Пре-выбор
    класса соблюдён»): уровень и привязки вида/класса вписываются в
    содержательную часть поверх того, что написала модель."""
    if context.level is not None:
        data["level"] = context.level
    for slot, choice in (("race", context.race), ("class", context.char_class)):
        if choice is None:
            continue
        info = data.setdefault("info", {})
        info[INFO_KEYS[slot]] = {"id": choice.slug, "name": choice.name or choice.slug}


# ── дозаполнение: текущий документ, склейка с защитой непустого, гейт ────────


def parse_top_up_current(current_document: str) -> dict[str, Any]:
    """Текущий документ (выход сборщика) → разобранный ``data``; мусор или
    разрушенная половина ``data`` — русский ``ValueError`` до круга."""
    try:
        envelope: Any = json.loads(current_document)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"текущий документ персонажа не является корректным JSON: {error.msg}"
        ) from error
    if not isinstance(envelope, dict):
        raise ValueError("текущий документ персонажа обязан быть JSON-объектом")
    data, issue = parse_data(envelope)
    if issue is not None:
        raise ValueError(issue.message)
    assert isinstance(data, dict)  # parse_data обещает dict при issue=None
    return data


def _ref_is_filled(value: object) -> bool:
    """Привязка считается заполненной, если в ней есть хоть строка-смысл:
    неразрешимый снимок ``{"id": "", "name": "…"}`` заполнен (источник снят —
    карточка отвечает снимком, дозаполнять нечего)."""
    return (
        isinstance(value, dict)
        and any(
            isinstance(value.get(part), str) and value[part].strip()
            for part in ("id", "name")
        )
    )


def _missing_from_data(data: dict[str, Any]) -> tuple[str, ...]:
    """Пустые содержательные поля документа — список дозаполнения и основа
    гейта (текстовые блоки — владение мастера: их набор не конечен, пустым
    считается и блок с пустым текстом, но его отсутствие полем не является)."""
    missing: list[str] = []
    if not str(data.get("name") or "").strip():
        missing.append(CAPTION_NAME)
    if not _is_int(data.get("level")):
        missing.append(CAPTION_LEVEL)
    raw_info = data.get("info")
    info = raw_info if isinstance(raw_info, dict) else {}
    for slot, _section, _type_key in LINK_SLOTS:
        if not _ref_is_filled(info.get(INFO_KEYS[slot])):
            missing.append(SLOT_CAPTIONS[slot])
    if not _document_spell_list(data):
        missing.append(CAPTION_SPELLS)
    return tuple(missing)


def top_up_missing_fields(current_document: str) -> tuple[str, ...]:
    """Гейт и промпт дозаполнения одним списком: пустые содержательные поля
    текущего документа (пустой кортеж — дозаполнять нечего, лист гасит
    кнопку)."""
    return _missing_from_data(parse_top_up_current(current_document))


def _merge_fill(current: dict[str, Any], addition: dict[str, Any]) -> dict[str, Any]:
    """Склейка дозаполнения (design Д5): заполненное мастером защищено на
    уровне склейки — непустые значения текущего документа не перезаписываются
    ничем; добавляется ровно то, чего не было (или было пустым блоком)."""
    merged = dict(current)
    if "name" in addition and not str(merged.get("name") or "").strip():
        merged["name"] = addition["name"]
    if "level" in addition and not _is_int(merged.get("level")):
        merged["level"] = addition["level"]
    if "avatar" in addition and not str(merged.get("avatar") or "").strip():
        merged["avatar"] = addition["avatar"]
    if "info" in addition:
        raw_info = merged.get("info")
        info = dict(raw_info) if isinstance(raw_info, dict) else {}
        for key, value in addition["info"].items():
            info.setdefault(key, value)
        if info:
            merged["info"] = info
    if "blocks" in addition:
        raw_blocks = merged.get("blocks")
        blocks = dict(raw_blocks) if isinstance(raw_blocks, dict) else {}
        for name, value in addition["blocks"].items():
            if name in blocks and _block_text(blocks[name]).strip():
                continue  # непустой блок мастера цел
            blocks[name] = value
        if blocks:
            merged["blocks"] = blocks
    if "spells" in addition and not _document_spell_list(merged):
        merged["spells"] = addition["spells"]
    return merged


# ── контекст и канал ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CharacterContext:
    """Входы одной генерации персонажа, общие для всех методов канала.

    С нуля: ``concept`` (концепция мастера) плюс опциональные пре-выборы
    (``level``/``race``/``char_class`` — пары slug+снимок из словаря
    подключённых источников). Дозаполнение: ``current_document`` — текст
    текущего документа из сборщика; конструктор отказывает русским
    ``ValueError``, когда пустых полей нет (spec scenario «Пусто дозаполнять»
    — генерация не запускается).

    ``world``/``concept``/``vocabulary`` уходят в промпт, ``record_ids``/
    ``spell_slugs`` — разрешению ссылок в валидаторе (единственная область
    ссылок — словарь подключённых источников); канал их не интерпретирует."""

    world: str = ""
    concept: str = ""
    level: int | None = None
    race: SlugVocabularyEntry | None = None
    char_class: SlugVocabularyEntry | None = None
    vocabulary: tuple[SlugVocabularyEntry, ...] = ()
    record_ids: tuple[str, ...] = ()
    spell_slugs: tuple[str, ...] | None = None
    current_document: str | None = None

    @property
    def is_top_up(self) -> bool:
        return self.current_document is not None

    def __post_init__(self) -> None:
        if self.level is not None:
            validate_level(self.level)
        if self.is_top_up and not top_up_missing_fields(self.current_document or ""):
            raise ValueError(TOP_UP_NOTHING_REFUSAL)


class CharacterChannel:
    """Один канал = один персонаж = один документ ``character.json``.

    Канал создаётся на контекст конкретной генерации (с нуля или
    дозаполнение — решает ``current_document``): протокол круга доносит
    контекст только до ``build_prompt``/``validate``, а склейка
    дозаполнения с защитой непустого происходит в ``parse``. Аргумент
    ``context`` у методов — форма протокола: раннер проводит один и тот же
    контекст, с которым канал и создан."""

    def __init__(
        self,
        context: CharacterContext,
        *,
        composer: PromptComposer | None = None,
        validator: CharacterValidatorService | None = None,
    ) -> None:
        self._context = context
        self._composer = composer if composer is not None else PromptComposer()
        self._validator = (
            validator if validator is not None else CharacterValidatorService()
        )

    def build_prompt(self, context: CharacterContext) -> Prompt:
        """Слои Д3 (скелет + фрагменты персонажа + мир + идея + словарь)
        плюс канал-специфичные входы (пре-выборы / текущий документ и список
        пустых полей — замечание группы 2: их канал дописывает сам)."""
        system, user = self._composer.compose_character(
            self._context.world, self._context.concept, self._context.vocabulary
        )
        lines = [_SPELLS_SHAPE_LINE]
        if self._context.is_top_up:
            current = parse_top_up_current(self._context.current_document or "")
            missing = ", ".join(_missing_from_data(current))
            lines.append(
                "Текущий документ персонажа (заполненные поля мастера трогать "
                "нельзя — не перепечатывай их):\n"
                + json.dumps(current, ensure_ascii=False, indent=2)
            )
            lines.append(
                f"Дозаполни только пустые поля: {missing}. Верни объект "
                "содержательной части ровно с этими полями, без заполненных."
            )
        else:
            preselects: list[str] = []
            if self._context.level is not None:
                preselects.append(f"- Уровень: {self._context.level}")
            for caption, choice in (
                (SLOT_CAPTIONS["race"], self._context.race),
                (SLOT_CAPTIONS["class"], self._context.char_class),
            ):
                if choice is None:
                    continue
                preselects.append(
                    f'- {caption}: {choice.slug} («{choice.name}») — '
                    f'выбери именно этот id'
                )
            if preselects:
                lines.append(
                    "Пре-выборы мастера, обязательные к соблюдению:\n"
                    + "\n".join(preselects)
                )
            lines.append(_NAME_LINE)
        return system, "\n\n".join([user, *lines])

    def parse(self, answer: str) -> str:
        """Содержательная часть ответа → текст документа ``character.json``.

        Терпимость одна и та же, что у остальных каналов:
        ``extract_json_document`` прощает fence и обрамляющий текст. С нуля —
        пре-выборы вписываются поверх ответа; дозаполнение — склейка с
        текущим документом, где непустое защищено. Служебные поля конверта и
        числовые механики — только правила приложения."""
        payload: Any = json.loads(extract_json_document(answer))
        addition = _content_data(payload)
        if self._context.is_top_up:
            data = _merge_fill(
                parse_top_up_current(self._context.current_document or ""), addition
            )
        else:
            data = addition
            _apply_preselects(data, self._context)
        return json.dumps(
            {
                "jsonType": CHARACTER_JSON_TYPE,
                "version": CHARACTER_FORMAT_VERSION,
                # живой экспорт носит data JSON-строкой (гейт CHAR_DATA разбирает её)
                "data": json.dumps(data, ensure_ascii=False),
            },
            ensure_ascii=False,
        )

    def validate(
        self, document: str, context: CharacterContext | None = None
    ) -> ValidationReport:
        """Существующий валидатор персонажа плюс разрешение ссылок канала:
        неразрешимый slug привязки или заклинания — ошибка круга (ERROR),
        она же уходит в обратную связь перегенерации."""
        ctx = context if isinstance(context, CharacterContext) else self._context
        report, data = self._validator.validate(document)
        if data is None:
            return report
        return ValidationReport.of(
            [*report.issues, *_resolution_issues(data, ctx)]
        )


def _resolution_issues(data: dict[str, Any], context: CharacterContext) -> list[CheckIssue]:
    """Разрешение ссылок по словарю подключённых источников: пустой ``id`` —
    законный неразрешимый снимок, не проверяется; ``spell_slugs=None`` —
    проверка слагов молчит (поза tolerance LSS, как у канала датасетов)."""
    issues: list[CheckIssue] = []
    corpus = frozenset(context.record_ids)
    raw_info = data.get("info")
    info = raw_info if isinstance(raw_info, dict) else {}
    for slot, _section, _type_key in LINK_SLOTS:
        key = INFO_KEYS[slot]
        ref = info.get(key)
        if not isinstance(ref, dict):
            continue
        ref_id = ref.get("id")
        if isinstance(ref_id, str) and ref_id.strip() and ref_id not in corpus:
            issues.append(
                CheckIssue(
                    code=CODE_CHAR_REF_UNRESOLVED,
                    severity=Severity.ERROR,
                    path=f"data.info.{key}.id",
                    message=(
                        f"идентификатор {ref_id!r} нет в словаре подключённых "
                        "источников: возьми id из словаря или убери привязку"
                    ),
                )
            )
    if context.spell_slugs is None:
        return issues
    slugs = frozenset(context.spell_slugs)
    raw_spells = data.get("spells")
    listed = raw_spells.get(SPELLS_LIST_KEY) if isinstance(raw_spells, dict) else None
    if isinstance(listed, list):
        for index, slug in enumerate(listed):
            if isinstance(slug, str) and slug not in slugs:
                issues.append(
                    CheckIssue(
                        code=CODE_CHAR_SPELL_SLUG_UNRESOLVED,
                        severity=Severity.ERROR,
                        path=f"data.spells.list[{index}]",
                        message=(
                            f"слаг заклинания {slug!r} нет среди слагов "
                            "подключённых наборов"
                        ),
                    )
                )
    return issues
