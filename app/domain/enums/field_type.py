from enum import Enum


class FieldType(Enum):
    """Nine field types of a character sheet template (v1)."""
    NUMBER = "number"
    SHORT_TEXT = "short_text"
    LONG_TEXT = "long_text"
    CHECKBOX = "checkbox"
    DROPDOWN = "dropdown"
    DATE = "date"
    PORTRAIT = "portrait"
    HEADING = "heading"
    STATIC_TEXT = "static_text"


#: field types rendered as a fillable PDF form field (all others are static)
INTERACTIVE_FIELDS = frozenset({
    FieldType.NUMBER,
    FieldType.SHORT_TEXT,
    FieldType.LONG_TEXT,
    FieldType.CHECKBOX,
    FieldType.DROPDOWN,
    FieldType.DATE,
})
