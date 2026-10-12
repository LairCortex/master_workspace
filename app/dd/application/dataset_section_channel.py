"""Канал датасетов (add-dnd-lss-generation, tasks 3.1–3.2; design Д2/Д6).

Qt-free реализация протокола :class:`GenerationChannel
<app.dd.application.generation_loop.GenerationChannel>` поверх механизма
круга группы 1: модель пишет ровно JSON-массив записей одной секции (скелет
промпта это и предписывает), а приложение оборачивает их в конверт
``dataset-<тип>.json`` — версия формата (``$schema``-URL встроенной
редакции), идентификатор датасета и прочие служебные поля живут по правилам
конверта и из ответа модели НЕ берутся (тест «числа модели в конверт не
попадают»: даже если модель обернула массив в объект со своими «version»,
«id» или «$schema», в конверт идут только значения приложения).

Лицензия — единственное поле принятия (design Д2): до подстановки конверт
собирается «холостым» (лицензия по умолчанию проходит валидатор, поэтому
круг не гоняет модель за поле, которое та не пишет), а при записи выбора
мастера подставляется настоящее значение из трёх разрешённых
(:data:`DATASET_LICENSE_CHOICES`, дефолт CC-BY 4.0 — spec «Предпросмотр и
принятие датасета»).

Валидация — существующим :class:`DatasetValidatorService` с подключёнными
датасетами и SRD-слагами (spec «Детерминированные примеры и словарь
идентификаторов»: неразрешимая ссылка — обычная ошибка круга). Принятие —
существующая дверь импорта (:class:`DatasetImportService`, source
``HOMEBREW`` — её собственный режим) + автоподключение
:class:`DatasetConnectionsService` (design Д6: никаких вторых дверей записи
в хранилище); документ с ошибками дверь не пропускает структурно, поэтому
принятие отказывает, ничего не записав и не подключив.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.dd.application.dataset_connections_service import (
    DatasetConnectionsService,
)
from app.dd.application.dataset_import_service import (
    DatasetImportOutcome,
    DatasetImportService,
    DatasetImportStatus,
)
from app.dd.application.dataset_validator_service import DatasetValidatorService
from app.dd.application.generation_loop import Prompt, extract_json_document
from app.dd.application.prompt_composer import PromptComposer, SlugVocabularyEntry
from app.dd.domain.dataset import DatasetSource, is_valid_dataset_id
from app.dd.domain.lss_checks import SECTIONS, ConnectedDataset
from app.dd.domain.validation_report import ValidationReport
from app.dd.infrastructure.lss_schemas import (
    FORMAT_VERSION,
    SCHEMA_DECLARATION_KEY,
    SCHEMA_URL_TEMPLATE,
)

#: Служебные значения конверта: приложение заполняет их само, по образцу
#: формата LSS (спека: «служебный конверт датасета … достраивает приложение»).
DATASET_SYSTEM = "dnd_5"
DATASET_EDITION = "2024"
DATASET_AUTHOR = "Master Workspace"

#: Число сущностей в секции: поле мастера 1…10, по умолчанию 5 (spec
#: «Задача генерации датасетов»).
SECTION_COUNT_MIN = 1
SECTION_COUNT_MAX = 10
SECTION_DEFAULT_COUNT = 5

#: Разрешённый выбор лицензии при принятии (spec: три — CC0, CC-BY и CC-BY-SA
#: с версией; по умолчанию CC-BY 4.0). Все значения проходят LICENSE_RE
#: валидатора, «CC-BY» без версии здесь нет намеренно.
DATASET_LICENSE_CHOICES: tuple[str, ...] = ("CC0", "CC-BY-4.0", "CC-BY-SA-4.0")
DEFAULT_DATASET_LICENSE = "CC-BY-4.0"

#: Строка числа сущностей, которую канал добавляет к user-части поверх
#: :class:`PromptComposer` (замечание группы 2: канал-специфичные входы
#: канал дописывает сам).
_COUNT_LINE_TEMPLATE = "Сущностей в секции: {count} — выдай ровно столько записей."


@dataclass(frozen=True)
class DatasetSectionContext:
    """Входы одной генерации секции, общие для всех трёх методов канала.

    ``world``/``idea``/``vocabulary``/``count`` уходят в промпт,
    ``connected``/``spell_slugs`` — существующему валидатору (корпус линков
    и словарь SRD-слагов игры); канал их не интерпретирует и не помнит.
    """

    world: str = ""
    idea: str = ""
    count: int = SECTION_DEFAULT_COUNT
    vocabulary: tuple[SlugVocabularyEntry, ...] = ()
    connected: tuple[ConnectedDataset, ...] = ()
    spell_slugs: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if not SECTION_COUNT_MIN <= self.count <= SECTION_COUNT_MAX:
            raise ValueError(
                f"число сущностей в секции — от {SECTION_COUNT_MIN} "
                f"до {SECTION_COUNT_MAX}, получено {self.count!r}"
            )


class DatasetSectionChannel:
    """Один канал = одна секция = один файл (spec «Задача генерации датасетов»).

    Секция и идентификатор датасета — свойства задачи (лист создаёт канал на
    секцию), остальное приходит контекстом круга. Идентификатор проверяется
    по грамматике хранилища сразу: он — будущая полка, отказ должен
    приходить до первого запроса, а не на принятии.
    """

    def __init__(
        self,
        section: str,
        dataset_id: str,
        *,
        composer: PromptComposer | None = None,
        validator: DatasetValidatorService | None = None,
        name: str = "",
        system: str = DATASET_SYSTEM,
        edition: str = DATASET_EDITION,
        author: str = DATASET_AUTHOR,
    ) -> None:
        if section not in SECTIONS:
            raise ValueError(f"неизвестная секция датасета: {section!r}")
        if not is_valid_dataset_id(dataset_id):
            raise ValueError(
                f"идентификатор датасета «{dataset_id}» не может именем файла"
            )
        self._section = section
        self._dataset_id = dataset_id
        self._composer = composer if composer is not None else PromptComposer()
        self._validator = (
            validator if validator is not None else DatasetValidatorService()
        )
        self._name = name or f"Хоумбрю: {self._composer.section_label(section)}"
        self._system = system
        self._edition = edition
        self._author = author

    def build_prompt(self, context: DatasetSectionContext) -> Prompt:
        """Слои Д3 (скелет + few-shot + мир + идея + словарь) плюс
        канал-специфичное число сущностей поверх пользовательской части."""
        system, user = self._composer.compose_dataset_section(
            self._section, context.world, context.idea, context.vocabulary
        )
        user = f"{user}\n\n{_COUNT_LINE_TEMPLATE.format(count=context.count)}"
        return system, user

    def parse(self, answer: str) -> str:
        """Массив записей секции → текст файла ``dataset-<тип>.json``.

        Терпимость одна и та же, что у остальных каналов: ``extract_json_document``
        прощает fence и обрамляющий текст. Модель, вопреки директиве, может
        обернуть массив в объект со служебными полями — тогда берутся записи
        запрошенной секции, а СЛУЖЕБНЫЕ ПОЛЯ (числа, id, версия формата)
        перечисляются заново по правилам конверта: из ответа модели в файл не
        попадает ничего, кроме записей секции. Лицензия — холостая (дефолт),
        её подменит принятие.
        """
        payload: Any = json.loads(extract_json_document(answer))
        if isinstance(payload, list):
            entries: list = payload
        elif isinstance(payload, dict) and isinstance(payload.get(self._section), list):
            entries = payload[self._section]
        else:
            raise ValueError(
                f"ответ модели не содержит JSON-массива записей секции "
                f"«{self._section}» — выдай только массив записей"
            )
        envelope = {
            SCHEMA_DECLARATION_KEY: SCHEMA_URL_TEMPLATE.format(version=FORMAT_VERSION),
            "id": self._dataset_id,
            "name": self._name,
            "system": self._system,
            "edition": self._edition,
            "author": self._author,
            "license": DEFAULT_DATASET_LICENSE,
            self._section: entries,
        }
        return json.dumps(envelope, ensure_ascii=False, indent=2)

    def validate(
        self, document: str, context: DatasetSectionContext
    ) -> ValidationReport:
        """Существующий валидатор датасетов: корпус линков и словарь слагов
        игры доходят до него как есть, хоумбрю-режим — свой ответу."""
        return self._validator.validate(
            document,
            connected=context.connected,
            spell_slugs=context.spell_slugs,
            source=DatasetSource.HOMEBREW,
        )


def insert_dataset_license(document: str, license: str) -> str:
    """Подставить лицензию принятия в конверт секции (единственное поле
    принятия, design Д2).

    Выбор закрыт :data:`DATASET_LICENSE_CHOICES` — спека не оставляет места
    для «CC-BY» без версии или произвольной строки; чужая лицензия — русский
    ``ValueError`` до любого касания двери импорта. Конверт обязан быть
    JSON-объектом — «холостой» конверт канала всегда он, а мусор — тоже
    русская ошибка.
    """
    if license not in DATASET_LICENSE_CHOICES:
        raise ValueError(
            f"лицензия {license!r} вне разрешённого выбора: "
            f"нужно одно из {', '.join(DATASET_LICENSE_CHOICES)}"
        )
    try:
        envelope = json.loads(document)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"документ секции не является корректным JSON: {exc.msg}"
        ) from exc
    if not isinstance(envelope, dict):
        raise ValueError(
            "документ секции не является JSON-объектом — конверт датасета не опознан"
        )
    envelope["license"] = license
    return json.dumps(envelope, ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class DatasetAcceptanceOutcome:
    """Ответ принятия: исход двери импорта и факт автоподключения.

    ``accepted`` — датасет лёг на полку (новая или подтверждённая замена);
    ``connected`` — он же отмечен подключённым к игре (только при ``accepted``:
    отказ и вопрос ничего не пишут и не подключают).
    """

    import_outcome: DatasetImportOutcome
    connected: bool = False

    @property
    def accepted(self) -> bool:
        return self.import_outcome.status is DatasetImportStatus.STORED


class DatasetSectionAcceptanceService:
    """Принятие секции: существующая дверь импорта + автоподключение (Д6).

    Никакой собственной валидации и своей записи в хранилище: лицензия
    подставляется в конверт, байты уходят :class:`DatasetImportService`
    (её полный валидатор и есть гейт «файл с ошибками не принимается» —
    до порога хранилище не трогается структурно), а успешная полка сразу
    :meth:`DatasetConnectionsService.connect`. Вопрос о замене существующей
    полки дверь задаёт сама — подтверждение доходит ``confirmed=True``.
    """

    def __init__(
        self,
        importer: DatasetImportService,
        connections: DatasetConnectionsService,
    ) -> None:
        self._importer = importer
        self._connections = connections

    async def accept(
        self,
        document: str,
        license: str = DEFAULT_DATASET_LICENSE,
        *,
        confirmed: bool = False,
    ) -> DatasetAcceptanceOutcome:
        """Принять документ секции с лицензией мастера; всегда отвечает,
        не бросает (чужая лицензия или мусор — русский ``ValueError``
        ДО двери: ни запись, ни подключение не начинаются)."""
        content = insert_dataset_license(document, license)
        outcome = await self._importer.import_dataset(content, confirmed=confirmed)
        if outcome.status is DatasetImportStatus.STORED and outcome.dataset_id:
            await self._connections.connect(outcome.dataset_id)
            return DatasetAcceptanceOutcome(import_outcome=outcome, connected=True)
        return DatasetAcceptanceOutcome(import_outcome=outcome)
