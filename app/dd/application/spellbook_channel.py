"""Канал заклинаний (add-dnd-lss-generation, tasks 4.1–4.2; design Д2/Д6).

Qt-free реализация протокола :class:`GenerationChannel
<app.dd.application.generation_loop.GenerationChannel>` поверх механизма
круга группы 1: модель пишет ровно JSON-массив содержательных частей
заклинаний (скелет промпта это и предписывает: ``name``, ``slug`` и содержимое
в блоке ``system``), а приложение собирает из них файл заклинаний Foundry —
конверты Foundry Item (``type``, ``flags.lss.slug``) и служебные поля живут
по правилам формата и из ответа модели НЕ берутся (поза канала датасетов:
даже если модель протащила ``_id`` или свой ``type``, в файл идут только
содержательные части и значения приложения).

Гейт отчёта (spec «Генерация файла заклинаний») — три класса находок:

- **ошибки — структурный гейт**: те же ошибки, что у импортной проверки
  гримуаров (:func:`app.dd.domain.grimoire.parse_grimoire` — найденный ею
  документ либо принимается импортёром, либо не принимается вовсе); семантика
  поверх сломанной структуры — шум, поэтому при ошибках возвращается ровно
  структурный отчёт;
- **предупреждения — семантика**: пустой текст описания, неизвестные уровень
  (вне ``0…9``) и школа (вне восьми школ скелета промпта);
- **предупреждения — «слаг вне SRD»**: словарь SRD-слагов игры (тот же
  корпус, что читают валидатор датасетов и импортёр гримуаров); список не
  передан — проверка молчит (поза tolerance LSS).

Предупреждения не запускают круг и не блокируют принятие, ошибки блокируют
(spec «Слаг вне SRD принимается осознанно», «Структурная ошибка блокирует
принятие»). Принятие — существующая дверь :class:`GrimoireImportService`
(её доменная проверка и есть гейт; хранилище под порогом не трогается),
новый файл ``GrimoireStorage``-полки; существующие файлы генерация не
изменяет, а повтор того же документа — штатный вопрос двери о замене своей
же полки (design Д6: никаких вторых дверей записи в хранилище).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.dd.application.generation_loop import Prompt, extract_json_document
from app.dd.application.grimoire_import_service import (
    GrimoireImportOutcome,
    GrimoireImportService,
)
from app.dd.application.prompt_composer import PromptComposer, SlugVocabularyEntry
from app.dd.domain.grimoire import (
    html_to_plain_text,
    normalize_spell_slug,
    parse_grimoire,
)
from app.dd.domain.lss_checks import CODE_SPELL_SLUG_NOT_SRD
from app.dd.domain.validation_report import CheckIssue, Severity, ValidationReport

#: Коды семантических предупреждений канала (стабильный машинный контракт,
#: поза кодов Д8): структура — вотчина парсера, семантика — вотчина канала.
CODE_SPELL_TEXT_EMPTY = "SPELL_TEXT_EMPTY"
CODE_SPELL_LEVEL_UNKNOWN = "SPELL_LEVEL_UNKNOWN"
CODE_SPELL_SCHOOL_UNKNOWN = "SPELL_SCHOOL_UNKNOWN"

#: Число заклинаний в файле: поле мастера 1…10, по умолчанию 5 (spec
#: «Генерация файла заклинаний»: состав задаёт мастер; open question дизайна
#: решён в пользу 5 — как у секций датасета).
SPELL_COUNT_MIN = 1
SPELL_COUNT_MAX = 10
SPELL_DEFAULT_COUNT = 5

#: Область известных уровней заклинания (заговоры … девятый круг).
SPELL_LEVEL_MIN = 0
SPELL_LEVEL_MAX = 9

#: Восемь школ — ровно список скелета промпта (skeletons/spellbook.txt);
#: числовое значение школы (наследие Foundry-энумов) семантике неизвестно.
SPELL_SCHOOL_CHOICES: tuple[str, ...] = (
    "abjuration",
    "conjuration",
    "divination",
    "enchantment",
    "evocation",
    "illusion",
    "necromancy",
    "transmutation",
)

#: Содержательные ключи блока ``system`` по скелету промпта — всё, что модель
#: имеет право написать; прочие ключи (служебные или выдуманные) в конверт
#: не попадают.
_SYSTEM_KEYS: tuple[str, ...] = (
    "level",
    "school",
    "time",
    "components",
    "range",
    "duration",
    "concentration",
    "ritual",
    "description",
    "higherLevel",
)

#: Ключи-обёртки списка заклинаний и кандидаты слага — те же формы, что
#: терпит парсер гримуаров (domain Д8), чтобы промпт-дрейф модели не
#: превращался в ошибку круга.
_LIST_KEYS: tuple[str, ...] = ("items", "spells")

#: Подпись нового хоумбрю-гримуара: полка отличается от импортированных
#: файлов мастера (spec: принятие создаёт НОВЫЙ гримуар).
DEFAULT_SPELLBOOK_NAME = "Хоумбрю: Заклинания"

#: Строка числа заклинаний, которую канал добавляет к user-части поверх
#: :class:`PromptComposer` (замечание группы 2: канал-специфичные входы
#: канал дописывает сам).
_COUNT_LINE_TEMPLATE = "Заклинаний в файле: {count} — выдай ровно столько заклинаний."


@dataclass(frozen=True)
class SpellbookContext:
    """Входы одной генерации файла заклинаний, общие для всех методов канала.

    ``world``/``idea``/``vocabulary``/``count`` уходят в промпт,
    ``srd_slugs`` — семантике (словарь SRD-слагов игры); канал их не
    интерпретирует и не помнит.
    """

    world: str = ""
    idea: str = ""
    count: int = SPELL_DEFAULT_COUNT
    vocabulary: tuple[SlugVocabularyEntry, ...] = ()
    srd_slugs: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if not SPELL_COUNT_MIN <= self.count <= SPELL_COUNT_MAX:
            raise ValueError(
                f"число заклинаний в файле — от {SPELL_COUNT_MIN} "
                f"до {SPELL_COUNT_MAX}, получено {self.count!r}"
            )


class SpellbookChannel:
    """Один канал = один файл = один новый хоумбрю-гримуар при принятии.

    Полку документу даёт импортёр: безымянный для хранилища документ
    (массив предметов сам себя не называет) получает адрес по содержимому —
    детерминированный для тех же байт, так что повторный приём того же
    файла — вопрос двери о замене своей полки, а не тихий близнец.
    """

    def __init__(
        self,
        *,
        composer: PromptComposer | None = None,
        name: str = "",
    ) -> None:
        self._composer = composer if composer is not None else PromptComposer()
        self._name = name or DEFAULT_SPELLBOOK_NAME

    def build_prompt(self, context: SpellbookContext) -> Prompt:
        """Слои Д3 (скелет + шаблон заклинания + мир + идея + словарь) плюс
        канал-специфичное число заклинаний поверх пользовательской части."""
        system, user = self._composer.compose_spellbook(
            context.world, context.idea, context.vocabulary
        )
        user = f"{user}\n\n{_COUNT_LINE_TEMPLATE.format(count=context.count)}"
        return system, user

    def parse(self, answer: str) -> str:
        """Массив содержательных частей → файл заклинаний Foundry.

        Терпимость одна и та же, что у остальных каналов:
        ``extract_json_document`` прощает fence и обрамляющий текст; список
        может приехать обёрнутым в ``items``/``spells`` или одним предметом
        (формы, которые принимает парсер гримуаров). Служебные поля конверта
        (``type``, ``flags.lss.slug``) собираются заново по правилам формата:
        из ответа модели в файл не попадает ничего, кроме содержательных
        частей; записи, которыми не может быть заклинание (не-словарь, чужой
        ``type``, имя-пустышка), в файл не пишутся — пустой после фильтра
        файл честно ловит структурная проверка.
        """
        payload: Any = json.loads(extract_json_document(answer))
        entries = _spell_entries(payload)
        if entries is None:
            raise ValueError(
                "ответ модели не содержит JSON-массива заклинаний — "
                "выдай только массив заклинаний"
            )
        items = [
            item
            for item in (_foundry_item(entry) for entry in entries)
            if item is not None
        ]
        document = {"name": self._name, "items": items}
        return json.dumps(document, ensure_ascii=False, indent=2)

    def validate(self, document: str, context: SpellbookContext) -> ValidationReport:
        """Гейт из трёх классов: структурные ошибки импортной проверки —
        ошибки (принятие невозможно, они же уходят в фидбек круга),
        семантика и «слаг вне SRD» — предупреждения с правом осознанного
        принятия."""
        parse = parse_grimoire(document)
        if not parse.report.import_allowed:
            # структурный гейт: поверх сломанной структуры семантика — шум.
            return parse.report
        srd = frozenset(context.srd_slugs) if context.srd_slugs is not None else None
        return ValidationReport.of(
            list(parse.report.issues) + _semantic_issues(document, srd)
        )


def _spell_entries(root: Any) -> list | None:
    """Список записей за корнем документа (те же формы, что терпит
    :func:`app.dd.domain.grimoire.parse_grimoire`), ``None`` — если корень
    не документ заклинаний вовсе."""
    if isinstance(root, list):
        return root
    if isinstance(root, dict):
        for key in _LIST_KEYS:
            candidate = root.get(key)
            if isinstance(candidate, list):
                return candidate
        name = root.get("name")
        if isinstance(name, str) and name.strip():
            return [root]
    return None


def _foundry_item(entry: Any) -> dict | None:
    """Содержательная часть модели → конверт Foundry Item; ``None`` — если
    записью не может быть заклинание (поза фильтрации парсера)."""
    if not isinstance(entry, Mapping):
        return None
    item_type = entry.get("type")
    if isinstance(item_type, str) and item_type.strip().lower() != "spell":
        return None
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    item: dict[str, Any] = {"name": name.strip(), "type": "spell"}
    slug = normalize_spell_slug(_entry_slug_text(entry))
    if slug:
        item["flags"] = {"lss": {"slug": slug}}
    item["system"] = _system_block(entry)
    return item


def _entry_slug_text(entry: Mapping[str, Any]) -> str:
    """Первый текстовый слага-кандидат модели: верхнеуровневый ``slug`` или
    ``flags.lss.slug``/``flags.slug`` (формы, которым доверяет парсер)."""
    direct = entry.get("slug")
    if isinstance(direct, str) and direct.strip():
        return direct
    flags = entry.get("flags")
    if isinstance(flags, Mapping):
        for candidate in (flags.get("lss"), flags):
            if isinstance(candidate, Mapping):
                text = candidate.get("slug")
                if isinstance(text, str) and text.strip():
                    return text
    return ""


def _system_block(entry: Mapping[str, Any]) -> dict:
    """Содержательный блок ``system``: только известные скелету ключи, с
    нормализованным описанием (строка → ``{"value": …}``, мусор ключа
    описания теряется — семантическая проверка честно скажет «пустой
    текст»)."""
    raw = entry.get("system")
    source: Mapping[str, Any] = raw if isinstance(raw, Mapping) else entry
    block = {key: source[key] for key in _SYSTEM_KEYS if key in source}
    description = block.get("description")
    if isinstance(description, str):
        block["description"] = {"value": description}
    elif description is not None and not isinstance(description, Mapping):
        del block["description"]
    return block


def _semantic_issues(document: str, srd: frozenset[str] | None) -> list[CheckIssue]:
    """Семантические предупреждения канала по собранному документу: пустой
    текст, неизвестные уровень/школа, «слаг вне SRD» (словарь не передан —
    проверка молчит). Структура здесь заведомо проходная — вызов идёт
    только после чистого структурного гейта."""
    issues: list[CheckIssue] = []
    entries = _spell_entries(json.loads(document)) or []
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            continue
        system = item.get("system") or {}
        slug = str(((item.get("flags") or {}).get("lss") or {}).get("slug") or "")
        path = f"spells[{slug or item.get('name') or index}]"
        level = system.get("level")
        if (
            isinstance(level, bool)
            or not isinstance(level, int)
            or not SPELL_LEVEL_MIN <= level <= SPELL_LEVEL_MAX
        ):
            issues.append(
                CheckIssue(
                    code=CODE_SPELL_LEVEL_UNKNOWN,
                    severity=Severity.WARNING,
                    path=f"{path}.level",
                    message=(
                        f"уровень заклинания {level!r} неизвестен: "
                        f"бывают уровни от {SPELL_LEVEL_MIN} до {SPELL_LEVEL_MAX}"
                    ),
                )
            )
        school = system.get("school")
        if not (isinstance(school, str) and school in SPELL_SCHOOL_CHOICES):
            issues.append(
                CheckIssue(
                    code=CODE_SPELL_SCHOOL_UNKNOWN,
                    severity=Severity.WARNING,
                    path=f"{path}.school",
                    message=(
                        f"школа заклинания {school!r} неизвестна: бывают "
                        f"{', '.join(SPELL_SCHOOL_CHOICES)}"
                    ),
                )
            )
        description = system.get("description") or {}
        value = description.get("value") if isinstance(description, Mapping) else ""
        text = html_to_plain_text(value) if isinstance(value, str) else ""
        if not text:
            issues.append(
                CheckIssue(
                    code=CODE_SPELL_TEXT_EMPTY,
                    severity=Severity.WARNING,
                    path=path,
                    message="пустой текст описания: заклинанию нечего показать мастеру",
                )
            )
        if srd is not None and slug and slug not in srd:
            issues.append(
                CheckIssue(
                    code=CODE_SPELL_SLUG_NOT_SRD,
                    severity=Severity.WARNING,
                    path=f"{path}.slug",
                    message=(
                        f"слаг заклинания {slug!r} нет в публичных SRD-списках "
                        "заклинаний"
                    ),
                )
            )
    return issues


class SpellbookAcceptanceService:
    """Принятие файла заклинаний: только существующая дверь (design Д6).

    Никакой собственной валидации и своей записи в хранилище: байты уходят
    :class:`GrimoireImportService` — её доменная проверка и есть гейт
    «ошибка блокирует принятие» (под порогом хранилище не трогается), а
    предупреждения — в том числе семантические, которые дверь не перепроверяет
    и не может перепроверить — едут с ответом, не блокируя полку.
    ``confirmed`` — штатный повтор после вопроса двери о замене своей же
    content-addressed полки; ``srd_slugs`` — тот же словарь SRD, что видел
    предпросмотр (пересечение с SRD дверь отметит своим предупреждением).
    """

    def __init__(self, importer: GrimoireImportService) -> None:
        self._importer = importer

    def accept(
        self,
        document: str,
        *,
        confirmed: bool = False,
        srd_slugs: Sequence[str] | None = None,
    ) -> GrimoireImportOutcome:
        """Принять документ заклинаний новым хоумбрю-гримуаром; всегда
        отвечает исходом двери, не бросает."""
        return self._importer.import_grimoire(
            document, confirmed=confirmed, srd_slugs=srd_slugs
        )
