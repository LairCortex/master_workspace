"""Preview generation — fixed pipeline: (original_bytes) -> preview_bytes.

Constants are frozen (design D5): 512px max side, WebP lossy q80. Preview is
never recomputed with different parameters — a future constant change is a
dedicated migration, not a runtime toggle.
"""
from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage

PREVIEW_MAX_SIZE = 512
PREVIEW_FORMAT = "WEBP"
PREVIEW_QUALITY = 80


def generate_preview(original_bytes: bytes) -> bytes:
    """Decode ``original_bytes`` and encode a 512px WebP (q80) preview.

    Raises ``ValueError`` if the input cannot be decoded as an image.
    """
    img = QImage()
    if not img.loadFromData(QByteArray(original_bytes)) or img.isNull():
        raise ValueError("Cannot decode image data for preview generation")

    if img.width() > PREVIEW_MAX_SIZE or img.height() > PREVIEW_MAX_SIZE:
        img = img.scaled(
            PREVIEW_MAX_SIZE, PREVIEW_MAX_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    buf_data = QByteArray()
    buf = QBuffer(buf_data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    ok = img.save(buf, PREVIEW_FORMAT, PREVIEW_QUALITY)
    buf.close()
    if not ok:
        raise ValueError("Failed to encode preview image")
    return bytes(buf_data.data())
