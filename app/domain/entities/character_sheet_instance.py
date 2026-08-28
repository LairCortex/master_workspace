"""Join of an instance value map with a saved character-sheet template (D2).

A filled sheet stores ``{field_id: value}``. Missing key ≠ empty value:
display then inherits the template default. A key that is present (including
JSON ``null`` for an image) is the instance's own value. Decorative types
(label / rect / line) never get a key. An id that is not on the current
template is kept in the map but is not a displayed field.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from app.domain.entities.character_sheet import SheetField, SheetTemplate
from app.domain.enums.field_type import FieldType

FILLABLE_TYPES: frozenset[FieldType] = frozenset({
    FieldType.TEXT,
    FieldType.TEXTAREA,
    FieldType.CHECKBOX,
    FieldType.NUMBER,
    FieldType.DROPDOWN,
    FieldType.IMAGE,
})


def field_default(field: SheetField) -> Any:
    """Template-side default for a fillable field (the inherit value)."""
    if field.type is FieldType.CHECKBOX:
        return field.content == "true"
    if field.type is FieldType.IMAGE:
        return field.image_id
    return field.content


def defaults_map(template: SheetTemplate) -> dict[str, Any]:
    """Copy current defaults of every fillable field. Decorative types omitted."""
    out: dict[str, Any] = {}
    for page in template.pages:
        for field in page.fields:
            if field.type in FILLABLE_TYPES:
                out[field.id] = field_default(field)
    return out


def resolve_display(field: SheetField, values: Mapping[str, Any]) -> Any:
    """Value shown for ``field``: instance key if present, else template default."""
    if field.id in values:
        return values[field.id]
    return field_default(field)


def display_fields(template: SheetTemplate) -> list[SheetField]:
    """Fields drawn on the canvas — those currently on the saved template."""
    return [field for page in template.pages for field in page.fields]


def iter_instance_image_ids(values_json: str) -> list[int]:
    """All ``images.id`` references in one instance ``values`` JSON object.

    Garbage JSON yields nothing rather than raising. JSON bools are not ids.
    """
    try:
        data = json.loads(values_json)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    ids: list[int] = []
    for value in data.values():
        if isinstance(value, int) and not isinstance(value, bool):
            ids.append(value)
    return ids


def null_instance_image_ids(values_json: str, image_id: int) -> str:
    """Null every map entry whose value is ``image_id`` (startup-gc drop)."""
    try:
        data = json.loads(values_json)
    except Exception:
        return values_json
    if not isinstance(data, dict):
        return values_json
    changed = False
    for key, value in list(data.items()):
        if isinstance(value, int) and not isinstance(value, bool) and value == image_id:
            data[key] = None
            changed = True
    if not changed:
        return values_json
    return json.dumps(data, ensure_ascii=False)
