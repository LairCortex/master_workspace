"""Встреча — доменные значения надстройки события (add-dnd-game-face task
11.1; spec dnd-encounters).

Qt-free, storage-free values, как всё доменное полотно модуля. Встреча —
необязательная надстройка существующего события (список «монстр × количество»
+ заметка), не отдельное время и не отдельная сущность (spec «Встреча —
надстройка события, не отдельное время»). Строка состава хранит снимок имени
монстра, взятый в момент выбора (Д6): монстр из бестиария не удаляется, но
снимок — честная память карточки о том, что мастер выбирал.

Пустой состав — не встреча (формулировка задачи 11.1): встречи без строк
состава не бывает, заметка одна существовать не может.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

#: Верхняя полоса количества: строка состава — набранные вручную монстры,
#: трёхзначное число с лихвой покрывает засаду; спиннер кадра ту же полосу
#: и показывает.
COUNT_MIN = 1
COUNT_MAX = 999

#: Строка состава без выбранного монстра (комбо «— не выбрано» дожил до
#: сохранения): отказ по-русски, карточка остаётся открытой.
MONSTER_NOT_PICKED_REFUSAL = (
    "встреча: в строке состава не выбран монстр — выберите монстра из бестиария"
)

#: Количество вне полосы (posture модуля: читатель видит, что не так).
COUNT_REFUSAL = f"количество монстра — целое от {COUNT_MIN} до {COUNT_MAX}"


@dataclass(frozen=True)
class EncounterEntry:
    """Одна строка состава: монстр бестиария, сколько их, снимок имени на
    момент выбора."""

    monster_id: int
    count: int
    name_snapshot: str


@dataclass(frozen=True)
class DdEncounter:
    """Надстройка одного события: строки состава в порядке заведения +
    свободная заметка. Пустых ``entries`` у сохранённой встречи не бывает —
    такое сохранение сервис превращает в удаление строки («пустой состав
    = нет встречи»)."""

    event_id: int
    entries: tuple[EncounterEntry, ...]
    note: str


def validate_entry(entry: EncounterEntry) -> EncounterEntry:
    """Доменные ворота одной строки: монстр обязан быть выбран (целое > 0),
    количество — попасть в 1…999. Отказ — русская фраза до всякого
    прикосновения к строке таблицы."""
    monster_id = entry.monster_id
    if isinstance(monster_id, bool) or not isinstance(monster_id, int) or monster_id <= 0:
        raise ValueError(MONSTER_NOT_PICKED_REFUSAL)
    count = entry.count
    if isinstance(count, bool) or not isinstance(count, int):
        raise ValueError(COUNT_REFUSAL)
    if not COUNT_MIN <= count <= COUNT_MAX:
        raise ValueError(COUNT_REFUSAL)
    return entry


def normalize_entries(
    entries: Sequence[EncounterEntry],
) -> tuple[EncounterEntry, ...]:
    """Состав на запись: порядок строк сохраняется (состав читают сверху
    вниз), каждая строка проходит ворота. Пустой список — законный ответ
    «встречи нет»."""
    return tuple(validate_entry(entry) for entry in entries)


def normalize_note(note: str) -> str:
    """Заметка — свободный текст: концевые переводы строки обрезаются,
    внутренняя вёрстка (переводы, абзацы) остаётся как набрана."""
    return str(note).rstrip()
