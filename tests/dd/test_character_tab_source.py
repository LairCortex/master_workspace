"""The character-tab source: module-lifetime visibility, the two tabs, the
wiring gate (add-dnd-game-face tasks 8.2/8.3, spec entity-card-tabs «Таб
модуля живёт с модулем», spec dnd-character-extension «выключение модуля
SHALL гасить табы»).

The source is tested as the kernel sees it — through the protocol doors —
plus its two factory doors (the frames' own behavior belongs to the frame
tests). No module type is registered here, no records are searched: this
source's whole contribution is the tab pair, and the dark-until-attached
posture is the guarantee the disable flow relies on.
"""
from __future__ import annotations

import asyncio

import pytest

from app.dd.presentation.character_tab_source import (
    CHARACTER_TAB_KEY,
    CHARACTER_TAB_TITLE,
    SPELLS_TAB_KEY,
    SPELLS_TAB_TITLE,
    DndCharacterTabSource,
)
from app.presentation.modules.protocol import CardTabTarget


class _StubIndex:
    async def snapshot(self):
        from app.dd.application.dataset_index_service import IndexSnapshot

        return IndexSnapshot(ids=(), titles={}, sections={}, slugs={})


def _source() -> DndCharacterTabSource:
    return DndCharacterTabSource(
        character_service=object(),
        dataset_index=_StubIndex(),
        grimoire_index=None,
    )


def test_dark_until_the_module_attaches():
    source = _source()
    assert source.visible is False
    assert source.card_tabs(CardTabTarget("character", "1")) == ()
    source.set_attached(True)
    assert source.visible is True
    source.set_attached(False)
    assert source.visible is False
    assert source.card_tabs(CardTabTarget("character", "1")) == ()


def test_two_tabs_only_for_a_character_only_while_attached():
    source = _source()
    source.set_attached(True)
    specs = source.card_tabs(CardTabTarget("character", "42"))
    assert [(spec.key, spec.title) for spec in specs] == [
        (CHARACTER_TAB_KEY, CHARACTER_TAB_TITLE),
        (SPELLS_TAB_KEY, SPELLS_TAB_TITLE),
    ]
    # A foreign target cannot be addressed — honest empty, not a guess.
    assert source.card_tabs(CardTabTarget("location", "42")) == ()


async def test_declares_no_types_and_stays_quiet_on_every_other_door():
    source = _source()
    source.set_attached(True)
    assert source.type_descriptors == ()
    assert await source.warm() is None
    assert await source.search("огненный") == ()
    assert await source.mention_candidates("ог") == ()
    assert source.card_source("dd_race", "x") is None
    assert source.resolve_mention("dd_race", "x") is None
    assert source.event_marks([1, 2]) == {}


def test_default_record_labels_come_from_the_declared_descriptors():
    source = _source()  # record_labels=None → the RECORD_TYPES door
    from app.dd.presentation.reference_source import RECORD_TYPES

    # The map rides the table: type key → singular caption.
    expected = {descriptor.key: descriptor.label for _section, descriptor in RECORD_TYPES}
    assert source._record_labels == expected
    # The five link captions resolve from the same table (a missing key
    # would raise at frame construction, not silently print a code).
    from app.dd.domain.character import LINK_SLOTS

    for _slot, _section, type_key in LINK_SLOTS:
        assert source._record_labels[type_key] == expected[type_key]


class _WiringWithoutLock:
    pass


class _WiringWithLock:
    def __init__(self):
        self.tasks: list[asyncio.Task] = []

    def run_locked(self, coro):
        task = asyncio.ensure_future(coro)
        self.tasks.append(task)
        return task


async def test_factory_refuses_a_card_without_a_connector():
    # A read-only half-tab would be the worse lie — the raise reaches the
    # host's journal-and-skip door.
    source = _source()
    source.set_attached(True)
    with pytest.raises(TypeError):
        source._build_character_tab(_WiringWithoutLock(), "7")
    with pytest.raises(TypeError):
        source._build_spells_tab(_WiringWithoutLock(), "7")


async def test_factory_builds_both_frames_on_a_whole_id(qtbot):
    from app.dd.domain.character import empty_ext
    from app.dd.presentation.character_tab_frames import (
        DndCharacterTabFrame,
        DndSpellsTabFrame,
    )

    class _StubService:
        async def get_ext(self, character_id):
            return empty_ext()

        async def get_spell_links(self, character_id):
            return []

    source = DndCharacterTabSource(
        character_service=_StubService(),
        dataset_index=_StubIndex(),
        grimoire_index=None,
    )
    source.set_attached(True)
    wiring = _WiringWithLock()
    character = source._build_character_tab(wiring, "7")
    spells = source._build_spells_tab(wiring, "7")
    qtbot.addWidget(character)
    qtbot.addWidget(spells)
    assert isinstance(character, DndCharacterTabFrame)
    assert isinstance(spells, DndSpellsTabFrame)
    # Each frame's constructor opened one locked load; let them settle.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert len(wiring.tasks) == 2
    for task in wiring.tasks:
        assert task.done() and not task.cancelled()
        task.result()


async def test_factory_refuses_a_foreign_id(qtbot):
    # A non-whole target id is a composition bug; the honest verdict is the
    # raise, which the host turns into journal-and-skip for that one tab.
    source = _source()
    source.set_attached(True)
    wiring = _WiringWithLock()
    with pytest.raises(ValueError):
        source._build_character_tab(wiring, "not-a-number")
    with pytest.raises(ValueError):
        source._build_spells_tab(wiring, "not-a-number")
