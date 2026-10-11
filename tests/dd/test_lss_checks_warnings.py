"""Warning-category checks and report determinism (task 4.4).

Table-driven where the check is a value table; every warning must leave the
import threshold untouched, and the whole report must be byte-identical
between two runs of the same file.
"""
from __future__ import annotations

from app.dd.domain.validation_report import Severity
from tests.dd.lss_check_fixtures import base_dataset, check_document, class_with, codes, srd_like_connected


def warning_codes(issues) -> list[str]:
    return [i.code for i in issues if i.severity is Severity.WARNING]


# ---------------------------------------------------------------------------
def test_trait_with_params_and_prose_warns_about_the_lost_channel():
    cases = [
        # (params, description, expected)
        ({"ft": 60}, "Видите в темноте.", True),
        ({"ft": 60}, "   ", False),
        ({}, "Текст", False),
        (None, "Текст", False),
    ]
    for params, description, expected in cases:
        trait = {"type": "trait", "id": "t", "name": "T", "description": description}
        if params is not None:
            trait["params"] = params
        issues = check_document(base_dataset(classes=[class_with(trait)]))
        fired = "TRAIT_PARAMS_PROSE" in codes(issues)
        assert fired is expected, (params, description)


def test_unparsable_roll_formula_warns():
    cases = [
        ("5d4*10", False),
        ("2 d 6", False),
        ("ceil([LVL])", False),
        ("2d", True),
        ("[HAR]d6", True),
    ]
    for dice, expected in cases:
        document = base_dataset(
            classes=[class_with({"type": "gold-dice", "dice": dice})]
        )
        assert ("ROLL_FORMULA" in codes(check_document(document))) is expected, dice


def test_counter_without_a_matching_trait_warns():
    cases = [
        # (extra resource fields, warning expected)
        ({"pairId": "font-of-magic"}, True),  # no such trait anywhere
        ({"pairId": None}, False),  # deliberate unpairing
        ({"pairId": "described"}, False),  # trait with that id exists below
        ({}, True),  # no pairId: pairs by id, no such trait
        ({"pairId": ""}, False),  # empty: nothing to look up
    ]
    trait = {"type": "trait", "id": "described", "name": "T"}
    for extra, expected in cases:
        resource = {"type": "resource", "id": "counter", "name": "C", "max": 1}
        resource.update(extra)
        document = base_dataset(classes=[class_with(trait, resource)])
        assert ("COUNTER_PAIR" in codes(check_document(document))) is expected, extra


def test_grant_type_without_consumer_channel_warns():
    cases = [
        ("races", {"type": "hp-die", "die": 8}, True),
        ("classes", {"type": "hp-die", "die": 8}, False),
        ("classes", {"type": "size", "value": "small"}, True),
        ("subraces", {"type": "size", "value": "small"}, False),
        ("classes", {"type": "gold", "amount": 25}, False),
    ]
    for section, grant, expected in cases:
        if section == "classes":
            entity = class_with(grant)
        else:
            entity = {"id": "elf", "label": "Elf", "size": "medium", "grants": [grant]}
        document = base_dataset(**{section: [entity]})
        assert ("CONSUMER_CHANNEL" in codes(check_document(document))) is expected, (section, grant)


def test_open_feat_slot_without_candidates_warns():
    open_slot = {
        "backgrounds": [
            {"id": "human", "label": "Human", "grants": [{"type": "feat", "featId": "any"}]}
        ]
    }
    document = base_dataset(**open_slot)
    issues = [i for i in check_document(document) if i.code == "FEAT_SLOT_NO_CANDIDATES"]
    assert len(issues) == 1
    filled = base_dataset(
        **open_slot, feats=[{"id": "alert", "label": "Alert", "grants": []}]
    )
    assert "FEAT_SLOT_NO_CANDIDATES" not in codes(check_document(filled))


def test_spell_fixed_slug_checked_against_lists_and_skipped_without_them():
    spell = {"type": "spell-fixed", "slug": "magic-missile"}
    document = base_dataset(classes=[class_with(spell)])
    # no downloaded lists — exactly this check stays silent
    assert check_document(document) == []
    # lists present: known slug passes, foreign one warns
    assert check_document(document, spell_slugs=["magic-missile", "shield"]) == []
    issues = check_document(document, spell_slugs=["shield"])
    assert [i.code for i in issues] == ["SPELL_SLUG_NOT_SRD"]


def test_slots_table_warnings():
    cases = [
        ("empty", [], "SLOTS_TABLE_EMPTY"),
        ("long row", [[0] * 10] + [[] for _ in range(20)], "SLOTS_TABLE_ROW_LEN"),
        ("normal", [[] for _ in range(21)], None),
    ]
    for name, table, expected in cases:
        document = base_dataset(
            classes=[
                class_with(
                    {
                        "type": "spellcasting",
                        "ability": "int",
                        "casterType": "book",
                        "spellList": "wizard",
                        "slotsByLevel": table,
                    }
                )
            ]
        )
        got = warning_codes(check_document(document))
        assert (expected in got) is (expected is not None), name
        if expected is None:
            assert got == []


# ---------------------------------------------------------------------------
def test_warnings_never_block_and_report_is_deterministic():
    """Spec «Детерминированность»: two runs of one file give identical reports."""
    from app.dd.application.dataset_validator_service import DatasetValidatorService
    import json

    noisy = base_dataset(
        classes=[
            class_with(
                {"type": "trait", "id": "darkvision", "name": "Darkvision",
                 "params": {"ft": 60}, "description": "Видите в темноте."},
                {"type": "gold-dice", "dice": "не-формула"},
                {"type": "hp-die", "die": 8},
            )
        ],
        races=[{"id": "elf", "label": "Elf", "size": "medium",
                "grants": [{"type": "hp-die", "die": 8}]}],
    )
    service = DatasetValidatorService()
    content = json.dumps(noisy, ensure_ascii=False)
    first = service.validate(content)
    second = service.validate(content)
    assert first.issues == second.issues
    assert first.import_allowed  # warnings only — import must proceed
    assert warning_codes(first.issues)  # sanity: the file does warn


def test_link_warnings_and_errors_resolve_over_connected_sets_together():
    document = base_dataset(
        subclasses=[{"id": "thief-hb", "classId": "wizard", "label": "T", "grants": [
            {"type": "resource", "id": "trick", "name": "Trick", "pairId": "sneak-attack", "max": 1}
        ]}],
    )
    connected = srd_like_connected()
    connected.document["classes"][0]["grants"] = [
        {"type": "trait", "id": "sneak-attack", "name": "SA"}
    ]
    # unconnected: link error + lonely counter warning
    assert "LINK_CLASS" in codes(check_document(document))
    assert "COUNTER_PAIR" in warning_codes(check_document(document))
    # connected over the official set: both resolve
    assert check_document(document, connected=(connected,)) == []
