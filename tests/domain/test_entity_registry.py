"""Wave 3 (audit A4, design D2): the single entity-type registry.

These tests pin the registry's completeness, the ``character`` plural
morphology and the exact shape the migrated consumers (card dialog, event
dialog, search, LLM, xlsx) derive from it — any drift in a label, a plural
or a relation order breaks here instead of silently in one consumer.
"""
import pytest

from app.domain import entity_registry as reg
from app.domain.enums.entity_type import EntityType

CARD_TYPES = (
    EntityType.ORGANIZATION,
    EntityType.CHARACTER,
    EntityType.ITEM,
    EntityType.LOCATION,
)


# ── completeness (every EntityType has a full descriptor) ─────────────────


def test_registry_covers_every_entity_type():
    assert set(reg.ORDER) == set(EntityType)
    assert set(reg.RELATED_CONFIG) == set(EntityType)


@pytest.mark.parametrize("entity_type", list(EntityType))
def test_descriptor_is_complete_and_consistent(entity_type):
    desc = reg.descriptor(entity_type)
    assert desc.entity_type is entity_type
    # the string key is the enum value itself — one canonical spelling
    assert desc.key == entity_type.value
    assert desc.label and desc.plural_label
    assert desc.plural.endswith("s")


def test_related_targets_are_registered_types():
    for etype, refs in reg.RELATED_CONFIG.items():
        for ref in refs:
            assert ref.entity_type in reg.ORDER
            assert ref.attr == reg.descriptor(ref.entity_type).plural
            assert ref.label == reg.descriptor(ref.entity_type).plural_label


# ── morphology: the plural form lives only here (A4) ──────────────────────


@pytest.mark.parametrize("entity_type", list(EntityType))
def test_plural_matches_the_historical_manual_formula(entity_type):
    key = entity_type.value
    # the old world-snapshot code spelled plurals as f"{key}s" with an
    # explicit "character" branch; the registry now owns that morphology
    historical = f"{key}s" if key != "character" else "characters"
    assert reg.descriptor(entity_type).plural == historical


def test_character_plural_is_characters():
    assert reg.descriptor(EntityType.CHARACTER).plural == "characters"
    assert reg.collection("character") == "characters"


def test_collection_looks_up_by_type_key():
    assert reg.collection("event") == "events"
    assert reg.collection("organization") == "organizations"


def test_collection_rejects_unknown_keys_like_the_replaced_dicts():
    with pytest.raises(KeyError):
        reg.collection("bogus")


# ── relation sets (the public successor of the card dialog's _RELATED_CONFIG)


def test_entity_relations_are_symmetric_pairs():
    for left in CARD_TYPES:
        for right in reg.related_refs(left):
            assert left in reg.descriptor(right.entity_type).related


def test_event_lists_the_four_card_types_and_no_back():
    assert reg.related_refs(EntityType.EVENT) == tuple(
        reg.RelatedRef(
            target,
            reg.descriptor(target).plural,
            reg.descriptor(target).plural_label,
        )
        for target in (
            EntityType.ORGANIZATION,
            EntityType.CHARACTER,
            EntityType.ITEM,
            EntityType.LOCATION,
        )
    )
    for card_type in CARD_TYPES:
        refs = reg.descriptor(card_type).related
        assert EntityType.EVENT not in refs
        assert card_type not in refs


def test_rating_has_no_relations():
    assert reg.related_refs(EntityType.RATING) == ()


def test_related_config_matches_the_migrated_card_dialog_shape():
    # byte-for-byte the values of the old entity_card_dialog._RELATED_CONFIG
    expected = {
        "organization": [("characters", "Персонажи", "character"),
                         ("items", "Предметы", "item"),
                         ("locations", "Локации", "location")],
        "character": [("items", "Предметы", "item"),
                      ("locations", "Локации", "location"),
                      ("organizations", "Организации", "organization")],
        "item": [("locations", "Локации", "location"),
                 ("characters", "Персонажи", "character"),
                 ("organizations", "Организации", "organization")],
        "location": [("characters", "Персонажи", "character"),
                     ("organizations", "Организации", "organization"),
                     ("items", "Предметы", "item")],
    }
    for key, rows in expected.items():
        refs = reg.related_refs_for_key(key)
        assert [(r.attr, r.label, r.entity_type.value) for r in refs] == rows


# ── string-key helpers: tolerant lookups at dialog/payload boundaries ─────


def test_resolve_known_and_unknown_keys():
    assert reg.resolve("character") is EntityType.CHARACTER
    assert reg.resolve("rating") is EntityType.RATING
    assert reg.resolve("bogus") is None


def test_by_collection_known_and_unknown():
    assert reg.by_collection("ratings").entity_type is EntityType.RATING
    assert reg.by_collection("bogus") is None


def test_type_for_collection_maps_every_plural():
    for entity_type in EntityType:
        desc = reg.descriptor(entity_type)
        assert reg.type_for_collection(desc.plural) is entity_type
    assert reg.type_for_collection("bogus") is None


def test_display_label_known_and_fallback():
    assert reg.display_label("character") == "Персонаж"
    assert reg.display_label("event") == "Событие"
    # unknown keys surface verbatim, as ENTITY_LABELS.get(x, x) used to
    assert reg.display_label("bogus") == "bogus"


def test_related_refs_for_key_rejects_unknown_keys():
    # wave 3.3: unknown keys are bugs, not silently empty relation sections
    with pytest.raises(KeyError):
        reg.related_refs_for_key("bogus")
    # a registered type with no card relations legitimately shows none
    assert reg.related_refs_for_key("rating") == ()


# ── display labels (the single source of RU names) ────────────────────────


def test_labels_match_the_migrated_llm_maps():
    # old llm_service.ENTITY_LABELS / llm_setup_view_model._ENTITY_LABELS
    searchable = [reg.descriptor(t) for t in reg.SEARCH_TYPES]
    assert {d.key: d.label for d in searchable} == {
        "event": "Событие", "organization": "Организация",
        "character": "Персонаж", "item": "Предмет", "location": "Локация",
    }
    assert {d.key: d.plural_label for d in searchable} == {
                "event": "События", "organization": "Организации",
                "character": "Персонажи", "item": "Предметы",
                "location": "Локации",
            }


# ── per-use participation flags ───────────────────────────────────────────


def test_search_and_llm_participation():
    assert tuple(t.value for t in reg.SEARCH_TYPES) == (
        "event", "organization", "character", "item", "location",
    )
    assert tuple(t.value for t in reg.LLM_TYPES) == (
        "event", "organization", "character", "item", "location",
    )


def test_llm_fields_match_the_migrated_field_config():
    # old llm_service.FIELD_CONFIG, order included
    assert {t.value: reg.descriptor(t).llm_fields for t in reg.LLM_TYPES} == {
        "event": ("name", "characteristics", "backstory"),
        "organization": ("name", "characteristics", "backstory", "tasks"),
        "character": ("name", "characteristics", "backstory", "personality", "tasks"),
        "item": ("name", "characteristics", "backstory"),
        "location": ("name", "characteristics", "backstory", "tasks"),
    }
