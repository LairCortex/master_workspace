"""Русские фразы предупреждения о повреждённом календарь-ключе (кусок C2).

Домен намеренно не локализует ничего (принцип куска C0): кодек
:func:`~app.domain.game_calendar.decode_calendar` отвечает машиночитаемыми
кодами причин (:class:`~app.domain.game_calendar.SpecProblem`), а смысл для
пользователя извлекает presentation (design D4). Здесь — чистые функции без Qt:
известный код получает русскую фразу, неизвестный код или неизвестная версия
``v`` — общую фразу о повреждённых настройках календаря (spec
«Повреждённое значение календарь-ключа», сценарий «Неизвестная версия
формата»). Показ окна (ровно одного на открытие) — дело ``Application``.
"""
from __future__ import annotations

from collections.abc import Iterable

from app.domain.game_calendar import SpecProblem

#: Заголовок предупреждающего окна о повреждённом календарь-ключе.
MONTH_WARNING_TITLE = "Настройки календаря"

#: Общая фраза для причины, кода которой нет в словаре, — и по умолчанию для
#: неизвестной версии формата (её код ``unknown_version`` намеренно отсутствует
#: в :data:`_CODE_PHRASES`, чтобы попасть именно сюда — spec
#: «Неизвестная версия формата»).
GENERIC_CORRUPT_PHRASE = "настройки календаря повреждены"

#: Машиночитаемые коды причин → русские фразы. Коды берёт из домена:
#: собственные коды кодека (``corrupt_json``/``corrupt_shape``) и полный набор
#: кодов валидации спеки (``validate``). ``unknown_version`` здесь отсутствует
#: специально — он уходит в общую фразу.
_CODE_PHRASES: dict[str, str] = {
    "corrupt_json": "запись календаря не читается как JSON",
    "corrupt_shape": "запись календаря имеет неверную структуру",
    "no_months": "в календаре нет ни одного месяца",
    "empty_month_name": "у месяца пустое название",
    "duplicate_month_name": "в календаре повторяются имена месяцев",
    "month_length_below_min": "длина месяца меньше одного дня",
    "week_too_short": "в неделе меньше двух дней",
    "week_length_mismatch": "длина недели не совпадает с числом её названий",
    "empty_week_name": "у дня недели пустое название",
    "duplicate_week_name": "в календаре повторяются названия дней недели",
    "empty_intercalary_name": "у вставного дня пустое название",
    "duplicate_intercalary_name": "в календаре повторяются названия вставных дней",
    "intercalary_unknown_month": "вставной день ссылается на несуществующий месяц",
    "year_length_overflow": "год слишком длинный — ключи не помещаются в 64 бита",
}


def corruption_reason_phrase(code: str) -> str:
    """Русская фраза для одной машины-причины; общая — для неизвестного кода."""
    return _CODE_PHRASES.get(code, GENERIC_CORRUPT_PHRASE)


def calendar_corruption_body(reasons: Iterable[SpecProblem]) -> str:
    """Тело предупреждающего окна: пресет + перечень причин по-русски.

    Повторяющиеся фразы (несколько проблем одного кода) сворачиваются в одну;
    пустого перечня не бывает — без причин он подставляется общий текст, так
    что предупреждение никогда не молчит (spec «Окно не глотает молчание»).
    """
    phrases: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        phrase = corruption_reason_phrase(reason.code)
        if phrase not in seen:
            seen.add(phrase)
            phrases.append(phrase)
    if not phrases:
        phrases = [GENERIC_CORRUPT_PHRASE]
    return (
        "Настройки календаря повреждены, поэтому игра открыта с пресетом "
        "«Стандартный».\nПричина: " + "; ".join(phrases)
    )
