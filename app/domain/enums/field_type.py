"""Field types available on a character-sheet page (closed catalog, A-playable).

- LABEL: a static caption (just a line + font size, no box border).
- TEXT: a single-line input box.
- TEXTAREA: a multi-line input box.
- CHECKBOX: an on/off square without text (content: "true"/"false").
- NUMBER: a fractional number (content: decimal string, '.' in JSON;
  optional min/max bounds).
- DROPDOWN: a single choice from an ordered list of options.
- IMAGE: a frame holding an ImageStore reference (``image_id``).
- RECT: a decorative border. No data.
- LINE: a decorative axis line; width > height → horizontal, otherwise
  vertical (thickness is the smaller side).
"""
from __future__ import annotations

from enum import Enum


class FieldType(Enum):
    """Kinds of layout objects drawn on a sheet page."""

    LABEL = "label"
    TEXT = "text"
    TEXTAREA = "textarea"
    CHECKBOX = "checkbox"
    NUMBER = "number"
    DROPDOWN = "dropdown"
    IMAGE = "image"
    RECT = "rect"
    LINE = "line"
