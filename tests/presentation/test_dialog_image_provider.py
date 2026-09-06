"""In-memory ``image://dialog/<key>`` provider (R3 pack 1, tasks 2.1–2.2)."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtQuick import QQuickImageProvider

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.dialog_image_provider import (
    DIALOG_IMAGE_PROVIDER_ID,
    DialogImageProvider,
    clear_dialog_pixmap,
    dialog_image_provider,
    put_dialog_pixmap,
    register_dialog_image_provider,
)
from app.presentation.qml.sheet_image_provider import SHEET_IMAGE_PROVIDER_ID
from app.presentation.theme import get_default_theme


def _pixmap(color=Qt.GlobalColor.red) -> QPixmap:
    img = QImage(8, 8, QImage.Format.Format_RGB32)
    img.fill(color)
    return QPixmap.fromImage(img)


def test_dialog_provider_put_get_clear_second_key_isolated():
    provider = DialogImageProvider()
    provider.put("one", _pixmap(Qt.GlobalColor.red))
    provider.put("two", _pixmap(Qt.GlobalColor.blue))
    one = provider.requestPixmap("one", QSize(), QSize()).toImage().pixelColor(0, 0)
    two = provider.requestPixmap("two", QSize(), QSize()).toImage().pixelColor(0, 0)
    assert one != two
    provider.clear("one")
    assert provider.requestPixmap("one", QSize(), QSize()).isNull()
    assert not provider.requestPixmap("two", QSize(), QSize()).isNull()


def test_dialog_provider_unknown_and_null_pixmap():
    provider = DialogImageProvider()
    assert provider.requestPixmap("missing", QSize(), QSize()).isNull()
    provider.put("empty", QPixmap())
    assert provider.requestPixmap("empty", QSize(), QSize()).isNull()


def test_dialog_provider_fills_size():
    provider = DialogImageProvider()
    provider.put("k", _pixmap())
    size = QSize()
    provider.requestPixmap("k", size, QSize())
    assert size.width() == 8
    assert size.height() == 8
    assert provider.requestPixmap("k", None, QSize()).width() == 8


def test_shell_registers_dialog_provider_beside_sheet(qapp):
    engine = setup_qml_shell(qapp, get_default_theme())
    provider = engine.imageProvider(DIALOG_IMAGE_PROVIDER_ID)
    assert isinstance(provider, QQuickImageProvider)
    assert engine.imageProvider(SHEET_IMAGE_PROVIDER_ID) is not None
    register_dialog_image_provider(engine)
    assert engine.imageProvider(DIALOG_IMAGE_PROVIDER_ID) is provider
    put_dialog_pixmap("live", _pixmap(Qt.GlobalColor.green))
    assert not dialog_image_provider().requestPixmap("live", QSize(), QSize()).isNull()
    clear_dialog_pixmap("live")
    assert dialog_image_provider().requestPixmap("live", QSize(), QSize()).isNull()


def test_helpers_noop_when_provider_missing(monkeypatch):
    import app.presentation.qml.dialog_image_provider as mod

    monkeypatch.setattr(mod, "dialog_image_provider", lambda: None)
    mod.put_dialog_pixmap("x", _pixmap())
    mod.clear_dialog_pixmap("x")


def test_dialog_image_provider_accessor_without_engine(monkeypatch):
    import app.presentation.qml.engine as engine_mod

    monkeypatch.setattr(engine_mod, "_engine", None)
    assert dialog_image_provider() is None
