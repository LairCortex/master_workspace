"""Image utilities — load previews/originals from file storage (design D10).

Base64-in-DB is gone (see openspec/changes/file-based-image-storage): images
are addressed by sha256 on disk (``app.infrastructure.images``). ``set_image_dir``
mirrors the per-game global-state pattern already used by
``date_utils.set_custom_months`` — set once in ``Application.start()``, read
by every view without DB/DI plumbing. Resolution needs an entity's
``image_ref`` (the eager-loaded ``ImageModel`` row, see ``db/models.py``) —
the view never assembles a path itself, only forwards the entity.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap

from app.infrastructure.images.paths import original_path, preview_path

logger = logging.getLogger("app.presentation.image_utils")

# Shared mutable state — set once on game load, used everywhere (mirrors date_utils).
_image_dir: Path | None = None


def set_image_dir(path: str | Path | None) -> None:
    """Set the current game's ``images/`` directory (None when no game is open)."""
    global _image_dir
    _image_dir = Path(path) if path is not None else None


def get_image_dir() -> Path | None:
    return _image_dir


def resolve_preview_path(entity: object) -> Path | None:
    """Deterministic preview-file path (design D2) for an entity's image, or None."""
    img = getattr(entity, "image_ref", None)
    if img is None or _image_dir is None:
        return None
    return preview_path(_image_dir, img.sha256)


def resolve_original_path(entity: object) -> Path | None:
    """Deterministic original-file path (design D2) for an entity's image, or None."""
    img = getattr(entity, "image_ref", None)
    if img is None or _image_dir is None:
        return None
    return original_path(_image_dir, img.sha256, img.ext)


def load_preview(path: str | Path | None, slot_size: int) -> QPixmap:
    """Load a preview file (≤512px WebP) and fit it into ``slot_size``.

    Null-safe: missing path/file/corrupt content → empty ``QPixmap()`` + log.
    """
    return _load(path, slot_size)


def load_original(path: str | Path | None) -> QPixmap:
    """Load the full-size original image file. Null-safe (see ``load_preview``)."""
    return _load(path, None)


def load_entity_preview(entity: object, slot_size: int) -> QPixmap:
    """Convenience: resolve + load an entity's preview in one call."""
    return load_preview(resolve_preview_path(entity), slot_size)


def load_entity_original(entity: object) -> QPixmap:
    """Convenience: resolve + load an entity's full-size original in one call."""
    return load_original(resolve_original_path(entity))


def _load(path: str | Path | None, max_size: int | None) -> QPixmap:
    if not path:
        return QPixmap()
    p = Path(path)
    if not p.exists():
        logger.warning("Image file missing: %s", p)
        return QPixmap()
    img = QImage(str(p))
    if img.isNull():
        logger.warning("Failed to decode image file: %s", p)
        return QPixmap()
    if max_size is not None:
        img = _fit_image(img, max_size)
    return QPixmap.fromImage(img)


def _fit_image(img: QImage, max_size: int) -> QImage:
    """Scale image to fit within max_size x max_size, keeping aspect ratio."""
    if img.width() <= max_size and img.height() <= max_size:
        return img
    return img.scaled(
        max_size, max_size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
