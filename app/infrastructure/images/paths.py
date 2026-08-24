"""Path resolution for file-based image storage.

Every path is derived deterministically from a game's ``images/`` directory
and a content hash (sha256) — no path is ever persisted in the database
(design D2). Files are laid out as::

    images/<hash[:2]>/<hash>.<ext>            original
    images/<hash[:2]>/<hash>.preview.webp     preview

The 2-character subdirectory avoids thousands of files in one flat directory.
"""
from __future__ import annotations

from pathlib import Path

PREVIEW_SUFFIX = ".preview.webp"


def hash_subdir(image_dir: Path, sha256: str) -> Path:
    """Return the 2-character subdirectory for a given hash."""
    return image_dir / sha256[:2]


def original_path(image_dir: Path, sha256: str, ext: str) -> Path:
    """Deterministic path for the original image file."""
    return hash_subdir(image_dir, sha256) / f"{sha256}.{ext}"


def preview_path(image_dir: Path, sha256: str) -> Path:
    """Deterministic path for the preview (512px WebP) file."""
    return hash_subdir(image_dir, sha256) / f"{sha256}{PREVIEW_SUFFIX}"
