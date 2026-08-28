"""Tests for the character-sheet domain model and geometry — TDD: red first.

A1 part: SheetField / SheetPage / SheetTemplate defaults, FieldType,
clamp_rect / default_size / place_field geometry, field collection +
pages-JSON round-trip.

A-playable part (tasks 1.1..1.2): the page tape (GUTTER 24, landscape
swaps w/h), clamp_rect in page-local coordinates, the v1/v2 parser
(``parse_template``), new field types, number `,`→`.` normalization,
empty dropdown option rejection, and the pure image-id JSON helpers.
"""
from __future__ import annotations

import json

import pytest

from app.domain.entities.character_sheet import (
    DEFAULT_FONT_SIZE,
    EMPTY_PAGES_JSON,
    GUTTER_PT,
    MIN_FIELD_W,
    MIN_FIELD_H,
    PAGE_HEIGHT_PT,
    PAGE_WIDTH_PT,
    SCHEMA_VERSION,
    SheetField,
    SheetPage,
    SheetTemplate,
    UnknownFieldTypeError,
    clamp_rect,
    default_size,
    iter_sheet_image_ids,
    null_sheet_image_ids,
    page_origin,
    page_size,
    place_field,
    scene_to_page,
)
from app.domain.enums.field_type import FieldType


# --- FieldType ---

class TestFieldType:
    def test_catalog_is_closed_nine_types(self):
        assert {f.value for f in FieldType} == {
            "label", "text", "textarea",
            "checkbox", "number", "dropdown",
            "image", "rect", "line",
        }

    def test_members(self):
        assert FieldType.LABEL.value == "label"
        assert FieldType.TEXT.value == "text"
        assert FieldType.TEXTAREA.value == "textarea"
        assert FieldType.CHECKBOX.value == "checkbox"
        assert FieldType.NUMBER.value == "number"
        assert FieldType.DROPDOWN.value == "dropdown"
        assert FieldType.IMAGE.value == "image"
        assert FieldType.RECT.value == "rect"
        assert FieldType.LINE.value == "line"


# --- Dataclass defaults ---

class TestSheetField:
    def test_defaults(self):
        f = SheetField(id="a", type=FieldType.LABEL, x=1.0, y=2.0, w=3.0, h=4.0)
        assert f.font_size == DEFAULT_FONT_SIZE
        assert f.content == ""

    def test_explicit_values(self):
        f = SheetField(id="b", type=FieldType.TEXT, x=0.0, y=0.0, w=20.0, h=18.0,
                       font_size=14.0, content="hi")
        assert f.font_size == 14.0
        assert f.content == "hi"

    def test_new_type_optional_fields_default_empty(self):
        f = SheetField(id="c", type=FieldType.NUMBER, x=0, y=0, w=72, h=18)
        assert f.min_value is None
        assert f.max_value is None
        assert f.options == []
        assert f.image_id is None


class TestSheetPage:
    def test_starts_empty(self):
        assert SheetPage().fields == []

    def test_default_name_is_page_1(self):
        assert SheetPage().name == "Страница 1"

    def test_explicit_name(self):
        assert SheetPage(name="Навыки").name == "Навыки"


class TestSheetTemplate:
    def test_defaults_single_portrait_page(self):
        t = SheetTemplate(name="Hero")
        assert len(t.pages) == 1
        assert t.pages[0].fields == []
        assert t.pages[0].name == "Страница 1"
        assert t.orientation == "portrait"
        assert t.schema_version == SCHEMA_VERSION == 2
        assert t.id is None

    def test_template_identity_and_field_members(self):
        f = SheetField(id="x", type=FieldType.LABEL, x=0, y=0, w=10, h=10)
        t = SheetTemplate(name="T", pages=[SheetPage(fields=[f])], id=7)
        assert t.id == 7
        assert t.page.fields == [f]


# --- Geometry: constants ---

class TestConstants:
    def test_a4_size(self):
        assert PAGE_WIDTH_PT == pytest.approx(595.28)
        assert PAGE_HEIGHT_PT == pytest.approx(841.89)

    def test_min_size(self):
        assert (MIN_FIELD_W, MIN_FIELD_H) == (16.0, 16.0)

    def test_gutter_is_24pt(self):
        assert GUTTER_PT == pytest.approx(24.0)


# --- Geometry: page size / orientation ---

class TestPageSize:
    def test_portrait(self):
        assert page_size("portrait") == (PAGE_WIDTH_PT, PAGE_HEIGHT_PT)

    def test_landscape_swaps_width_and_height(self):
        assert page_size("landscape") == (PAGE_HEIGHT_PT, PAGE_WIDTH_PT)

    def test_template_page_size_follows_orientation(self):
        t = SheetTemplate(name="T")
        assert t.page_size == (PAGE_WIDTH_PT, PAGE_HEIGHT_PT)
        t.set_orientation("landscape")
        assert t.page_size == (PAGE_HEIGHT_PT, PAGE_WIDTH_PT)

    def test_set_orientation_clamps_fields_without_scaling(self):
        t = SheetTemplate(name="T")
        f = t.add_field(FieldType.TEXTAREA, (100.0, PAGE_HEIGHT_PT - 20))
        size_before = (f.w, f.h)
        t.set_orientation("landscape")
        _, landscape_h = t.page_size
        assert (f.w, f.h) == size_before          # no proportional scale
        assert f.x + f.w <= t.page_size[0]        # clamped into the new page
        assert f.y + f.h <= landscape_h + 1e-6
        assert f.y == landscape_h - f.h           # bottom-anchored field clamped up


# --- Geometry: default_size ---

class TestDefaultSize:
    def test_label(self):
        assert default_size(FieldType.LABEL) == (72.0, 18.0)

    def test_text(self):
        assert default_size(FieldType.TEXT) == (120.0, 18.0)

    def test_textarea(self):
        assert default_size(FieldType.TEXTAREA) == (120.0, 54.0)

    def test_checkbox(self):
        assert default_size(FieldType.CHECKBOX) == (18.0, 18.0)

    def test_number(self):
        assert default_size(FieldType.NUMBER) == (72.0, 18.0)

    def test_dropdown(self):
        assert default_size(FieldType.DROPDOWN) == (120.0, 18.0)

    def test_image(self):
        assert default_size(FieldType.IMAGE) == (120.0, 120.0)

    def test_rect(self):
        assert default_size(FieldType.RECT) == (120.0, 72.0)

    def test_line(self):
        assert default_size(FieldType.LINE) == (120.0, 2.0)


# --- Geometry: clamp_rect ---

class TestClampRect:
    def test_within_page_unchanged(self):
        assert clamp_rect(100.0, 100.0, 100.0, 50.0) == (100.0, 100.0, 100.0, 50.0)

    def test_overshoot_right_is_pulled_back(self):
        x, y, w, h = clamp_rect(600.0, 100.0, 100.0, 50.0)
        assert x == pytest.approx(PAGE_WIDTH_PT - 100.0)
        assert (y, w, h) == (100.0, 100.0, 50.0)

    def test_overshoot_bottom_is_pulled_back(self):
        x, y, w, h = clamp_rect(100.0, 900.0, 100.0, 50.0)
        assert y == pytest.approx(PAGE_HEIGHT_PT - 50.0)
        assert (x, w, h) == (100.0, 100.0, 50.0)

    def test_negative_is_clamped_to_origin(self):
        x, y, w, h = clamp_rect(-30.0, -30.0, 100.0, 100.0)
        assert (x, y) == (0.0, 0.0)
        assert (w, h) == (100.0, 100.0)

    def test_enforces_min_size(self):
        x, y, w, h = clamp_rect(0.0, 0.0, 1.0, 2.0)
        assert (w, h) == (MIN_FIELD_W, MIN_FIELD_H)
        assert (x, y) == (0.0, 0.0)

    def test_rect_never_escapes_page(self):
        eps = 1e-6
        for x in (-50.0, 0.0, 0.1 * PAGE_WIDTH_PT, 0.9 * PAGE_WIDTH_PT, 999.0):
            for w in (MIN_FIELD_W, 100.0, 400.0, PAGE_WIDTH_PT):
                rx, ry, rw, rh = clamp_rect(x, 10.0, w, 30.0)
                assert rx >= 0.0
                assert rx + rw <= PAGE_WIDTH_PT + eps
                assert ry >= 0.0
                assert ry + rh <= PAGE_HEIGHT_PT + eps


class TestClampRectPageLocal:
    """Clamp operates in the local coordinates of the (oriented) page."""

    def test_clamp_against_landscape_width(self):
        w, h = page_size("landscape")
        x, y, fw, fh = clamp_rect(10.0, 10.0, 100.0, 50.0, page_w=w, page_h=h)
        assert (x, y, fw, fh) == (10.0, 10.0, 100.0, 50.0)
        x, y, fw, fh = clamp_rect(w - 10.0, 10.0, 100.0, 50.0, page_w=w, page_h=h)
        assert x == pytest.approx(w - 100.0)

    def test_clamp_against_landscape_height(self):
        w, h = page_size("landscape")
        x, y, fw, fh = clamp_rect(10.0, h + 500.0, 100.0, 50.0, page_w=w, page_h=h)
        assert y == pytest.approx(h - 50.0)

    def test_default_args_stay_portrait(self):
        # no page args: A1 behaviour (portrait A4) is preserved
        x, y, w, h = clamp_rect(999.0, 999.0, 100.0, 50.0)
        assert (x, y) == (PAGE_WIDTH_PT - 100.0, PAGE_HEIGHT_PT - 50.0)

    def test_line_thickness_may_be_1pt(self):
        # line: length >= 16pt, thickness (the smaller side) >= 1pt
        x, y, fw, fh = clamp_rect(0.0, 0.0, 300.0, 1.0, field_type=FieldType.LINE)
        assert (fw, fh) == (300.0, 1.0)
        x, y, fw, fh = clamp_rect(0.0, 0.0, 1.0, 300.0, field_type=FieldType.LINE)
        assert (fw, fh) == (1.0, 300.0)

    def test_line_degenerate_grows_to_min_length(self):
        x, y, fw, fh = clamp_rect(0.0, 0.0, 1.0, 1.0, field_type=FieldType.LINE)
        assert (fw, fh) == (16.0, 1.0)   # the larger side becomes the 16pt length

    def test_non_line_keeps_min_16x16(self):
        x, y, fw, fh = clamp_rect(0.0, 0.0, 1.0, 1.0, field_type=FieldType.RECT)
        assert (fw, fh) == (MIN_FIELD_W, MIN_FIELD_H)


# --- Geometry: the page tape (scene coordinates) ---

class TestPageOrigin:
    def test_first_page_at_scene_origin(self):
        assert page_origin(0, PAGE_HEIGHT_PT) == (0.0, 0.0)

    def test_second_page_sits_after_the_gutter(self):
        assert page_origin(1, PAGE_HEIGHT_PT) == (0.0, PAGE_HEIGHT_PT + GUTTER_PT)

    def test_nth_page(self):
        assert page_origin(3, PAGE_HEIGHT_PT) == (0.0, 3 * (PAGE_HEIGHT_PT + GUTTER_PT))

    def test_uses_page_height_of_the_orientation(self):
        _, landscape_h = page_size("landscape")
        assert page_origin(1, landscape_h) == (0.0, landscape_h + GUTTER_PT)


class TestSceneToPage:
    """scene_to_page maps a point of the vertical tape to (index, local)."""

    def test_point_on_first_page_returns_local(self):
        assert scene_to_page(100.0, 200.0, PAGE_WIDTH_PT, PAGE_HEIGHT_PT, 2) == (0, 100.0, 200.0)

    def test_point_on_second_page_is_subtracted_by_the_offset(self):
        idx, lx, ly = scene_to_page(
            50.0, PAGE_HEIGHT_PT + GUTTER_PT + 100.0, PAGE_WIDTH_PT, PAGE_HEIGHT_PT, 2
        )
        assert (idx, lx, ly) == (1, 50.0, 100.0)

    def test_gutter_between_pages_is_none(self):
        for dy in (1.0, GUTTER_PT / 2, GUTTER_PT - 1.0):
            assert scene_to_page(
                100.0, PAGE_HEIGHT_PT + dy, PAGE_WIDTH_PT, PAGE_HEIGHT_PT, 2
            ) is None

    def test_x_outside_the_page_width_is_none(self):
        for x in (-0.5, PAGE_WIDTH_PT + 0.5):
            assert scene_to_page(x, 100.0, PAGE_WIDTH_PT, PAGE_HEIGHT_PT, 2) is None

    def test_y_before_the_first_page_is_none(self):
        assert scene_to_page(100.0, -1.0, PAGE_WIDTH_PT, PAGE_HEIGHT_PT, 1) is None

    def test_y_past_the_last_page_is_none(self):
        assert scene_to_page(
            100.0, 2 * PAGE_HEIGHT_PT + GUTTER_PT + 1.0, PAGE_WIDTH_PT, PAGE_HEIGHT_PT, 2
        ) is None

    def test_page_bottom_edge_belongs_to_the_page(self):
        assert scene_to_page(100.0, PAGE_HEIGHT_PT, PAGE_WIDTH_PT, PAGE_HEIGHT_PT, 1) == (
            0, 100.0, PAGE_HEIGHT_PT
        )

    def test_gutter_end_is_the_next_page_top(self):
        idx, _, ly = scene_to_page(
            100.0, PAGE_HEIGHT_PT + GUTTER_PT, PAGE_WIDTH_PT, PAGE_HEIGHT_PT, 2
        )
        assert idx == 1 and ly == 0.0

    def test_landscape_swapped_dimensions(self):
        w, h = page_size("landscape")
        idx, lx, ly = scene_to_page(100.0, h + GUTTER_PT + 5.0, w, h, 2)
        assert (idx, lx, ly) == (1, 100.0, 5.0)


# --- Geometry: place_field ---

class TestPlaceField:
    def test_top_left_at_click_when_centred(self):
        f = place_field(FieldType.LABEL, (100.0, 200.0))
        assert f.type == FieldType.LABEL
        assert (f.x, f.y) == pytest.approx((100.0, 200.0))
        assert (f.w, f.h) == pytest.approx(default_size(FieldType.LABEL))
        assert f.content == ""
        assert f.font_size == DEFAULT_FONT_SIZE

    def test_id_is_assigned_and_unique(self):
        a = place_field(FieldType.TEXT, (10.0, 10.0))
        b = place_field(FieldType.TEXT, (12.0, 12.0))
        assert a.id and b.id
        assert a.id != b.id

    def test_place_near_edge_is_clamped_inside(self):
        eps = 1e-6
        f = place_field(FieldType.TEXTAREA, (PAGE_WIDTH_PT, PAGE_HEIGHT_PT))
        assert f.x >= 0.0
        assert f.y >= 0.0
        assert f.x + f.w <= PAGE_WIDTH_PT + eps
        assert f.y + f.h <= PAGE_HEIGHT_PT + eps

    def test_explicit_id_respected(self):
        f = place_field(FieldType.LABEL, (0.0, 0.0), field_id="fixed")
        assert f.id == "fixed"

    def test_new_checkbox_defaults_to_off(self):
        f = place_field(FieldType.CHECKBOX, (10.0, 10.0))
        assert f.content == "false"

    def test_other_new_types_default_to_empty_content(self):
        for t in (FieldType.NUMBER, FieldType.DROPDOWN, FieldType.IMAGE,
                  FieldType.RECT, FieldType.LINE):
            assert place_field(t, (10.0, 10.0)).content == ""


# --- Field collection (model behavior the service/VM rely on) ---

class TestFieldCollection:
    def _template(self) -> SheetTemplate:
        t = SheetTemplate(name="T")
        t.add_field(FieldType.LABEL, (10.0, 10.0))
        t.add_field(FieldType.TEXT, (50.0, 50.0))
        return t

    def test_add_field_appends_to_page(self):
        t = self._template()
        assert len(t.page.fields) == 2
        assert t.page.fields[0].type == FieldType.LABEL
        assert t.page.fields[1].type == FieldType.TEXT

    def test_get_field_finds_by_id(self):
        t = self._template()
        fid = t.page.fields[1].id
        assert t.get_field(fid) is t.page.fields[1]

    def test_get_field_missing_returns_none(self):
        assert self._template().get_field("nope") is None

    def test_remove_field_leaves_sibling_id_untouched(self):
        t = self._template()
        first_id = t.page.fields[0].id
        second = t.page.fields[1]
        assert t.remove_field(first_id) is True
        assert len(t.page.fields) == 1
        assert t.page.fields[0] is second
        assert t.page.fields[0].id == second.id

    def test_remove_field_missing_returns_false(self):
        assert self._template().remove_field("nope") is False

    def test_get_field_and_page_of_search_all_pages(self):
        t = SheetTemplate(name="T")
        t.add_page()
        a = t.add_field(FieldType.LABEL, (10.0, 10.0), page_index=0).id
        b = t.add_field(FieldType.TEXT, (10.0, 10.0), page_index=1).id
        assert t.get_field(b) is t.pages[1].fields[0]
        assert t.page_of(a) == 0
        assert t.page_of(b) == 1
        assert t.page_of("nope") is None


# --- Pages JSON round-trip ---

class TestPagesJson:
    def test_round_trip_preserves_fields_and_ids(self):
        t = SheetTemplate(name="R")
        t.add_field(FieldType.LABEL, (10.0, 10.0))
        t.add_field(FieldType.TEXTAREA, (20.0, 20.0))
        t.page.fields[0].content = "Имя"
        t.page.fields[1].font_size = 12.0
        ids_before = [f.id for f in t.page.fields]

        data = t.to_pages_json()
        back = SheetTemplate.parse_template(data, name="R", schema_version=2)

        assert [f.id for f in back.page.fields] == ids_before
        assert back.page.fields[0].content == "Имя"
        assert back.page.fields[0].type == FieldType.LABEL
        assert back.page.fields[1].font_size == 12.0

    def test_empty_template_round_trips(self):
        t = SheetTemplate(name="Empty")
        back = SheetTemplate.parse_template(t.to_pages_json(), name="Empty", schema_version=2)
        assert back.page.fields == []

    def test_from_pages_json_rejects_garbage(self):
        with pytest.raises(ValueError):
            SheetTemplate.parse_template("this is not json", name="X", schema_version=2)

    def test_saved_json_is_v2_shape(self):
        data = json.loads(SheetTemplate(name="R").to_pages_json())
        assert data == [{"name": "Страница 1", "fields": []}]


# ── corrupt / degenerate pages JSON (service load must reject these) ────────

class TestFromPagesJsonDegenerate:
    def test_non_array_json_is_invalid(self):
        with pytest.raises(ValueError):
            SheetTemplate.parse_template('{"fields": []}', name="X", schema_version=2)

    def test_page_without_fields_list_is_invalid(self):
        with pytest.raises(ValueError):
            SheetTemplate.parse_template("[42]", name="X", schema_version=2)

    def test_empty_pages_becomes_single_empty_page(self):
        template = SheetTemplate.parse_template("[]", name="X", schema_version=2)
        assert len(template.pages) == 1
        assert template.page.fields == []
        assert template.page.name == "Страница 1"

    def test_multi_page_array_is_valid_v2(self):
        pages = json.dumps([
            {"name": "A", "fields": []},
            {"name": "B", "fields": []},
        ])
        template = SheetTemplate.parse_template(pages, name="X", schema_version=2)
        assert [p.name for p in template.pages] == ["A", "B"]

    def test_invalid_field_entry_is_invalid(self):
        with pytest.raises(ValueError):
            SheetTemplate.parse_template(
                '[{"fields": [{"id": 1}]}]', name="X", schema_version=2
            )


# ── v1 / v2 parser (A-playable, design D3) ──────────────────────────────────

def _field_json(fid: str, ftype: str, content: str = "", **extra) -> dict:
    base = {
        "id": fid,
        "type": ftype,
        "x": 10.0,
        "y": 20.0,
        "w": 60.0,
        "h": 18.0,
        "font_size": 10.0,
        "content": content,
    }
    base.update(extra)
    return base


class TestParseTemplateV1:
    def test_v1_becomes_single_page_named_page_1(self):
        fields = [
            _field_json("a", "label", "Имя"),
            _field_json("b", "text", "Иван"),
        ]
        t = SheetTemplate.parse_template(
            json.dumps([{"fields": fields}]), name="Т", schema_version=1
        )
        assert len(t.pages) == 1
        assert t.pages[0].name == "Страница 1"
        assert [f.id for f in t.pages[0].fields] == ["a", "b"]

    def test_v1_preserves_geometry_content_font(self):
        fields = [_field_json("a", "label", "Имя")]
        fields[0].update(x=1.5, y=2.5, w=66.0, h=22.0, font_size=14.0)
        t = SheetTemplate.parse_template(
            json.dumps([{"fields": fields}]), name="Т",
            orientation="landscape", schema_version=1,
        )
        f = t.pages[0].fields[0]
        assert (f.x, f.y, f.w, f.h) == (1.5, 2.5, 66.0, 22.0)
        assert f.font_size == 14.0
        assert f.content == "Имя"
        assert t.orientation == "landscape"

    def test_v1_empty_fields_ok(self):
        t = SheetTemplate.parse_template(
            json.dumps([{"fields": []}]), name="Т", schema_version=1
        )
        assert t.pages[0].fields == []
        assert t.pages[0].name == "Страница 1"


class TestParseTemplateV2:
    def test_two_pages_with_names(self):
        pages = [
            {"name": "Основное", "fields": [_field_json("a", "label", "Имя")]},
            {"name": "Навыки", "fields": []},
        ]
        t = SheetTemplate.parse_template(
            json.dumps(pages), name="Т", schema_version=2
        )
        assert [p.name for p in t.pages] == ["Основное", "Навыки"]
        assert [f.id for f in t.pages[0].fields] == ["a"]
        assert t.pages[1].fields == []

    def test_missing_page_names_default_to_page_n(self):
        t = SheetTemplate.parse_template(
            json.dumps([{"fields": []}, {"fields": []}]), name="Т", schema_version=2
        )
        assert [p.name for p in t.pages] == ["Страница 1", "Страница 2"]

    def test_unknown_type_raises(self):
        pages = [{"name": "P", "fields": [_field_json("a", "sparkles")]}]
        with pytest.raises(UnknownFieldTypeError):
            SheetTemplate.parse_template(json.dumps(pages), name="Т", schema_version=2)

    def test_unknown_type_raises_in_v1_file_too(self):
        pages = [{"fields": [_field_json("a", "sparkles")]}]
        with pytest.raises(UnknownFieldTypeError):
            SheetTemplate.parse_template(json.dumps(pages), name="Т", schema_version=1)

    def test_unknown_type_message_names_the_type(self):
        pages = [{"name": "P", "fields": [_field_json("a", "teleport")]}]
        with pytest.raises(UnknownFieldTypeError) as ei:
            SheetTemplate.parse_template(json.dumps(pages), name="Т", schema_version=2)
        assert "teleport" in str(ei.value)

    def test_every_catalog_type_parses(self):
        types = [f.value for f in FieldType]
        extra_by_type = {
            "number": {"min": 1.0, "max": 10.5, "content": "3.14"},
            "dropdown": {"options": ["А", "Б"], "content": "А"},
            "image": {"image_id": 7},
            "checkbox": {"content": "true"},
        }
        fields = [
            _field_json(f"i{k}", t, **extra_by_type.get(t, {}))
            for k, t in enumerate(types)
        ]
        t = SheetTemplate.parse_template(
            json.dumps([{"name": "P", "fields": fields}]), name="Т", schema_version=2
        )
        parsed = t.pages[0].fields
        assert [f.type for f in parsed] == [FieldType(x) for x in types]
        number = parsed[types.index("number")]
        assert (number.min_value, number.max_value, number.content) == (1.0, 10.5, "3.14")
        dropdown = parsed[types.index("dropdown")]
        assert dropdown.options == ["А", "Б"]
        assert dropdown.content == "А"
        assert parsed[types.index("image")].image_id == 7
        assert parsed[types.index("checkbox")].content == "true"


class TestParseTemplateNormalization:
    def test_number_comma_is_normalized_to_dot(self):
        pages = [{"name": "P", "fields": [_field_json("n", "number", "1,5")]}]
        t = SheetTemplate.parse_template(json.dumps(pages), name="Т", schema_version=2)
        assert t.pages[0].fields[0].content == "1.5"

    def test_number_allows_empty_and_plain_dot(self):
        pages = [
            {"name": "P", "fields": [
                _field_json("e", "number", ""),
                _field_json("d", "number", "3.5"),
            ]}
        ]
        t = SheetTemplate.parse_template(json.dumps(pages), name="Т", schema_version=2)
        assert [f.content for f in t.pages[0].fields] == ["", "3.5"]

    def test_number_non_numeric_content_is_rejected(self):
        pages = [{"name": "P", "fields": [_field_json("n", "number", "abc")]}]
        with pytest.raises(ValueError):
            SheetTemplate.parse_template(json.dumps(pages), name="Т", schema_version=2)

    def test_omitting_number_leaves_bounds_none(self):
        pages = [{"name": "P", "fields": [_field_json("n", "number", "2")]}]
        t = SheetTemplate.parse_template(json.dumps(pages), name="Т", schema_version=2)
        assert t.pages[0].fields[0].min_value is None
        assert t.pages[0].fields[0].max_value is None

    def test_empty_dropdown_option_is_rejected(self):
        pages = [{"name": "P", "fields": [
            _field_json("d", "dropdown", "", options=["А", "   "]),
        ]}]
        with pytest.raises(ValueError):
            SheetTemplate.parse_template(json.dumps(pages), name="Т", schema_version=2)

    def test_options_order_and_content_preserved(self):
        pages = [{"name": "P", "fields": [
            _field_json("d", "dropdown", "Б", options=["А", "Б", "В"]),
        ]}]
        t = SheetTemplate.parse_template(json.dumps(pages), name="Т", schema_version=2)
        f = t.pages[0].fields[0]
        assert f.options == ["А", "Б", "В"]
        assert f.content == "Б"


# ── pure image-id JSON helpers (used by ImageStore refcount / GC) ──────────

class TestSheetImageIdHelpers:
    def test_iter_finds_image_ids_across_pages(self):
        pages = [
            {"name": "P1", "fields": [
                _field_json("a", "image", image_id=5),
                _field_json("b", "label"),
                _field_json("c", "image", image_id=9),
            ]},
            {"name": "P2", "fields": [_field_json("d", "image", image_id=5)]},
        ]
        assert iter_sheet_image_ids(json.dumps(pages)) == [5, 9, 5]

    def test_iter_ignores_null_and_non_image_fields(self):
        pages = [{"name": "P", "fields": [
            _field_json("a", "image", image_id=None),
            _field_json("b", "label", image_id=99),   # stray key, not an image field
        ]}]
        assert iter_sheet_image_ids(json.dumps(pages)) == []

    def test_iter_garbage_json_yields_nothing(self):
        assert iter_sheet_image_ids("not json") == []

    def test_null_helper_clears_only_matching_fields(self):
        pages = [
            {"name": "P1", "fields": [
                _field_json("a", "image", image_id=5),
                _field_json("b", "image", image_id=7),
                _field_json("c", "image", image_id=5),
            ]},
        ]
        raw = json.dumps(pages)
        cleared = null_sheet_image_ids(raw, 5)
        data = json.loads(cleared)
        ids = [f.get("image_id") for f in data[0]["fields"]]
        assert ids == [None, 7, None]
        # ids of the other fields are untouched
        assert [f["id"] for f in data[0]["fields"]] == ["a", "b", "c"]

    def test_null_helper_noop_when_unreferenced(self):
        raw = json.dumps([{"name": "P", "fields": [_field_json("a", "image", image_id=7)]}])
        assert null_sheet_image_ids(raw, 5) == raw

    def test_null_helper_garbage_returns_input_unchanged(self):
        assert null_sheet_image_ids("not json", 5) == "not json"
