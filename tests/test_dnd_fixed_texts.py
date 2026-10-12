"""Дословные пины текстов, зафиксированных нормой в ядре (fix-dnd-followups,
task 1.2; design Д4: «один источник — константа»).

Спека dnd-module-lifecycle модифицирована дельтой fix-dnd-followups: тексты
трёх предупреждений жизненного цикла «фиксированы дословно». Здесь каждый из
трёх закреплён РОВНО ОДНИМ сравнением с литералом: дрейф константы в
``app/main.py`` (будущая правка, опечатка, «улучшение формулировки») роняет
этот тест, а не живую приёмку. Остальные дословно зафиксированные тексты
модуля живут в соседнем пине ``tests/dd/test_dd_fixed_texts.py``.
"""
from __future__ import annotations

from app.main import (
    DD_MODULE_OFF_WARNING,
    DD_MODULE_PROFILE_WARNING,
    DD_MODULE_VERSION_WARNING,
)


def test_module_off_warning_is_the_fixed_sentence():
    """spec dnd-module-lifecycle «Выключение модуля с сохранением данных»."""
    assert DD_MODULE_OFF_WARNING == (
        "D&D-модуль в этой игре выключен. Данные модуля сохранены и скрыты; "
        "включить модуль можно пунктом «Включить D&D-модуль…» в меню «Игра»."
    )


def test_module_version_warning_is_the_fixed_sentence():
    """spec dnd-module-lifecycle «Версия модуля и совместимость версий»."""
    assert DD_MODULE_VERSION_WARNING == (
        "Игра создана более новой версией D&D-модуля, чем поддерживает это "
        "приложение. Игра открыта как обычная; признак и данные модуля не "
        "изменены."
    )


def test_module_profile_warning_is_the_fixed_sentence():
    """spec dnd-module-lifecycle «Профиль сборки без модуля»."""
    assert DD_MODULE_PROFILE_WARNING == (
        "D&D-модуль недоступен в этом профиле приложения. Игра открыта как "
        "обычная; признак и данные модуля не изменены."
    )
