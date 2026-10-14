"""The mechanics storage and service floors (dd-card-redesign task 2.3;
design Д6/Д8; spec dnd-character-mechanics).

Three layers, each through its own door:

* the two JSON codecs of the new columns — the module's tolerant posture on
  every read (empty + one journal line, the stored row never rewritten), the
  canonical key order on every write, the domain bands enforced on read so
  garbage that predates the gates never reaches a reader;
* the row → value mapper — the six columns are all-or-nothing on read too
  (a half-written row shows no half-counted lines), an absent row reads as
  the empty block;
* the service over the shared test unit-of-work: every write is one
  transaction finish, every refused value dies at the domain gate BEFORE a
  row appears, design Д8's split (stored manual set vs the class's saves
  re-resolved at read) holds, and the feat links keep the spell links'
  idempotence with snapshots stored verbatim.

The spec scenarios reproduced here: «Ячейки пережили перезаход», «Класс
задал спасброски», «Без класса — мастер волен», «Датасет сняли — имена
целы» (storage half), «Без уровня бонус мастерства минимальный» (the +2
answer is the domain's, pinned in the formulas file).
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.dd.application.dnd_character_extension_service import (
    TEXT_BLOCK_KEY_REFUSAL,
    DndCharacterExtensionService,
)
from app.dd.domain.character import DdFeatLink, ReferenceLink
from app.dd.domain.character_mechanics import (
    ABILITY_KEYS,
    CharacterMechanics,
    SCORES_REFUSAL,
    SAVING_THROWS_REFUSAL,
    SKILLS_REFUSAL,
    SLOTS_REFUSAL,
    empty_mechanics,
)
from app.dd.infrastructure.db.dd_models import (
    DdCharacterExtModel,
    decode_proficiencies,
    decode_spell_slots,
    encode_proficiencies,
    encode_spell_slots,
)
from app.dd.infrastructure.repositories.dd_character_repository import (
    DdCharacterRepository,
    mechanics_from_row,
)
from app.infrastructure.db.models import CharacterModel

D1 = date(1300, 1, 1)

_FULL = dict(
    zip(
        ABILITY_KEYS,
        (16, 14, 15, 10, 11, 8),
    )
)


async def _add_character(session, name: str = "Грог") -> int:
    char = CharacterModel(name=name, start_date=D1)
    session.add(char)
    await session.commit()
    return char.id


# ── the slots codec ─────────────────────────────────────────────────────────


def test_slots_codec_roundtrips_in_level_order():
    body = encode_spell_slots({9: 1, 1: 4, 2: 3})
    assert body == '{"1": 4, "2": 3, "9": 1}'
    assert decode_spell_slots(body) == {1: 4, 2: 3, 9: 1}


@pytest.mark.parametrize("raw", [None, ""])
def test_slots_codec_absent_reads_as_not_set(raw):
    assert decode_spell_slots(raw) == {}


def test_slots_codec_unparsable_body_reads_empty_with_one_journal_line(caplog):
    with caplog.at_level("WARNING"):
        assert decode_spell_slots("{не json") == {}
    assert any("slots_json" in record.getMessage() for record in caplog.records)


def test_slots_codec_non_object_body_reads_empty_with_one_journal_line(caplog):
    with caplog.at_level("WARNING"):
        assert decode_spell_slots('["список", "а не объект"]') == {}
    assert any("не объект" in record.getMessage() for record in caplog.records)


def test_slots_codec_drops_pairs_outside_the_domain_bands():
    # A body written by some older/other hand can carry garbage; the reader
    # sees only pairs inside levels 1…9 and counts 0…99.
    body = (
        '{"0": 1, "1": 4, "2": true, "3": "4", "4": 100, "10": 1, "x": 1, "9": 99}'
    )
    assert decode_spell_slots(body) == {1: 4, 9: 99}


# ── the prof codec ──────────────────────────────────────────────────────────


def test_prof_codec_prints_canonical_order_and_roundtrips():
    body = encode_proficiencies(
        ["stealth", "perception"], {"constitution", "strength"}
    )
    # Canonical order: the SKILL_ABILITIES order, then ABILITY_KEYS order.
    assert body == (
        '{"skills": ["stealth", "perception"], '
        '"saving_throws": ["strength", "constitution"]}'
    )
    assert decode_proficiencies(body) == (
        frozenset({"stealth", "perception"}),
        frozenset({"strength", "constitution"}),
    )


def test_prof_codec_stores_the_manual_set_even_in_class_mode():
    # Design Д8: the body holds the master's set whatever the class owns —
    # the codec has no mode flag to lose it over.
    body = encode_proficiencies([], {"wisdom"})
    skills, saves = decode_proficiencies(body)
    assert skills == frozenset()
    assert saves == frozenset({"wisdom"})


@pytest.mark.parametrize("raw", [None, ""])
def test_prof_codec_absent_reads_as_two_empty_sets(raw):
    assert decode_proficiencies(raw) == (frozenset(), frozenset())


def test_prof_codec_unparsable_body_reads_empty_with_one_journal_line(caplog):
    with caplog.at_level("WARNING"):
        assert decode_proficiencies("{не json") == (frozenset(), frozenset())
    assert any("prof_json" in record.getMessage() for record in caplog.records)


def test_prof_codec_non_object_body_reads_empty_with_one_journal_line(caplog):
    with caplog.at_level("WARNING"):
        assert decode_proficiencies("[]") == (frozenset(), frozenset())
    assert any("не объект" in record.getMessage() for record in caplog.records)


def test_prof_codec_drops_unknown_keys_and_non_list_halves():
    body = (
        '{"skills": ["perception", "baking", 7], "saving_throws": "не список",'
        ' "extra": [1]}'
    )
    assert decode_proficiencies(body) == (frozenset({"perception"}), frozenset())


def test_prof_codec_missing_halves_read_as_empty():
    assert decode_proficiencies('{"skills": ["stealth"]}') == (
        frozenset({"stealth"}),
        frozenset(),
    )


# ── the row → value mapper ──────────────────────────────────────────────────


def test_mechanics_from_absent_row_reads_the_empty_block():
    assert mechanics_from_row(None) == empty_mechanics()


def test_mechanics_from_row_reads_a_full_set_and_the_typed_columns():
    row = DdCharacterExtModel(
        character_id=1,
        **_FULL,
        speed=35,
        alignment="истинно нейтральный",
        slots_json=encode_spell_slots({1: 4}),
        prof_json=encode_proficiencies(["perception"], ["strength"]),
    )
    mechanics = mechanics_from_row(row)
    assert mechanics.scores == _FULL
    assert mechanics.speed == 35
    assert mechanics.alignment == "истинно нейтральный"
    assert mechanics.spell_slots == {1: 4}
    assert mechanics.skill_proficiencies == frozenset({"perception"})
    assert mechanics.manual_saving_throws == frozenset({"strength"})


def test_mechanics_from_row_reads_a_half_written_set_as_no_set():
    # «Частичный набор не показывает полусчитанных строк» also on read: an
    # honestly written row never carries a partial set, so a half-set is
    # corruption — the reader prints no half-counted lines.
    half = dict(_FULL)
    half["charisma"] = None
    row = DdCharacterExtModel(character_id=1, **half)
    assert mechanics_from_row(row).scores is None


def test_mechanics_from_a_never_mechanicked_row_reads_all_absent():
    row = DdCharacterExtModel(character_id=1)
    assert mechanics_from_row(row) == empty_mechanics()


def test_mechanics_value_defaults_are_the_empty_block():
    mechanics = CharacterMechanics()
    assert mechanics.scores is None
    assert mechanics.spell_slots == {}


# ── the service: mechanics writes over the shared unit-of-work ──────────────


async def test_get_mechanics_without_a_row_reads_empty(uow):
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    assert await service.get_mechanics(char_id) == empty_mechanics()


async def test_ability_scores_roundtrip_and_clear(uow):
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    await service.set_ability_scores(char_id, _FULL)
    assert (await service.get_mechanics(char_id)).scores == _FULL
    await service.set_ability_scores(char_id, None)
    assert (await service.get_mechanics(char_id)).scores is None


@pytest.mark.parametrize("bad", [dict(_FULL, charisma=31), dict(_FULL, strength=0)])
async def test_out_of_band_scores_are_refused_before_any_row(uow, bad):
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    with pytest.raises(ValueError) as caught:
        await service.set_ability_scores(char_id, bad)
    assert str(caught.value) == SCORES_REFUSAL
    assert await DdCharacterRepository(uow.session).get_ext(char_id) is None


async def test_partial_scores_are_refused_never_half_stored(uow):
    # Spec: «Непустой набор шести значений SHALL храниться целиком или не
    # храниться вовсе» — the card's partial typing keeps the old face.
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    await service.set_ability_scores(char_id, _FULL)
    partial = dict(_FULL)
    del partial["wisdom"]
    with pytest.raises(ValueError):
        await service.set_ability_scores(char_id, partial)
    assert (await service.get_mechanics(char_id)).scores == _FULL


async def test_speed_roundtrip_independent_of_jumps(uow):
    # Spec «скорость остаётся тем, что ввёл мастер»: the stored number rides
    # alone; the computed block (the domain's) never reads it.
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    await service.set_speed(char_id, 30)
    assert (await service.get_mechanics(char_id)).speed == 30
    await service.set_speed(char_id, None)
    assert (await service.get_mechanics(char_id)).speed is None


async def test_alignment_roundtrip_nine_unset_and_refusal(uow):
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    await service.set_alignment(char_id, "хаотично-добрый")
    assert (await service.get_mechanics(char_id)).alignment == "хаотично-добрый"
    await service.set_alignment(char_id, "")  # «не задано» — one stored NULL
    assert (await service.get_mechanics(char_id)).alignment is None
    with pytest.raises(ValueError):
        await service.set_alignment(char_id, "добрый")
    assert (await service.get_mechanics(char_id)).alignment is None


async def test_spell_slots_survive_the_roundtrip_and_empty_clears(uow):
    # Spec scenario «Ячейки пережили перезаход»: stored, read back the same.
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    await service.set_spell_slots(char_id, {2: 3, 1: 4})
    assert (await service.get_mechanics(char_id)).spell_slots == {1: 4, 2: 3}
    await service.set_spell_slots(char_id, {})
    assert (await service.get_mechanics(char_id)).spell_slots == {}
    row = await DdCharacterRepository(uow.session).get_ext(char_id)
    assert row.slots_json is None  # «не задано» is one stored NULL fact


async def test_out_of_band_slots_are_refused_before_the_row_changes(uow):
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    await service.set_spell_slots(char_id, {1: 4})
    for bad, sentence in (({1: 100}, SLOTS_REFUSAL), ({10: 1}, SLOTS_REFUSAL)):
        with pytest.raises(ValueError) as caught:
            await service.set_spell_slots(char_id, bad)
        assert str(caught.value) == sentence
    assert (await service.get_mechanics(char_id)).spell_slots == {1: 4}


# ── the service: proficiencies and design Д8 ───────────────────────────────


async def test_skill_switches_roundtrip_preserving_the_saving_half(uow):
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    await service.set_skill_proficiencies(char_id, ["perception", "athletics"])
    await service.set_saving_throw_proficiencies(char_id, ["strength"])
    mechanics = await service.get_mechanics(char_id)
    assert mechanics.skill_proficiencies == frozenset({"perception", "athletics"})
    assert mechanics.manual_saving_throws == frozenset({"strength"})
    # Replacing one half leaves the other whole (the shared body, Д8).
    await service.set_skill_proficiencies(char_id, ["stealth"])
    mechanics = await service.get_mechanics(char_id)
    assert mechanics.skill_proficiencies == frozenset({"stealth"})
    assert mechanics.manual_saving_throws == frozenset({"strength"})


async def test_unknown_proficiency_keys_are_refused_before_the_row(uow):
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    with pytest.raises(ValueError) as caught:
        await service.set_skill_proficiencies(char_id, ["baking"])
    assert str(caught.value) == SKILLS_REFUSAL
    with pytest.raises(ValueError) as caught:
        await service.set_saving_throw_proficiencies(char_id, ["perception"])
    assert str(caught.value) == SAVING_THROWS_REFUSAL
    assert await DdCharacterRepository(uow.session).get_ext(char_id) is None


async def test_saving_throw_resolution_class_wins_manual_survives(uow):
    # Design Д8: the class's named saves own the answer at every read; the
    # stored manual set is never rewritten by a class appearing or leaving.
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    await service.set_saving_throw_proficiencies(char_id, ["wisdom"])

    # «Без класса — мастер волен»
    assert await service.get_saving_throw_profs(char_id, None) == frozenset({"wisdom"})
    assert await service.get_saving_throw_profs(char_id, []) == frozenset({"wisdom"})

    # «Класс задал спасброски» — the class's set answers…
    resolved = await service.get_saving_throw_profs(
        char_id, ["strength", "constitution"]
    )
    assert resolved == frozenset({"strength", "constitution"})

    # …and the manual set stands where it was, ready for the class-less mode.
    mechanics = await service.get_mechanics(char_id)
    assert mechanics.manual_saving_throws == frozenset({"wisdom"})
    assert await service.get_saving_throw_profs(char_id, None) == frozenset({"wisdom"})

    # «пересчитываться при смене класса» — another class, another answer.
    resolved = await service.get_saving_throw_profs(char_id, ["dexterity"])
    assert resolved == frozenset({"dexterity"})


# ── the service: feat links ─────────────────────────────────────────────────


async def test_feat_link_add_is_idempotent_and_keeps_order(uow):
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    first = DdFeatLink("srd-2014", "feat-alert", "Настороженность")
    second = DdFeatLink("grim", "42", "Своя черта")
    await service.add_feat_link(char_id, first)
    await service.add_feat_link(char_id, first)  # the same pair: a no-op
    await service.add_feat_link(char_id, second)
    assert await service.get_feat_links(char_id) == [first, second]
    # Same record id under another source is another feat (the pair is identity).
    await service.add_feat_link(char_id, DdFeatLink("other", "42", "Двойник"))
    assert len(await service.get_feat_links(char_id)) == 3


async def test_feat_link_stores_a_dead_source_triple_verbatim(uow):
    # Spec scenario «Датасет сняли — имена целы» (storage half): nothing is
    # re-resolved or cleared — the snapshot waits for the reader's annotation.
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    dead = DdFeatLink("removed-set", "feat-x", "Забытая черта")
    await service.add_feat_link(char_id, dead)
    assert await service.get_feat_links(char_id) == [dead]


async def test_feat_link_remove_and_absent_noop(uow):
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    link = DdFeatLink("srd-2014", "feat-alert", "Настороженность")
    await service.add_feat_link(char_id, link)
    # Removing another pair keeps the feat (spec «снятие» is pair-exact)…
    await service.remove_feat_link(char_id, link.source_key, "нет-такого")
    assert await service.get_feat_links(char_id) == [link]
    await service.remove_feat_link(char_id, link.source_key, link.ref_id)
    assert await service.get_feat_links(char_id) == []
    # …and removing after removal stays a no-op.
    await service.remove_feat_link(char_id, link.source_key, link.ref_id)
    assert await service.get_feat_links(char_id) == []


async def test_feat_links_are_per_character(uow):
    service = DndCharacterExtensionService(uow)
    first_id = await _add_character(uow.session, "Грог")
    second_id = await _add_character(uow.session, "Мия")
    await service.add_feat_link(
        first_id, DdFeatLink("srd-2014", "feat-alert", "Настороженность")
    )
    assert await service.get_feat_links(second_id) == []
    rows = (
        await uow.session.execute(
            select(DdCharacterExtModel).where(
                DdCharacterExtModel.character_id == first_id
            )
        )
    ).scalars().all()
    # The feat door does not grow an ext face — links live in their own table.
    assert rows == []


async def test_mechanics_write_appears_on_first_write_only_one_row(uow):
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    await service.set_speed(char_id, 30)
    await service.set_alignment(char_id, "законно-добрый")
    await service.set_spell_slots(char_id, {1: 2})
    rows = (
        await uow.session.execute(
            select(DdCharacterExtModel).where(
                DdCharacterExtModel.character_id == char_id
            )
        )
    ).scalars().all()
    assert len(rows) == 1  # PK = FK: one face, no second row per door
    mechanics = await service.get_mechanics(char_id)
    assert (mechanics.speed, mechanics.alignment, mechanics.spell_slots) == (
        30,
        "законно-добрый",
        {1: 2},
    )
    # The old doors keep working over the same row (no regression).
    await service.set_reference_link(char_id, "race", ReferenceLink("s", "r", " раз"))
    assert (await service.get_mechanics(char_id)).speed == 30
    assert await service.get_spell_links(char_id) == []


async def test_text_blocks_roundtrip_one_key_never_rewrites_the_rest(uow):
    # Task 5.3 «круговое чтение/запись в text_blocks»: the «Личность» fields
    # share the importer's column — one door upserts one key and the stored
    # neighbours (here: an importer-shaped block) ride through untouched.
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    assert await service.get_text_blocks(char_id) == {}  # absent row = empty
    await service.set_text_block(char_id, "Личность и характер", "ворчун")
    await service.set_text_block(char_id, "Внешность", "шрамы")
    assert await service.get_text_blocks(char_id) == {
        "Личность и характер": "ворчун",
        "Внешность": "шрамы",
    }
    # Empty text removes ONE key; the other survives (never a wholesale pass).
    await service.set_text_block(char_id, "Внешность", "")
    assert await service.get_text_blocks(char_id) == {
        "Личность и характер": "ворчун",
    }
    # The last key emptied stores NULL — «не задано» is one stored absence.
    await service.set_text_block(char_id, "Личность и характер", "")
    assert await service.get_text_blocks(char_id) == {}
    row = await DdCharacterRepository(uow.session).get_ext(char_id)
    assert row.text_blocks is None


async def test_text_block_key_refused_before_any_row(uow):
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    with pytest.raises(ValueError) as caught:
        await service.set_text_block(char_id, "   ", "текст без имени")
    assert str(caught.value) == TEXT_BLOCK_KEY_REFUSAL
    assert await service.get_text_blocks(char_id) == {}
    # The refusal left no ext face behind.
    rows = (
        await uow.session.execute(
            select(DdCharacterExtModel).where(
                DdCharacterExtModel.character_id == char_id
            )
        )
    ).scalars().all()
    assert rows == []
