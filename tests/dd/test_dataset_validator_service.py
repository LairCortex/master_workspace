"""Dataset validator service — end-to-end pipeline (tasks 4.1–4.5)."""
from __future__ import annotations

import json

from app.dd.application.dataset_validator_service import DatasetValidatorService
from app.dd.domain.dataset import DatasetSource
from app.dd.domain.lss_checks import ConnectedDataset
from tests.dd.lss_check_fixtures import base_dataset, class_with
from tests.dd.test_lss_schemas import golden_dataset


def service() -> DatasetValidatorService:
    return DatasetValidatorService()


def content_of(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False)


# ---------------------------------------------------------------------------
def test_invalid_json_names_the_reason():
    report = service().validate("{ это не json")
    assert len(report.errors) == 1
    issue = report.errors[0]
    assert issue.code == "INVALID_JSON"
    assert "JSON" in issue.message and not report.import_allowed


def test_non_object_root_is_rejected():
    report = service().validate("[1, 2, 3]")
    assert report.errors[0].code == "INVALID_JSON"
    assert "JSON-объектом" in report.errors[0].message


def test_unknown_format_version_short_circuits_with_one_error():
    document = golden_dataset()
    document["$schema"] = "https://longstoryshort.app/schema/v7/wizard-dataset.json"
    report = service().validate(content_of(document))
    assert [i.code for i in report.issues] == ["UNSUPPORTED_FORMAT"]


def test_declared_supported_version_validates_normally():
    document = golden_dataset()
    document["$schema"] = "https://longstoryshort.app/schema/v1/wizard-dataset.json"
    report = service().validate(content_of(document), source=DatasetSource.SRD)
    assert report.issues == ()


def test_golden_srd_like_file_is_importable():
    report = service().validate(content_of(golden_dataset()), source=DatasetSource.SRD)
    assert report.errors == ()


def test_shape_and_cross_errors_land_in_one_report():
    document = base_dataset(
        classes=[
            class_with({"type": "bonus", "target": "не-таргет", "label": "L", "value": 1}),
        ],
        subclasses=[{"id": "orphan", "classId": "nope", "label": "X", "grants": []}],
    )
    report = service().validate(content_of(document))
    assert not report.import_allowed
    assert any(i.code == "BONUS_TARGET" for i in report.errors)
    assert any(i.code == "LINK_CLASS" for i in report.errors)


def test_warnings_allow_import_and_are_shown():
    document = base_dataset(
        races=[
            {
                "id": "elf",
                "label": "Elf",
                "size": "medium",
                "grants": [
                    {
                        "type": "trait",
                        "id": "darkvision",
                        "name": "Darkvision",
                        "params": {"ft": 60},
                        "description": "Видите в темноте.",
                    }
                ],
            }
        ]
    )
    report = service().validate(content_of(document))
    assert report.import_allowed
    assert [i.code for i in report.warnings] == ["TRAIT_PARAMS_PROSE"]


def test_same_file_twice_gives_identical_reports():
    document = base_dataset(
        classes=[class_with({"type": "gold-dice", "dice": "2d"})],
        subclasses=[{"id": "a", "classId": "wizard", "label": "A", "grants": []}],
    )
    content = content_of(document)
    first = service().validate(content)
    second = service().validate(content)
    assert first.issues == second.issues


def test_homebrew_link_resolves_through_connected_official_set():
    document = base_dataset(
        subclasses=[{"id": "hb-thief", "classId": "wizard", "label": "HB", "grants": []}]
    )
    connected = ConnectedDataset(
        dataset_id="srd-2024",
        source=DatasetSource.SRD,
        document={"classes": [{"id": "wizard", "label": "W", "info": {}, "grants": []}]},
    )
    alone = service().validate(content_of(document))
    together = service().validate(content_of(document), connected=(connected,))
    assert any(i.code == "LINK_CLASS" for i in alone.errors)
    assert together.errors == ()


def test_spell_slug_check_skips_without_downloaded_lists():
    document = base_dataset(
        classes=[class_with({"type": "spell-fixed", "slug": "homemade-sparkles"})]
    )
    without_lists = service().validate(content_of(document))
    with_lists = service().validate(
        content_of(document), spell_slugs=["fireball", "shield"]
    )
    assert "SPELL_SLUG_NOT_SRD" not in [i.code for i in without_lists.issues]
    assert "SPELL_SLUG_NOT_SRD" in [i.code for i in with_lists.warnings]


def test_own_official_casters_are_covered_like_the_lss_database():
    """SRD files keep class spellcasting without spellList — own class ids count."""
    document = base_dataset(
        classes=[
            class_with({"type": "spellcasting", "ability": "wis", "casterType": "list"})
        ]
    )
    homebrew = service().validate(content_of(document))
    official = service().validate(content_of(document), source=DatasetSource.SRD)
    assert any(i.code == "SPELL_CASTER_LIST" for i in homebrew.errors)
    assert official.errors == ()
