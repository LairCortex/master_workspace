"""The mechanics formulas and gates — every band branch (dd-card-redesign
task 2.1, design Д7; spec dnd-character-mechanics).

The spec's own numbers are the pins: the modifier band walked across the
whole 1…30 (rounding DOWN, so 9 → −1 and 11 → 0 — «округление вниз» also on
the negative half), the proficiency bands one level at a time for 1…20 plus
the unset level (+2, scenario «Без уровня бонус мастерства минимальный»),
the «Сила 16 кормит и прыгает» quartet (240 / 16 / 8 / 4) and the skill /
passive coupling (switching the skill moves both by exactly the bonus). The
gates mirror the spec's all-or-nothing six-value rule, the 0…99 slot band,
the fixed nine alignments and the штатный skill list.
"""
from __future__ import annotations

import pytest

from app.dd.domain.character_mechanics import (
    ABILITY_KEYS,
    ABILITY_MAX,
    ABILITY_MIN,
    ALIGNMENTS,
    ALIGNMENT_REFUSAL,
    PASSIVE_SENSE_SKILLS,
    PROFICIENCY_LEVEL_REFUSAL,
    SAVING_THROWS_REFUSAL,
    SCORES_REFUSAL,
    SKILLS_REFUSAL,
    SKILL_ABILITIES,
    SLOTS_REFUSAL,
    CharacterMechanics,
    ability_modifier,
    check_value,
    empty_mechanics,
    jumps_and_carry,
    passive_sense_value,
    proficiency_bonus,
    resolve_saving_throw_profs,
    saving_throw_value,
    skill_value,
    validate_ability_scores,
    validate_alignment,
    validate_saving_throw_keys,
    validate_skill_keys,
    validate_spell_slots,
)

# The spec band's own modifier table (1…30): (value − 10) / 2 rounded DOWN.
# Hand-written here — if the domain formula drifts (e.g. to banker's or
# toward-zero rounding), this table is what catches it.
_MODIFIERS_BY_SCORE = {
    1: -5, 2: -4, 3: -4, 4: -3, 5: -3, 6: -2, 7: -2, 8: -1, 9: -1,
    10: 0, 11: 0, 12: 1, 13: 1, 14: 2, 15: 2, 16: 3, 17: 3, 18: 4, 19: 4,
    20: 5, 21: 5, 22: 6, 23: 6, 24: 7, 25: 7, 26: 8, 27: 8, 28: 9,
    29: 9, 30: 10,
}


# ── the ability band 1…30 ───────────────────────────────────────────────────


@pytest.mark.parametrize("score", range(ABILITY_MIN, ABILITY_MAX + 1))
def test_modifier_walks_the_whole_band_rounding_down(score):
    # Both halves of the rounding: 9 → −1 (−0.5 rounds DOWN, not toward
    # zero) and 11 → 0 — the spec's «округление вниз» verbatim.
    assert ability_modifier(score) == _MODIFIERS_BY_SCORE[score]


@pytest.mark.parametrize("score", range(ABILITY_MIN, ABILITY_MAX + 1))
def test_check_is_the_modifier_itself(score):
    # Spec: «проверка» = модификатор — every value of the band.
    assert check_value(score) == ability_modifier(score)


def test_modifier_band_edges_are_the_spec_scenario_numbers():
    assert ability_modifier(16) == 3  # scenario «Сила 16 … проверка +3»
    assert ability_modifier(8) == -1
    assert ability_modifier(1) == -5
    assert ability_modifier(30) == 10


# ── proficiency bonus by level (1…20 and «не задан») ───────────────────────


@pytest.mark.parametrize(
    ("level", "bonus"),
    [
        *[(level, 2) for level in (1, 2, 3, 4)],
        *[(level, 3) for level in (5, 6, 7, 8)],
        *[(level, 4) for level in (9, 10, 11, 12)],
        *[(level, 5) for level in (13, 14, 15, 16)],
        *[(level, 6) for level in (17, 18, 19, 20)],
    ],
)
def test_proficiency_bonus_covers_every_spec_band(level, bonus):
    # 1–4 → +2, 5–8 → +3, 9–12 → +4, 13–16 → +5, 17–20 → +6 — every band
    # walked at its first AND last level (the boundaries are where a
    # formula drift shows first).
    assert proficiency_bonus(level) == bonus


def test_proficiency_bonus_without_a_level_is_the_minimal_two():
    # Spec scenario «Без уровня бонус мастерства минимальный».
    assert proficiency_bonus(None) == 2


@pytest.mark.parametrize("bad", [0, 21, -1, 999, True, False, "7", 7.0])
def test_proficiency_bonus_refuses_levels_outside_the_band(bad):
    with pytest.raises(ValueError) as caught:
        proficiency_bonus(bad)
    assert str(caught.value) == PROFICIENCY_LEVEL_REFUSAL


# ── saves / skills / passive senses ─────────────────────────────────────────


@pytest.mark.parametrize("proficient", [True, False])
def test_saving_throw_adds_the_whole_bonus_only_when_proficient(proficient):
    # Spec scenario «Правка характеристики двигает производные» on Сила 16:
    # +3 base; proficiency carries exactly the bonus (+2 without a level).
    assert saving_throw_value(16, 2, proficient) == 3 + (2 if proficient else 0)


@pytest.mark.parametrize("proficient", [True, False])
def test_skill_value_matches_the_save_arithmetic(proficient):
    assert skill_value(13, 4, proficient) == 1 + (4 if proficient else 0)


def test_switching_a_skill_moves_it_and_its_passive_sense_identically():
    # Spec scenario «Отметил навык — выросли и он, и пассивное чувство»:
    # both grow by exactly the proficiency bonus.
    for bonus in (2, 6):
        for score in (8, 16):
            unproficient = skill_value(score, bonus, False)
            proficient = skill_value(score, bonus, True)
            assert proficient - unproficient == bonus
            assert (
                passive_sense_value(score, bonus, True)
                - passive_sense_value(score, bonus, False)
                == bonus
            )


def test_passive_sense_is_ten_plus_the_skill():
    # Perception 16 (mod +3, proficient, +2) → 10 + 5 = 15; unproficient 13.
    assert passive_sense_value(16, 2, True) == 15
    assert passive_sense_value(16, 2, False) == 13


# ── jumps and carry ─────────────────────────────────────────────────────────


# NOTE on the high jump: the requirement formula — and design Д7 verbatim
# («высота = 3 + модификатор») — gives 6 for Сила 16, while the scenario
# line of the same spec prints «высота 4». The formula wins (two
# authoritative statements agree, the scenario is the arithmetic outlier);
# the deviation is reported to the change owner, the tests pin the FORMULA
# so a later fix of the scenario text or of this choice stays visible.
def test_strength_sixteen_feeds_and_jumps_the_scenarios_three_honest_numbers():
    stats = jumps_and_carry(16)
    assert stats.carry_limit_pounds == 240  # 15 × the VALUE, not the modifier
    assert stats.long_jump_feet == 16
    assert stats.standing_long_jump_feet == 8  # half
    assert stats.high_jump_feet == 3 + ability_modifier(16) == 6


def test_odd_strength_stands_on_whole_feet_rounded_down():
    stats = jumps_and_carry(15)
    assert stats.carry_limit_pounds == 225
    assert stats.long_jump_feet == 15
    assert stats.standing_long_jump_feet == 7  # whole feet — half rounds down
    assert stats.high_jump_feet == 5  # 3 + modifier(15) = 3 + 2


def test_weak_strength_high_jump_dips_below_three():
    # High jump is 3 + the modifier — a weak character's modifier is
    # negative and the distance honestly shrinks (Сила 8 → 3 − 1 = 2).
    stats = jumps_and_carry(8)
    assert stats.high_jump_feet == 2
    assert stats.carry_limit_pounds == 120
    assert stats.standing_long_jump_feet == 4


# ── saving-throw ownership (design Д8) ─────────────────────────────────────


def test_class_saves_own_the_saves_when_named():
    resolved = resolve_saving_throw_profs(["strength", "constitution"], {"wisdom"})
    assert resolved == frozenset({"strength", "constitution"})


def test_without_class_saves_the_manual_set_answers():
    assert resolve_saving_throw_profs(None, {"wisdom"}) == frozenset({"wisdom"})
    # An empty class answer («запись не указана») is the manual mode too.
    assert resolve_saving_throw_profs([], {"wisdom"}) == frozenset({"wisdom"})


def test_resolution_is_a_frozen_copy_of_the_inputs():
    saves = resolve_saving_throw_profs(["strength"], [])
    assert isinstance(saves, frozenset)


# ── the штатный skill list and the passive trio ────────────────────────────


def test_skill_list_is_the_shtatny_eighteen_over_the_six_abilities():
    assert len(SKILL_ABILITIES) == 18
    assert set(SKILL_ABILITIES.values()) <= set(ABILITY_KEYS)
    # The D&D truth the list encodes: five abilities carry skills, the
    # sixteenth fact is that Телосложение owns none — an owned-by-all assert
    # would invent a constitution skill the штатный list does not have.
    assert "constitution" not in SKILL_ABILITIES.values()
    abilities_without_skills = set(ABILITY_KEYS) - set(SKILL_ABILITIES.values())
    assert abilities_without_skills == {"constitution"}
    assert len(ABILITY_KEYS) == 6


def test_passive_senses_are_the_named_trio_of_real_skills():
    assert PASSIVE_SENSE_SKILLS == ("perception", "insight", "investigation")
    assert set(PASSIVE_SENSE_SKILLS) <= SKILL_ABILITIES.keys()


def test_alignment_list_is_the_fixed_nine_of_the_spec():
    assert len(ALIGNMENTS) == 9
    assert len(set(ALIGNMENTS)) == 9
    assert "истинно нейтральный" in ALIGNMENTS


# ── gates: the six values (all-or-nothing) ─────────────────────────────────


_FULL_SCORES = {
    "strength": 16,
    "dexterity": 14,
    "constitution": 15,
    "intelligence": 10,
    "wisdom": 11,
    "charisma": 8,
}


def test_scores_gate_passes_the_full_set_through():
    assert validate_ability_scores(_FULL_SCORES) == _FULL_SCORES


@pytest.mark.parametrize("scores", [None, {}])
def test_scores_gate_reads_absent_as_nothing_to_store(scores):
    # «Не храниться вовсе» is a legal state: clearing goes through the gate.
    assert validate_ability_scores(scores) is None


def test_scores_gate_refuses_a_partial_set():
    # Spec: «Непустой набор шести значений SHALL храниться целиком» — five
    # of six is refused, never half-stored.
    partial = dict(_FULL_SCORES)
    del partial["charisma"]
    with pytest.raises(ValueError) as caught:
        validate_ability_scores(partial)
    assert str(caught.value) == SCORES_REFUSAL


@pytest.mark.parametrize("bad", [0, 31, -1, True, "16", 16.0])
def test_scores_gate_refuses_out_of_band_and_non_whole_values(bad):
    scores = dict(_FULL_SCORES, charisma=bad)
    with pytest.raises(ValueError):
        validate_ability_scores(scores)


def test_scores_gate_returns_exactly_the_six_keys_in_order():
    result = validate_ability_scores(dict(reversed(list(_FULL_SCORES.items()))))
    assert list(result) == list(ABILITY_KEYS)


# ── gates: slots, alignment, proficiency keys ──────────────────────────────


@pytest.mark.parametrize("slots", [None, {}])
def test_slots_gate_reads_absent_as_an_empty_grid(slots):
    assert validate_spell_slots(slots) == {}


def test_slots_gate_returns_the_grid_in_level_order():
    assert validate_spell_slots({9: 1, 1: 4, 2: 3}) == {1: 4, 2: 3, 9: 1}


@pytest.mark.parametrize(
    "bad", [{0: 1}, {10: 1}, {1: -1}, {1: 100}, {1: True}, {True: 1}, {"1": 1}, {1: "4"}]
)
def test_slots_gate_refuses_out_of_band_pairs(bad):
    with pytest.raises(ValueError) as caught:
        validate_spell_slots(bad)
    assert str(caught.value) == SLOTS_REFUSAL


def test_slots_band_edges_are_legal():
    assert validate_spell_slots({1: 0, 9: 99}) == {1: 0, 9: 99}


@pytest.mark.parametrize("alignment", [None, *ALIGNMENTS])
def test_alignment_gate_passes_the_nine_and_unset(alignment):
    assert validate_alignment(alignment) == alignment


def test_alignment_gate_reads_empty_string_as_unset():
    assert validate_alignment("") is None


def test_alignment_gate_refuses_hand_typed_invention():
    with pytest.raises(ValueError) as caught:
        validate_alignment("нейтрально-добрый-злой")
    assert str(caught.value) == ALIGNMENT_REFUSAL


def test_skill_gate_accepts_the_shtatny_subset_and_empty():
    assert validate_skill_keys(["perception", "athletics"]) == frozenset(
        {"perception", "athletics"}
    )
    assert validate_skill_keys([]) == frozenset()


def test_skill_gate_refuses_an_unknown_skill():
    with pytest.raises(ValueError) as caught:
        validate_skill_keys(["perception", "baking"])
    assert str(caught.value) == SKILLS_REFUSAL


def test_saving_throw_gate_accepts_the_six_and_empty():
    assert validate_saving_throw_keys(ABILITY_KEYS) == frozenset(ABILITY_KEYS)
    assert validate_saving_throw_keys([]) == frozenset()


def test_saving_throw_gate_refuses_a_non_ability():
    with pytest.raises(ValueError) as caught:
        validate_saving_throw_keys(["perception"])
    assert str(caught.value) == SAVING_THROWS_REFUSAL


# ── the read value ──────────────────────────────────────────────────────────


def test_empty_mechanics_is_the_never_edited_block():
    mechanics = empty_mechanics()
    assert mechanics == CharacterMechanics()
    assert mechanics.scores is None
    assert mechanics.speed is None
    assert mechanics.alignment is None
    assert mechanics.spell_slots == {}
    assert mechanics.skill_proficiencies == frozenset()
    assert mechanics.manual_saving_throws == frozenset()
