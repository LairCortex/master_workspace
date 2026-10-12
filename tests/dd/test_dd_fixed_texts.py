"""Дословные пины текстов модуля, зафиксированных нормой (fix-dnd-followups,
task 1.2; design Д4: «один источник — константа; тесты-пины добавляют защиту
от будущего дрейфа»).

Каждый зафиксированный дельтами текст закреплён РОВНО ОДНИМ сравнением с
литералом — текстовые срезы и подстроки в поведенческих тестах пинами не
считаются. Три предупреждения жизненного цикла (константы ``app/main.py``)
запинены в соседнем контуре ``tests/test_dnd_fixed_texts.py`` — ядро и модуль
в один пин-файл не смешиваем.

Покрытые тексты (спека → носитель):
- dnd-dataset-library «Автозагрузка SRD-наборов» → сводные успех/«уже в
  хранилище»/ошибка — ``OfficialDatasetsResult.summary``;
- dnd-character-import «Точки входа явные…» → подтверждение перезаписи —
  ``OVERWRITE_CONFIRM_BODY``;
- dnd-dataset-library (замена набора только с подтверждением) → сообщение
  ветки NEEDS_CONFIRMATION сервиса — собирается на полке;
- dnd-grimoire-import «…ложится в глобальное хранилище» → подтверждение
  замены гримуара — собирается на полке;
- dnd-generation «Гейт активации генерации» → ``DndModule.GENERATION_NO_DATASET_BODY``;
- dnd-generation «Дозаполнение персонажа» → ``TOP_UP_NOTHING_REFUSAL``
  (константа повышена до полного предложения задачей 1.1);
- dnd-generation «Жизнь задачи в её листе» → ``CLOSE_CONFIRM_TEXT``.
"""
from __future__ import annotations

import json

from app.dd.application.character_channel import TOP_UP_NOTHING_REFUSAL
from app.dd.application.character_import_service import OVERWRITE_CONFIRM_BODY
from app.dd.application.dataset_library_service import DatasetLibraryService
from app.dd.application.grimoire_import_service import (
    GrimoireImportService,
    GrimoireImportStatus,
)
from app.dd.domain.dataset import (
    DownloadStatus,
    OfficialDatasetOutcome,
    OfficialDatasetsResult,
    StoreStatus,
)
from app.dd.infrastructure.dataset_storage import DatasetStorage
from app.dd.infrastructure.grimoire_storage import GrimoireStorage
from app.dd.module import DndModule
from app.dd.presentation.generation.base import CLOSE_CONFIRM_TEXT
from tests.dd.grimoire_fixtures import content_of, foundry_compendium_export


# ── сводные SRD-тексты автозагрузки (dnd-dataset-library) ────────────────────


def test_srd_summary_success_is_the_fixed_sentence():
    result = OfficialDatasetsResult(
        items=(
            OfficialDatasetOutcome("srd51", "SRD 5.1 (2014)", DownloadStatus.DOWNLOADED),
            OfficialDatasetOutcome("srd52", "SRD 5.2 (2024)", DownloadStatus.DOWNLOADED),
        )
    )
    assert result.summary == (
        "Официальные наборы SRD загружены в хранилище: SRD 5.1 (2014), SRD 5.2 (2024)."
    )


def test_srd_summary_all_present_is_the_fixed_sentence():
    result = OfficialDatasetsResult(
        items=(
            OfficialDatasetOutcome("srd51", "SRD 5.1 (2014)", DownloadStatus.ALREADY_PRESENT),
            OfficialDatasetOutcome("srd52", "SRD 5.2 (2024)", DownloadStatus.ALREADY_PRESENT),
        )
    )
    assert result.summary == "Официальные наборы SRD уже в хранилище — сеть не требовалась."


def test_srd_summary_failure_is_the_fixed_template():
    result = OfficialDatasetsResult(
        items=(
            OfficialDatasetOutcome(
                "srd51", "SRD 5.1 (2014)", DownloadStatus.FAILED, "longstoryshort.app недоступен"
            ),
            OfficialDatasetOutcome(
                "srd52", "SRD 5.2 (2024)", DownloadStatus.FAILED, "404 Not Found"
            ),
        )
    )
    assert result.summary == (
        "Не удалось загрузить официальные наборы SRD. "
        "SRD 5.1 (2014): longstoryshort.app недоступен; "
        "SRD 5.2 (2024): 404 Not Found."
    )


# ── подтверждения сервисного слоя (character-import / dataset / grimoire) ────


def test_overwrite_confirmation_is_the_fixed_sentence():
    """spec dnd-character-import «Перезапись требует подтверждения»."""
    assert OVERWRITE_CONFIRM_BODY == (
        "Перезаписать персонажа из файла LSS? Поля, карточка D&D, текстовые "
        "блоки и сохранённый файл-снимок будут заменены содержимым файла."
    )


def test_dataset_replacement_confirmation_is_the_fixed_sentence(tmp_path):
    """Замена лежащего в хранилище набора спрашивается дословно этой фразой
    (spec dnd-dataset-library: «заменять только после подтверждения»)."""
    storage = DatasetStorage(tmp_path / "datasets")
    service = DatasetLibraryService(
        storage, object()  # type: ignore[arg-type] - полка клиента автозагрузки не трогает
    )
    doc = json.dumps({"id": "my-pack", "title": "Первый"})
    service.store_dataset(doc)

    outcome = service.store_dataset(json.dumps({"id": "my-pack", "title": "Второй"}))

    assert outcome.status is StoreStatus.NEEDS_CONFIRMATION
    assert outcome.message == (
        "Набор «Второй» уже в хранилище — заменить его можно только с вашим подтверждением."
    )


def test_grimoire_replacement_confirmation_is_the_fixed_sentence(tmp_path):
    """spec dnd-grimoire-import «Замена подтверждается»."""
    storage = GrimoireStorage(tmp_path / "grimoires")
    service = GrimoireImportService(storage)
    storage.save("tina-grimoire", json.dumps({"id": "tina-grimoire", "name": "Старая"}))

    outcome = service.import_grimoire(content_of(foundry_compendium_export()))

    assert outcome.status is GrimoireImportStatus.NEEDS_CONFIRMATION
    assert outcome.message == (
        "Гримуар «Гримуар Тины» уже в хранилище — заменить его можно только с вашим подтверждением."
    )


# ── тексты листа генерации (dnd-generation) ──────────────────────────────────


def test_dataset_gate_refusal_is_the_fixed_sentence():
    """spec dnd-generation «Текст отказа датасет-гейта»."""
    assert DndModule.GENERATION_NO_DATASET_BODY == (
        "Для генерации персонажа нужен хотя бы один подключённый к игре "
        "датасет: включите набор в листе «Датасеты D&D…» и повторите."
    )


def test_top_up_refusal_is_the_fixed_sentence():
    """spec dnd-generation «Пусто дозаполнять» (задача 1.1 подняла константу
    до полного предложения с заглавной)."""
    assert TOP_UP_NOTHING_REFUSAL == (
        "Дозаполнять нечего: все содержательные поля карточки уже заполнены"
    )


def test_generation_sheet_close_confirmation_is_the_fixed_sentence():
    """spec dnd-generation «Закрытие посреди задачи»."""
    assert CLOSE_CONFIRM_TEXT == (
        "Генерация ещё выполняется. Закрыть лист? Незавершённые запросы будут "
        "прерваны, несохранённая задача не сохранится."
    )
