"""Tests for instance value map + join with the saved template (design D2).

Covers task 1.1: resolve_display (missing key / present key including image
null / orphan ids not displayed); defaults_map copies fillable types only.
"""
from __future__ import annotations

from app.domain.entities.character_sheet import SheetField, SheetPage, SheetTemplate
from app.domain.entities.character_sheet_instance import (
    defaults_map,
    display_fields,
    resolve_display,
)
from app.domain.enums.field_type import FieldType


def _field(fid: str, ftype: FieldType, **kwargs) -> SheetField:
    defaults = dict(x=0.0, y=0.0, w=40.0, h=18.0)
    defaults.update(kwargs)
    return SheetField(id=fid, type=ftype, **defaults)


def _template(*fields: SheetField) -> SheetTemplate:
    return SheetTemplate(name="T", pages=[SheetPage(fields=list(fields))])


class TestResolveDisplay:
    def test_missing_key_uses_template_default_text(self):
        f = _field("name", FieldType.TEXT, content="Иван")
        assert resolve_display(f, {}) == "Иван"

    def test_missing_key_uses_template_default_checkbox(self):
        f = _field("chk", FieldType.CHECKBOX, content="true")
        assert resolve_display(f, {}) is True

    def test_missing_key_uses_template_default_number(self):
        f = _field("hp", FieldType.NUMBER, content="10")
        assert resolve_display(f, {}) == "10"

    def test_missing_key_uses_template_default_dropdown(self):
        f = _field("race", FieldType.DROPDOWN, content="эльф", options=["эльф", "орк"])
        assert resolve_display(f, {}) == "эльф"

    def test_missing_key_uses_template_default_image(self):
        f = _field("port", FieldType.IMAGE, image_id=7)
        assert resolve_display(f, {}) == 7

    def test_present_key_overrides_text(self):
        f = _field("name", FieldType.TEXT, content="Иван")
        assert resolve_display(f, {"name": "Пётр"}) == "Пётр"

    def test_present_key_overrides_checkbox_false(self):
        f = _field("chk", FieldType.CHECKBOX, content="true")
        assert resolve_display(f, {"chk": False}) is False

    def test_present_image_null_overrides_template_file(self):
        f = _field("port", FieldType.IMAGE, image_id=7)
        assert resolve_display(f, {"port": None}) is None

    def test_present_image_id_overrides(self):
        f = _field("port", FieldType.IMAGE, image_id=7)
        assert resolve_display(f, {"port": 3}) == 3

    def test_empty_string_key_is_not_missing(self):
        f = _field("hp", FieldType.NUMBER, content="10")
        assert resolve_display(f, {"hp": ""}) == ""


class TestDisplayFields:
    def test_orphan_id_not_in_displayed_fields(self):
        f = _field("alive", FieldType.TEXT, content="")
        template = _template(f)
        values = {"alive": "да", "deleted": "сирота"}
        ids = [field.id for field in display_fields(template)]
        assert ids == ["alive"]
        assert "deleted" not in ids
        # orphan stays in the map; it just is not a displayed field
        assert "deleted" in values


class TestDefaultsMap:
    def test_copies_fillable_types(self):
        template = _template(
            _field("t", FieldType.TEXT, content="a"),
            _field("ta", FieldType.TEXTAREA, content="b"),
            _field("c", FieldType.CHECKBOX, content="true"),
            _field("n", FieldType.NUMBER, content="1.5"),
            _field("d", FieldType.DROPDOWN, content="x", options=["x"]),
            _field("i", FieldType.IMAGE, image_id=4),
        )
        assert defaults_map(template) == {
            "t": "a",
            "ta": "b",
            "c": True,
            "n": "1.5",
            "d": "x",
            "i": 4,
        }

    def test_image_default_null_when_template_has_no_file(self):
        template = _template(_field("i", FieldType.IMAGE, image_id=None))
        assert defaults_map(template) == {"i": None}

    def test_checkbox_false_default(self):
        template = _template(_field("c", FieldType.CHECKBOX, content="false"))
        assert defaults_map(template) == {"c": False}

    def test_empty_number_default(self):
        template = _template(_field("n", FieldType.NUMBER, content=""))
        assert defaults_map(template) == {"n": ""}

    def test_label_rect_line_have_no_keys(self):
        template = _template(
            _field("lab", FieldType.LABEL, content="Имя"),
            _field("r", FieldType.RECT),
            _field("ln", FieldType.LINE),
            _field("t", FieldType.TEXT, content="x"),
        )
        mapped = defaults_map(template)
        assert set(mapped) == {"t"}
        assert mapped["t"] == "x"
