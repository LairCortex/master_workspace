"""Bundled schema artifacts, format gate and shape validation (task 4.1)."""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import pytest

from app.dd.infrastructure.lss_schemas import (
    BUNDLED_SCHEMA_FILES,
    CHARACTER_SCHEMA_FILE,
    FORMAT_VERSION,
    SCHEMA_URL_TEMPLATE,
    extract_format_version,
    format_version_error,
    load_bundle,
    schema_resource_dir,
    validate_shape,
)
from app.dd.domain.validation_report import Severity


@pytest.fixture(scope="module")
def bundle():  # noqa: ANN201
    return load_bundle()


def golden_dataset() -> dict:
    """SRD-эталонный сниппет: класс жреца с чертой, счётчиком и выбором навыка."""
    return {
        "id": "golden-cleric",
        "name": "Golden cleric",
        "system": "dnd",
        "edition": "2024",
        "author": "LSS golden snippet",
        "license": "CC-BY-4.0",
        "classes": [
            {
                "id": "cleric",
                "label": "Cleric",
                "info": {"primaryStats": [["wis"]], "complexity": 1},
                "grants": [
                    {"type": "hp-die", "die": 8},
                    {"type": "saving-throw", "stats": ["wis", "cha"]},
                    {
                        "type": "trait",
                        "id": "spellcasting-wis",
                        "name": "Spellcasting",
                        "description": "Вы заклинатель.",
                    },
                    {
                        "type": "resource",
                        "id": "channel-divinity",
                        "name": "Channel Divinity",
                        "pairId": None,
                        "max": 1,
                        "isShortRest": True,
                        "isLongRest": True,
                    },
                    {
                        "type": "skill-choice",
                        "count": 2,
                        "options": ["history", "insight", "persuasion", "religion"],
                    },
                ],
                "leveledGrants": [
                    {
                        "level": 1,
                        "grants": [
                            {
                                "type": "pick-one",
                                "options": [
                                    {
                                        "label": "Доспехи",
                                        "grants": [{"type": "gold", "amount": 25}],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# the bundled artifacts themselves
# ---------------------------------------------------------------------------
def test_bundle_loads_every_artifact_and_exposes_the_dataset_root(bundle):
    assert len(BUNDLED_SCHEMA_FILES) == 8
    assert bundle.dataset_schema["title"]
    assert bundle.schema_store, "the $id schema store must be populated"
    for doc in bundle.schema_store.values():
        assert doc.get("$schema") == "http://json-schema.org/draft-07/schema#"


def test_vocabulary_extracted_from_schemas(bundle):
    vocabulary = bundle.vocabulary
    assert "stealth" in vocabulary.skill_keys
    assert "intimidation" in vocabulary.skill_keys
    assert vocabulary.stat_keys == frozenset({"str", "dex", "con", "int", "wis", "cha"})
    assert "armor-heavy" in vocabulary.armor_keys
    assert "weapon-martial" in vocabulary.weapon_keys
    assert "ac" in vocabulary.bonus_targets
    assert "skill.stealth" in vocabulary.bonus_targets
    assert vocabulary.bonus_target_patterns  # weapon.<key>.attack family


def test_schema_resource_dir_frozen_override(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert schema_resource_dir() == tmp_path / "app" / "dd" / "resources" / "schemas"


def test_load_bundle_from_explicit_directory(tmp_path):
    for name in BUNDLED_SCHEMA_FILES:
        source = schema_resource_dir() / name
        (tmp_path / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    # add-dnd-game-face task 9.1: the character artifact joins the bundle as
    # its own file (outside BUNDLED_SCHEMA_FILES — the dataset set keeps its
    # version-gate contract), so the explicit directory needs it too.
    character_source = schema_resource_dir() / CHARACTER_SCHEMA_FILE
    (tmp_path / CHARACTER_SCHEMA_FILE).write_text(
        character_source.read_text(encoding="utf-8"), encoding="utf-8"
    )
    local = load_bundle(schema_dir=tmp_path)
    assert local.dataset_schema["title"]
    assert local.character_schema["title"]


# ---------------------------------------------------------------------------
# format version gate
# ---------------------------------------------------------------------------
def test_undeclared_document_defaults_to_the_bundled_revision():
    assert extract_format_version({}) is None
    assert extract_format_version({"$schema": SCHEMA_URL_TEMPLATE.format(version=1)}) == 1


def test_unknown_revision_is_extracted():
    assert extract_format_version({"$schema": SCHEMA_URL_TEMPLATE.format(version=2)}) == 2


@pytest.mark.parametrize("bad", [42, "https://example.com/whatever.json", "v1"])
def test_malformed_declaration_reads_as_unsupported(bad):
    assert extract_format_version({"$schema": bad}) == -1


def test_unsupported_version_error_text():
    issue = format_version_error(9)
    assert issue.code == "UNSUPPORTED_FORMAT"
    assert issue.severity is Severity.ERROR
    assert "v9" in issue.message and f"v{FORMAT_VERSION}" in issue.message
    sentinel = format_version_error(-1)
    assert "не удалось разобрать" in sentinel.message


# ---------------------------------------------------------------------------
# shape validation against the bundled schema
# ---------------------------------------------------------------------------
def test_golden_snippet_passes_the_shape(bundle):
    assert validate_shape(golden_dataset(), bundle) == []


def test_unknown_field_is_a_shape_error_with_a_path(bundle):
    document = golden_dataset()
    document["classes"][0]["likes2"] = "x"
    issues = validate_shape(document, bundle)
    assert issues
    issue = issues[0]
    assert issue.code == "SCHEMA" and issue.severity is Severity.ERROR
    assert "classes[0]" in issue.path
    assert "неизвестным именем" in issue.message and "likes2" in issue.message


def test_wrong_type_is_a_shape_error(bundle):
    document = golden_dataset()
    document["id"] = 5
    issues = validate_shape(document, bundle)
    assert any("неверный тип" in i.message and i.path == "id" for i in issues)


def test_missing_required_is_a_shape_error(bundle):
    document = golden_dataset()
    del document["name"]
    issues = validate_shape(document, bundle)
    assert any("обязательное поле" in i.message and "name" in i.message for i in issues)


def test_grant_beyond_all_variants_is_reported_once(bundle):
    document = golden_dataset()
    document["classes"][0]["grants"].append({"type": "flight", "wings": 2})
    issues = validate_shape(document, bundle)
    assert any("ни под один" in i.message and "grants[5]" in i.path for i in issues)


def test_schema_declaration_is_stripped_before_validation(bundle):
    document = golden_dataset()
    document["$schema"] = SCHEMA_URL_TEMPLATE.format(version=1)
    assert validate_shape(document, bundle) == []


def test_root_level_rendering(bundle):
    issues = validate_shape({"id": 5, "name": [], "system": {}, "edition": [], "author": []}, bundle)
    assert issues
    assert any("<корень>" in i.path or "id" in i.path for i in issues)


def test_render_message_falls_back_for_unknown_kinds(bundle):
    document = golden_dataset()
    # const violation: enum value for a const field is not of type — force a
    # message kind outside the RU templates via a pattern/const mismatch
    document["classes"][0]["grants"][1]["stats"] = ["wis", "wis"]  # uniqueItems? not set
    # deterministic fallback probe: a raw ValidationError with a fresh message
    from app.dd.infrastructure.lss_schemas import _render_message
    from jsonschema.exceptions import ValidationError

    raw = ValidationError("документ не прошёл проверку", validator="custom", schema={}, instance={})
    assert _render_message(raw) == "ошибка схемы: документ не прошёл проверку"
    assert validate_shape(document, bundle) == []


def test_bundle_json_is_utf8_loadable(bundle):
    # the store keys are the official $id URLs the dataset files reference
    assert any(key.startswith("https://longstoryshort.app/schema/v1/") for key in bundle.schema_store)
    assert json.dumps(bundle.dataset_schema)[:1] == "{"


# ---------------------------------------------------------------------------
# the modern ``referencing`` wiring replaces the deprecated RefResolver
# (audit of add-dnd-module-foundation, SUGGESTION): the deprecated name must
# not return to the module, and validation must stay warning-free
# ---------------------------------------------------------------------------
def test_deprecated_ref_resolver_api_is_not_used() -> None:
    module = sys.modules[validate_shape.__module__]
    assert "RefResolver" not in Path(module.__file__).read_text(encoding="utf-8")


def test_shape_validation_emits_no_deprecation_warnings(bundle) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        assert validate_shape(golden_dataset(), bundle) == []
