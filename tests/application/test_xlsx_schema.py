"""Tests for the xlsx import file-format registry (app.application.services.xlsx_schema).

Covers tasks 1.1 (registry completeness vs the 13 M2M association tables),
1.2 (header normalization / aliases / required-column check) and
1.3 (date / rating / link-list value parsing edge cases).
"""
from datetime import date, datetime

import pytest

from app.application.services import xlsx_schema as schema
from app.infrastructure.db.models import Base


# ── 1.1 registry completeness ─────────────────────────────────────────────

EXPECTED_SHEET_NAMES = {"События", "Персонажи", "Локации", "Организации", "Предметы"}


def _association_tables() -> set[str]:
    return {
        t.name
        for t in Base.metadata.tables.values()
        if len(t.primary_key.columns) == 2
    }


def test_registry_has_five_sheets_expected_names():
    sheets = schema.all_sheets()
    assert len(sheets) == 5
    assert {s.sheet_name for s in sheets} == EXPECTED_SHEET_NAMES
    assert {s.entity_type for s in sheets} == {
        "event", "character", "location", "organization", "item",
    }


def test_every_sheet_has_required_name_and_start_date():
    for sheet in schema.all_sheets():
        required = {c.key: c for c in sheet.required_columns}
        assert set(required) == {"name", "start_date"}, sheet.sheet_name
        assert required["name"].label == "Имя"
        assert required["start_date"].label == "Дата начала"


def test_link_columns_cover_all_m2m_except_ratings():
    # Sanity: the schema really has 13 M2M tables, 3 of them *_rating.
    assoc = _association_tables()
    assert len(assoc) == 13
    assert {n for n in assoc if n.endswith("_rating")} == {
        "character_rating", "item_rating", "location_rating",
    }
    reachable = {
        schema.link_table(sheet.entity_type, target)
        for sheet in schema.all_sheets()
        for target in sheet.link_targets
    }
    assert reachable == assoc - {n for n in assoc if n.endswith("_rating")}
    # The link registry must never point at a *_rating table.
    assert not any(t.endswith("_rating") for t in schema.LINK_TABLES.values())


def test_link_column_counts_per_sheet():
    # Spec: event sheet has four link columns without "Связь событиями",
    # every other sheet has four including it.
    event = schema.sheet_for("event")
    assert "event" not in event.link_targets
    assert len(event.link_columns) == 4
    for sheet in schema.all_sheets():
        if sheet.entity_type == "event":
            continue
        assert "event" in sheet.link_targets
        assert sheet.entity_type not in sheet.link_targets
        assert len(sheet.link_columns) == 4
        assert schema.LINK_COLUMNS_BY_TARGET["event"].label == "Связь событиями"


def test_link_table_lookup_is_symmetric_and_rejects_unknown():
    assert schema.link_table("event", "character") == "event_character"
    assert schema.link_table("character", "event") == "event_character"
    assert schema.link_table("item", "location").startswith("item_location")
    with pytest.raises(ValueError):
        schema.link_table("event", "rating")


def test_special_columns_placement():
    event = schema.sheet_for("event")
    assert event.column("event_type") is not None  # "Тип" — events only
    for sheet in schema.all_sheets():
        if sheet.entity_type != "event":
            assert sheet.column("event_type") is None
    image_types = {"character", "organization", "location"}
    for sheet in schema.all_sheets():
        # "Рейтинг" — on all sheets (spec), marked special.
        rating = sheet.column("rating")
        assert rating is not None and rating.label == "Рейтинг" and rating.special
        has_image = sheet.column("image") is not None
        assert has_image == (sheet.entity_type in image_types)
        if has_image:
            assert sheet.column("image").label == "Изображение"


def test_legacy_english_alias_columns_available_by_type():
    # personality only characters; tasks — character/location/organization;
    # music_url — everywhere except events (mirrors the old per-type columns).
    assert schema.sheet_for("character").column("personality") is not None
    assert schema.sheet_for("location").column("personality") is None
    for et in ("character", "location", "organization"):
        assert schema.sheet_for(et).column("tasks") is not None
    assert schema.sheet_for("event").column("tasks") is None
    for et in ("character", "location", "organization", "item"):
        assert schema.sheet_for(et).column("music_url") is not None


# ── 1.2 header normalization + required check ─────────────────────────────

def test_normalize_header_case_and_whitespace_insensitive():
    assert schema.normalize_header("  Дата   начала\n") == schema.normalize_header("датаначала")
    assert schema.normalize_header("Имя") == schema.normalize_header("  имя ")
    assert schema.normalize_header(None) == ""


def test_english_headers_read_as_russian_columns():
    # Spec scenario: `name` / `start_date` are treated as `Имя` / `Дата начала`.
    sheet = schema.sheet_for("character")
    resolved = schema.resolve_headers(sheet, ["START_DATE", " Name "])
    assert resolved.position("name") == 1
    assert resolved.position("start_date") == 0
    assert not resolved.unknown
    assert resolved.position("backstory") is None  # нет такой колонки — нет позиции
    assert schema.missing_required_headers(sheet, ["name", "start_date"]) == []


def test_russian_headers_and_case_variants_resolve():
    sheet = schema.sheet_for("event")
    resolved = schema.resolve_headers(sheet, ["ИМЯ", "Дата  начала", "Тип"])
    assert resolved.position("name") == 0
    assert resolved.position("start_date") == 1
    assert resolved.scalars[2].key == "event_type"
    assert resolved.scalars[2].special


def test_link_headers_resolve_to_link_columns():
    sheet = schema.sheet_for("event")
    resolved = schema.resolve_headers(
        sheet, ["Имя", "Дата начала", " связь Персонажами ", "СВЯЗЬ ПРЕДМЕТАМИ"]
    )
    assert {c.target_type for c in resolved.links.values()} == {"character", "item"}
    assert not resolved.unknown


def test_unknown_columns_reported_and_ignored():
    sheet = schema.sheet_for("event")
    resolved = schema.resolve_headers(sheet, ["Имя", "Заметка", "", None, "Дата начала"])
    assert resolved.unknown == ["Заметка"]


def test_link_column_of_foreign_semantics_not_matched_wrongly():
    # "Связь событиями" is not a column of the events sheet, so it is unknown there.
    resolved = schema.resolve_headers(schema.sheet_for("event"), ["Связь событиями"])
    assert resolved.unknown == ["Связь событиями"]


def test_duplicate_header_first_occurrence_wins():
    sheet = schema.sheet_for("event")
    resolved = schema.resolve_headers(sheet, ["Имя", "name", "Дата начала"])
    assert resolved.position("name") == 0
    assert resolved.unknown == []  # duplicate alias is known, just superseded


def test_missing_required_headers_lists_labels():
    sheet = schema.sheet_for("character")
    assert schema.missing_required_headers(sheet, ["Характеристики"]) == [
        "Имя", "Дата начала",
    ]
    assert schema.missing_required_headers(sheet, ["Имя", "Дата начала"]) == []


def test_find_sheet_by_name_case_insensitive():
    assert schema.sheet_for("event") is schema.find_sheet_by_name("события")
    assert schema.find_sheet_by_name("  ОРГАНИЗАЦИИ ").entity_type == "organization"
    assert schema.find_sheet_by_name("Заметки") is None


def test_sheet_for_unknown_type_raises():
    with pytest.raises(ValueError):
        schema.sheet_for("planet")


# ── 1.3 value parsing ─────────────────────────────────────────────────────

def test_parse_date_native_cell():
    assert schema.parse_cell_date(datetime(2025, 12, 31, 10, 30)) == date(2025, 12, 31)
    assert schema.parse_cell_date(date(1820, 5, 1)) == date(1820, 5, 1)


def test_parse_date_text_iso():
    assert schema.parse_cell_date("2025-12-31") == date(2025, 12, 31)
    assert schema.parse_cell_date(" 2025-12-31 ") == date(2025, 12, 31)


def test_parse_date_bad_values_are_none():
    assert schema.parse_cell_date("31.12.2025") is None
    assert schema.parse_cell_date("не дата") is None
    assert schema.parse_cell_date("") is None
    assert schema.parse_cell_date("   ") is None
    assert schema.parse_cell_date(None) is None
    assert schema.parse_cell_date(12345) is None


def test_parse_rating_valid():
    assert schema.parse_cell_rating(4) == 4
    assert schema.parse_cell_rating("3") == 3
    assert schema.parse_cell_rating(5.0) == 5


def test_parse_rating_empty_is_none():
    assert schema.parse_cell_rating(None) is None
    assert schema.parse_cell_rating("") is None
    assert schema.parse_cell_rating("  ") is None


@pytest.mark.parametrize("bad", ["abc", "0", "6", -1, 3.7, "4.5", True, object()])
def test_parse_rating_garbage_raises(bad):
    with pytest.raises(ValueError):
        schema.parse_cell_rating(bad)


def test_parse_link_cell_strips_and_skips_empty_segments():
    # Task edge-case: " а;б; ;в "
    assert schema.parse_link_cell(" а;б; ;в ") == ["а", "б", "в"]


def test_parse_link_cell_edge_cases():
    assert schema.parse_link_cell(None) == []
    assert schema.parse_link_cell("") == []
    assert schema.parse_link_cell("; ; ;") == []
    assert schema.parse_link_cell("Иван") == ["Иван"]
    # Order and duplicates preserved; dedup is the apply pass' job.
    assert schema.parse_link_cell("б;а;б") == ["б", "а", "б"]
