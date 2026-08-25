"""Character sheet domain model: template, pages, fields.

The template is a single self-contained document (design D1/D2): the whole
tree round-trips to/from a plain dict (storage `pages` column, JSON project
export/import) one-to-one.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from app.domain.enums.field_type import FieldType
from app.domain.enums.sheet_orientation import SheetOrientation, a4_size

_GEOM_KEYS = ("x", "y", "w", "h")


def _as_finite_number(value, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number, got {value!r}")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"{key} must be a finite number, got {value!r}")
    return number


@dataclass
class SheetField:
    """One field on a sheet page.

    ``id`` is a stable uuid4-hex identifier assigned once at creation; it
    never changes and is used as the PDF form-field name (design D1).
    Geometry is float in pt, top-left origin, rounded to 2 decimals on
    persistence (design D2).
    """
    id: str
    type: FieldType
    x: float
    y: float
    w: float
    h: float
    label: str = ""
    default_value: str = ""
    font_size: float = 12.0
    # type-specific properties (only the matching set is meaningful per type)
    min_value: int = 0
    max_value: int = 20
    options: list[str] = field(default_factory=list)
    initial_checked: bool = False

    def __post_init__(self) -> None:
        for key in _GEOM_KEYS:
            setattr(self, key, _as_finite_number(getattr(self, key), key))
        _as_finite_number(self.font_size, "font_size")
        if not isinstance(self.type, FieldType):
            raise ValueError(f"field type must be FieldType, got {self.type!r}")
        if not isinstance(self.label, str):
            raise ValueError("label must be str")
        if not isinstance(self.default_value, str):
            raise ValueError("default_value must be str")
        if not isinstance(self.min_value, int) or isinstance(self.min_value, bool):
            raise ValueError("min_value must be int")
        if not isinstance(self.max_value, int) or isinstance(self.max_value, bool):
            raise ValueError("max_value must be int")
        if not isinstance(self.options, list) or not all(isinstance(o, str) for o in self.options):
            raise ValueError("options must be a list of str")
        if not isinstance(self.initial_checked, bool):
            raise ValueError("initial_checked must be bool")

    def to_dict(self) -> dict:
        # Geometry is rounded to 2 decimals on persistence (design D2), which
        # protects against float error accumulation over repeated resizes.
        return {
            "id": self.id,
            "type": self.type.value,
            "x": round(self.x, 2),
            "y": round(self.y, 2),
            "w": round(self.w, 2),
            "h": round(self.h, 2),
            "label": self.label,
            "default_value": self.default_value,
            "font_size": self.font_size,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "options": list(self.options),
            "initial_checked": self.initial_checked,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SheetField:
        if not isinstance(data, dict):
            raise ValueError(f"field is not an object: {data!r}")
        try:
            field_type = FieldType(data["type"])
        except (KeyError, ValueError) as exc:
            raise ValueError(f"unknown field type: {data.get('type')!r}") from exc
        geometry = {}
        for key in _GEOM_KEYS:
            try:
                geometry[key] = _as_finite_number(data[key], f"field {key}")
            except KeyError as exc:
                raise ValueError(f"field is missing {key!r}") from exc
        return cls(
            id=data.get("id", ""),
            type=field_type,
            x=geometry["x"],
            y=geometry["y"],
            w=geometry["w"],
            h=geometry["h"],
            label=data.get("label", ""),
            default_value=data.get("default_value", ""),
            font_size=data.get("font_size", 12.0),
            min_value=data.get("min_value", 0),
            max_value=data.get("max_value", 20),
            options=list(data.get("options", [])),
            initial_checked=bool(data.get("initial_checked", False)),
        )

    def clone(self) -> SheetField:
        return copy.deepcopy(self)


@dataclass
class SheetPage:
    name: str
    fields: list[SheetField] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"name": self.name, "fields": [f.to_dict() for f in self.fields]}

    @classmethod
    def from_dict(cls, data: dict) -> SheetPage:
        if not isinstance(data, dict):
            raise ValueError(f"page is not an object: {data!r}")
        name = data.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("page name must be a non-empty string")
        raw_fields = data.get("fields", [])
        if not isinstance(raw_fields, list):
            raise ValueError("page fields must be a list")
        return cls(name=name, fields=[SheetField.from_dict(f) for f in raw_fields])

    def find_field(self, field_id: str) -> SheetField | None:
        for f in self.fields:
            if f.id == field_id:
                return f
        return None

    def clone(self) -> SheetPage:
        return SheetPage(name=self.name, fields=[f.clone() for f in self.fields])


@dataclass
class SheetTemplate:
    name: str
    orientation: SheetOrientation
    pages: list[SheetPage] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.orientation, SheetOrientation):
            raise ValueError(
                f"orientation must be SheetOrientation, got {self.orientation!r}"
            )
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("template name must be a non-empty string")
        if not self.pages:
            raise ValueError("a template must have at least one page")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "orientation": self.orientation.value,
            "pages": [p.to_dict() for p in self.pages],
        }

    @classmethod
    def from_dict(cls, data: dict) -> SheetTemplate:
        if not isinstance(data, dict):
            raise ValueError(f"template is not an object: {data!r}")
        name = data.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("template name must be a non-empty string")
        try:
            orientation = SheetOrientation(data.get("orientation"))
        except ValueError as exc:
            raise ValueError(f"unknown orientation: {data.get('orientation')!r}") from exc
        raw_pages = data.get("pages")
        if not isinstance(raw_pages, list) or not raw_pages:
            raise ValueError("pages must be a non-empty list")
        return cls(
            name=name,
            orientation=orientation,
            pages=[SheetPage.from_dict(p) for p in raw_pages],
        )

    def find_field(self, field_id: str) -> tuple[int, SheetField] | None:
        """Locate a field by id; returns (page_index, field) or None."""
        for index, page in enumerate(self.pages):
            found = page.find_field(field_id)
            if found is not None:
                return index, found
        return None

    def clone(self) -> SheetTemplate:
        return SheetTemplate(
            name=self.name,
            orientation=self.orientation,
            pages=[p.clone() for p in self.pages],
        )


def scale_for_orientation(template: SheetTemplate, new_orientation: SheetOrientation) -> SheetTemplate:
    """Pure orientation switch (design D3): proportional geometry scaling.

    x/w scale by the new/old page-width ratio, y/h by the height ratio;
    geometry is rounded to 2 decimals (protects against error accumulation
    over repeated switches). Field ids, labels, values and type-specific
    properties are preserved untouched.
    """
    if not isinstance(new_orientation, SheetOrientation):
        raise ValueError(f"orientation must be SheetOrientation, got {new_orientation!r}")
    if template.orientation is new_orientation:
        return template.clone()
    old_w, old_h = a4_size(template.orientation)
    new_w, new_h = a4_size(new_orientation)
    kx = new_w / old_w
    ky = new_h / old_h
    pages = []
    for page in template.pages:
        scaled = [
            SheetField(
                id=f.id,
                type=f.type,
                x=round(f.x * kx, 2),
                y=round(f.y * ky, 2),
                w=round(f.w * kx, 2),
                h=round(f.h * ky, 2),
                label=f.label,
                default_value=f.default_value,
                font_size=f.font_size,
                min_value=f.min_value,
                max_value=f.max_value,
                options=list(f.options),
                initial_checked=f.initial_checked,
            )
            for f in page.fields
        ]
        pages.append(SheetPage(name=page.name, fields=scaled))
    return SheetTemplate(name=template.name, orientation=new_orientation, pages=pages)
