"""The character-tab source: module-lifetime visibility, the three tabs, the
wiring gate (add-dnd-game-face tasks 8.2/8.3; the lineup reworked by
dd-card-redesign task 5.5 — spec entity-card-tabs «Таб модуля живёт с
модулем», spec dnd-character-extension «Вкладки модуля на карточке
персонажа» «выключение модуля SHALL гасить табы»).

The source is tested as the kernel sees it — through the protocol doors —
plus its three factory doors (the frames' own behavior belongs to the frame
tests). No module type is registered here, no records are searched: this
source's whole tab contribution is the trio «Способности», «Личность»,
«Заклинания» that completes the kernel's «Основное» into the four-tab
lineup, and the dark-until-attached posture is the guarantee the disable
flow relies on.
"""
from __future__ import annotations

import asyncio

import pytest

from app.dd.presentation.character_tab_source import (
    FEATS_TAB_KEY,
    FEATS_TAB_TITLE,
    PERSONALITY_TAB_KEY,
    PERSONALITY_TAB_TITLE,
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


def test_three_tabs_only_for_a_character_only_while_attached():
    source = _source()
    source.set_attached(True)
    specs = source.card_tabs(CardTabTarget("character", "42"))
    # The module tail of the spec's four-tab lineup, in the spec's order
    # (the kernel's «Основное» heads the strip; these three append after
    # it — the tab key of the retired «D&D» tab is gone for good).
    assert [(spec.key, spec.title) for spec in specs] == [
        (FEATS_TAB_KEY, FEATS_TAB_TITLE),
        (PERSONALITY_TAB_KEY, PERSONALITY_TAB_TITLE),
        (SPELLS_TAB_KEY, SPELLS_TAB_TITLE),
    ]
    assert "dnd.sheet" not in [spec.key for spec in specs]
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
        source._build_feats_tab(_WiringWithoutLock(), "7")
    with pytest.raises(TypeError):
        source._build_personality_tab(_WiringWithoutLock(), "7")
    with pytest.raises(TypeError):
        source._build_spells_tab(_WiringWithoutLock(), "7")


async def test_factory_builds_all_three_frames_on_a_whole_id(qtbot):
    from app.dd.domain.character import empty_ext
    from app.dd.domain.character_mechanics import empty_mechanics
    from app.dd.presentation.character_feats_frame import DndFeatsTabFrame
    from app.dd.presentation.character_personality_frame import (
        DndPersonalityTabFrame,
    )
    from app.dd.presentation.character_tab_frames import DndSpellsTabFrame

    class _StubService:
        async def get_ext(self, character_id):
            return empty_ext()

        async def get_mechanics(self, character_id):
            return empty_mechanics()

        async def get_spell_links(self, character_id):
            return []

        async def get_feat_links(self, character_id):
            return []

        async def get_text_blocks(self, character_id):
            return {}

    source = DndCharacterTabSource(
        character_service=_StubService(),
        dataset_index=_StubIndex(),
        grimoire_index=None,
    )
    source.set_attached(True)
    wiring = _WiringWithLock()
    feats = source._build_feats_tab(wiring, "7")
    personality = source._build_personality_tab(wiring, "7")
    spells = source._build_spells_tab(wiring, "7")
    qtbot.addWidget(feats)
    qtbot.addWidget(personality)
    qtbot.addWidget(spells)
    assert isinstance(feats, DndFeatsTabFrame)
    assert isinstance(personality, DndPersonalityTabFrame)
    assert isinstance(spells, DndSpellsTabFrame)
    # Each frame's constructor opened one locked load; let them settle.
    for _ in range(8):
        await asyncio.sleep(0)
    assert len(wiring.tasks) == 3
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
        source._build_feats_tab(wiring, "not-a-number")
    with pytest.raises(ValueError):
        source._build_personality_tab(wiring, "not-a-number")
    with pytest.raises(ValueError):
        source._build_spells_tab(wiring, "not-a-number")


# ── the fresh card (checkpoint-2 audit; spec «Новая карточка с пустыми
#    разделами») ─────────────────────────────────────────────────────────────


def test_the_fresh_card_gets_the_same_lineup_on_the_empty_id():
    # The tab lineup never depends on the record existing — a fresh card
    # opens with the three module tabs standing; the emptiness lives in the
    # sections, not in the strip (spec «Пустое событие тоже с двумя табами»
    # is the event-side twin of the same rule).
    source = _source()
    source.set_attached(True)
    specs = source.card_tabs(CardTabTarget("character", ""))
    assert [spec.key for spec in specs] == [
        FEATS_TAB_KEY,
        PERSONALITY_TAB_KEY,
        SPELLS_TAB_KEY,
    ]
    assert source.card_tabs(CardTabTarget("location", "")) == ()


async def test_factory_builds_the_frames_unsaved_on_the_empty_id(qtbot):
    # The empty id is the frames' None: the character half stays unopened,
    # while each frame still reads its dataset door once and paints the
    # honest empty face (checkpoint-2 audit; spec «Новая карточка с пустыми
    # разделами»).
    source = _source()
    source.set_attached(True)
    wiring = _WiringWithLock()
    feats = source._build_feats_tab(wiring, "")
    personality = source._build_personality_tab(wiring, "")
    spells = source._build_spells_tab(wiring, "")
    qtbot.addWidget(feats)
    qtbot.addWidget(personality)
    qtbot.addWidget(spells)
    assert feats._character_id is None
    assert personality._character_id is None
    assert spells._character_id is None
    for _ in range(8):
        await asyncio.sleep(0)
    assert len(wiring.tasks) == 3  # one dataset-only read each
    for task in wiring.tasks:
        assert task.done() and not task.cancelled()
        task.result()


async def test_creation_door_stands_the_extension_up():
    calls: list[tuple] = []

    class _ExtService:
        async def ensure_ext(self, character_id):
            calls.append(character_id)

    source = DndCharacterTabSource(
        character_service=_ExtService(),
        dataset_index=_StubIndex(),
        grimoire_index=None,
    )
    # detached: the door answers nothing (the module is not on the table)
    await source.on_entity_created("character", "5")
    assert calls == []
    source.set_attached(True)
    # foreign keys answer nothing; the character's new row gets its extension
    await source.on_entity_created("location", "5")
    assert calls == []
    await source.on_entity_created("character", "5")
    assert calls == [5]  # the protocol string became the kernel int


# ── the preview mirror door (dd-card-redesign task 7.1, design Д5) ──────────


class _MirrorService:
    """The six read doors of the mirror, in one place; the door's sequential
    posture (one shared session) is pinned by the recorded order."""

    def __init__(self, ext=None, mech=None, fail=False):
        from app.dd.domain.character import empty_ext
        from app.dd.domain.character_mechanics import CharacterMechanics

        self.ext = empty_ext() if ext is None else ext
        self.mech = CharacterMechanics() if mech is None else mech
        self.fail = fail
        self.calls: list[str] = []

    async def get_ext(self, character_id):
        self.calls.append("ext")
        self._raise_if()
        return self.ext

    async def get_mechanics(self, character_id):
        self.calls.append("mech")
        return self.mech

    async def get_feat_links(self, character_id):
        self.calls.append("feats")
        return []

    async def get_spell_links(self, character_id):
        self.calls.append("spells")
        return []

    async def get_text_blocks(self, character_id):
        self.calls.append("blocks")
        self._raise_if()
        return {"Возраст": "47"}

    async def get_saving_throw_profs(self, character_id):  # pragma: no cover
        raise AssertionError("the mirror resolves saves through the class")

    def _raise_if(self):
        if self.fail:
            raise RuntimeError("диск отказал")


def _mirror_source(service=None, index=None) -> DndCharacterTabSource:
    from app.dd.application.dataset_index_service import IndexSnapshot

    class _Snap:
        async def snapshot(self):
            return IndexSnapshot(ids=(), titles={}, sections={}, slugs={})

    source = DndCharacterTabSource(
        character_service=service if service is not None else _MirrorService(),
        dataset_index=index if index is not None else _Snap(),
    )
    source.set_attached(True)
    return source


async def test_mirror_dark_or_foreign_answers_empty_without_reading():
    service = _MirrorService()
    source = _mirror_source(service)
    source.set_attached(False)
    assert await source.module_sections("character", "3") == ()
    source.set_attached(True)
    assert await source.module_sections("event", "3") == ()
    assert service.calls == []


async def test_mirror_reads_the_stored_face_in_order():
    from dataclasses import replace

    from app.dd.domain.character import ReferenceLink, empty_ext

    ext = replace(
        replace(empty_ext(), level=3),
    )
    ext.links["race"] = ReferenceLink("srd", "dwarf", "Дворф")
    service = _MirrorService(ext=ext)
    source = _mirror_source(service)
    sections = await source.module_sections("character", "3")
    assert service.calls == ["ext", "mech", "feats", "spells", "blocks"]
    titles = [section.title for section in sections]
    assert titles == ["Происхождение", "Личность"]
    # The empty stub snapshot honestly marks the link dead — the wording
    # seat itself is pinned in tests/dd/test_character_preview_sections.py.
    assert sections[0].lines == (
        "Вид: Дворф — источник не подключён",
        "Уровень: 3",
    )
    assert sections[1].lines == ("Возраст: 47",)


async def test_mirror_refuses_a_foreign_id_like_every_other_door():
    source = _mirror_source()
    with pytest.raises(ValueError):
        await source.module_sections("character", "не-число")


async def test_mirror_failure_propagates_to_the_bridge():
    """The door itself does not swallow: the connector's bridge is the one
    tolerant seat (journal-and-silence), pinned in
    tests/presentation/test_wiring_preview_slots.py."""
    source = _mirror_source(_MirrorService(fail=True))
    with pytest.raises(RuntimeError):
        await source.module_sections("character", "3")
