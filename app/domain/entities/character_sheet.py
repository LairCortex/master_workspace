"""Domain model for character-sheet templates (epic A1 + A-playable).

Pure dataclasses + pure geometry functions (design D2): no Qt, no I/O, so the
model and its layout math are unit-testable without a display.

Coordinate unit is the point (pt), origin top-left (as in Qt). A template is
an ordered list of named A4 pages (the canvas lays them out as a vertical
tape, design D1); the order of fields on a page is the z-order (later fields
render and hit-test on top).

Storage (design D3): ``schema_version 2`` — every page is
``{"name": str, "fields": [...]}``. Version 1 rows (one page, no names, only
A1 types) are read back without loss; a field ``type`` outside the closed
catalog raises :class:`UnknownFieldTypeError` and the template must not open.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field
from uuid import uuid4

from app.domain.enums.field_type import FieldType

# ── Page / layout constants ────────────────────────────────────────────────

PAGE_WIDTH_PT: float = 595.28   # A4 portrait, width in points
PAGE_HEIGHT_PT: float = 841.89  # A4 portrait, height in points

GUTTER_PT: float = 24.0         # vertical gap between the pages of the tape

ORIENTATION_PORTRAIT: str = "portrait"
ORIENTATION_LANDSCAPE: str = "landscape"

SCHEMA_VERSION: int = 2         # A-playable: multi-page v2 layout
SCHEMA_VERSION_V1: int = 1      # A1 single-page rows (read-only legacy)

DEFAULT_FONT_SIZE: float = 10.0

MIN_FIELD_W: float = 16.0
MIN_FIELD_H: float = 16.0
LINE_MIN_THICKNESS: float = 1.0  # line: the smaller side (thickness) floor

PAGE_1_NAME: str = "Страница 1"


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(value, hi))


class UnknownFieldTypeError(ValueError):
    """A stored field ``type`` is not in the closed catalog (design D3).

    A template containing such a field must not be opened — the editor has
    no way to draw or edit it. ``str(exc)`` is user-facing.
    """

    def __init__(self, type_value: object) -> None:
        super().__init__(f"неизвестный тип поля «{type_value}»")
        self.type_value = type_value


# ── Geometry (pure) ────────────────────────────────────────────────────────

def page_size(orientation: str) -> tuple[float, float]:
    """(width, height) of one A4 page for the orientation of the template."""
    if orientation == ORIENTATION_LANDSCAPE:
        return PAGE_HEIGHT_PT, PAGE_WIDTH_PT
    return PAGE_WIDTH_PT, PAGE_HEIGHT_PT


def page_origin(index: int, page_h: float) -> tuple[float, float]:
    """Scene origin (top-left) of page ``index`` in the vertical tape (D1)."""
    return (0.0, float(index) * (page_h + GUTTER_PT))


def tape_height(num_pages: int, page_h: float) -> float:
    """Total scene height of the tape: pages + the gutters between them."""
    if num_pages <= 0:
        return 0.0
    return num_pages * page_h + (num_pages - 1) * GUTTER_PT


def scene_to_page(
    x: float, y: float, page_w: float, page_h: float, num_pages: int
) -> tuple[int, float, float] | None:
    """Map a scene point to ``(page_index, local_x, local_y)`` of the tape.

    ``None`` — the point is in a gutter or outside the tape (D1): clicking
    there must not place a field, and dropping one must not move its page.
    The bottom edge of a page belongs to the page; the top edge of the next
    page (gutter end) belongs to the next page.
    """
    if num_pages <= 0 or x < 0.0 or x > page_w or y < 0.0:
        return None
    for i in range(num_pages):
        y0 = i * (page_h + GUTTER_PT)
        if y >= y0 and y <= y0 + page_h:
            return (i, x, y - y0)
        if y < y0:
            return None  # in the gutter above page i (or before the first)
    return None  # below the last page


def default_size(field_type: FieldType) -> tuple[float, float]:
    """Default (width, height) in points for a freshly placed field (D7)."""
    if field_type is FieldType.LABEL:
        return 72.0, 18.0
    if field_type is FieldType.TEXT:
        return 120.0, 18.0
    if field_type is FieldType.TEXTAREA:
        return 120.0, 54.0
    if field_type is FieldType.CHECKBOX:
        return 18.0, 18.0
    if field_type is FieldType.NUMBER:
        return 72.0, 18.0
    if field_type is FieldType.DROPDOWN:
        return 120.0, 18.0
    if field_type is FieldType.IMAGE:
        return 120.0, 120.0
    if field_type is FieldType.RECT:
        return 120.0, 72.0
    return 120.0, 2.0  # LINE (thickness is the smaller side: 2pt)


def default_content(field_type: FieldType) -> str:
    """Default content of a freshly placed field (A-playable)."""
    return "false" if field_type is FieldType.CHECKBOX else ""


def clamp_rect(
    x: float,
    y: float,
    w: float,
    h: float,
    page_w: float = PAGE_WIDTH_PT,
    page_h: float = PAGE_HEIGHT_PT,
    field_type: FieldType | None = None,
) -> tuple[float, float, float, float]:
    """Clamp a rect so it cannot leave the given (oriented) page.

    Works in the local coordinates of the page (D4): the caller converts
    between scene and page space. Size is clamped into
    ``[min, page]``; position is clamped so the whole rect stays within
    ``[0, page_w] x [0, page_h]`` (top-left pushed back from the edge).
    A line may be thinner than the usual 16pt minimum — its thickness (the
    smaller side) has a 1pt floor, the length keeps the 16pt minimum (D7).
    """
    if field_type is FieldType.LINE:
        if w >= h:
            w = _clamp(w, MIN_FIELD_W, page_w)
            h = _clamp(h, LINE_MIN_THICKNESS, page_h)
        else:
            w = _clamp(w, LINE_MIN_THICKNESS, page_w)
            h = _clamp(h, MIN_FIELD_W, page_h)
    else:
        w = _clamp(w, MIN_FIELD_W, page_w)
        h = _clamp(h, MIN_FIELD_H, page_h)
    x = _clamp(x, 0.0, max(0.0, page_w - w))
    y = _clamp(y, 0.0, max(0.0, page_h - h))
    return x, y, w, h


def place_field(
    field_type: FieldType,
    click: tuple[float, float],
    field_id: str | None = None,
    page_w: float = PAGE_WIDTH_PT,
    page_h: float = PAGE_HEIGHT_PT,
) -> "SheetField":
    """Build a field whose top-left sits at ``click`` (default size), clamped
    into the given page. The field order/z-order is decided by where the
    page appends it. ``id`` is a uuid4 hex string unless an id is passed."""
    cx, cy = click
    w, h = default_size(field_type)
    x, y, w, h = clamp_rect(cx, cy, w, h, page_w=page_w, page_h=page_h, field_type=field_type)
    return SheetField(
        id=field_id if field_id is not None else uuid4().hex,
        type=field_type,
        x=x,
        y=y,
        w=w,
        h=h,
        font_size=DEFAULT_FONT_SIZE,
        content=default_content(field_type),
    )


# ── Field JSON (de)serialization ───────────────────────────────────────────

def _opt_number(value, key: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"«{key}» must be a number")
    return float(value)


def _opt_options(value, field_id: str) -> list[str]:
    """Dropdown options: an ordered string list with no empty entries."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("«options» must be an array of strings")
    options: list[str] = []
    for option in value:
        if not isinstance(option, str):
            raise ValueError("dropdown option must be a string")
        if not option.strip():
            raise ValueError(f"dropdown field «{field_id}»: empty option is not allowed")
        options.append(option)
    return options


def _opt_image_id(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("«image_id» must be an integer or null")
    return value


# ── Model ──────────────────────────────────────────────────────────────────

@dataclass
class SheetField:
    """One layout object on a page. ``id`` is stable across save/reopen."""

    id: str
    type: FieldType
    x: float
    y: float
    w: float
    h: float
    font_size: float = DEFAULT_FONT_SIZE
    content: str = ""
    # A-playable, per-type extras (design D3):
    min_value: float | None = None   # NUMBER
    max_value: float | None = None   # NUMBER
    options: list[str] = dc_field(default_factory=list)  # DROPDOWN
    image_id: int | None = None      # IMAGE → images.id

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "type": self.type.value,
            "x": self.x,
            "y": self.y,
            "w": self.w,
            "h": self.h,
            "font_size": self.font_size,
            "content": self.content,
        }
        if self.type is FieldType.NUMBER:
            if self.min_value is not None:
                d["min"] = self.min_value
            if self.max_value is not None:
                d["max"] = self.max_value
        if self.type is FieldType.DROPDOWN:
            d["options"] = list(self.options)
        if self.type is FieldType.IMAGE:
            d["image_id"] = self.image_id
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "SheetField":
        if not isinstance(data, dict) or "id" not in data or "type" not in data:
            raise ValueError("field entry must be an object with 'id' and 'type'")
        field_id = str(data["id"])
        try:
            ftype = FieldType(data["type"])
        except ValueError as exc:
            raise UnknownFieldTypeError(data["type"]) from exc
        content = str(data.get("content", ""))
        if ftype is FieldType.NUMBER and content:
            content = content.replace(",", ".")  # design D3: ',' → '.'
            try:
                float(content)
            except ValueError as exc:
                raise ValueError(
                    f"number field «{field_id}»: {content!r} is not a number"
                ) from exc
        return cls(
            id=field_id,
            type=ftype,
            x=float(data["x"]),
            y=float(data["y"]),
            w=float(data["w"]),
            h=float(data["h"]),
            font_size=float(data.get("font_size", DEFAULT_FONT_SIZE)),
            content=content,
            min_value=_opt_number(data.get("min"), "min"),
            max_value=_opt_number(data.get("max"), "max"),
            options=_opt_options(data.get("options"), field_id),
            image_id=_opt_image_id(data.get("image_id")),
        )


@dataclass
class SheetPage:
    name: str = PAGE_1_NAME
    fields: list[SheetField] = dc_field(default_factory=list)


def _clamp_index(index: int, length: int) -> int:
    return max(0, min(index, length))


@dataclass
class SheetTemplate:
    """A character-sheet template: the vertical tape of named A4 pages."""

    name: str
    pages: list[SheetPage] = dc_field(default_factory=lambda: [SheetPage()])
    orientation: str = ORIENTATION_PORTRAIT
    schema_version: int = SCHEMA_VERSION
    id: int | None = None

    @property
    def page(self) -> SheetPage:
        """The first page. A-playable callers that mean "the current page"
        index ``pages`` explicitly (the VM tracks the current index)."""
        return self.pages[0]

    @property
    def page_size(self) -> tuple[float, float]:
        """(width, height) of every page (one orientation per template)."""
        return page_size(self.orientation)

    # -- fields (per page; order == z-order, later = on top) ----------------

    def add_field(
        self,
        field_type: FieldType,
        click: tuple[float, float],
        page_index: int = 0,
    ) -> SheetField:
        """Place a new field on page ``page_index`` (top-left at ``click``).

        Appending makes the new field the topmost one of that page. The id is
        assigned at creation and from then on never changes.
        """
        page = self.pages[page_index]
        f = place_field(field_type, click, page_w=self.page_size[0], page_h=self.page_size[1])
        page.fields.append(f)
        return f

    def page_of(self, field_id: str) -> int | None:
        """The index of the page holding the field (or None)."""
        for i, page in enumerate(self.pages):
            if any(f.id == field_id for f in page.fields):
                return i
        return None

    def get_field(self, field_id: str) -> SheetField | None:
        for page in self.pages:
            for f in page.fields:
                if f.id == field_id:
                    return f
        return None

    def remove_field(self, field_id: str) -> bool:
        for page in self.pages:
            for i, f in enumerate(page.fields):
                if f.id == field_id:
                    del page.fields[i]
                    return True
        return False

    # -- pages (A-playable: unlimited, named, ordered) ----------------------

    def add_page(self, after_index: int | None = None) -> SheetPage:
        """Insert a page after ``after_index`` (default: at the end)."""
        pos = len(self.pages)
        if after_index is not None:
            pos = _clamp_index(after_index + 1, len(self.pages))
        page = SheetPage(name=f"Страница {len(self.pages) + 1}")
        self.pages.insert(pos, page)
        return page

    def remove_page(self, index: int) -> None:
        """Remove page ``index``. The last remaining page cannot be removed."""
        if len(self.pages) <= 1:
            raise ValueError("нельзя удалить последнюю страницу")
        del self.pages[index]

    def move_page(self, from_index: int, to_index: int) -> None:
        """Reorder: move page ``from_index`` so it sits at ``to_index``.

        Both indices are clamped into ``[0, len-1]`` — out-of-range moves are
        a no-op, never a silent append/remove.
        """
        n = len(self.pages)
        if n <= 1:
            return
        src = _clamp_index(from_index, n - 1)
        dst = _clamp_index(to_index, n - 1)
        if src == dst:
            return
        page = self.pages.pop(src)
        self.pages.insert(dst, page)

    def rename_page(self, index: int, new_name: str) -> None:
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("имя страницы не может быть пустым")
        self.pages[index].name = new_name

    # -- orientation (one per template, D4) ----------------------------------

    def set_orientation(self, orientation: str) -> None:
        """Switch the whole template; fields are clamped, never scaled (D4)."""
        if orientation not in (ORIENTATION_PORTRAIT, ORIENTATION_LANDSCAPE):
            raise ValueError(f"unknown orientation: {orientation}")
        if orientation == self.orientation:
            return
        self.orientation = orientation
        page_w, page_h = self.page_size
        for page in self.pages:
            for f in page.fields:
                f.x, f.y, f.w, f.h = clamp_rect(
                    f.x, f.y, f.w, f.h, page_w=page_w, page_h=page_h, field_type=f.type
                )

    # -- pages JSON round-trip (design D3: v2 shape) ------------------------

    def to_pages_json(self) -> str:
        """Serialize to the ``pages`` column value (always v2 shape)."""
        pages = [
            {"name": page.name, "fields": [f.to_dict() for f in page.fields]}
            for page in self.pages
        ]
        return json.dumps(pages, ensure_ascii=False)

    @classmethod
    def parse_template(
        cls,
        pages_json: str,
        *,
        name: str,
        orientation: str = ORIENTATION_PORTRAIT,
        schema_version: int = SCHEMA_VERSION,
        id: int | None = None,
    ) -> "SheetTemplate":
        """Build a template from a stored ``pages`` value (v1 or v2).

        v1 rows (one page object without ``name``) normalize to a single page
        «Страница 1» in memory without loss (A1 data is unchanged on disk
        until the next Save, which writes v2). Unknown field types raise
        :class:`UnknownFieldTypeError`; anything structurally corrupt raises
        ``ValueError`` — a corrupt row must surface as an error, never be
        handed to the editor as a layout.
        """
        try:
            data = json.loads(pages_json)
            if not isinstance(data, list):
                raise ValueError("pages must be a JSON array")
            pages: list[SheetPage] = []
            for i, page_data in enumerate(data):
                if not isinstance(page_data, dict):
                    raise ValueError("page must be an object")
                if not isinstance(page_data.get("fields"), list):
                    raise ValueError("page must be an object with a 'fields' list")
                pname = page_data.get("name")
                if not isinstance(pname, str) or not pname.strip():
                    pname = f"Страница {i + 1}"
                fields = [SheetField.from_dict(fd) for fd in page_data["fields"]]
                pages.append(SheetPage(name=pname, fields=fields))
            if not pages:
                pages = [SheetPage()]
        except ValueError:
            raise
        except Exception as exc:  # bad JSON / bad field entry
            raise ValueError(f"invalid character-sheet pages: {exc}") from exc
        return cls(
            name=name,
            pages=pages,
            orientation=orientation,
            schema_version=schema_version,
            id=id,
        )

    # A1-era alias: existing callers (service, older tests) use this name.
    from_pages_json = parse_template


EMPTY_PAGES_JSON: str = json.dumps(
    [{"name": PAGE_1_NAME, "fields": []}], ensure_ascii=False
)


# ── Image-references inside pages JSON (design D6, used by ImageStore) ─────

def iter_sheet_image_ids(pages_json: str) -> list[int]:
    """All ``images.id`` references of the image fields of one template.

    Pure scan of the stored ``pages`` JSON (may be called on raw column
    values during GC, not only on parsed templates). Garbage JSON yields
    nothing rather than raising.
    """
    try:
        data = json.loads(pages_json)
    except Exception:
        return []
    ids: list[int] = []
    if not isinstance(data, list):
        return ids
    for page in data:
        if not isinstance(page, dict):
            continue
        for fd in page.get("fields") or []:
            if not isinstance(fd, dict) or fd.get("type") != "image":
                continue
            value = fd.get("image_id")
            if isinstance(value, int) and not isinstance(value, bool):
                ids.append(value)
    return ids


def null_sheet_image_ids(pages_json: str, image_id: int) -> str:
    """Return the JSON with every image field referencing ``image_id`` nulled.

    Used when an ``images`` row is dropped: the stored layouts are cleared of
    the dangling reference. Input without the reference is returned unchanged
    (including unparseable garbage — nothing to fix there).
    """
    try:
        data = json.loads(pages_json)
    except Exception:
        return pages_json
    if not isinstance(data, list):
        return pages_json
    for page in data:
        if not isinstance(page, dict):
            continue
        for fd in page.get("fields") or []:
            if (
                isinstance(fd, dict)
                and fd.get("type") == "image"
                and fd.get("image_id") == image_id
            ):
                fd["image_id"] = None
    return json.dumps(data, ensure_ascii=False)
