"""Error-category cross-field checks (task 4.3).

One test per check from the LSS list, each proving both halves: the violation
fires with the RU text and a document path, the clean document stays silent.
Plus the spec scenario «Ссылка через подключённый набор».
"""
from __future__ import annotations

from tests.dd.lss_check_fixtures import (
    base_dataset,
    check_document,
    class_with,
    codes,
    srd_like_connected,
)
from app.dd.domain.validation_report import Severity


def error_codes(issues) -> list[str]:
    return [i.code for i in issues if i.severity is Severity.ERROR]


# ---------------------------------------------------------------------------
# license
# ---------------------------------------------------------------------------
def test_license_out_of_whitelist_is_error():
    for bad in ("CC-BY", "CC-BY-NC-4.0", "", "MIT"):
        issues = check_document(base_dataset(license=bad))
        assert "LICENSE" in codes(issues), bad


def test_license_missing_is_error():
    document = base_dataset()
    del document["license"]
    assert error_codes(check_document(document)) == ["LICENSE"]


def test_licensed_documents_pass():
    for good in ("CC0", "CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0"):
        assert check_document(base_dataset(license=good)) == [], good


# ---------------------------------------------------------------------------
# unique ids inside a collection
# ---------------------------------------------------------------------------
def test_duplicate_ids_inside_one_collection_report_both_paths():
    document = base_dataset(
        classes=[
            class_with(entity_id="cleric"),
            class_with(entity_id="cleric"),
        ]
    )
    issues = [i for i in check_document(document) if i.code == "DUP_ID"]
    assert len(issues) == 1
    assert "classes[cleric]" in issues[0].message
    assert issues[0].path == "classes[cleric]"


def test_same_id_in_different_collections_is_fine():
    document = base_dataset(
        classes=[class_with(entity_id="elf")],
        races=[{"id": "elf", "label": "Elf", "size": "medium", "grants": []}],
    )
    assert codes(check_document(document)) == []


# ---------------------------------------------------------------------------
# cross-entity links, resolved across ALL connected sets
# ---------------------------------------------------------------------------
def test_subclass_classid_must_resolve():
    document = base_dataset(
        subclasses=[{"id": "thief", "classId": "rogue", "label": "Thief", "grants": []}]
    )
    issues = [i for i in check_document(document) if i.code == "LINK_CLASS"]
    assert issues and "rogue" in issues[0].message


def test_subclass_link_through_connected_set_is_valid():
    """Spec scenario «Ссылка через подключённый набор»."""
    document = base_dataset(
        subclasses=[{"id": "school-hb", "classId": "wizard", "label": "HB", "grants": []}]
    )
    assert check_document(document) != []
    assert check_document(document, connected=(srd_like_connected(),)) == []


def test_subrace_raceid_must_resolve():
    document = base_dataset(
        subraces=[{"id": "high-elf", "raceId": "elf", "label": "High Elf", "grants": []}]
    )
    assert [i.code for i in check_document(document)] == ["LINK_RACE"]
    assert check_document(document, connected=(srd_like_connected(),)) == []


def test_featid_must_resolve_and_any_is_open_slot():
    document = base_dataset(
        feats=[{"id": "lucky", "label": "Lucky", "grants": []}],
        backgrounds=[
            {
                "id": "criminal",
                "label": "Criminal",
                "grants": [{"type": "feat", "featId": "alert"}],
            }
        ],
    )
    issues = [i for i in check_document(document) if i.code == "LINK_FEAT"]
    assert issues and "alert" in issues[0].message

    resolved = base_dataset(
        feats=[{"id": "alert", "label": "Alert", "grants": []}],
        backgrounds=[
            {
                "id": "criminal",
                "label": "Criminal",
                "grants": [{"type": "feat", "featId": "alert"}],
            }
        ],
    )
    assert check_document(resolved) == []

    open_slot = base_dataset(
        feats=[{"id": "alert", "label": "Alert", "grants": []}],
        backgrounds=[
            {
                "id": "human",
                "label": "Human",
                "grants": [{"type": "feat", "featId": "any"}],
            }
        ],
    )
    assert check_document(open_slot) == []


# ---------------------------------------------------------------------------
# bonus
# ---------------------------------------------------------------------------
def test_bonus_carries_exactly_one_of_value_or_expr():
    both = class_with(
        {"type": "bonus", "target": "ac", "label": "L", "value": 1, "expr": "1"}
    )
    neither = class_with({"type": "bonus", "target": "ac", "label": "L"}, entity_id="barbarian")
    document = base_dataset(classes=[both, neither])
    assert codes(check_document(document)).count("BONUS_SOURCE_XOR") == 2

    clean = base_dataset(
        classes=[
            class_with({"type": "bonus", "target": "ac", "label": "L", "value": 1}),
            class_with({"type": "bonus", "target": "ac", "label": "L", "expr": "[PROF]"}, entity_id="bard"),
        ]
    )
    assert check_document(clean) == []


def test_bonus_formula_must_compute():
    document = base_dataset(
        classes=[class_with({"type": "bonus", "target": "ac", "label": "L", "expr": "1d"})]
    )
    issues = [i for i in check_document(document) if i.code == "FORMULA"]
    assert issues and "1d" in issues[0].message


def test_bonus_target_must_be_from_the_schema_enum():
    bad = class_with({"type": "bonus", "target": "skill.stelth", "label": "L", "value": 1})
    closed = class_with({"type": "bonus", "target": "skill.stealth", "label": "L", "value": 1})
    # open families (weapon.<key>.attack) are legal by schema pattern
    pattern = class_with(
        {"type": "bonus", "target": "weapon.longsword.attack", "label": "L", "value": 1}
    )
    document = base_dataset(classes=[bad, closed, pattern])
    issues = [i for i in check_document(document) if i.code == "BONUS_TARGET"]
    assert len(issues) == 1
    assert "skill.stelth" in issues[0].message


# ---------------------------------------------------------------------------
# keys from the closed schema lists
# ---------------------------------------------------------------------------
def test_skill_keys_from_schema_list():
    document = base_dataset(
        classes=[
            class_with(
                {"type": "skill-fixed", "skills": ["stelth"]},
                {"type": "skill-choice", "count": 1, "options": ["athletics", "perceptio"]},
                {"type": "expertise-choice", "count": 1, "options": ["acrobatics"]},
                {"type": "skill-choice", "count": 1, "options": "any"},
            )
        ]
    )
    key_issues = [i for i in check_document(document) if i.code == "KEY"]
    assert len(key_issues) == 2
    texts = " ".join(i.message for i in key_issues)
    assert "stelth" in texts and "perceptio" in texts


def test_stat_armor_weapon_keys_from_schema_list():
    document = base_dataset(
        classes=[
            class_with(
                # save.cor exists in the bonus-target enum but is not a StatKey
                {"type": "saving-throw", "stats": ["cor", "con"]},
                {"type": "asi-fixed", "values": {"str": 2, "flo": 1}},
                {"type": "asi-pool", "total": 3, "max": 2, "options": ["str", "dexx"]},
                {
                    "type": "asi-flexible",
                    "sets": [{"count": 1, "amount": 2, "options": ["wis", "hp"]}],
                },
                {"type": "armor-prof", "armors": ["armor-heavy", "shield-x"]},
                {"type": "weapon-prof", "weapons": ["weapon-simple", "weapon-rare"]},
            )
        ]
    )
    key_issues = [i for i in check_document(document) if i.code == "KEY"]
    bad_keys = ["cor", "flo", "dexx", "hp", "shield-x", "weapon-rare"]
    for key in bad_keys:
        assert any(f"'{key}'" in i.message for i in key_issues), key
    assert not any("'con'" in i.message for i in key_issues)


# ---------------------------------------------------------------------------
# choice grants offer at least one slot
# ---------------------------------------------------------------------------
def test_choice_grant_must_offer_at_least_one_slot():
    document = base_dataset(
        classes=[
            class_with(
                {"type": "skill-choice", "count": 0, "options": "any"},
                {"type": "tool-choice", "count": -1, "options": []},
                {"type": "asi-pool", "total": 0, "max": 2, "options": ["str"]},
                {"type": "equipment-choice", "options": []},
                {"type": "pick-one", "options": []},
            )
        ]
    )
    assert codes(check_document(document)).count("CHOICE_EMPTY") == 5


# ---------------------------------------------------------------------------
# named pick-one: options carry stable ids; recursion into nested grants
# ---------------------------------------------------------------------------
def test_named_pick_one_requires_option_ids():
    named = {
        "type": "pick-one",
        "id": "draconic-ancestry",
        "options": [{"label": "Red", "grants": []}, {"label": "Blue", "id": "blue", "grants": []}],
    }
    free = {"type": "pick-one", "options": [{"label": "Gear", "grants": []}]}
    document = base_dataset(classes=[class_with(named, free)])
    issues = [i for i in check_document(document) if i.code == "PICK_ONE_OPTION_ID"]
    assert len(issues) == 1
    assert "options[0]" in issues[0].path


def test_named_pick_one_option_ids_are_unique():
    named = {
        "type": "pick-one",
        "id": "ancestry",
        "options": [
            {"label": "A", "id": "same", "grants": []},
            {"label": "B", "id": "same", "grants": []},
        ],
    }
    issues = [i for i in check_document(base_dataset(classes=[class_with(named)])) if i.code == "PICK_ONE_OPTION_DUP"]
    assert len(issues) == 1


def test_recursion_walks_into_pick_one_nested_grants():
    """The error hides inside options[].grants — only a recursive walk sees it."""
    nested = {
        "type": "pick-one",
        "options": [
            {
                "label": "Option",
                "grants": [
                    {
                        "type": "pick-one",
                        "options": [
                            {
                                "label": "Deeper",
                                "grants": [
                                    {"type": "bonus", "target": "не-таргет", "label": "L", "value": 1}
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    issues = [i for i in check_document(base_dataset(classes=[class_with(nested)])) if i.code == "BONUS_TARGET"]
    assert len(issues) == 1
    assert issues[0].path.endswith("options[0].grants[0](bonus)")
    assert "pick-one" in issues[0].path


# ---------------------------------------------------------------------------
# resource counter
# ---------------------------------------------------------------------------
def test_resource_carries_exactly_one_of_max_or_maxexpr():
    both = {"type": "resource", "id": "ki", "name": "Ki", "max": 1, "maxExpr": "[LVL]", "pairId": None}
    neither = {"type": "resource", "id": "rage", "name": "Rage", "pairId": None}
    clean = {"type": "resource", "id": "focus", "name": "Focus", "max": 5, "pairId": None}
    document = base_dataset(classes=[class_with(both, neither, clean)])
    assert codes(check_document(document)).count("RESOURCE_SOURCE_XOR") == 2
    clean_doc = base_dataset(
        classes=[class_with({"type": "resource", "id": "r", "name": "R", "max": 3, "pairId": None})]
    )
    assert check_document(clean_doc) == []


def test_resource_maxexpr_must_compute():
    document = base_dataset(
        classes=[class_with({"type": "resource", "id": "r", "name": "R", "maxExpr": "2d", "pairId": None})]
    )
    assert [i.code for i in check_document(document)] == ["FORMULA"]


# ---------------------------------------------------------------------------
# spell checks
# ---------------------------------------------------------------------------
def test_spell_choice_requires_count_circle_and_list():
    document = base_dataset(
        classes=[
            class_with(
                {"type": "spell-choice", "count": 0, "circle": 5, "spellList": "wizard"},
                {"type": "spell-choice", "count": 1, "circle": 10, "spellList": "wizard"},
                {"type": "spell-choice", "count": 1, "circle": 0, "spellList": "wizard"},
                {"type": "spell-choice", "count": 1, "circle": 0, "spellList": ""},
            )
        ]
    )
    got = codes(check_document(document))
    assert got.count("SPELL_CHOICE_EMPTY") == 1
    assert got.count("SPELL_CHOICE_CIRCLE") == 1
    assert got.count("SPELL_CHOICE_DUP_CIRCLE") == 1
    assert got.count("SPELL_LIST") == 1  # only the empty one: wizard is this class


def test_two_spell_choices_one_circle_on_one_entity_is_error():
    spec_scenario = class_with(
        {"type": "spell-choice", "count": 1, "circle": 1, "spellList": "wizard"},
        {"type": "spell-choice", "count": 2, "circle": 1, "spellList": "wizard"},
    )
    other_circle = class_with(
        {"type": "spell-choice", "count": 1, "circle": 1, "spellList": "wizard"},
        {"type": "spell-choice", "count": 2, "circle": 0, "spellList": "wizard"},
    )
    document = base_dataset(classes=[spec_scenario, other_circle])
    issues = [i for i in check_document(document) if i.code == "SPELL_CHOICE_DUP_CIRCLE"]
    assert len(issues) == 1
    assert "круга 1" in issues[0].message


def test_own_caster_class_must_declare_spelllist():
    """Homebrew caster without spellList: slots would ship with an empty list."""
    caster = class_with({"type": "spellcasting", "ability": "int", "casterType": "book"})
    document = base_dataset(classes=[caster])
    issues = [i for i in check_document(document) if i.code == "SPELL_CASTER_LIST"]
    assert len(issues) == 1

    with_list = class_with(
        {"type": "spellcasting", "ability": "int", "casterType": "book", "spellList": "wizard"}
    )
    covered_set = base_dataset(classes=[with_list], subclasses=[
        {"id": "evoker", "classId": "wizard", "label": "Evoker", "grants": [
            {"type": "spellcasting", "ability": "int", "casterType": "book"}
        ]}
    ])
    assert check_document(covered_set) == []

    # official file: its own class ids are covered the way LSS's database does
    official = base_dataset(classes=[caster])
    assert check_document(official, own_is_official=True) == []

    # covered by a connected official set under the same class id
    connected_cover = base_dataset(
        classes=[{"id": "wizard", "label": "Wizard", "info": {}, "grants": [
            {"type": "spellcasting", "ability": "int", "casterType": "book"}
        ]}]
    )
    assert check_document(connected_cover, connected=(srd_like_connected(),)) == []


def test_spellcasting_outside_class_needs_explicit_list():
    document = base_dataset(
        races=[{
            "id": "elf", "label": "Elf", "size": "medium", "grants": [
                {"type": "spellcasting", "ability": "wis", "casterType": "list"}
            ]
        }]
    )
    assert "SPELL_CASTER_LIST" in codes(check_document(document))


def test_uses_carries_exactly_one_of_count_or_countexpr():
    both = {
        "type": "spell-fixed",
        "slug": "shield",
        "uses": {"count": 1, "countExpr": "[LVL]", "per": "long-rest"},
    }
    neither = {"type": "spell-fixed", "slug": "shield", "uses": {"per": "long-rest"}}
    good = {"type": "spell-fixed", "slug": "shield", "uses": {"count": 1, "per": "long-rest"}}
    expr_good = {
        "type": "spell-fixed",
        "slug": "shield",
        "uses": {"countExpr": "[PROF]", "per": "long-rest"},
    }
    document = base_dataset(classes=[class_with(both, neither, good, expr_good)])
    assert codes(check_document(document)).count("SPELL_USES_XOR") == 2


def test_short_rest_regain_formula_must_compute():
    document = base_dataset(
        classes=[
            class_with(
                {
                    "type": "spell-fixed",
                    "slug": "heal",
                    "uses": {"count": 1, "per": "short-rest", "shortRestRegain": "ceil("},
                },
                {
                    "type": "resource",
                    "id": "r",
                    "name": "R",
                    "max": 3,
                    "isShortRest": True,
                    "shortRestRegain": "[LVL]/0",
                },
            )
        ]
    )
    formula_issues = [i for i in check_document(document) if i.code == "FORMULA"]
    assert len(formula_issues) == 2


def test_short_rest_regain_at_long_rest_is_error():
    # Spec `dnd-dataset-validator` counts «shortRestRegain … не стоит при
    # длинном отдыхе» among the error-category checks (task 4.3 «все
    # проверки заклинаний»), so the placement issue blocks the import.
    document = base_dataset(
        classes=[
            class_with(
                {
                    "type": "resource",
                    "id": "r1",
                    "name": "R",
                    "max": 3,
                    "isLongRest": True,
                    "shortRestRegain": "[PROF]",
                },
                {
                    "type": "resource",
                    "id": "r2",
                    "name": "R",
                    "max": 3,
                    "isShortRest": True,
                    "isLongRest": True,
                    "shortRestRegain": "[PROF]",
                },
                {
                    "type": "spell-fixed",
                    "slug": "heal",
                    "uses": {"count": 1, "per": "long-rest", "shortRestRegain": "1"},
                },
            )
        ]
    )
    regain = [i for i in check_document(document) if i.code == "REST_REGAIN_LONG_REST"]
    assert len(regain) == 2  # counter without isShortRest + spell uses per long-rest
    assert all(i.severity is Severity.ERROR for i in regain)


def test_slots_table_structure_errors():
    too_short = {"type": "spellcasting", "ability": "int", "casterType": "book",
                 "spellList": "wizard", "slotsByLevel": [[0]] * 5}
    not_rows = {"type": "spellcasting", "ability": "int", "casterType": "book",
                "spellList": "wizard", "slotsByLevel": "rows"}
    bad_cells = {"type": "spellcasting", "ability": "int", "casterType": "book",
                 "spellList": "wizard",
                 "slotsByLevel": [["a"]] + [[] for _ in range(20)]}
    negative = {"type": "spellcasting", "ability": "int", "casterType": "book",
                "spellList": "wizard",
                "slotsByLevel": [[-1]] + [[] for _ in range(20)]}
    fractional = {"type": "spellcasting", "ability": "int", "casterType": "book",
                  "spellList": "wizard",
                  "slotsByLevel": [[1.5]] + [[] for _ in range(20)]}
    row_not_list = {"type": "spellcasting", "ability": "int", "casterType": "book",
                    "spellList": "wizard",
                    "slotsByLevel": ["five"] + [[] for _ in range(20)]}
    document = base_dataset(
        classes=[class_with(too_short, not_rows, bad_cells, negative, fractional, row_not_list)]
    )
    slot_issues = [i for i in check_document(document) if i.code == "SLOTS_TABLE"]
    messages = "\n".join(i.message for i in slot_issues)
    assert "короче 21" in messages
    assert "массивом строк" in messages
    assert "не целое неотрицательное" in messages
    assert "строка 0 таблицы ячеек обязана быть массивом" in messages
    assert len(slot_issues) == 6


def test_slots_table_full_and_correct_is_silent():
    table = [[0] * 9 if level else [] for level in range(21)]
    caster = class_with(
        {"type": "spellcasting", "ability": "int", "casterType": "book", "spellList": "wizard",
         "slotsByLevel": table}
    )
    assert check_document(base_dataset(classes=[caster])) == []


# ---------------------------------------------------------------------------
# spellList reference resolution and countExpr computability
# ---------------------------------------------------------------------------
def test_spell_list_must_name_a_known_class():
    document = base_dataset(
        classes=[
            class_with(
                {"type": "spell-choice", "count": 1, "circle": 0, "spellList": "nope"}
            )
        ]
    )
    issues = [i for i in check_document(document) if i.code == "SPELL_LIST"]
    assert len(issues) == 1 and "nope" in issues[0].message


def test_uses_countexpr_must_compute():
    document = base_dataset(
        classes=[
            class_with(
                {
                    "type": "spell-fixed",
                    "slug": "heal",
                    "uses": {"countExpr": "2d", "per": "long-rest"},
                }
            )
        ]
    )
    assert [i.code for i in check_document(document)] == ["FORMULA"]


def test_feat_grant_without_id_is_ignored_by_link_check():
    document = base_dataset(
        classes=[class_with({"type": "feat", "category": "general"})]
    )
    assert check_document(document) == []


# ---------------------------------------------------------------------------
# defensive traversal: broken structures are skipped, never crash the check
# (the shape validator reports them; cross-field checks must not explode)
# ---------------------------------------------------------------------------
def test_malformed_structures_are_tolerated():
    document = base_dataset(
        classes=[
            class_with(),
            "не-объект вместо сущности",
            {"label": "без id", "grants": "не массив"},
            {"id": "junk", "label": "junk", "info": {}, "grants": ["строка вместо грана"]},
            {
                "id": "weird",
                "label": "weird",
                "info": {},
                "grants": [
                    {"label": "gran без типа"},
                    {
                        "type": "pick-one",
                        "id": "named-broken",
                        "options": "не массив",
                    },
                    {
                        "type": "pick-one",
                        "id": "named-odd",
                        "options": ["строка вместо опции"],
                    },
                ],
                "leveledGrants": ["не блок", {"level": 1, "grants": "не массив"}],
            },
        ],
        races="не список секции",
    )
    issues = check_document(document)
    # the walk survived every broken structure; the healthy license/ids parts
    # still say nothing — no phantom issues from garbage nodes
    assert issues == []


def test_non_mapping_document_returns_empty():
    from app.dd.domain.lss_checks import run_cross_checks
    from tests.dd.lss_check_fixtures import shared_vocabulary

    assert run_cross_checks(["не", "объект"], shared_vocabulary()) == []
