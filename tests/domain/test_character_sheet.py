"""Unit tests for the character sheet domain model (tasks 2.1/2.2)."""
from __future__ import annotations

import pytest

from app.domain.entities.character_sheet import (
    SheetField,
    SheetPage,
    SheetTemplate,
    scale_for_orientation,
)
from app.domain.enums.field_type import FieldType
from app.domain.enums.sheet_orientation import (
    A4_LANDSCAPE_SIZE,
    A4_PORTRAIT_SIZE,
    SheetOrientation,
)


def make_field(**overrides) -> SheetField:
    params = dict(
        id="0" * 32,
        type=FieldType.SHORT_TEXT,
        x=100.0,
        y=80.0,
        w=180.0,
        h=24.0,
        label="Имя",
        default_value="Без",
        font_size=12.0,
    )
    params.update(overrides)
    return SheetField(**params)


class TestFieldType:
    def test_nine_types(self):
        assert {t.value for t in FieldType} == {
            "number", "short_text", "long_text", "checkbox",
            "dropdown", "date", "portrait", "heading", "static_text",
        }

    def test_orientation_a4_sizes(self):
        assert A4_PORTRAIT_SIZE == (595.28, 841.89)
        assert A4_LANDSCAPE_SIZE == (841.89, 595.28)


class TestSheetField:
    def test_construction_defaults(self):
        f = make_field()
        assert f.min_value == 0
        assert f.max_value == 20
        assert f.options == []
        assert f.initial_checked is False

    def test_geometry_rejects_non_numeric(self):
        with pytest.raises(ValueError):
            make_field(x="100")
        with pytest.raises(ValueError):
            make_field(w=True)

    def test_geometry_rejects_nan(self):
        with pytest.raises(ValueError):
            make_field(x=float("nan"))

    def test_unknown_type_rejected(self):
        with pytest.raises(ValueError):
            make_field(type="bogus")

    def test_options_must_be_strings(self):
        with pytest.raises(ValueError):
            make_field(options=[1, 2])

    def test_to_dict_from_dict_round_trip(self):
        f = make_field(
            type=FieldType.DROPDOWN,
            options=["Сила", "Ловкость"],
            min_value=1,
            max_value=30,
            initial_checked=True,
        )
        restored = SheetField.from_dict(f.to_dict())
        assert restored == f
        d = f.to_dict()
        assert d["type"] == "dropdown"
        assert d["options"] == ["Сила", "Ловкость"]

    def test_from_dict_rejects_unknown_type(self):
        d = make_field().to_dict()
        d["type"] = "bogus"
        with pytest.raises(ValueError, match="unknown field type"):
            SheetField.from_dict(d)

    def test_from_dict_rejects_missing_geometry(self):
        d = make_field().to_dict()
        del d["w"]
        with pytest.raises(ValueError, match="'w'"):
            SheetField.from_dict(d)

    def test_clone_is_deep(self):
        f = make_field(options=["А"])
        c = f.clone()
        c.options.append("Б")
        assert f.options == ["А"]


class TestSheetPage:
    def test_round_trip(self):
        p = SheetPage(name="Стр 1", fields=[make_field(), make_field(id="1" * 32, x=50.0)])
        assert SheetPage.from_dict(p.to_dict()) == p

    def test_find_field(self):
        f = make_field(id="abc")
        p = SheetPage(name="s", fields=[f, make_field()])
        assert p.find_field("abc") is f
        assert p.find_field("nope") is None

    def test_from_dict_rejects_empty_name(self):
        with pytest.raises(ValueError):
            SheetPage.from_dict({"name": "", "fields": []})


class TestSheetTemplate:
    def make_template(self, **overrides) -> SheetTemplate:
        params = dict(
            name="Лист",
            orientation=SheetOrientation.LANDSCAPE,
            pages=[SheetPage(name="Стр 1", fields=[make_field()])],
        )
        params.update(overrides)
        return SheetTemplate(**params)

    def test_to_dict_from_dict_round_trip(self):
        t = self.make_template(
            pages=[
                SheetPage(name="ОСН", fields=[make_field(id="a" * 32), make_field(id="b" * 32, y=90.0)]),
                SheetPage(name="ЗАП", fields=[]),
            ]
        )
        assert SheetTemplate.from_dict(t.to_dict()) == t

    def test_post_init_validation(self):
        with pytest.raises(ValueError):
            self.make_template(name="")
        with pytest.raises(ValueError):
            self.make_template(orientation="sideways")
        with pytest.raises(ValueError):
            self.make_template(pages=[])

    def test_from_dict_validation_errors(self):
        d = self.make_template().to_dict()
        d["orientation"] = "diagonal"
        with pytest.raises(ValueError, match="unknown orientation"):
            SheetTemplate.from_dict(d)
        d2 = self.make_template().to_dict()
        d2["pages"] = []
        with pytest.raises(ValueError, match="non-empty list"):
            SheetTemplate.from_dict(d2)

    def test_find_field_across_pages(self):
        target = make_field(id="hit")
        t = self.make_template(pages=[
            SheetPage(name="1", fields=[make_field()]),
            SheetPage(name="2", fields=[target]),
        ])
        assert t.find_field("hit") == (1, target)
        assert t.find_field("miss") is None

    def test_clone_preserves_ids_and_content(self):
        t = self.make_template()
        c = t.clone()
        assert c == t
        c.pages[0].fields[0].x = 999.0
        assert t.pages[0].fields[0].x != 999.0


class TestScaleForOrientation:
    # grid-aligned values: the landscape→portrait→landscape round trip must
    # reproduce them exactly (2-decimal rounding is exact for these)
    def test_landscape_portrait_landscape_round_trip(self):
        t = SheetTemplate(
            name="Лист",
            orientation=SheetOrientation.LANDSCAPE,
            pages=[
                SheetPage(name="ОСН", fields=[
                    make_field(id="a", x=100.0, y=80.0, w=120.0, h=40.0,
                               label="Сила", default_value="10",
                               min_value=1, max_value=20, options=["М"], initial_checked=True),
                    make_field(id="b", type=FieldType.CHECKBOX, x=640.0, y=400.0,
                               w=20.0, h=20.0),
                ]),
                SheetPage(name="Пустая", fields=[]),
            ],
        )
        portrait = scale_for_orientation(t, SheetOrientation.PORTRAIT)
        back = scale_for_orientation(portrait, SheetOrientation.LANDSCAPE)

        assert back.orientation is SheetOrientation.LANDSCAPE
        assert [p.name for p in back.pages] == ["ОСН", "Пустая"]
        first, second = back.pages[0].fields
        assert (first.x, first.y, first.w, first.h) == (100.0, 80.0, 120.0, 40.0)
        assert (second.x, second.y, second.w, second.h) == (640.0, 400.0, 20.0, 20.0)
        # ids and content untouched
        assert [f.id for f in back.pages[0].fields] == ["a", "b"]
        assert first.label == "Сила" and first.default_value == "10"
        assert (first.min_value, first.max_value, first.options, first.initial_checked) == (1, 20, ["М"], True)
        assert back.pages[0].fields[0] == t.pages[0].fields[0]

    def test_scales_by_proportional_ratios(self):
        old_w, old_h = A4_LANDSCAPE_SIZE
        new_w, new_h = A4_PORTRAIT_SIZE
        t = SheetTemplate(
            name="x",
            orientation=SheetOrientation.LANDSCAPE,
            pages=[SheetPage(name="p", fields=[make_field(x=100.0, y=100.0, w=100.0, h=100.0)])],
        )
        scaled = scale_for_orientation(t, SheetOrientation.PORTRAIT)
        f = scaled.pages[0].fields[0]
        assert f.x == round(100.0 * new_w / old_w, 2)
        assert f.w == round(100.0 * new_w / old_w, 2)
        assert f.y == round(100.0 * new_h / old_h, 2)
        assert f.h == round(100.0 * new_h / old_h, 2)
        assert scaled.orientation is SheetOrientation.PORTRAIT

    def test_same_orientation_returns_equal_clone(self):
        t = SheetTemplate(
            name="x",
            orientation=SheetOrientation.PORTRAIT,
            pages=[SheetPage(name="p", fields=[make_field()])],
        )
        again = scale_for_orientation(t, SheetOrientation.PORTRAIT)
        assert again == t
        assert again is not t

    def test_input_not_mutated(self):
        t = SheetTemplate(
            name="x",
            orientation=SheetOrientation.LANDSCAPE,
            pages=[SheetPage(name="p", fields=[make_field(x=10.0, y=10.0, w=10.0, h=10.0)])],
        )
        scale_for_orientation(t, SheetOrientation.PORTRAIT)
        assert t.pages[0].fields[0].x == 10.0

    def test_invalid_orientation_rejected(self):
        t = SheetTemplate(
            name="x",
            orientation=SheetOrientation.LANDSCAPE,
            pages=[SheetPage(name="p", fields=[])],
        )
        with pytest.raises(ValueError):
            scale_for_orientation(t, "sideways")


class TestValidationGaps:
    """ValueError branches that the serialization tests don't trip (100% gate)."""

    @staticmethod
    def make_field(**overrides):
        from app.domain.entities.character_sheet import SheetField
        from app.domain.enums.field_type import FieldType

        params = dict(id="a", type=FieldType.SHORT_TEXT, x=0, y=0, w=10, h=10)
        params.update(overrides)
        return SheetField(**params)

    def test_non_str_label_rejected(self):
        with pytest.raises(ValueError, match="label"):
            self.make_field(label=123)

    def test_non_str_default_value_rejected(self):
        with pytest.raises(ValueError, match="default_value"):
            self.make_field(default_value=5)

    def test_non_int_min_rejected(self):
        with pytest.raises(ValueError, match="min_value"):
            self.make_field(min_value="x")

    def test_bool_max_rejected(self):
        with pytest.raises(ValueError, match="max_value"):
            self.make_field(max_value=True)

    def test_non_bool_initial_checked_rejected(self):
        with pytest.raises(ValueError, match="initial_checked"):
            self.make_field(initial_checked="yes")

    def test_non_dict_field_rejected(self):
        from app.domain.entities.character_sheet import SheetField

        with pytest.raises(ValueError, match="not an object"):
            SheetField.from_dict([1])

    def test_non_dict_page_rejected(self):
        from app.domain.entities.character_sheet import SheetPage

        with pytest.raises(ValueError, match="not an object"):
            SheetPage.from_dict([1])

    def test_empty_page_name_rejected(self):
        from app.domain.entities.character_sheet import SheetPage

        with pytest.raises(ValueError, match="page name"):
            SheetPage.from_dict({"name": ""})

    def test_non_list_page_fields_rejected(self):
        from app.domain.entities.character_sheet import SheetPage

        with pytest.raises(ValueError, match="page fields"):
            SheetPage.from_dict({"name": "p", "fields": "nope"})

    def test_empty_template_name_rejected(self):
        from app.domain.entities.character_sheet import SheetTemplate

        with pytest.raises(ValueError, match="template name"):
            SheetTemplate.from_dict(
                {"name": "", "orientation": "landscape", "pages": []}
            )
