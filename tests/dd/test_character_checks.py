"""The character-export check layer (add-dnd-game-face task 9.1; spec
dnd-character-import «Документ проверяется по схеме формата, предупреждения
не блокируют»).

Two floors, one file:

* the domain gates (:mod:`app.dd.domain.character_checks`) — a foreign
  ``jsonType`` and a version this build has no schema for stop the pipeline
  with the Russian sentence (the datasets' version-gate posture); a
  destroyed ``data`` half — missing, a string that no longer parses, a
  non-object body — is the spec's «разрушенная структура data»; the
  live-export keys (``bonusesSkills``/``bonusesStats``, ``createdAt``,
  ``wizardStep``/``choices``) are legal citizens answered warning-per-key;
* the validator pipeline (:class:`CharacterValidatorService`) — unreadable
  JSON (shared ``INVALID_JSON`` code), the gate's early stop (schema never
  approached for a foreign file), the string-``data`` substitution before
  the schema (paths read ``data.…``), and the golden live export answering
  exactly the warning set with the import open.
"""
from __future__ import annotations

import json

import pytest

from app.dd.application.character_validator_service import CharacterValidatorService
from app.dd.domain.character_checks import (
    CODE_CHAR_DATA,
    CODE_CHAR_DEPRECATED_BONUSES,
    CODE_CHAR_JSON_TYPE,
    CODE_CHAR_SERVICE_KEYS,
    CODE_CHAR_UNSUPPORTED_VERSION,
    document_warnings,
    envelope_gate,
    parse_data,
)
from app.dd.domain.validation_report import Severity
from app.dd.infrastructure.lss_schemas import CHARACTER_FORMAT_VERSION


def _envelope(**over) -> dict:
    document = {
        "jsonType": "character",
        "version": CHARACTER_FORMAT_VERSION,
        "data": {"name": "Грог"},
    }
    document.update(over)
    return document


# ── envelope gates ─────────────────────────────────────────────────────────


def test_honest_envelope_passes_the_gate():
    assert envelope_gate(_envelope(), CHARACTER_FORMAT_VERSION) == []


def test_foreign_json_type_refuses_with_the_russian_sentence():
    issues = envelope_gate(_envelope(jsonType="dataset"), CHARACTER_FORMAT_VERSION)
    assert [issue.code for issue in issues] == [CODE_CHAR_JSON_TYPE]
    assert issues[0].severity is Severity.ERROR
    assert "jsonType" in issues[0].message


def test_absent_version_names_the_bundled_revision():
    issues = envelope_gate(_envelope(version=None), CHARACTER_FORMAT_VERSION)
    assert [issue.code for issue in issues] == [CODE_CHAR_UNSUPPORTED_VERSION]
    assert CHARACTER_FORMAT_VERSION in issues[0].message


@pytest.mark.parametrize("version", ["1", 2, "3"])
def test_version_ahead_or_behind_is_refused(version):
    issues = envelope_gate(_envelope(version=version), CHARACTER_FORMAT_VERSION)
    assert [issue.code for issue in issues] == [CODE_CHAR_UNSUPPORTED_VERSION]
    assert issues[0].path == "version"


# ── the data half ──────────────────────────────────────────────────────────


def test_dict_data_passes_through():
    data, issue = parse_data({"data": {"name": "Грог"}})
    assert data == {"name": "Грог"}
    assert issue is None


def test_string_data_is_parsed_the_way_the_live_export_carries_it():
    data, issue = parse_data({"data": '{"name": "Грог"}'})
    assert data == {"name": "Грог"}
    assert issue is None


def test_unparseable_string_data_is_one_char_data_error():
    data, issue = parse_data({"data": "{имена не дожили до скобки"})
    assert data is None
    assert issue is not None and issue.code == CODE_CHAR_DATA
    assert "не является корректным JSON" in issue.message


def test_parsed_non_object_data_is_refused():
    _, issue = parse_data({"data": "[1, 2]"})
    assert issue is not None and issue.code == CODE_CHAR_DATA
    assert "обязан быть объектом" in issue.message


@pytest.mark.parametrize("raw", [None, 42, ["x"]])
def test_absent_or_exotic_data_is_refused(raw):
    _, issue = parse_data({"data": raw})
    assert issue is not None and issue.code == CODE_CHAR_DATA


# ── live-export warnings ───────────────────────────────────────────────────


def test_clean_document_answers_no_warnings():
    assert document_warnings({}, {"name": "Грог"}) == []


def test_every_live_key_earns_its_own_warning_line():
    envelope = {"createdAt": "2026-01-01T00:00:00Z"}
    data = {
        "name": "Грог",
        "bonusesSkills": {"athletics": 2},
        "bonusesStats": {"str": 1},
        "wizardStep": "summary",
        "choices": {},
    }
    issues = document_warnings(envelope, data)
    assert [(issue.code, issue.path) for issue in issues] == [
        (CODE_CHAR_DEPRECATED_BONUSES, "data.bonusesSkills"),
        (CODE_CHAR_DEPRECATED_BONUSES, "data.bonusesStats"),
        (CODE_CHAR_SERVICE_KEYS, "createdAt"),
        (CODE_CHAR_SERVICE_KEYS, "data.wizardStep"),
        (CODE_CHAR_SERVICE_KEYS, "data.choices"),
    ]
    assert all(issue.severity is Severity.WARNING for issue in issues)


# ── the pipeline ───────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def validator() -> CharacterValidatorService:
    return CharacterValidatorService()


def _text(document) -> str:
    return json.dumps(document, ensure_ascii=False)


def test_unreadable_file_is_the_shared_invalid_json_error(validator):
    report, data = validator.validate("это не json {{{")
    assert data is None
    assert [(issue.code, issue.path) for issue in report.issues] == [
        ("INVALID_JSON", "<файл>")
    ]
    assert not report.import_allowed


def test_non_object_root_is_refused_too(validator):
    report, _ = validator.validate("[1, 2, 3]")
    assert report.issues[0].code == "INVALID_JSON"
    assert "обязан быть JSON-объектом" in report.issues[0].message


def test_a_foreign_file_stops_at_the_gate_the_schema_never_spoke(validator):
    # A dataset-shaped file: had the pipeline continued, the character schema
    # would have added its own noise — the gate's early stop answers exactly
    # the identity error.
    report, data = validator.validate(_text(_envelope(jsonType="dataset")))
    assert data is None
    assert [issue.code for issue in report.issues] == [CODE_CHAR_JSON_TYPE]


def test_destroyed_data_refuses_with_the_single_error(validator):
    report, data = validator.validate(_text(_envelope(data="{битый json")))
    assert data is None
    assert [issue.code for issue in report.issues] == [CODE_CHAR_DATA]


def test_broken_structure_data_answers_schema_errors_with_data_paths(validator):
    # Schema half: a name that is not a string and a level outside 1…20.
    report, data = validator.validate(
        _text(_envelope(data={"name": 42, "level": 99}))
    )
    assert data is not None  # the layout gets the verdict, not a guess
    paths = {issue.path for issue in report.errors}
    assert "data.name" in paths and "data.level" in paths
    assert all(issue.code == "SCHEMA" for issue in report.errors)
    assert not report.import_allowed


def test_golden_live_export_passes_with_the_warning_set_only(validator):
    # Д7's acceptance picture: a download with the retired bonus channel and
    # the service keys rides through the import threshold (spec scenario
    # «Живой экспорт проходит с предупреждениями»).
    live = _envelope(
        createdAt="2026-01-01T00:00:00Z",
        data=json.dumps(
            {
                "name": "Грог",
                "level": 3,
                "bonuses": [{"target": "spell_attack", "formula": "[Prof]"}],
                "bonusesSkills": {"athletics": 2},
                "wizardStep": "summary",
                "choices": {"feat": ["great-weapon-mastery"]},
            },
            ensure_ascii=False,
        ),
    )
    report, data = validator.validate(_text(live))
    assert data is not None and data["name"] == "Грог"
    assert report.errors == ()
    assert report.import_allowed
    assert {issue.code for issue in report.warnings} == {
        CODE_CHAR_DEPRECATED_BONUSES,
        CODE_CHAR_SERVICE_KEYS,
    }
