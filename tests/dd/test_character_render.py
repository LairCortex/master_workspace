"""The structural render (add-dnd-game-face task 9.2, design Д7; spec
dnd-character-import «Структура читается без LSS»).

Pinned contract: the eight named blocks arrive in the fixed order, the same
document always renders the same lines (determinism), known slugs gain their
Russian labels while unknown slugs print as they stand, empty families
produce NO block, and tolerant garbage — non-dict entries, bool masquerading
as int, missing names — never reaches the reader's eyes as noise.
"""
from __future__ import annotations

from app.dd.domain.character_render import (
    BLOCK_BONUSES,
    BLOCK_COINS,
    BLOCK_SAVES,
    BLOCK_SKILLS,
    BLOCK_SLOTS,
    BLOCK_STATS,
    BLOCK_WEAPONS,
    structural_blocks,
)


def _as_dict(blocks) -> dict[str, str]:
    return dict(blocks)


def test_empty_document_produces_no_blocks():
    assert structural_blocks({}) == []


def test_same_document_renders_byte_identical_twice():
    data = {
        "stats": {"str": {"value": 16, "save": True}, "dex": {"value": 12}},
        "skills": {"stealth": {"proficient": True}},
        "coins": {"gp": 10},
    }
    assert structural_blocks(data) == structural_blocks(data)


def test_stats_save_in_the_sheet_order_unknown_slugs_last_alphabetical():
    blocks = _as_dict(
        structural_blocks(
            {
                "stats": {
                    "zzz": {"value": 3},
                    "cha": {"value": 8},
                    "str": {"value": 16},
                    "aaa": {"value": 9},
                }
            }
        )
    )
    assert blocks["Характеристики"] == "Сила: 16\nХаризма: 8\naaa: 9\nzzz: 3"


def test_saves_print_bool_as_proficiency_signed_ints_with_glyphs():
    blocks = _as_dict(
        structural_blocks(
            {
                "stats": {
                    "str": {"save": True},
                    "dex": {"save": False},
                    "con": {"save": 5},
                    "int": {"save": -1},
                    "wis": {"save": "не число"},
                    "cha": "не объект",
                }
            }
        )
    )
    # canonical order str→cha; False, non-number and non-object entries skip.
    assert blocks[BLOCK_SAVES] == "Сила: владеет\nТелосложение: +5\nИнтеллект: −1"


def test_stat_bool_never_passes_as_a_score():
    blocks = _as_dict(structural_blocks({"stats": {"str": {"value": True}}}))
    assert BLOCK_STATS not in blocks


def test_skills_list_only_the_proficient_known_and_unknown_labels():
    blocks = _as_dict(
        structural_blocks(
            {
                "skills": {
                    "stealth": {"proficient": False},
                    "athletics": {"proficient": True},
                    "art_of_war": {"proficient": True},
                    "broken": "не объект",
                }
            }
        )
    )
    # alphabetical over the slugs: art_of_war before athletics.
    assert blocks[BLOCK_SKILLS] == "- art_of_war\n- Атлетика"


def test_bonus_lines_tolerant_shapes():
    blocks = _as_dict(
        structural_blocks(
            {
                "bonuses": [
                    {"target": "spell_attack", "formula": "[Prof]"},
                    {"target": "ac", "value": 1},
                    {"target": "naked"},
                    {"target": "", "formula": "x"},
                    {"formula": "orphan"},
                    "не объект",
                ]
            }
        )
    )
    assert blocks[BLOCK_BONUSES] == "- spell_attack: [Prof]\n- ac: 1\n- naked"


def test_weapon_lines_join_the_formulae_with_dots():
    blocks = _as_dict(
        structural_blocks(
            {
                "weaponsList": [
                    {
                        "name": "Боевой топор",
                        "attackFormula": "[STR]+[Prof]",
                        "damageFormula": "1d8+[STR]",
                    },
                    {"name": "Кинжал"},
                    {"attackFormula": "без имени"},
                    "не объект",
                ]
            }
        )
    )
    assert blocks[BLOCK_WEAPONS] == (
        "- Боевой топор · атака [STR]+[Prof] · урон 1d8+[STR]\n- Кинжал"
    )


def test_resource_lines_count_only_int_pairs():
    blocks = _as_dict(
        structural_blocks(
            {
                "resources": [
                    {"name": "Ярость", "value": 2, "max": 3},
                    {"name": "Без счётчика"},
                    {"name": "Странное", "value": "x", "max": 3},
                    {"value": 1, "max": 2},
                    "не объект",
                ]
            }
        )
    )
    assert blocks["Ресурсы"] == "- Ярость: 2/3\n- Без счётчика\n- Странное"


def test_coins_print_pp_to_cp_then_unknown_alphabetical():
    blocks = _as_dict(
        structural_blocks({"coins": {"gp": 50, "cp": 3, "amber": 1, "bool": True}})
    )
    assert blocks[BLOCK_COINS] == "gp: 50\ncp: 3\namber: 1"


def test_spell_slot_lines_level_first_only_int_pairs():
    blocks = _as_dict(
        structural_blocks(
            {
                "spells": {
                    "slots": [
                        {"level": 1, "value": 3, "max": 4},
                        {"level": 2},
                        {"level": "x", "value": 1, "max": 1},
                        "не объект",
                    ]
                }
            }
        )
    )
    assert blocks[BLOCK_SLOTS] == "- 1-й круг: 3 / 4\n- 2-й круг"


def test_slots_without_a_list_silently_absent():
    assert BLOCK_SLOTS not in _as_dict(structural_blocks({"spells": "не объект"}))
    assert BLOCK_SLOTS not in _as_dict(structural_blocks({"spells": {"slots": "не список"}}))


def test_full_document_lays_the_eight_blocks_in_the_fixed_order():
    blocks = structural_blocks(
        {
            "stats": {"str": {"value": 16, "save": True}},
            "skills": {"athletics": {"proficient": True}},
            "bonuses": [{"target": "ac", "value": 1}],
            "weaponsList": [{"name": "Топор"}],
            "resources": [{"name": "Рывок", "value": 1, "max": 1}],
            "coins": {"gp": 1},
            "spells": {"slots": [{"level": 1, "value": 1, "max": 2}]},
        }
    )
    assert [name for name, _text in blocks] == [
        "Характеристики",
        "Спасброски",
        "Навыки",
        "Бонусы",
        "Оружие",
        "Ресурсы",
        "Монеты",
        "Ячейки заклинаний",
    ]
