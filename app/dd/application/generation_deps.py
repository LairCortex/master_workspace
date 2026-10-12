"""Зависимости ИИ-генерации, приходящие из приложения (design Д8, task 7.5).

Ядро генерации (круг, каналы, контексты) не знает ни про Qt, ни про LLM-настройку
игры: всё изменчивое — готов ли ассистент, что за текст подсказки, каково описание
мира и каким провайдером отвечать — доходит сюда четырьмя вызываемыми объектами,
которые композиция root'а (``app/main.py``) строит замыканиями на живой
:class:`~app.presentation.viewmodels.llm_viewmodel.LlmViewModel`. Листы-задачи
читают эти двери в момент клика, поэтому смена настройки LLM посреди сессии
видна без пересоздания листов (тот же постур AI-кнопок карточек).

:class:`GenerationBundle` — весь набор дверей, который façade модуля получает
одним параметром: сами двери гейта, сборщик контекстов и три accept-двери
хранилищ (design Д6 — принятие идёт через существующие импортные двери).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from app.dd.application.character_document_builder import CharacterDocumentBuilder
    from app.dd.application.character_import_service import CharacterImportService
    from app.dd.application.dataset_section_channel import (
        DatasetSectionAcceptanceService,
    )
    from app.dd.application.generation_inputs import GenerationInputs
    from app.dd.application.generation_loop import AnswerFn
    from app.dd.application.spellbook_channel import SpellbookAcceptanceService

__all__ = ["GenerationBundle", "GenerationDeps"]


@dataclass(frozen=True)
class GenerationDeps:
    """Четыре двери приложения в лист-задачу (поза AI-кнопок карточек).

    ``available`` — общий AI-гейт (ассистент «готов» + описание мира задано);
    ``hint`` — та же русская подсказка, что показывают AI-кнопки карточек,
    когда гейт закрыт (тексты живут в ``event_dialog_island_view_model``,
    одно знание — одно место); ``world`` — текущее описание мира игры;
    ``make_answer`` — фабрика канала ответа на ТЕКУЩЕМ провайдере (настройка
    LLM могла измениться с момента открытия листа).
    """

    available: Callable[[], bool]
    hint: Callable[[], str]
    world: Callable[[], str]
    make_answer: Callable[[], "AnswerFn"]


@dataclass(frozen=True)
class GenerationBundle:
    """Всё, что façade модуля отдаёт листам-задачам (design Д6/Д7/Д8).

    Ни Qt, ни оконных типов: только Qt-free двери. ``dataset_acceptance`` и
    ``spellbook_acceptance`` — принятие через существующие двери импорта
    хранилищ, ``character_import``/``character_document`` — те же двери, что
    уже служат импорту и экспорту персонажа (спека «результат SHALL проходить
    импортный конвейер существующего импорта»).
    """

    deps: GenerationDeps
    inputs: "GenerationInputs"
    dataset_acceptance: "DatasetSectionAcceptanceService"
    spellbook_acceptance: "SpellbookAcceptanceService"
    character_import: "CharacterImportService"
    character_document: "CharacterDocumentBuilder"
