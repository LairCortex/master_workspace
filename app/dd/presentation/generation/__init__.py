"""Листы-задачи ИИ-генерации модуля D&D (add-dnd-lss-generation, группа 7).

Три widget-листа поверх Qt-free ядра круга (design Д7): задача датасетов,
лист заклинаний и лист персонажа (создание/дозаполнение). Жизненный цикл
общий и живёт в :mod:`.base`: задачи qasync на общем цикле, закрытие с
in-flight через modeless-подтверждение с отменой (отмена — не ошибка),
released-лист не отвечает, кнопки гейтуются общим AI-гейтом с общей же
русской подсказкой AI-кнопок.
"""
from app.dd.presentation.generation.base import DndGenerationTaskSheet
from app.dd.presentation.generation.character_task_sheet import (
    DD_CHARACTER_TASK_TITLE,
    DD_TOP_UP_TASK_TITLE,
    DndCharacterTaskSheet,
)
from app.dd.presentation.generation.dataset_task_sheet import (
    DD_DATASET_TASK_TITLE,
    DndDatasetTaskSheet,
    generation_dataset_id,
)
from app.dd.presentation.generation.spellbook_task_sheet import (
    DD_SPELLBOOK_TASK_TITLE,
    DndSpellbookTaskSheet,
)

__all__ = [
    "DD_CHARACTER_TASK_TITLE",
    "DD_DATASET_TASK_TITLE",
    "DD_SPELLBOOK_TASK_TITLE",
    "DD_TOP_UP_TASK_TITLE",
    "DndCharacterTaskSheet",
    "DndDatasetTaskSheet",
    "DndGenerationTaskSheet",
    "DndSpellbookTaskSheet",
    "generation_dataset_id",
]
