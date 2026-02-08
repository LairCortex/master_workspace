"""Image utilities — load, resize, encode/decode base64 for DB storage."""
from __future__ import annotations

import base64

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage, QPixmap


def load_and_encode(file_path: str, max_size: int = 1000) -> str:
    """Load image from disk, resize to fit max_size x max_size, return base64 string."""
    img = QImage(file_path)
    if img.isNull():
        raise ValueError(f"Cannot load image: {file_path}")
    img = _fit_image(img, max_size)
    return _image_to_base64(img)


def base64_to_pixmap(b64: str, max_size: int = 1000) -> QPixmap:
    """Decode base64 string to QPixmap, scaled to fit max_size."""
    if not b64 or not isinstance(b64, str):
        return QPixmap()
    try:
        data = base64.b64decode(b64)
    except Exception:
        return QPixmap()
    img = QImage()
    img.loadFromData(QByteArray(data))
    if img.isNull():
        return QPixmap()
    img = _fit_image(img, max_size)
    return QPixmap.fromImage(img)


def base64_to_thumbnail(b64: str, size: int = 100) -> QPixmap:
    """Decode base64 string to a square thumbnail QPixmap."""
    return base64_to_pixmap(b64, max_size=size)


def _fit_image(img: QImage, max_size: int) -> QImage:
    """Scale image to fit within max_size x max_size, keeping aspect ratio."""
    if img.width() <= max_size and img.height() <= max_size:
        return img
    return img.scaled(
        max_size, max_size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _image_to_base64(img: QImage) -> str:
    """Convert QImage to base64-encoded PNG string."""
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return base64.b64encode(ba.data()).decode("ascii")
