"""JSON fields → CSS left/top/width/height in pt; labels are not inputs."""
from __future__ import annotations

from app.domain.entities.character_sheet import FieldType, SheetTemplate, place_field
from app.domain.entities.sheet_html_layout import css_box, html_layout, input_fields


def test_css_box_is_pt():
    field = place_field(FieldType.TEXT, (12.0, 24.0))
    box = css_box(field)
    assert box["left"].endswith("pt")
    assert box["top"].endswith("pt")
    assert box["width"].endswith("pt")
    assert box["height"].endswith("pt")
    assert float(box["left"][:-2]) == field.x
    assert float(box["top"][:-2]) == field.y
    assert float(box["width"][:-2]) == field.w
    assert float(box["height"][:-2]) == field.h


def test_label_rect_line_are_not_inputs():
    template = SheetTemplate(name="Макет")
    label = template.add_field(FieldType.LABEL, (10.0, 10.0))
    text = template.add_field(FieldType.TEXT, (10.0, 40.0))
    template.add_field(FieldType.RECT, (10.0, 80.0))
    template.add_field(FieldType.LINE, (10.0, 200.0))
    ids = {field.id for field in input_fields(template)}
    assert label.id not in ids
    assert text.id in ids
    layout = html_layout(template)
    by_id = {item["id"]: item for page in layout["pages"] for item in page["fields"]}
    assert by_id[label.id]["input"] is False
    assert by_id[text.id]["input"] is True
    assert by_id[label.id]["css"]["left"].endswith("pt")


def test_html_layout_includes_dropdown_options_and_number_bounds():
    template = SheetTemplate(name="Макет")
    dd = template.add_field(FieldType.DROPDOWN, (10.0, 10.0))
    dd.options = ["эльф", "орк"]
    num = template.add_field(FieldType.NUMBER, (10.0, 40.0))
    num.min_value = 0.0
    num.max_value = 10.0
    layout = html_layout(template)
    by_id = {item["id"]: item for page in layout["pages"] for item in page["fields"]}
    assert by_id[dd.id]["options"] == ["эльф", "орк"]
    assert by_id[num.id]["min"] == 0.0
    assert by_id[num.id]["max"] == 10.0


def test_html_layout_carries_image_default():
    """The web Fill inherits the template default when the map has no key —
    for an image that default is ``image_id``, so the layout must carry it."""
    template = SheetTemplate(name="Макет")
    with_file = template.add_field(FieldType.IMAGE, (10.0, 10.0))
    with_file.image_id = 7
    empty = template.add_field(FieldType.IMAGE, (10.0, 200.0))
    layout = html_layout(template)
    by_id = {item["id"]: item for page in layout["pages"] for item in page["fields"]}
    assert by_id[with_file.id]["image_id"] == 7
    assert by_id[empty.id]["image_id"] is None
