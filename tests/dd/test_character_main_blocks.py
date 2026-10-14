"""The declarative «Основное» content of the character card (dd-card-redesign
task 4.3; design Д2/Д8; spec dnd-character-mechanics).

Two halves, offscreen:

* the source's ``module_blocks`` door: a dark source / foreign-target card
  gets the empty frame (the kernel renders 0.19.1), a fresh character the
  hidden-fields-only frame (spec «Пустой новый персонаж … с пустыми
  разделами»), a stored one the hidden-fields frame plus the factory, and
  the factory refuses to build without the connector's lock;
* the controller: the frame it republishes after the load (option captions
  with the «источник не подключён» dead item, the derived columns of the
  abilities/skills tables — «Сила 16 кормит и прыгает» reproduced to the
  pound, the passive senses, the class-owned saving throws per design Д8),
  every write channel (links verbatim, the level, the all-or-nothing six,
  the switch sets, speed), the LSS file doors + «Дозаполнить ИИ» restating
  the old «D&D» tab's flows on the block channel, and the release posture.

The service/index doors are stubs (the storage floor belongs to the service
tests); what is pinned here is which triple reaches the service, what the
frame paints and which box the master gets.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QMessageBox, QWidget

from app.dd.application.character_channel import TOP_UP_NOTHING_REFUSAL
from app.dd.application.character_import_service import (
    CharacterImportOutcome,
    CharacterImportStatus,
)
from app.dd.application.dataset_index_service import DatasetEntry, IndexSnapshot
from app.dd.domain.character import ReferenceLink, empty_ext
from app.dd.domain.character_mechanics import CharacterMechanics
from app.dd.domain.validation_report import CheckIssue, Severity, ValidationReport
from app.dd.presentation import character_main_blocks as blocks
from app.dd.presentation.character_main_blocks import (
    ABILITIES_BLOCK_ID,
    DOORS_BLOCK_ID,
    HIDDEN_KERNEL_FIELDS,
    LEVEL_BLOCK_ID,
    PASSIVE_BLOCK_ID,
    SHEET_BLOCK_ID,
    SHEET_PLACEHOLDER,
    SKILLS_BLOCK_ID,
    SPEED_BLOCK_ID,
    CharacterMainBlockController,
    class_record_saving_throws,
    link_block_id,
)
from app.dd.presentation.character_tab_frames import (
    SOURCE_UNAVAILABLE_NOTE,
    UNSET_ITEM,
    lss_sheet_url,
)
from app.dd.presentation.character_tab_source import DndCharacterTabSource
from app.presentation.modules.protocol import CardTabTarget


async def _drain(times: int = 10) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


class _StubService:
    """The extension service's doors the controller rides; every ask is
    journalled so the test can watch which triple reached the storage half."""

    def __init__(self, ext=None, mech=None, fail_load=False, fail_write=False):
        self.ext = ext if ext is not None else empty_ext()
        self.mech = mech if mech is not None else CharacterMechanics()
        self.fail_load = fail_load
        self.fail_write = fail_write
        self.asks: list[tuple] = []

    async def get_ext(self, character_id):
        self.asks.append(("get_ext", character_id))
        if self.fail_load:
            raise RuntimeError("диск отказал")
        return self.ext

    async def get_mechanics(self, character_id):
        return self.mech

    async def set_reference_link(self, character_id, slot, link):
        self.asks.append(("link", slot, link))
        if self.fail_write:
            raise RuntimeError("запись не прошла")
        self.ext.links[slot] = link

    async def set_level(self, character_id, level):
        self.asks.append(("level", level))
        if self.fail_write:
            raise RuntimeError("запись не прошла")
        self.ext = replace(self.ext, level=level)

    async def set_ability_scores(self, character_id, scores):
        self.asks.append(("scores", dict(scores) if scores else scores))
        if self.fail_write:
            raise RuntimeError("запись не прошла")
        self.mech = replace(self.mech, scores=dict(scores) if scores else None)

    async def set_speed(self, character_id, speed):
        self.asks.append(("speed", speed))
        if self.fail_write:
            raise RuntimeError("запись не прошла")
        self.mech = replace(self.mech, speed=speed)

    async def set_skill_proficiencies(self, character_id, skills):
        self.asks.append(("skills", frozenset(skills)))
        if self.fail_write:
            raise RuntimeError("запись не прошла")
        self.mech = replace(self.mech, skill_proficiencies=frozenset(skills))

    async def set_saving_throw_proficiencies(self, character_id, saves):
        self.asks.append(("saves", frozenset(saves)))
        if self.fail_write:
            raise RuntimeError("запись не прошла")
        self.mech = replace(self.mech, manual_saving_throws=frozenset(saves))

    async def set_lss_sheet_id(self, character_id, sheet_id):
        self.asks.append(("sheet", sheet_id))
        if self.fail_write:
            raise RuntimeError("запись не прошла")
        self.ext = replace(self.ext, lss_sheet_id=sheet_id)

    def last(self, kind: str):
        """The most recent ask of the kind (every write is followed by the
        re-read's ``get_ext``, so the tail is never the write itself)."""
        for ask in reversed(self.asks):
            if ask[0] == kind:
                return ask
        return None


class _StubIndex:
    def __init__(self, snap: IndexSnapshot) -> None:
        self._snap = snap

    async def snapshot(self):
        return self._snap


def _run_locked(coro):
    return asyncio.ensure_future(coro)


def _target(key: str, source_id: str) -> CardTabTarget:
    return CardTabTarget(key=key, source_id=source_id)


def _class_snap(save_grants: object = None) -> IndexSnapshot:
    class_record: dict = {}
    if save_grants is not None:
        class_record["grants"] = save_grants
    return IndexSnapshot(
        ids=("srd",),
        titles={"srd": "SRD-5.1"},
        sections={
            "races": {
                "srd": (
                    DatasetEntry("srd", "dwarf", "Дворф", {}),
                    DatasetEntry("srd", "elf", "Эльф", {}),
                )
            },
            "subraces": {},
            "classes": {"srd": (DatasetEntry("srd", "cleric", "Жрец", class_record),)},
            "subclasses": {},
            "backgrounds": {},
        },
        slugs={},
    )


_RECORD_LABELS = {
    "dd_race": "Вид",
    "dd_subrace": "Подвид",
    "dd_class": "Класс",
    "dd_subclass": "Подкласс",
    "dd_background": "Предыстория",
}


def _boxes(parent) -> list[QMessageBox]:
    return [box for box in parent.findChildren(QMessageBox) if not box.isHidden()]


def _labels(options) -> list[str]:
    return [option.label for option in options]


def _block(entries, block_id: str):
    return next(entry for entry in entries if entry.id == block_id)


def _has_block(entries, block_id: str) -> bool:
    return any(entry.id == block_id for entry in entries)


def _controller(
    qtbot,
    service,
    snap=None,
    *,
    import_service=None,
    document_builder=None,
    generation_open=None,
    generation_deps=None,
):
    published: list[tuple] = []

    def republish(entries, hidden):
        published.append((list(entries), tuple(hidden)))

    dialog = QWidget()
    qtbot.addWidget(dialog)
    controller = CharacterMainBlockController(
        character_id=7,
        service=service,
        dataset_index=_StubIndex(snap or _class_snap()),
        record_labels=_RECORD_LABELS,
        run_locked=_run_locked,
        dialog=dialog,
        republish=republish,
        import_service=import_service,
        document_builder=document_builder,
        generation_open=generation_open,
        generation_deps=generation_deps,
    )
    return controller, dialog, published


# ── the source's door ────────────────────────────────────────────────────────


def _source() -> DndCharacterTabSource:
    return DndCharacterTabSource(
        character_service=_StubService(),
        dataset_index=_StubIndex(_class_snap()),
    )


def test_dark_source_and_foreign_targets_answer_empty_frames():
    source = _source()  # the module is not attached yet
    frame = source.module_blocks(_target("character", "7"))
    assert frame.blocks == () and frame.hidden_fields == ()
    assert frame.handler_factory is None
    source.set_attached(True)
    # The module answers characters only — events keep their kernel texts.
    event = source.module_blocks(_target("event", "3"))
    assert event.blocks == () and event.hidden_fields == ()


def test_fresh_card_gets_hidden_fields_without_a_factory():
    source = _source()
    source.set_attached(True)
    frame = source.module_blocks(_target("character", ""))
    assert frame.blocks == ()
    assert frame.hidden_fields == HIDDEN_KERNEL_FIELDS
    # No row exists yet — there is nothing for a write handler to address.
    assert frame.handler_factory is None


def test_stored_card_frame_factory_and_bad_id():
    source = _source()
    source.set_attached(True)
    frame = source.module_blocks(_target("character", "7"))
    assert frame.blocks == ()  # the door is sync; blocks arrive on load
    assert frame.hidden_fields == HIDDEN_KERNEL_FIELDS
    assert callable(frame.handler_factory)
    # A non-whole id this source cannot address raises for the host's
    # tolerant door (journal-and-skip), never a guessed record.
    with pytest.raises(ValueError):
        source.module_blocks(_target("character", "не-число"))
    # …and a card built without the connector's lock refuses the factory.
    with pytest.raises(TypeError, match="без коннектора"):
        frame.handler_factory(object(), QWidget(), lambda *a: None)


# ── the controller: the frame after the load ─────────────────────────────────


async def test_frame_lists_options_dead_link_and_level(qtbot):
    ext = empty_ext()
    ext.links["race"] = ReferenceLink("srd", "dwarf", "Дворф")
    ext.links["subrace"] = ReferenceLink("gone", "r9", "Тифлинг")
    ext = replace(ext, level=3)
    controller, _dialog, published = _controller(qtbot, _StubService(ext=ext))
    await _drain()
    assert len(published) == 1
    entries, hidden = published[0]
    assert hidden == HIDDEN_KERNEL_FIELDS
    race = _block(entries, link_block_id("race"))
    assert race.label == "Вид"
    assert race.anchor == "after_short_fields"
    assert _labels(race.options) == [UNSET_ITEM, "Дворф · SRD-5.1", "Эльф · SRD-5.1"]
    assert race.value == "o1"  # the stored «Дворф» is the selected option
    subrace = _block(entries, link_block_id("subrace"))
    assert subrace.options[-1].label.endswith(SOURCE_UNAVAILABLE_NOTE)
    assert subrace.value == "dead"  # visible AND re-savable verbatim
    level = _block(entries, LEVEL_BLOCK_ID)
    assert level.value == "3" and len(level.options) == 21  # «—» + 1…20
    assert _block(entries, "jumps").value == ""  # no scores → no derived text
    assert _block(entries, "carry").value == ""
    assert _block(entries, PASSIVE_BLOCK_ID).value == UNSET_ITEM
    assert _block(entries, SPEED_BLOCK_ID).value == ""
    # No file doors composed → no dead buttons (the no-dead-action posture).
    assert not _has_block(entries, DOORS_BLOCK_ID)


async def test_scores_drive_every_derived_number(qtbot):
    mech = CharacterMechanics(
        scores={
            "strength": 16,
            "dexterity": 10,
            "constitution": 12,
            "intelligence": 8,
            "wisdom": 13,
            "charisma": 10,
        },
        speed=35,
        skill_proficiencies=frozenset({"perception", "athletics"}),
        manual_saving_throws=frozenset({"wisdom"}),
    )
    controller, _dialog, published = _controller(
        qtbot, _StubService(ext=empty_ext(), mech=mech)
    )
    await _drain()
    entries, _ = published[-1]
    abilities = {row.id: row for row in _block(entries, ABILITIES_BLOCK_ID).rows}
    strength = {c.field + c.kind: c for c in abilities["strength"].cells}
    # «Сила 16 кормит и прыгает»: 16, проверка +3, спасбросок +3 (без владения).
    assert strength["scorenumber"].value == "16"
    assert strength["checktext"].value == "+3"
    assert strength["savetext"].value == "+3"
    assert strength["saveswitch"].checked is False
    assert strength["saveswitch"].name == "Владение спасброском: Сила"
    wisdom = {c.field + c.kind: c for c in abilities["wisdom"].cells}
    # Мудрость 13 → +1, ручное владение спасброском → +1 + 2 = +3.
    assert wisdom["savetext"].value == "+3"
    assert wisdom["saveswitch"].checked is True
    skills = {row.id: row for row in _block(entries, SKILLS_BLOCK_ID).rows}
    athletics = {c.field + c.kind: c for c in skills["athletics"].cells}
    assert athletics["valuetext"].value == "+5"  # +3 + 2
    assert athletics["profswitch"].checked is True
    perception = {c.field + c.kind: c for c in skills["perception"].cells}
    assert perception["valuetext"].value == "+3"  # +1 + 2
    assert perception["profswitch"].checked is True
    passives = _block(entries, PASSIVE_BLOCK_ID).value
    assert "Восприятие 13" in passives  # 10 + 3 (владение едет и в пассивку)
    assert "Проницательность 11" in passives
    assert _block(entries, "carry").value == "240 фн"
    assert (
        _block(entries, "jumps").value
        == "с разбега 16 фт · с места 8 фт · в высоту 6 фт"
    )  # высота = 3 + модификатор (механика закреплена в своих тестах)
    assert _block(entries, SPEED_BLOCK_ID).value == "35"


async def test_class_record_owns_the_saving_throws(qtbot):
    ext = empty_ext()
    ext.links["class"] = ReferenceLink("srd", "cleric", "Жрец")
    snap = _class_snap(
        [
            {"type": "saving-throw", "stats": ["wis", "cha", "bogus"]},
            {"type": "pick-one", "options": [
                {"grants": [{"type": "saving-throw", "stats": ["str"]}]},
            ]},
        ]
    )
    mech = CharacterMechanics(  # the manual set loses to the class record
        manual_saving_throws=frozenset({"intelligence"})
    )
    controller, _dialog, published = _controller(
        qtbot, _StubService(ext=ext, mech=mech), snap
    )
    await _drain()
    entries, _ = published[-1]
    abilities = {row.id: row for row in _block(entries, ABILITIES_BLOCK_ID).rows}
    wisdom = {c.field + c.kind: c for c in abilities["wisdom"].cells}
    assert wisdom["saveswitch"].checked is True
    assert wisdom["saveswitch"].enabled is False  # the class owns the saves (Д8)
    intel = {c.field + c.kind: c for c in abilities["intelligence"].cells}
    assert intel["saveswitch"].checked is False  # the manual set is shadowed
    assert set(abilities) == {
        "strength", "dexterity", "constitution",
        "intelligence", "wisdom", "charisma",
    }


def test_class_record_saves_traversal_edges():
    # no class / disconnected class / no grants → None (manual switches win)
    assert class_record_saving_throws(empty_ext(), _class_snap()) is None
    dead = empty_ext()
    dead.links["class"] = ReferenceLink("gone", "cleric", "Жрец")
    assert class_record_saving_throws(dead, _class_snap()) is None
    bare = empty_ext()
    bare.links["class"] = ReferenceLink("srd", "cleric", "Жрец")
    assert class_record_saving_throws(bare, _class_snap()) is None
    leveled = _class_snap()
    record = leveled.sections["classes"]["srd"][0].record
    record["leveledGrants"] = [
        {"grants": [
            {"type": "saving-throw", "stats": ["con"]},
            {"type": "pick-one", "options": "не-список"},
            "не-черта-словарь",
        ]},
        "не-словарь",
    ]
    assert class_record_saving_throws(bare, leveled) == ("constitution",)


# ── the controller: writes ───────────────────────────────────────────────────


async def _written(controller, published, block_id, field, value):
    before = len(published)
    controller.handle_write(block_id, field, value)
    await _drain()
    assert len(published) == before + 1  # every committed write repaints


async def test_link_and_level_writes(qtbot):
    ext = empty_ext()
    ext.links["subrace"] = ReferenceLink("gone", "r9", "Тифлинг")
    service = _StubService(ext=ext)
    controller, _dialog, published = _controller(qtbot, service)
    await _drain()
    await _written(controller, published, link_block_id("race"), "value", "o1")
    assert service.last("link") == (
        "link", "race", ReferenceLink("srd", "dwarf", "Дворф"),
    )
    await _written(controller, published, link_block_id("race"), "value", "unset")
    assert service.last("link") == ("link", "race", ReferenceLink("", "", ""))
    # The dead stored triple re-saves verbatim (spec «карточка не немеет»).
    await _written(controller, published, link_block_id("subrace"), "value", "dead")
    assert service.last("link") == (
        "link", "subrace", ReferenceLink("gone", "r9", "Тифлинг"),
    )
    await _written(controller, published, LEVEL_BLOCK_ID, "value", "5")
    assert service.last("level") == ("level", 5)
    await _written(controller, published, LEVEL_BLOCK_ID, "value", "")
    assert service.last("level") == ("level", None)


_FULL_SCORES = {
    "strength": 16, "dexterity": 10, "constitution": 12,
    "intelligence": 8, "wisdom": 13, "charisma": 10,
}


async def test_full_score_edit_writes_the_whole_set(qtbot):
    service = _StubService(mech=CharacterMechanics(scores=dict(_FULL_SCORES)))
    controller, _dialog, published = _controller(qtbot, service)
    await _drain()
    await _written(controller, published, ABILITIES_BLOCK_ID, "strength.score", "18")
    written = service.last("scores")[1]
    assert written["strength"] == 18 and written["charisma"] == 10


async def test_partial_score_edit_is_refused_before_any_write(qtbot):
    service = _StubService(mech=CharacterMechanics(scores=dict(_FULL_SCORES)))
    controller, dialog, _published = _controller(qtbot, service)
    await _drain()
    # Снять одно значение из шести — отказ, транзакции нет (all-or-nothing).
    controller.handle_write(ABILITIES_BLOCK_ID, "strength.score", "")
    await _drain()
    assert service.last("scores") is None
    assert "полный набор" in _boxes(dialog)[-1].text()
    # A non-numeric edit is refused in place, likewise with no transaction.
    controller.handle_write(ABILITIES_BLOCK_ID, "strength.score", "sixteen")
    await _drain()
    assert service.last("scores") is None
    assert "целое число" in _boxes(dialog)[-1].text()
    # A foreign ability key in the address is ignored without a box.
    before = len(_boxes(dialog))
    controller.handle_write(ABILITIES_BLOCK_ID, "luck.score", "16")
    await _drain()
    assert len(_boxes(dialog)) == before and service.last("scores") is None


async def test_clearing_an_empty_set_writes_the_honest_clear(qtbot):
    # The stored set is already empty (reads as None); an «empty» edit is the
    # legal all-or-nothing clear — None reaches the service, not {}.
    service = _StubService()
    controller, _dialog, published = _controller(qtbot, service)
    await _drain()
    await _written(controller, published, ABILITIES_BLOCK_ID, "strength.score", "")
    assert service.last("scores") == ("scores", None)


async def test_switch_writes_skills_and_saves(qtbot):
    service = _StubService()
    controller, _dialog, published = _controller(qtbot, service)
    await _drain()
    await _written(controller, published, SKILLS_BLOCK_ID, "athletics.prof", True)
    assert service.last("skills") == ("skills", frozenset({"athletics"}))
    await _written(controller, published, SKILLS_BLOCK_ID, "athletics.prof", True)
    assert service.last("skills") == ("skills", frozenset())
    await _written(controller, published, ABILITIES_BLOCK_ID, "wisdom.save", True)
    assert service.last("saves") == ("saves", frozenset({"wisdom"}))
    # The same switch again lifts the stored manual proficiency (free mode,
    # spec «Без класса — мастер волен»: the switch reflects and moves state).
    await _written(controller, published, ABILITIES_BLOCK_ID, "wisdom.save", True)
    assert service.last("saves") == ("saves", frozenset())
    # Foreign row ids in the address are refused in silence.
    service.asks.clear()
    controller.handle_write(SKILLS_BLOCK_ID, "hacking.prof", True)
    controller.handle_write(ABILITIES_BLOCK_ID, "luck.save", True)
    controller.handle_write(ABILITIES_BLOCK_ID, "luck.check", "x")
    await _drain()
    assert service.asks == []


async def test_class_owns_the_saves_the_click_is_ignored(qtbot):
    ext = empty_ext()
    ext.links["class"] = ReferenceLink("srd", "cleric", "Жрец")
    service = _StubService(
        ext=ext, mech=CharacterMechanics(scores=dict(_FULL_SCORES))
    )
    snap = _class_snap([{"type": "saving-throw", "stats": ["wis"]}])
    controller, _dialog, _published = _controller(qtbot, service, snap)
    await _drain()
    service.asks.clear()
    controller.handle_write(ABILITIES_BLOCK_ID, "wisdom.save", True)
    await _drain()
    assert service.asks == []  # design Д8: the switches cannot fight the class


async def test_speed_write_and_refusals(qtbot):
    service = _StubService(mech=CharacterMechanics(speed=30))
    controller, dialog, published = _controller(qtbot, service)
    await _drain()
    await _written(controller, published, SPEED_BLOCK_ID, "value", "35")
    assert service.last("speed") == ("speed", 35)
    await _written(controller, published, SPEED_BLOCK_ID, "value", "")
    assert service.last("speed") == ("speed", None)
    service.asks.clear()
    controller.handle_write(SPEED_BLOCK_ID, "value", "быстро")
    await _drain()
    assert service.asks == []
    assert _boxes(dialog)[-1].text().startswith("Скорость — целое")


async def test_failed_write_notices_once(qtbot):
    service = _StubService(fail_write=True)
    controller, dialog, published = _controller(qtbot, service)
    await _drain()
    controller.handle_write(LEVEL_BLOCK_ID, "value", "5")
    await _drain()
    assert len(published) == 1  # the failed write publishes nothing new
    assert "уровень" in _boxes(dialog)[-1].text()
    # The modeless box keeps its reference only while it is up (PR-010
    # posture): its «finished» retires the reference, the next notice is a
    # fresh box, not a second face on the answered one.
    _boxes(dialog)[-1].button(QMessageBox.StandardButton.Ok).click()
    assert controller._notice_box is None


async def test_failed_load_notices_and_stays_quiet(qtbot):
    service = _StubService(fail_load=True)
    controller, dialog, published = _controller(qtbot, service)
    await _drain()
    assert published == []  # only the door's hidden-fields frame exists
    assert _boxes(dialog)  # one Russian box about the failed load
    # Without the loaded face every write is ignored (nothing to merge with).
    service.asks.clear()
    controller.handle_write(LEVEL_BLOCK_ID, "value", "5")
    await _drain()
    assert service.asks == []


async def test_release_cancels_and_silences(qtbot, monkeypatch):
    importer = _StubImporter([
        CharacterImportOutcome(
            status=CharacterImportStatus.NEEDS_CONFIRMATION, message="Перезаписать?"
        ),
        CharacterImportOutcome(status=CharacterImportStatus.OVERWRITTEN, message="Готово"),
    ])
    monkeypatch.setattr(blocks.Path, "read_text", lambda self, **k: "BYTES")
    controller, dialog, published, _opened = await _composed(
        qtbot, monkeypatch, importer=importer
    )
    published_after_load = len(published)
    # The door's confirm box is up; the card closes before the master answers.
    _pick_open(monkeypatch, "/tmp/x.json")
    controller.handle_write(DOORS_BLOCK_ID, "overwrite", True)
    await _drain()
    question = _boxes(dialog)[-1]
    controller.release()
    question.button(QMessageBox.StandardButton.Yes).click()
    await _drain()
    # The confirmed import ran to its end, yet the released card prints no
    # box, publishes nothing and reloads nothing (a released card answers
    # nothing — and every later write is refused outright).
    assert importer.asks[-1] == ("BYTES", True)
    assert len(published) == published_after_load
    controller.handle_write(LEVEL_BLOCK_ID, "value", "5")
    await _drain()
    assert _boxes(dialog) == []


async def test_release_mid_load_prints_nothing(qtbot):
    controller, dialog, published = _controller(qtbot, _StubService())
    controller.release()
    await _drain()
    assert published == []  # the load was cancelled mid-flight, no box, no frame
    service = controller._service  # noqa: SLF001 — the released card must not
    service.asks.clear()           # have reached the storage at all
    controller.handle_write(LEVEL_BLOCK_ID, "value", "5")
    await _drain()
    assert service.asks == []


# ── the controller: the LSS doors and «Дозаполнить ИИ» ───────────────────────


class _StubImporter:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.asks: list[tuple] = []

    async def import_character(self, content, *, character_id=None, confirmed=False):
        self.asks.append((content, confirmed))
        return self.outcomes.pop(0)

    async def save_raw_document(self, character_id, path):
        self.asks.append(("raw", path))
        return self.outcomes.pop(0)


class _StubBuilder:
    def __init__(self, document="{}", fail=False):
        self.document = document
        self.fail = fail
        self.asks: list = []

    async def build(self, character_id):
        self.asks.append(("build", character_id))
        if self.fail:
            raise RuntimeError("нет документа")
        return self.document

    async def export_document(self, character_id, path):
        self.asks.append(("export", path))
        if self.fail:
            raise RuntimeError("нет диска")
        return True


class _StubDeps:
    def __init__(self, available):
        self._available = available

    def available(self):
        return self._available

    def hint(self):
        return "настрой LLM"


def _pick_open(monkeypatch, path: str) -> None:
    monkeypatch.setattr(
        blocks.QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **k: (path, "")),
    )


def _pick_save(monkeypatch, path: str) -> None:
    monkeypatch.setattr(
        blocks.QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (path, "")),
    )


def _envelope(data: dict) -> str:
    """The builder's output envelope as the channel expects it (the shape
    the channel's own tests fix)."""
    return json.dumps(
        {
            "jsonType": "character",
            "version": "2",
            "data": json.dumps(data, ensure_ascii=False),
        },
        ensure_ascii=False,
    )


# А: имя, уровень, пять привязок-снимков и список заклинаний — всё целое.
_FULL_TOP_UP_DOC = _envelope({
    "name": "Грог",
    "level": 3,
    "info": {
        "race": {"id": "dwarf", "name": "Дворф"},
        "subrace": {"id": "hill", "name": "Холмовой"},
        "charClass": {"id": "cleric", "name": "Жрец"},
        "subclass": {"id": "life", "name": "Жизнь"},
        "background": {"id": "acolyte", "name": "Аколит"},
    },
    "spells": {"list": ["mending"]},
})
# Б: только имя — остальному есть что дозаполнить.
_HOLES_TOP_UP_DOC = _envelope({"name": "Грог"})


async def _composed(qtbot, monkeypatch, *, importer=None, builder=None, deps=None,
                    snap=None, service=None):
    opened: list[tuple] = []

    def generation_open(character_id, document):
        opened.append((character_id, document))

    controller, dialog, published = _controller(
        qtbot,
        service if service is not None else _StubService(),
        snap,
        import_service=importer,
        document_builder=builder,
        generation_open=generation_open if builder is not None else None,
        generation_deps=deps,
    )
    await _drain()
    return controller, dialog, published, opened


async def test_doors_frame_gates_buttons_by_composition(qtbot):
    controller, _dialog, published, _ = await _composed(
        qtbot, None,
        importer=_StubImporter([]),
        builder=_StubBuilder(),
        deps=_StubDeps(False),
    )
    entries, _ = published[-1]
    doors = _block(entries, DOORS_BLOCK_ID)
    assert doors.anchor == "after_music"
    assert _labels(doors.actions) == [
        "Перезаписать из файла LSS…",
        "Сохранить исходный файл…",
        "Экспорт для LSS…",
        "Дозаполнить ИИ",
    ]
    by_id = {action.id: action for action in doors.actions}
    assert by_id["top_up"].enabled is False  # the standing AI gate
    assert by_id["overwrite"].enabled is True
    del controller
    # With no deps composed at all the AI button is open (the old tab's
    # showEvent posture: absent gate object = no gate).
    _controller_, _dialog_, published2, _ = await _composed(
        qtbot, None, builder=_StubBuilder()
    )
    del _controller_
    doors2 = _block(published2[-1][0], DOORS_BLOCK_ID)
    top_up = next(a for a in doors2.actions if a.id == "top_up")
    assert top_up.enabled is True


async def test_overwrite_confirmation_dance(qtbot, monkeypatch):
    monkeypatch.setattr(blocks.Path, "read_text", lambda self, **k: "BYTES")
    importer = _StubImporter([
        # h1: предпроверка просит — «нет»; h2: просит снова — «да», импорт
        # проходит; h3: уже подтверждённый круг вдруг опять просит — печать.
        CharacterImportOutcome(
            status=CharacterImportStatus.NEEDS_CONFIRMATION, message="Перезаписать?"
        ),
        CharacterImportOutcome(
            status=CharacterImportStatus.NEEDS_CONFIRMATION, message="Перезаписать?"
        ),
        CharacterImportOutcome(
            status=CharacterImportStatus.OVERWRITTEN, message="Готово"
        ),
        CharacterImportOutcome(
            status=CharacterImportStatus.NEEDS_CONFIRMATION, message="Перезаписать?"
        ),
        CharacterImportOutcome(
            status=CharacterImportStatus.NEEDS_CONFIRMATION, message="ещё раз?"
        ),
    ])
    controller, dialog, _published, _ = await _composed(
        qtbot, monkeypatch, importer=importer
    )
    _pick_open(monkeypatch, "/tmp/x.json")
    # «Нет» — бездействие: предпроверка была, подтверждения не было.
    controller.handle_write(DOORS_BLOCK_ID, "overwrite", True)
    await _drain()
    question = _boxes(dialog)[-1]
    assert question.icon() == QMessageBox.Icon.Question
    assert question.text() == "Перезаписать?"
    question.button(QMessageBox.StandardButton.No).click()
    await _drain()
    assert importer.asks == [("BYTES", False)]
    # «Да» пересылает ровно те же байты первого прочтения.
    controller.handle_write(DOORS_BLOCK_ID, "overwrite", True)
    await _drain()
    _boxes(dialog)[-1].button(QMessageBox.StandardButton.Yes).click()
    await _drain()
    assert importer.asks[-1] == ("BYTES", True)
    assert _boxes(dialog)[-1].icon() == QMessageBox.Icon.Information
    # NEEDS_CONFIRMATION after an already-confirmed ask prints the message.
    controller.handle_write(DOORS_BLOCK_ID, "overwrite", True)
    await _drain()
    _boxes(dialog)[-1].button(QMessageBox.StandardButton.Yes).click()
    await _drain()
    assert _boxes(dialog)[-1].text() == "ещё раз?"


async def test_overwrite_confirmed_rerequest_crash_answers_a_box(qtbot, monkeypatch):
    # The ported belt of the retired tab: the pre-check passed, the reader
    # said «да», and the confirmed write itself crashed — one box, journalled
    # (the old «Импорт персонажа не завершился» wording survives on the
    # block channel).
    monkeypatch.setattr(blocks.Path, "read_text", lambda self, **k: "BYTES")

    class _BoomAfterConfirm(_StubImporter):
        async def import_character(self, content, **kwargs):
            self.asks.append((content, bool(kwargs.get("confirmed"))))
            if kwargs.get("confirmed"):
                raise RuntimeError("запись не прошла")
            return CharacterImportOutcome(
                status=CharacterImportStatus.NEEDS_CONFIRMATION, message="Перезаписать?"
            )

    controller, dialog, _published, _ = await _composed(
        qtbot, monkeypatch, importer=_BoomAfterConfirm([])
    )
    _pick_open(monkeypatch, "/tmp/x.json")
    controller.handle_write(DOORS_BLOCK_ID, "overwrite", True)
    await _drain()
    _boxes(dialog)[-1].button(QMessageBox.StandardButton.Yes).click()
    await _drain()
    assert _boxes(dialog)[-1].text().startswith("Импорт персонажа не завершился")


async def test_overwrite_read_error_and_blocked_report(qtbot, monkeypatch):
    importer = _StubImporter([])
    controller, dialog, _published, _ = await _composed(
        qtbot, monkeypatch, importer=importer
    )

    def boom(self, **k):
        raise OSError("нет доступа")

    monkeypatch.setattr(blocks.Path, "read_text", boom)
    _pick_open(monkeypatch, "/tmp/x.json")
    controller.handle_write(DOORS_BLOCK_ID, "overwrite", True)
    await _drain()
    assert "нет доступа" in _boxes(dialog)[-1].text()
    assert importer.asks == []

    # The unconfirmed answer that reports the block: the honest printed
    # check report (the same lines the old sheet's box carried).
    monkeypatch.setattr(blocks.Path, "read_text", lambda self, **k: "X")
    report = ValidationReport.of([
        CheckIssue("E1", Severity.ERROR, "info.level", "не уровень"),
    ])
    importer.outcomes = [
        CharacterImportOutcome(
            status=CharacterImportStatus.BLOCKED, report=report, message="отчёт"
        )
    ]
    controller.handle_write(DOORS_BLOCK_ID, "overwrite", True)
    await _drain()
    body = _boxes(dialog)[-1].text()
    assert body.startswith("Импорт отклонён — отчёт проверки:")
    assert "info.level — не уровень" in body


async def test_overwrite_precheck_failure_and_cancel(qtbot, monkeypatch):
    class _BoomImporter(_StubImporter):
        async def import_character(self, content, **kwargs):
            raise RuntimeError("отказ")

    monkeypatch.setattr(blocks.Path, "read_text", lambda self, **k: "BYTES")
    controller, dialog, _published, _ = await _composed(
        qtbot, monkeypatch, importer=_BoomImporter([])
    )
    _pick_open(monkeypatch, "/tmp/x.json")
    controller.handle_write(DOORS_BLOCK_ID, "overwrite", True)
    await _drain()
    assert "проверить файл" in _boxes(dialog)[-1].text()
    # The отвод (empty path) never approaches the service or the boxes.
    _pick_open(monkeypatch, "")
    before = len(_boxes(dialog))
    controller.handle_write(DOORS_BLOCK_ID, "overwrite", True)
    await _drain()
    assert len(_boxes(dialog)) == before


async def test_import_success_carries_warnings_and_republishes(qtbot, monkeypatch):
    monkeypatch.setattr(blocks.Path, "read_text", lambda self, **k: "B")
    report = ValidationReport.of([
        CheckIssue("W1", Severity.WARNING, "info.level", "странно"),
    ])
    importer = _StubImporter([
        CharacterImportOutcome(
            status=CharacterImportStatus.OVERWRITTEN,
            message="Обновлён",
            report=report,
        )
    ])
    controller, dialog, published, _ = await _composed(
        qtbot, monkeypatch, importer=importer
    )
    before = len(published)
    _pick_open(monkeypatch, "/tmp/x.json")
    controller.handle_write(DOORS_BLOCK_ID, "overwrite", True)
    await _drain()
    body = _boxes(dialog)[-1].text()
    assert body.startswith("Обновлён")
    assert "Предупреждения:" in body and "info.level — странно" in body
    # The stored face changed wholesale — the frame reloads and repaints.
    assert len(published) == before + 1


async def test_save_raw_branches(qtbot, monkeypatch):
    importer = _StubImporter([False, True])
    controller, dialog, _published, _ = await _composed(
        qtbot, monkeypatch, importer=importer
    )
    _pick_save(monkeypatch, "/tmp/out.json")
    controller.handle_write(DOORS_BLOCK_ID, "save_raw", True)
    await _drain()
    assert "не импортирован файл LSS" in _boxes(dialog)[-1].text()
    controller.handle_write(DOORS_BLOCK_ID, "save_raw", True)
    await _drain()
    assert _boxes(dialog)[-1].icon() == QMessageBox.Icon.Information
    _pick_save(monkeypatch, "")
    before = len(_boxes(dialog))
    controller.handle_write(DOORS_BLOCK_ID, "save_raw", True)
    await _drain()
    assert len(_boxes(dialog)) == before  # the отвод is silent

    class _Boom(_StubImporter):
        async def save_raw_document(self, character_id, path):
            raise RuntimeError("нет диска")

    controller, dialog, _published, _ = await _composed(
        qtbot, monkeypatch, importer=_Boom([])
    )
    _pick_save(monkeypatch, "/tmp/out.json")
    controller.handle_write(DOORS_BLOCK_ID, "save_raw", True)
    await _drain()
    assert "записать файл" in _boxes(dialog)[-1].text()


async def test_export_branches(qtbot, monkeypatch):
    builder = _StubBuilder()
    controller, dialog, _published, _ = await _composed(
        qtbot, monkeypatch, builder=builder
    )
    _pick_save(monkeypatch, "")
    controller.handle_write(DOORS_BLOCK_ID, "export", True)
    await _drain()
    assert _boxes(dialog) == [] and builder.asks == []  # the отвод is silent
    _pick_save(monkeypatch, "/tmp/out.json")
    controller.handle_write(DOORS_BLOCK_ID, "export", True)
    await _drain()
    assert builder.asks == [("export", "/tmp/out.json")]
    assert _boxes(dialog)[-1].icon() == QMessageBox.Icon.Information

    failing = _StubBuilder(fail=True)
    controller, dialog, _published, _ = await _composed(
        qtbot, monkeypatch, builder=failing
    )
    _pick_save(monkeypatch, "/tmp/out.json")
    controller.handle_write(DOORS_BLOCK_ID, "export", True)
    await _drain()
    assert "Не удалось собрать и записать" in _boxes(dialog)[-1].text()


async def test_top_up_gate_refusal_and_opener(qtbot):
    # Gate closed: the painted button is disabled and the door ignores writes.
    builder = _StubBuilder(document=_FULL_TOP_UP_DOC)
    controller, _dialog, _published, opened = await _composed(
        qtbot, None, builder=builder, deps=_StubDeps(False)
    )
    controller.handle_write(DOORS_BLOCK_ID, "top_up", True)
    await _drain()
    assert builder.asks == [] and opened == []
    # Open gate, a document with nothing missing → the honest refusal, the
    # generation sheet stays shut (spec «Пусто дозаполнять»).
    controller, dialog, _published, opened = await _composed(
        qtbot, None, builder=builder, deps=_StubDeps(True)
    )
    controller.handle_write(DOORS_BLOCK_ID, "top_up", True)
    await _drain()
    assert opened == []
    box = _boxes(dialog)[-1]
    assert box.text() == TOP_UP_NOTHING_REFUSAL
    assert box.icon() == QMessageBox.Icon.Information
    # A document with holes raises the sheet through the façade's opener.
    controller, _dialog, _published, opened = await _composed(
        qtbot, None,
        builder=_StubBuilder(document=_HOLES_TOP_UP_DOC),
        deps=_StubDeps(True),
    )
    controller.handle_write(DOORS_BLOCK_ID, "top_up", True)
    await _drain()
    assert opened == [(7, _HOLES_TOP_UP_DOC)]
    # A failed assembly notices once (the same wording the old tab carried).
    controller, dialog, _published, _ = await _composed(
        qtbot, None, builder=_StubBuilder(fail=True), deps=_StubDeps(True)
    )
    controller.handle_write(DOORS_BLOCK_ID, "top_up", True)
    await _drain()
    assert "дозаполнения" in _boxes(dialog)[-1].text()


async def test_door_writers_are_belted_when_services_absent(qtbot):
    # No services composed at all: the frame prints no door row, and a
    # synthetic write to the door ids returns without a box.
    controller, dialog, published, _ = await _composed(qtbot, None)
    entries, _ = published[-1]
    assert not _has_block(entries, DOORS_BLOCK_ID)
    for door in ("overwrite", "save_raw", "export", "top_up", "нет-такого"):
        controller.handle_write(DOORS_BLOCK_ID, door, True)
    await _drain()
    assert _boxes(dialog) == []


# ── the LSS sheet row: the textline block and «Открыть в браузере» ───────────


async def test_sheet_textline_prints_stored_id_and_commits_the_edit(qtbot):
    # spec dnd-character-extension «адрес листа… пустой идентификатор
    # скрывает кнопку браузера»: the stored id paints in the textline, the
    # committed edit lands in the service and the repaint follows.
    service = _StubService(ext=replace(empty_ext(), lss_sheet_id="42"))
    controller, _dialog, published = _controller(qtbot, service)
    await _drain()
    sheet = _block(published[-1][0], SHEET_BLOCK_ID)
    assert sheet.kind == "textline"
    assert sheet.anchor == "after_music"
    assert sheet.value == "42"
    assert sheet.placeholder == SHEET_PLACEHOLDER

    controller.handle_write(SHEET_BLOCK_ID, "value", " 99 ")
    await _drain()
    assert service.last("sheet") == ("sheet", "99")
    assert _block(published[-1][0], SHEET_BLOCK_ID).value == "99"


async def test_untouched_sheet_commit_saves_nothing(qtbot):
    # The old tab's discipline on the new channel: a strip-equal commit is
    # no transaction (focus leaving an untouched field).
    service = _StubService(ext=replace(empty_ext(), lss_sheet_id="42"))
    controller, _dialog, published = _controller(qtbot, service)
    await _drain()
    controller.handle_write(SHEET_BLOCK_ID, "value", "42  ")
    await _drain()
    assert service.last("sheet") is None
    assert len(published) == 1  # no repaint for a no-op


async def test_sheet_write_failure_notices_once(qtbot):
    service = _StubService(fail_write=True)
    controller, dialog, _published = _controller(qtbot, service)
    await _drain()
    controller.handle_write(SHEET_BLOCK_ID, "value", "7")
    await _drain()
    assert "идентификатор листа LSS" in _boxes(dialog)[-1].text()


async def test_browser_door_prints_with_id_and_opens_the_page(qtbot, monkeypatch):
    # An empty id: the door row carries no browser button at all (the old
    # hidden button is now an absent option). A stored id: it heads the row
    # and opens the very digital-sheet address the old tab used.
    empty_service = _StubService()
    controller, _dialog, published, _ = await _composed(
        qtbot, None, importer=_StubImporter([]), service=empty_service
    )
    doors = _block(published[-1][0], DOORS_BLOCK_ID)
    assert "open" not in {a.id for a in doors.actions}

    storer = _StubService(ext=replace(empty_ext(), lss_sheet_id="42"))
    controller, _dialog, published, _ = await _composed(
        qtbot, None, importer=_StubImporter([]), service=storer
    )
    doors = _block(published[-1][0], DOORS_BLOCK_ID)
    assert doors.actions[0].id == "open"
    assert doors.label == "Файл LSS"

    opened_urls: list[str] = []
    monkeypatch.setattr(
        blocks.QDesktopServices,
        "openUrl",
        staticmethod(lambda url: opened_urls.append(url.toString())),
    )
    controller.handle_write(DOORS_BLOCK_ID, "open", True)
    await _drain()
    assert opened_urls == [lss_sheet_url("42")]

    # A lone browser button (no file services composed) stands captionless
    # under the sheet line — «Файл LSS» would caption a file row that is
    # not there.
    controller, _dialog, published, _ = await _composed(qtbot, None, service=storer)
    doors = _block(published[-1][0], DOORS_BLOCK_ID)
    assert doors.label == ""
    assert [a.id for a in doors.actions] == ["open"]
