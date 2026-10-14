"""The shared module-tab doors and the «Заклинания» frame of a character card
(add-dnd-game-face tasks 8.2/8.3; the slot grid of dd-card-redesign task 5.4;
the «D&D» tab frame retired by task 5.5 — its pickers, level and sheet field
are pinned in ``test_character_main_blocks.py``, its history picker moved to
«Личность»).

The frames are the module's half of the card; the kernel host is tested
apart. What is pinned here is the contract the reader gets:

* the «Заклинания» tab: bindings print their origin through the two read
  doors (SRD slugs, then grimoires), add and remove reload inside the one
  locked coroutine, the candidate list is filterable and capped;
* the slot grid under the list (spec dnd-character-mechanics «Ячейки
  заклинаний — сетка уровней»): nine fields, the stored counts printed,
  each field commits its level on editingFinished inside one write+reload,
  an untouched field is no transaction, and a number past the validator's
  gate is refused in the frame before the service ever sees it;
* failure posture: a failed load or write is one modeless Russian box;
* release posture: ``release_tab`` cancels the in-flight work in silence.

The service/index/grimoire doors are stubs — the storage floor belongs to
``test_character_extension.py``; what matters here is which triple the frame
hands out and what the reader can see.
"""
from __future__ import annotations

import asyncio

from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QLabel, QLineEdit, QMessageBox, QPushButton

from app.dd.application.dataset_index_service import DatasetEntry, IndexSnapshot
from app.dd.application.grimoire_index_service import GrimoireIndexSnapshot
from app.dd.domain.character import DdSpellLink
from app.dd.domain.character_mechanics import CharacterMechanics
from app.dd.presentation.character_tab_frames import (
    SOURCE_UNAVAILABLE_NOTE,
    DndSpellsTabFrame,
    lss_sheet_url,
)


async def _drain(times: int = 8) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


class _StubService:
    """The service door as the spells frame sees it: canned answers,
    recorded asks."""

    def __init__(
        self,
        links: list[DdSpellLink] | None = None,
        slots: dict[int, int] | None = None,
        fail_load: bool = False,
        fail_write: bool = False,
    ) -> None:
        self.links = list(links or [])
        self.mechanics = CharacterMechanics(spell_slots=dict(slots or {}))
        self.fail_load = fail_load
        self.fail_write = fail_write
        self.asks: list[tuple] = []

    def slots_asks(self) -> list[tuple]:
        return [ask for ask in self.asks if ask[0] == "slots"]

    async def get_spell_links(self, character_id):
        self.asks.append(("get_links", character_id))
        if self.fail_load:
            raise RuntimeError("диск отказал")
        return list(self.links)

    async def get_mechanics(self, character_id):
        self.asks.append(("get_mechanics", character_id))
        if self.fail_load:
            raise RuntimeError("диск отказал")
        return self.mechanics

    async def add_spell_link(self, character_id, link):
        self.asks.append(("add", link))
        if self.fail_write:
            raise RuntimeError("запись не прошла")
        self.links.append(link)

    async def remove_spell_link(self, character_id, source_key, slug):
        self.asks.append(("remove", source_key, slug))
        if self.fail_write:
            raise RuntimeError("запись не прошла")
        self.links = [
            link
            for link in self.links
            if (link.source_key, link.slug) != (source_key, slug)
        ]

    async def set_spell_slots(self, character_id, slots):
        self.asks.append(("slots", dict(slots)))
        if self.fail_write:
            raise RuntimeError("запись не прошла")
        self.mechanics = CharacterMechanics(spell_slots=dict(slots))


class _StubIndex:
    def __init__(self, snap: IndexSnapshot) -> None:
        self._snap = snap

    async def snapshot(self):
        return self._snap


def _snapshot_with_entries() -> IndexSnapshot:
    """One connected set; the spell-slug half is the spells tab's SRD door
    (the races section keeps the snapshot shape honest)."""
    return IndexSnapshot(
        ids=("srd",),
        titles={"srd": "SRD-5.1"},
        sections={
            "races": {
                "srd": (
                    DatasetEntry("srd", "dwarf", "Дворф", {}),
                    DatasetEntry("srd", "elf", "Эльф", {}),
                )
            }
        },
        slugs={"srd": ("fire-bolt", "mage-hand")},
    )


def _grimoire_snapshot() -> GrimoireIndexSnapshot:
    from app.dd.domain.grimoire import GrimoireSpell

    return GrimoireIndexSnapshot(
        ids=("grim",),
        titles={"grim": "Гримуар А"},
        spells={
            "grim": {"witch-sight": GrimoireSpell("witch-sight", "Ведьмин глаз", "…")}
        },
    )


def _run_locked(coro):
    return asyncio.ensure_future(coro)


def _boxes(frame) -> list[QMessageBox]:
    # The frame itself stays hidden offscreen; ``isHidden`` reads the box's
    # own explicit hide — a shown modeless box answers False.
    return [box for box in frame.findChildren(QMessageBox) if not box.isHidden()]


# ── the LSS door ──────────────────────────────────────────────────────────


def test_lss_sheet_url_trims_and_fills_the_digital_page():
    assert (
        lss_sheet_url(" abc123 ")
        == "https://longstoryshort.app/iframe/characters/digital/abc123/"
    )


def test_source_unavailable_note_is_the_single_fixed_wording():
    """fix-dnd-followups 4.2 (spec dnd-character-extension «Снятый датасет не
    калечит карточку» / dnd-reference-records): пометка недоступного источника
    — дословно «источник не подключён». Ровно одно сравнение с литералом;
    поверхности модуля, печатающие запись с недоступным источником (пики
    блока «Основное», строки табов «Заклинания» и «Способности» — остальные
    справочные поверхности по построению недоступных записей не показывают),
    несут ЭТУ константу: их пины ниже сравнивают текст строки с константой,
    цепочка «поверхность = константа = литерал» замкнута."""
    assert SOURCE_UNAVAILABLE_NOTE == "источник не подключён"


# ── the «Заклинания» tab ──────────────────────────────────────────────────


def _spells_links() -> list[DdSpellLink]:
    return [
        DdSpellLink("srd", "fire-bolt", "Fire bolt"),
        DdSpellLink("grim", "witch-sight", "Ведьмин глаз"),
        DdSpellLink("gone", "x", "Мёртвый"),
    ]


async def _open_spells_tab(qtbot, service, *, grimoire="default") -> DndSpellsTabFrame:
    class _StubGrimoire:
        def __init__(self, snap):
            self._snap = snap

        async def snapshot(self):
            return self._snap

    frame = DndSpellsTabFrame(
        character_id=7,
        service=service,
        dataset_index=_StubIndex(_snapshot_with_entries()),
        grimoire_index=(
            _StubGrimoire(_grimoire_snapshot())
            if grimoire == "default"
            else None
        ),
        run_locked=_run_locked,
    )
    qtbot.addWidget(frame)
    await _drain()
    return frame


async def test_spells_tab_prints_bindings_with_their_origins(qtbot):
    service = _StubService(links=_spells_links())
    frame = await _open_spells_tab(qtbot, service)
    captions = [
        label.text() for label in frame.findChildren(QLabel, "ddSpellsRowName")
    ]
    assert captions == [
        "Fire bolt · SRD-5.1",
        "Ведьмин глаз · Гримуар А",
        f"Мёртвый — {SOURCE_UNAVAILABLE_NOTE}",
    ]
    assert len(frame.findChildren(QPushButton, "ddSpellsRemove")) == 3


async def test_spells_tab_empty_states(qtbot):
    from app.dd.application.grimoire_index_service import GrimoireIndexSnapshot

    service = _StubService(links=[])
    frame = await _open_spells_tab(qtbot, service)
    assert frame.findChild(QLabel, "ddSpellsEmpty").text().startswith("Пока нет")
    # candidates exist (fire-bolt/mage-hand + the grimoire spell)
    assert frame.findChildren(QPushButton, "ddSpellsCandidate")
    # nothing connected at all → the explanation replaces the list
    empty_index = IndexSnapshot(ids=(), titles={}, sections={}, slugs={})
    frame._snap = empty_index
    frame._gsnap = GrimoireIndexSnapshot(ids=(), titles={}, spells={})
    frame._render_candidates()
    assert frame.findChild(QLabel, "ddSpellsNoCandidates") is not None


async def test_spells_tab_candidates_exclude_bound_and_filter(qtbot):
    service = _StubService(links=_spells_links())
    frame = await _open_spells_tab(qtbot, service)
    captions = [
        button.text()
        for button in frame.findChildren(QPushButton, "ddSpellsCandidate")
    ]
    # all three bindings live, only the unbound SRD slug can be added;
    # its name rides the humanization
    assert captions == ["Добавить: Mage hand · SRD-5.1"]
    frame.findChild(QLineEdit, "ddSpellsFilter").setText("mage")
    assert len(frame.findChildren(QPushButton, "ddSpellsCandidate")) == 1
    # a needle that hits nothing replaces the wall with the explanation
    frame.findChild(QLineEdit, "ddSpellsFilter").setText("глаз")
    assert frame.findChildren(QPushButton, "ddSpellsCandidate") == []
    assert frame.findChild(QLabel, "ddSpellsNoCandidates") is not None
    # the filter runs through the grimoire half too (its spell neither
    # matches by name nor by slug here)
    frame.findChild(QLineEdit, "ddSpellsFilter").setText("fire")
    assert frame.findChildren(QPushButton, "ddSpellsCandidate") == []


async def test_spells_tab_add_click_binds_and_reloads_in_one_wave(qtbot):
    # fire-bolt stays bound, the grimoire spell is last — «Mage hand» is the
    # first candidate button the click can reach.
    links = [_spells_links()[0], _spells_links()[2]]
    service = _StubService(links=links)
    frame = await _open_spells_tab(qtbot, service)
    add_buttons = frame.findChildren(QPushButton, "ddSpellsCandidate")
    add_buttons[0].click()  # «Mage hand · SRD-5.1»
    await _drain()
    mage = DdSpellLink("srd", "mage-hand", "Mage hand")
    # the write and the reload are ONE coroutine: exactly one read pair
    # followed the add — no second refresh rides the done-callback.
    assert service.asks == [
        ("get_links", 7),
        ("get_mechanics", 7),
        ("add", mage),
        ("get_links", 7),
        ("get_mechanics", 7),
    ]
    names = [label.text() for label in frame.findChildren(QLabel, "ddSpellsRowName")]
    assert "Mage hand · SRD-5.1" in names
    # the filter also crosses the grimoire half: «hand» matches neither the
    # unbound grimoire spell's name nor its slug
    frame.findChild(QLineEdit, "ddSpellsFilter").setText("hand")
    assert frame.findChildren(QPushButton, "ddSpellsCandidate") == []


async def test_spells_tab_remove_click_unbinds_and_reloads(qtbot):
    service = _StubService(links=_spells_links())
    frame = await _open_spells_tab(qtbot, service)
    frame.findChildren(QPushButton, "ddSpellsRemove")[1].click()  # Ведьмин глаз
    await _drain()
    assert ("remove", "grim", "witch-sight") in service.asks
    assert service.asks[-1] == ("get_mechanics", 7)  # reload rode the same wave
    names = [label.text() for label in frame.findChildren(QLabel, "ddSpellsRowName")]
    assert "Ведьмин глаз · Гримуар А" not in names


async def test_spells_tab_caps_the_candidate_wall(qtbot):
    service = _StubService(links=[])
    frame = await _open_spells_tab(qtbot, service)
    big = IndexSnapshot(
        ids=("srd",),
        titles={"srd": "SRD"},
        sections={},
        slugs={"srd": tuple(f"spell-{i:03d}" for i in range(60))},
    )
    frame._snap = big
    # the grimoire spell is out of this reading — the cap math is the point
    from app.dd.application.grimoire_index_service import GrimoireIndexSnapshot

    frame._gsnap = GrimoireIndexSnapshot(ids=(), titles={}, spells={})
    frame._render_candidates()
    assert len(frame.findChildren(QPushButton, "ddSpellsCandidate")) == 50
    cap = frame.findChild(QLabel, "ddSpellsCandidateCap")
    assert "Показаны первые 50" in cap.text() and "ещё 10" in cap.text()


async def test_spells_tab_without_the_grimoire_door_reads_an_empty_shelf(qtbot):
    service = _StubService(links=[])
    frame = await _open_spells_tab(qtbot, service, grimoire=None)
    captions = [
        button.text()
        for button in frame.findChildren(QPushButton, "ddSpellsCandidate")
    ]
    assert captions == [
        "Добавить: Fire bolt · SRD-5.1",
        "Добавить: Mage hand · SRD-5.1",
    ]


async def test_spells_tab_failures_are_modeless_boxes(qtbot):
    service = _StubService(fail_load=True)
    frame = await _open_spells_tab(qtbot, service)
    boxes = _boxes(frame)
    assert len(boxes) == 1
    assert "Не удалось загрузить привязки заклинаний" in boxes[0].text()
    boxes[0].button(QMessageBox.StandardButton.Ok).click()
    assert frame._notice_box is None

    # the tab recovers by itself: a successful refresh paints the surface…
    service.fail_load = False
    service.fail_write = True
    frame.request_refresh()
    await _drain()
    add_buttons = frame.findChildren(QPushButton, "ddSpellsCandidate")
    assert add_buttons
    # …and a failed write is its own single modeless box
    add_buttons[0].click()
    await _drain()
    boxes = _boxes(frame)
    assert len(boxes) == 1
    assert "Не удалось выполнить действие" in boxes[0].text()


# ── the slot grid (dd-card-redesign task 5.4; spec «Ячейки заклинаний —
# сетка уровней», «Ячейки под списком», «„не задано“») ────────────────────


async def test_slot_grid_prints_nine_fields_the_stored_counts_and_the_gate(qtbot):
    service = _StubService(slots={1: 4, 9: 0})
    frame = await _open_spells_tab(qtbot, service)
    for level in range(1, 10):
        edit = frame.findChild(QLineEdit, f"ddSpellsSlot_{level}")
        assert edit is not None
        assert edit.accessibleName() == f"Ячейки {level} уровня"
        assert edit.placeholderText() == "не задано"
        # the interactive gate: only whole 0…99 can be typed (spec «0…99»)
        validator = edit.validator()
        assert isinstance(validator, QIntValidator)
        assert (validator.bottom(), validator.top()) == (0, 99)
    # stored counts print verbatim — including the stored ZERO (0 slots is
    # a fact, «не задано» is the ABSENT level); absent levels print empty.
    assert frame.findChild(QLineEdit, "ddSpellsSlot_1").text() == "4"
    assert frame.findChild(QLineEdit, "ddSpellsSlot_9").text() == "0"
    assert frame.findChild(QLineEdit, "ddSpellsSlot_5").text() == ""
    # the grid stands under the binding list («под списком» verbatim): the
    # header sequence in the tab is bindings → slots → candidates.
    headers = [label.text() for label in frame.findChildren(QLabel, "ddSpellsHeader")]
    assert headers == [
        "Привязанные заклинания",
        "Ячейки заклинаний",
        "Добавить из подключённых словарей",
    ]


async def test_slot_edit_commits_its_level_and_repaints(qtbot):
    service = _StubService(slots={1: 4})
    frame = await _open_spells_tab(qtbot, service)
    third = frame.findChild(QLineEdit, "ddSpellsSlot_3")
    third.setText("2")
    third.editingFinished.emit()  # focus leaves a changed field → one write
    await _drain()
    # the whole map rides with the one edited level (the service door stores
    # the map; the frame merges its level into what it believes is stored)
    assert service.slots_asks() == [("slots", {1: 4, 3: 2})]
    assert frame.findChild(QLineEdit, "ddSpellsSlot_3").text() == "2"
    # the write reloaded inside its own wave: one read pair followed it
    assert service.asks[-2:] == [("get_links", 7), ("get_mechanics", 7)]


async def test_slot_cleared_back_to_unset_drops_the_level(qtbot):
    service = _StubService(slots={1: 4, 2: 3})
    frame = await _open_spells_tab(qtbot, service)
    second = frame.findChild(QLineEdit, "ddSpellsSlot_2")
    second.setText("")
    second.editingFinished.emit()
    await _drain()
    assert service.slots_asks() == [("slots", {1: 4})]
    assert frame.findChild(QLineEdit, "ddSpellsSlot_2").text() == ""


async def test_untouched_slot_field_losing_focus_saves_nothing(qtbot):
    service = _StubService(slots={1: 4})
    frame = await _open_spells_tab(qtbot, service)
    first = frame.findChild(QLineEdit, "ddSpellsSlot_1")
    first.editingFinished.emit()  # the belt: focus left an untouched field
    await _drain()
    assert service.slots_asks() == []


async def test_slot_value_past_the_gate_is_refused_before_the_service(qtbot):
    # setText rides past the QIntValidator (the gate is interactive), so the
    # commit repeats it: the belt refuses without asking the service.
    service = _StubService(slots={1: 4})
    frame = await _open_spells_tab(qtbot, service)
    first = frame.findChild(QLineEdit, "ddSpellsSlot_1")
    first.setText("150")
    first.editingFinished.emit()
    await _drain()
    assert service.slots_asks() == []
    boxes = _boxes(frame)
    assert len(boxes) == 1
    assert "от 0 до 99" in boxes[0].text()
    # the refusal leaves the frame's belief (and the next honest commit)
    # untouched: committing a real number still merges with the STORED 4.
    first.setText("5")
    first.editingFinished.emit()
    await _drain()
    assert service.slots_asks() == [("slots", {1: 5})]
    boxes[0].button(QMessageBox.StandardButton.Ok).click()

    # non-numeric garbage gets the same single box
    first.setText("abc")
    first.editingFinished.emit()
    await _drain()
    assert len(_boxes(frame)) == 1
    assert "от 0 до 99" in _boxes(frame)[0].text()


async def test_slot_write_failure_notices_once(qtbot):
    service = _StubService(slots={1: 4}, fail_write=True)
    frame = await _open_spells_tab(qtbot, service)
    first = frame.findChild(QLineEdit, "ddSpellsSlot_1")
    first.setText("7")
    first.editingFinished.emit()
    await _drain()
    boxes = _boxes(frame)
    assert len(boxes) == 1
    assert "Не удалось выполнить действие" in boxes[0].text()
    assert "ячеек" in boxes[0].text()


async def test_release_tab_cancels_in_flight_load_in_silence(qtbot):
    gate = asyncio.Event()

    class _SlowService(_StubService):
        async def get_spell_links(self, character_id):
            await gate.wait()
            return []

    service = _SlowService()
    frame = await _open_spells_tab(qtbot, service)
    frame.request_refresh()
    await asyncio.sleep(0)
    frame.release_tab()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert _boxes(frame) == []  # cancellation is silent
    gate.set()


async def test_fresh_spells_tab_refuses_every_write(qtbot):
    # The unsaved-character rule of the feats tab, same posture on every
    # write door the «Заклинания» tab owns: choosing a candidate, editing a
    # slot field, removing a spell. Each refusal names the save; none of
    # them reaches the service (checkpoint-2 lineage, spec «Новая карточка с
    # пустыми разделами»).
    service = _StubService()
    frame = DndSpellsTabFrame(
        character_id=None,
        service=service,
        dataset_index=_StubIndex(_snapshot_with_entries()),
        grimoire_index=None,
        run_locked=_run_locked,
    )
    qtbot.addWidget(frame)
    await _drain()
    assert service.asks == []  # the unsaved face is painted, never read

    add_buttons = frame.findChildren(QPushButton, "ddSpellsCandidate")
    assert add_buttons
    add_buttons[0].click()
    await _drain()
    boxes = _boxes(frame)
    assert len(boxes) == 1 and "не сохранён" in boxes[0].text()
    boxes[0].button(QMessageBox.StandardButton.Ok).click()

    # A slot field commits through the same gate; the row is a QLineEdit
    # the reader can type into on the fresh face, but the handler itself is
    # the door — a stale commit aimed at no record refuses, not pretends.
    frame._on_slot_edited(1, "3")
    await _drain()
    boxes = _boxes(frame)
    assert len(boxes) == 1 and "не сохранён" in boxes[0].text()
    boxes[0].button(QMessageBox.StandardButton.Ok).click()

    # A remove of a link the fresh face never shows (no reads, no rows)
    # still answers the gate, should a stale row ever aim one.
    frame._on_remove(DdSpellLink("srd", "fire-bolt", "Fire bolt"))
    await _drain()
    boxes = _boxes(frame)
    assert len(boxes) == 1 and "не сохранён" in boxes[0].text()
    boxes[0].button(QMessageBox.StandardButton.Ok).click()

    assert service.asks == []  # three refusals, zero writes


async def test_release_tab_disposes_finished_and_detached_tasks(qtbot):
    # The release loop answers three task shapes: a finished task is left
    # alone (its coroutine disposed itself), a task whose loop is gone —
    # the teardown race the loop check exists for — gets the direct cancel,
    # and the bookkeeping empties either way.
    frame = DndSpellsTabFrame(
        character_id=None,
        service=_StubService(),
        dataset_index=_StubIndex(_snapshot_with_entries()),
        grimoire_index=None,
        run_locked=_run_locked,
    )
    qtbot.addWidget(frame)
    await _drain()

    class _Stub:
        def __init__(self, *, done: bool, loop) -> None:
            self._done = done
            self._loop = loop
            self.cancelled = 0

        def done(self) -> bool:
            return self._done

        def get_loop(self):
            return self._loop

        def cancel(self) -> None:
            self.cancelled += 1

    finished = _Stub(done=True, loop=None)
    detached = _Stub(done=False, loop=None)
    frame._tasks.update((finished, detached))
    frame.release_tab()
    assert finished.cancelled == 0  # done: nothing to cancel
    assert detached.cancelled == 1  # loop gone: the direct cancel
    assert not frame._tasks
