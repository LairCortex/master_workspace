"""``image://dialog/<key>`` — in-memory pixmaps for ImageViewerDialog.

Registered once on the shared engine next to ``image://sheet``. Keys live
only for an open viewer: put on open/exec, clear in ``done()``. Sync
GUI-thread lookup of already-decoded ``QPixmap`` — no disk, no DB.
"""
from __future__ import annotations

from PySide6.QtGui import QPixmap
from PySide6.QtQuick import QQuickImageProvider

DIALOG_IMAGE_PROVIDER_ID: str = "dialog"


class DialogImageProvider(QQuickImageProvider):
    """key → QPixmap dictionary. Engine-owned once registered."""

    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.ImageType.Pixmap)
        self._pixmaps: dict[str, QPixmap] = {}

    def put(self, key: str, pixmap: QPixmap) -> None:
        self._pixmaps[key] = pixmap

    def clear(self, key: str) -> None:
        self._pixmaps.pop(key, None)

    def requestPixmap(self, image_id: str, size, requested_size):  # Qt API
        pixmap = self._pixmaps.get(image_id)
        if pixmap is None or pixmap.isNull():
            return QPixmap()
        if size is not None and hasattr(size, "setWidth"):
            size.setWidth(pixmap.width())
            size.setHeight(pixmap.height())
        return pixmap


def dialog_image_provider():
    from app.presentation.qml.engine import qml_engine

    engine = qml_engine()
    if engine is None:
        return None
    return engine.imageProvider(DIALOG_IMAGE_PROVIDER_ID)


def put_dialog_pixmap(key: str, pixmap: QPixmap) -> None:
    provider = dialog_image_provider()
    if provider is not None:
        provider.put(key, pixmap)


def clear_dialog_pixmap(key: str) -> None:
    provider = dialog_image_provider()
    if provider is not None:
        provider.clear(key)


def register_dialog_image_provider(engine) -> None:
    if engine.imageProvider(DIALOG_IMAGE_PROVIDER_ID) is not None:
        return
    engine.addImageProvider(DIALOG_IMAGE_PROVIDER_ID, DialogImageProvider())
