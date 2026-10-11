"""Домен «Встречи» (add-dnd-game-face task 11.1; spec dnd-encounters).

Ворота строки состава живут ДО транзакции и ДО всякого виджета: монстр обязан
быть выбран (целое > 0), количество — попасть в 1…999; отказы — русские
фразы, их печатает карточка через коннектор. Нормализация состава сохраняет
порядок строк; заметка теряет только концевые переводы строки.
"""
from __future__ import annotations

import pytest

from app.dd.domain.encounter import (
    COUNT_MAX,
    COUNT_REFUSAL,
    MONSTER_NOT_PICKED_REFUSAL,
    DdEncounter,
    EncounterEntry,
    normalize_entries,
    normalize_note,
    validate_entry,
)


def _entry(mid=1, count=1, name="Гоблин"):
    return EncounterEntry(monster_id=mid, count=count, name_snapshot=name)


def test_values_are_frozen_records():
    entry = _entry()
    encounter = DdEncounter(event_id=7, entries=(entry,), note="засада у моста")
    assert encounter.event_id == 7 and encounter.entries == (entry,)
    with pytest.raises(Exception):
        entry.count = 2  # type: ignore[misc]


def test_validate_entry_accepts_the_clean_row():
    entry = _entry(mid=3, count=COUNT_MAX)
    assert validate_entry(entry) is entry


@pytest.mark.parametrize("mid", [0, -1, -42, True, False, 1.5, "1", None])
def test_unpicked_monster_refuses_in_russian(mid):
    with pytest.raises(ValueError) as exc:
        validate_entry(_entry(mid=mid))
    assert str(exc.value) == MONSTER_NOT_PICKED_REFUSAL


@pytest.mark.parametrize("count", [0, COUNT_MAX + 1, -5, True, False, 1.5, "12", None])
def test_count_out_of_band_refuses_in_russian(count):
    with pytest.raises(ValueError) as exc:
        validate_entry(_entry(count=count))
    assert str(exc.value) == COUNT_REFUSAL


def test_normalize_entries_keeps_the_order_and_lets_empty_pass():
    entries = [_entry(mid=2, count=3), _entry(mid=1, count=1)]
    assert normalize_entries(entries) == tuple(entries)
    assert normalize_entries([]) == ()


def test_normalize_note_trims_only_the_tail():
    assert normalize_note("  засада\nу моста\n\n ") == "  засада\nу моста"
    assert normalize_note("") == ""
