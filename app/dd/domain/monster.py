"""Монстр бестиария — доменные значения (add-dnd-game-face task 10.1; spec
dnd-bestiary).

Qt-free, storage-free values, как всё доменное полотно модуля. Монстр —
собственная сущность игры (в датасетах Long Story Short монстров нет): имя
плюс общие поля карточки — текстовые блоки, картинка, рейтинг. Механика
(класс доспеха, хиты, атаки) живёт текстом: типизированных механических
полей объём изменения не заводит (spec «Механика — текстом»).

Рейтинг — то же поле карточки, что и у сущностей ядра: целое 1…20, полоса
одна (``_ValueProxy(…, 1, 20)`` карточного диалога); доменное gates-правило
зеркалит ``validate_level`` группы 8 — с тем же отказом по-русски.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Полоса рейтинга карточки: те же 1…20, что печатает спиннер карточек ядра.
RATING_MIN = 1
RATING_MAX = 20

#: Русский отказ рейтинга вне полосы (posture модуля: читатель видит, что не
#: так, а не код).
RATING_REFUSAL = "рейтинг монстра — целое от 1 до 20"

#: Монстра без имени не бывает: имя — строка бестиария, строка поиска и
#: дисплей упоминания; creation-половина карточки пустое имя не принимает.
NAME_REFUSAL = "имя монстра не может быть пустым"


@dataclass(frozen=True)
class DdMonster:
    """Одна строка бестиария. ``blocks`` — именованные текстовые блоки в
    порядке заведения (та же форма, что ``dd_character_ext.text_blocks``);
    ``image_id`` — ссылка на хранилище картинок ядра (``images.id``) либо
    ``None`` («нет изображения»)."""

    id: int
    name: str
    rating: int
    blocks: dict[str, str]
    image_id: int | None


def validate_rating(rating: int) -> int:
    """Доменные ворота полосы: не-целое (и ``bool`` заодно) и выход за 1…20
    отказываются русскую фразу до всякого прикосновения к строке."""
    if not isinstance(rating, int) or isinstance(rating, bool):
        raise ValueError(RATING_REFUSAL)
    if not RATING_MIN <= rating <= RATING_MAX:
        raise ValueError(RATING_REFUSAL)
    return rating


def normalize_name(name: str) -> str:
    """Имя сохраняется обрезанным; пустое (или из одних пробелов) — отказ."""
    stripped = name.strip()
    if not stripped:
        raise ValueError(NAME_REFUSAL)
    return stripped


def normalize_blocks(blocks: dict[str, str]) -> dict[str, str]:
    """Блоки на запись: заголовки обрезаются, безымянный блок — не именованный
    и выпадает. Хранилище — JSON-словарь (codec группы 9), поэтому одно
    знание об одинаковых заголовках уже живёт в словаре: кадр карточки
    собирает строки в dict, последний заголовок побеждает."""
    return {name.strip(): text for name, text in blocks.items() if name.strip()}
