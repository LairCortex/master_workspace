"""Хранилище и сервис «Встречи» (add-dnd-game-face task 11.1).

Два этажа, как у бестиария:

* codec состава — tolerant-чтение (пустое/неразбираемое/не-список читаются
  как пусто с журнальной строкой; мусорная строка выпадает, честные строки
  остаются — хранящаяся строка чтением не переписывается);
* репозиторий + сервис на общем тестовом unit-of-work: первая запись
  создаёт строку надстройки, повторная правит те же строки, пустой состав
  удаляет строку («пустой состав = нет встречи» — task 11.1), отказ ворот
  не открывает транзакцию и не трогает хранилище, а список событий-встреч
  для пометок лестницы читает тот же критерий непустоты, что и карточка.
"""
from __future__ import annotations

import pytest

from app.dd.application.dd_encounter_service import DdEncounterService
from app.dd.domain.encounter import (
    COUNT_REFUSAL,
    MONSTER_NOT_PICKED_REFUSAL,
    EncounterEntry,
)
from app.dd.infrastructure.db.dd_models import (
    DdEncounterModel,
    decode_composition,
    encode_composition,
)
from app.dd.infrastructure.repositories.dd_encounter_repository import (
    DdEncounterRepository,
    encounter_to_domain,
)


# ── codec ─────────────────────────────────────────────────────────────────


def test_composition_codec_roundtrips_the_clean_rows():
    entries = [
        {"monster_id": 3, "count": 2, "name": "Гоблин"},
        {"monster_id": 1, "count": 10, "name": "Волк"},
    ]
    assert decode_composition(encode_composition(entries)) == entries


@pytest.mark.parametrize("bad", [None, "", "{не json", '{"monster_id": 1}', "[]"])
def test_unreadable_composition_reads_empty(bad):
    assert decode_composition(bad) == []


def test_garbage_rows_drop_honest_rows_stay():
    raw = encode_composition([
        {"monster_id": 1, "count": 1, "name": "Гоблин"},
        {"monster_id": "abc", "count": 1, "name": "не целое"},
        {"monster_id": 2, "count": 0, "name": "нулевое количество"},
        {"monster_id": True, "count": 1, "name": "bool вместо id"},
        {"monster_id": 3, "count": True, "name": "bool вместо count"},
        {"monster_id": 4, "count": 1, "name": 5},
        "не объект",
        {"monster_id": 5, "count": 2, "name": "Волк"},
    ])
    assert decode_composition(raw) == [
        {"monster_id": 1, "count": 1, "name": "Гоблин"},
        {"monster_id": 5, "count": 2, "name": "Волк"},
    ]


# ── сервис + репозиторий ──────────────────────────────────────────────────


def _entry(mid=1, count=1, name="Гоблин"):
    return EncounterEntry(monster_id=mid, count=count, name_snapshot=name)


async def _make_event(uow, name="Засада"):
    """Ядренное событие для FK-владельца надстройки — тем же сессией."""
    from datetime import date

    from app.infrastructure.db.models import EventModel

    event = EventModel(
        name=name,
        start_date=date(1200, 1, 5),
        end_date=None,
    )
    uow.session.add(event)
    await uow.session.flush()
    return event.id


async def test_missing_overlay_reads_none(uow):
    service = DdEncounterService(uow)
    event_id = await _make_event(uow)
    assert await service.get_encounter(event_id) is None


async def test_first_save_creates_the_overlay_row(uow):
    service = DdEncounterService(uow)
    event_id = await _make_event(uow)
    encounter = await service.save_encounter(
        event_id,
        [_entry(mid=2, count=3, name="Огр"), _entry(mid=1, count=1)],
        "  нападение на рассвете\n\n",
    )
    assert encounter is not None
    assert [entry.monster_id for entry in encounter.entries] == [2, 1]
    assert encounter.entries[0].name_snapshot == "Огр"
    assert encounter.note == "  нападение на рассвете"
    row = await DdEncounterRepository(uow.session).get_row(event_id)
    assert row is not None and row.note == "  нападение на рассвете"
    assert await service.get_encounter(event_id) == encounter


async def test_second_save_edits_the_same_row(uow):
    service = DdEncounterService(uow)
    event_id = await _make_event(uow)
    await service.save_encounter(event_id, [_entry()], "")
    updated = await service.save_encounter(
        event_id, [_entry(mid=4, count=2, name="Нетопырь")], "пещера"
    )
    assert updated is not None and updated.note == "пещера"
    rows = await DdEncounterRepository(uow.session).list_rows()
    assert [row.event_id for row in rows] == [event_id]  # одна строка на событие


async def test_empty_composition_deletes_the_row(uow):
    """«Пустой состав = нет встречи» (task 11.1): сохранение без строк
    состава убирает надстройку и отвечает None — заметка одна не живёт."""
    service = DdEncounterService(uow)
    event_id = await _make_event(uow)
    await service.save_encounter(event_id, [_entry()], "было")
    assert await service.save_encounter(event_id, [], "заметка сама по себе") is None
    assert await DdEncounterRepository(uow.session).get_row(event_id) is None
    assert await service.get_encounter(event_id) is None


async def test_empty_composition_without_a_row_changes_nothing(uow):
    service = DdEncounterService(uow)
    event_id = await _make_event(uow)
    assert await service.save_encounter(event_id, [], "") is None
    assert await service.encountered_event_ids() == []


@pytest.mark.parametrize(
    ("entries", "refusal"),
    [
        ([_entry(mid=0)], MONSTER_NOT_PICKED_REFUSAL),
        ([_entry(count=1000)], COUNT_REFUSAL),
    ],
)
async def test_refusal_never_opens_the_unit(uow, entries, refusal):
    service = DdEncounterService(uow)
    event_id = await _make_event(uow)
    with pytest.raises(ValueError) as exc:
        await service.save_encounter(event_id, entries, "")
    assert str(exc.value) == refusal
    assert await DdEncounterRepository(uow.session).get_row(event_id) is None


async def test_encountered_event_ids_reads_the_same_truth_as_the_card(uow):
    service = DdEncounterService(uow)
    first = await _make_event(uow, name="Первое")
    second = await _make_event(uow, name="Второе")
    third = await _make_event(uow, name="Третье")
    await service.save_encounter(first, [_entry()], "")
    await service.save_encounter(second, [_entry(mid=2, count=5)], "")
    # Третье: строка с НЕЧИТАЕМЫМ составом — полувстреча, не встреча.
    repo = DdEncounterRepository(uow.session)
    row = await repo.insert_row(third)
    row.composition = "{мусор"
    await uow.session.flush()
    assert await service.encountered_event_ids() == [first, second]
    assert await service.get_encounter(third) is None


async def test_domain_rebuild_of_a_row_goes_through_the_codec(uow):
    service = DdEncounterService(uow)
    event_id = await _make_event(uow)
    await service.save_encounter(event_id, [_entry(mid=2, count=7, name="Огр")], "ноты")
    row = await DdEncounterRepository(uow.session).get_row(event_id)
    encounter = encounter_to_domain(row)
    assert encounter.event_id == event_id
    assert encounter.entries == (_entry(mid=2, count=7, name="Огр"),)
    assert encounter.note == "ноты"


async def test_overlay_row_is_in_the_dd_wave():
    from app.dd.infrastructure.db.dd_models import DD_TABLES

    assert DdEncounterModel.__tablename__ == "dd_encounter"
    assert DdEncounterModel.__table__ in DD_TABLES
