"""Сборщик промптов генерации (add-dnd-lss-generation, tasks 2.1–2.2; design Д3).

Qt-free ядро промптостроения: скелет системного промпта канала + фиксированный
few-shot-набор из ресурсов модуля — в системную часть; описание мира, идея
мастера и слой slug-словаря подключённых источников (источник + slug + снимок
имени) — в пользовательскую. Скелеты и образцы живут в
``app/dd/resources/generation/`` и НЕ зависят от подключённых датасетов
(spec «Детерминированные примеры и словарь идентификаторов»: содержимое
подключённых наборов SHALL NOT влиять на примеры; слаги подключённых источников
уходят отдельным слоем и служат единственной областью разрешения ссылок).

Детерминизм — контракт, а не пожелание: одна и та же пара входов даёт
побайтово одинаковый промпт (golden-тесты сборки), а подключение разных
датасетов меняет ровно слой словаря. Языковая директива («содержимое
по-русски, протокол латиницей») вшита в скелеты.

Каналы (группы 3/4/6) получают отсюда пару ``(system, user)`` для
:meth:`GenerationChannel.build_prompt
<app.dd.application.generation_loop.GenerationChannel.build_prompt>`;
канал-специфичные входы (число сущностей, пре-выборы, текущий документ) к
базовой сборке добавляет сам канал — она знает только четыре слоя Д3.
"""
from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app.dd.application.generation_loop import Prompt
from app.dd.domain.lss_checks import SECTIONS

#: Каталог ресурсов генерации рядом с пакетом (dev-раскладка).
GENERATION_RESOURCE_DIR = (
    Path(__file__).resolve().parents[1] / "resources" / "generation"
)

_SKELETON_DIR = "skeletons"
_FEWSHOT_DIR = "fewshot"

#: Канал → файл скелета системного промпта (RU, с языковой директивой).
SKELETON_FILES: dict[str, str] = {
    "dataset-section": "dataset-section.txt",
    "spellbook": "spellbook.txt",
    "character": "character.txt",
}

#: Ключи few-shot-наборов: шесть секций датасета (ключи — протокольные имена
#: из SECTIONS, одна правда в lss_checks) плюс шаблон заклинания и фрагменты
#: персонажа.
FEWSHOT_KEYS: tuple[str, ...] = SECTIONS + ("spellbook", "character")

#: Заголовки блока образцов в системной части — по одному на канал.
_SAMPLES_HEADERS: dict[str, str] = {
    "dataset-section": (
        "Образцы записей секции — повторяй их формат точно, содержимое пиши своё:"
    ),
    "spellbook": (
        "Образец заклинания — повторяй его формат точно, содержимое пиши своё:"
    ),
    "character": (
        "Образцы фрагментов документов персонажей — повторяй их формат точно, "
        "содержимое пиши своё:"
    ),
}

#: Шапка слоя словаря в пользовательской части.
_VOCABULARY_HEADER = (
    "Словарь идентификаторов подключённых источников — единственная область "
    "ссылок (id/slug/featId/classId/raceId берутся только отсюда); формат "
    "строки: slug — «снимок имени»."
)

_VOCABULARY_EMPTY_LINE = "(пусто — ссылаться ни на какие идентификаторы нельзя)"


def generation_resource_dir() -> Path:
    """Каталог ресурсов генерации в dev-раскладке и в замороженной сборке.

    Тот же механизм, что :func:`app.dd.infrastructure.lss_schemas.schema_resource_dir`:
    в PyInstaller-бандле каталог лежит под ``sys._MEIPASS``.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base is not None:
        return Path(base) / "app" / "dd" / "resources" / "generation"
    return GENERATION_RESOURCE_DIR


@dataclass(frozen=True)
class SlugVocabularyEntry:
    """Одна строка слоя словаря: ``источник + slug + снимок имени`` (design Д3).

    ``source`` — id подключённого датасета или гримуара, ``slug`` —
    протокольный идентификатор записи (парный ключ ``источник/запись``),
    ``name`` — снимок имени из файла только для понимания смысла; пустой или
    совпадающий со слагом — честное «имени нет», строка печатается без кавычек.
    """

    source: str
    slug: str
    name: str = ""


def _render_vocabulary(entries: Sequence[SlugVocabularyEntry]) -> str:
    """Слой словаря: шапка, затем группы по источникам (порядок входа —
    порядок вывода, порядок внутри источника — порядок записей)."""
    lines = [_VOCABULARY_HEADER]
    if not entries:
        lines.append(_VOCABULARY_EMPTY_LINE)
        return "\n".join(lines)
    grouped: dict[str, list[SlugVocabularyEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.source, []).append(entry)
    for source, source_entries in grouped.items():
        lines.append(f"[{source}]")
        for entry in source_entries:
            if entry.name and entry.name != entry.slug:
                lines.append(f"- {entry.slug} — «{entry.name}»")
            else:
                lines.append(f"- {entry.slug}")
    return "\n".join(lines)


def _render_user_prompt(
    world: str, idea: str, vocabulary: Sequence[SlugVocabularyEntry]
) -> str:
    """Пользовательская часть: мир → идея мастера → слой словаря. Пустые
    текстовые слои не печатаются; словарь печатается всегда (пустой словарь —
    тоже ответ модели о границе ссылок)."""
    parts: list[str] = []
    if world.strip():
        parts.append(f"Описание мира:\n{world.strip()}")
    if idea.strip():
        parts.append(f"Идея мастера:\n{idea.strip()}")
    parts.append(_render_vocabulary(vocabulary))
    return "\n\n".join(parts)


def _render_samples(channel: str, fewshot: Mapping[str, Any]) -> str:
    """Блок образцов: фиксированное содержимое ресурса печатается как есть —
    порядок ключей и записей берётся из файла, детерминизм гарантирует сам
    файл."""
    rendered = json.dumps(fewshot["samples"], ensure_ascii=False, indent=2)
    return f"{_SAMPLES_HEADERS[channel]}\n{rendered}"


class PromptComposer:
    """Собирает ``(system, user)`` для первых запросов каналов круга.

    Конструктор читает фиксированные ресурсы один раз; составление — чистая
    функция входов. Порядок и тексты слоёв зафиксированы golden-тестами:
    правка ресурсов или сборки — явная смена промпта, а не случайный дрейф.
    """

    def __init__(self, resource_dir: Path | None = None) -> None:
        directory = resource_dir if resource_dir is not None else generation_resource_dir()
        self._skeletons = {
            channel: (directory / _SKELETON_DIR / name).read_text(encoding="utf-8").strip()
            for channel, name in SKELETON_FILES.items()
        }
        self._fewshot = {
            key: json.loads(
                (directory / _FEWSHOT_DIR / f"{key}.json").read_text(encoding="utf-8")
            )
            for key in FEWSHOT_KEYS
        }

    def section_label(self, section: str) -> str:
        """RU-подпись секции — из фиксированного few-shot-набора (единственное
        место, где подпись живёт; каналы достраивают ею служебные поля конверта)."""
        if section not in SECTIONS:
            raise ValueError(f"неизвестная секция датасета: {section!r}")
        return self._fewshot[section]["label"]

    def compose_dataset_section(
        self,
        section: str,
        world: str = "",
        idea: str = "",
        vocabulary: Sequence[SlugVocabularyEntry] = (),
    ) -> Prompt:
        """Промпт секции датасета: скелет + «Секция: <ключ> («подпись»)» +
        few-shot этой секции; мир/идея/словарь — пользовательская часть."""
        if section not in SECTIONS:
            raise ValueError(f"неизвестная секция датасета: {section!r}")
        fewshot = self._fewshot[section]
        system = "\n\n".join(
            [
                self._skeletons["dataset-section"],
                f"Секция: {section} («{fewshot['label']}»).",
                _render_samples("dataset-section", fewshot),
            ]
        )
        return system, _render_user_prompt(world, idea, vocabulary)

    def compose_spellbook(
        self,
        world: str = "",
        idea: str = "",
        vocabulary: Sequence[SlugVocabularyEntry] = (),
    ) -> Prompt:
        """Промпт файла заклинаний: скелет + шаблон заклинания."""
        system = "\n\n".join(
            [
                self._skeletons["spellbook"],
                _render_samples("spellbook", self._fewshot["spellbook"]),
            ]
        )
        return system, _render_user_prompt(world, idea, vocabulary)

    def compose_character(
        self,
        world: str = "",
        idea: str = "",
        vocabulary: Sequence[SlugVocabularyEntry] = (),
    ) -> Prompt:
        """Промпт персонажа: скелет + фрагменты документов персонажа."""
        system = "\n\n".join(
            [
                self._skeletons["character"],
                _render_samples("character", self._fewshot["character"]),
            ]
        )
        return system, _render_user_prompt(world, idea, vocabulary)
