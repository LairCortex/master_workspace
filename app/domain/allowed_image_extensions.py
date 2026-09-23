"""Domain whitelist of accepted image file extensions.

The same six extensions are the import/pick contract in four places (audit
A5): the xlsx image column check, the entity-card pick filter, the sheet
fill picker and the sheet editor picker. One constant, so the next format
is a one-line change; the tuple order is the order file dialogs offer the
patterns in.
"""
from __future__ import annotations

#: Lower-case file suffixes accepted for entity images.
ALLOWED_IMAGE_EXTENSIONS: tuple[str, ...] = (
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".gif",
    ".webp",
)
