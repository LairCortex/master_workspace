"""JSON template fields → CSS boxes in pt for the web Fill (task 4.1)."""
from __future__ import annotations

from app.domain.entities.character_sheet import (
    GUTTER_PT,
    SheetField,
    SheetTemplate,
    page_size,
)
from app.domain.entities.character_sheet_instance import FILLABLE_TYPES
from app.domain.enums.field_type import FieldType


def pt(value: float) -> str:
    return f"{value:g}pt"


def css_box(field: SheetField) -> dict[str, str]:
    return {
        "left": pt(field.x),
        "top": pt(field.y),
        "width": pt(field.w),
        "height": pt(field.h),
    }


def is_input_field(field: SheetField) -> bool:
    return field.type in FILLABLE_TYPES


def input_fields(template: SheetTemplate) -> list[SheetField]:
    return [
        field
        for page in template.pages
        for field in page.fields
        if is_input_field(field)
    ]


def html_layout(template: SheetTemplate) -> dict:
    page_w, page_h = page_size(template.orientation)
    pages = []
    for page in template.pages:
        fields = []
        for field in page.fields:
            item = {
                "id": field.id,
                "type": field.type.value,
                "css": css_box(field),
                "input": is_input_field(field),
                "font_size": field.font_size,
                "content": field.content,
            }
            if field.type is FieldType.DROPDOWN:
                item["options"] = list(field.options)
            if field.type is FieldType.NUMBER:
                item["min"] = field.min_value
                item["max"] = field.max_value
            if field.type is FieldType.IMAGE:
                # the template default the web client inherits when the
                # instance map has no key for this field (spec: value join)
                item["image_id"] = field.image_id
            fields.append(item)
        pages.append({
            "name": page.name,
            "width": pt(page_w),
            "height": pt(page_h),
            "fields": fields,
        })
    return {
        "orientation": template.orientation,
        "gutter": pt(GUTTER_PT),
        "pages": pages,
    }
