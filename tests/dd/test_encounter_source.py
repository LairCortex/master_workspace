"""Источник «Встреча» (add-dnd-game-face task 11.1/11.2; spec dnd-encounters).

Три вещи, которые здесь живут, пинуются точно:

* двери-заглушки: ни типов, ни поиска, ни карточек — весь вклад источника
  это таб события и пометки лестницы (spec «не отдельная сущность»);
* таб отвечает ТОЛЬКО событию и ТОЛЬКО живому модулю (duck-дверь
  ``set_attached`` фасада; spec «При недоступном модуле таб SHALL отсутствовать
  без следа», «Без модуля таба нет»);
* пометки — синхронная дверь из кэша: warm обновляет, apply_saved мирит
  на месте (connector перезагружает лестницу сразу после сохранения),
  тёмный источник не отвечает никому.
"""
from __future__ import annotations

import asyncio

import pytest

from app.dd.presentation.dd_encounter_source import (
    ENCOUNTER_MARK,
    ENCOUNTER_TAB_KEY,
    ENCOUNTER_TAB_TITLE,
    DndEncounterSource,
)
from app.presentation.modules.protocol import CardTabTarget


class _Encounters:
    def __init__(self, ids=None, fail=False):
        self.ids = list(ids or [])
        self.fail = fail
        self.calls = 0

    async def encountered_event_ids(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("диск отказал")
        return list(self.ids)

    async def get_encounter(self, event_id):
        return None


class _Monsters:
    async def list_monsters(self):
        return []


def _target(key="event", row_id="7") -> CardTabTarget:
    return CardTabTarget(key=key, source_id=row_id)


def _attached(ids=None, fail=False) -> DndEncounterSource:
    source = DndEncounterSource(
        encounter_service=_Encounters(ids, fail), monster_service=_Monsters()
    )
    source.set_attached(True)
    return source


def test_declares_no_types_and_no_records():
    source = _attached([1, 2])
    assert source.type_descriptors == ()
    assert source.card_source("event", "7") is None
    assert source.resolve_mention("event", "7") is None


async def test_search_and_mentions_stay_empty():
    source = _attached([1])
    assert await source.search("засада") == ()
    assert await source.mention_candidates("засада") == ()


def test_dark_source_answers_nothing():
    source = DndEncounterSource(
        encounter_service=_Encounters([1]), monster_service=_Monsters()
    )
    assert source.visible is False
    assert source.card_tabs(_target()) == ()
    assert source.event_marks([1]) == {}
    assert source._encounters.calls == 0  # warm тёмного источника не читает


async def test_dark_warm_reads_nothing():
    encounters = _Encounters([1])
    source = DndEncounterSource(
        encounter_service=encounters, monster_service=_Monsters()
    )
    await source.warm()
    assert encounters.calls == 0


async def test_warm_fills_the_cache_tab_and_marks_answer():
    source = _attached([3, 5])
    await source.warm()
    assert source.visible is True
    assert source.event_marks([1, 3, 5, 9]) == {3: ENCOUNTER_MARK, 5: ENCOUNTER_MARK}


async def test_tab_spec_is_the_kernel_event_only():
    source = _attached([])
    await source.warm()
    tabs = source.card_tabs(_target(key="event"))
    assert [(tab.key, tab.title) for tab in tabs] == [
        (ENCOUNTER_TAB_KEY, ENCOUNTER_TAB_TITLE)
    ]
    assert tabs[0].factory == source._build_tab  # bound methods: ==, not is
    assert source.card_tabs(_target(key="character")) == ()


async def test_apply_saved_reconciles_in_place():
    source = _attached([1])
    await source.warm()
    source.apply_saved(1, False)  # встреча разбита сохранением
    source.apply_saved(2, True)  # новая встреча
    assert source.event_marks([1, 2]) == {2: ENCOUNTER_MARK}
    assert source.event_marks([1]) == {}  # absent = no mark, not a False entry


async def test_detached_source_hides_data_marks_and_tabs():
    source = _attached([1, 2])
    await source.warm()
    source.set_attached(False)  # фасад снял модуль (spec: пометки — не данные)
    assert source.visible is False
    assert source.event_marks([1, 2]) == {}
    assert source.card_tabs(_target()) == ()


async def test_warm_failure_is_the_sources_own_silence():
    source = _attached(fail=True)
    await source.warm()  # не бросает — протокольная тишина warm
    assert source.event_marks([1]) == {}


async def test_foreign_id_raises_for_the_hosts_tolerant_door():
    source = _attached([])
    with pytest.raises(ValueError):
        source._event_id("не-число")
    assert source._event_id("42") == 42


# ── factory doors (the tab's construction, the frames' own suite aside) ─────


class _WiringWithoutLock:
    """A read-only half-card: without the connector's lock door the honest
    verdict is the raise — the host journals and skips the one tab."""


class _WiringWithLock:
    def __init__(self):
        self.tasks = []

    def run_locked(self, coro):
        task = asyncio.ensure_future(coro)
        self.tasks.append(task)
        return task


async def test_factory_refuses_a_card_without_a_connector():
    source = _attached([])
    with pytest.raises(TypeError):
        source._build_tab(_WiringWithoutLock(), "7")


async def test_factory_builds_the_frame_on_a_whole_id(qtbot):
    from app.dd.presentation.dd_encounter_frame import DndEncounterTabFrame

    source = _attached([])
    wiring = _WiringWithLock()
    frame = source._build_tab(wiring, "7")
    qtbot.addWidget(frame)
    assert isinstance(frame, DndEncounterTabFrame)
    # The constructor opened one locked load; let it settle.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert len(wiring.tasks) == 1
    assert wiring.tasks[0].done() and not wiring.tasks[0].cancelled()
    wiring.tasks[0].result()


async def test_factory_refuses_a_foreign_id(qtbot):
    source = _attached([])
    with pytest.raises(ValueError):
        source._build_tab(_WiringWithLock(), "не-число")
