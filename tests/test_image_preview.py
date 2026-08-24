"""Tests for the preview generator — TDD."""
from __future__ import annotations

import hashlib

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.infrastructure.images.preview import PREVIEW_MAX_SIZE, generate_preview


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_png_bytes(w: int, h: int) -> bytes:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(Qt.GlobalColor.blue)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(data.data())


class TestGeneratePreview:
    def test_output_is_webp(self, qapp):
        original = _make_png_bytes(800, 600)
        preview = generate_preview(original)
        img = QImage()
        assert img.loadFromData(QByteArray(preview), "WEBP")

    def test_max_side_capped(self, qapp):
        original = _make_png_bytes(2000, 1000)
        preview = generate_preview(original)
        img = QImage()
        img.loadFromData(QByteArray(preview))
        assert img.width() <= PREVIEW_MAX_SIZE
        assert img.height() <= PREVIEW_MAX_SIZE

    def test_small_image_not_upscaled(self, qapp):
        original = _make_png_bytes(50, 40)
        preview = generate_preview(original)
        img = QImage()
        img.loadFromData(QByteArray(preview))
        assert img.width() == 50
        assert img.height() == 40

    def test_deterministic_same_hash(self, qapp):
        original = _make_png_bytes(300, 300)
        preview1 = generate_preview(original)
        preview2 = generate_preview(original)
        assert hashlib.sha256(preview1).hexdigest() == hashlib.sha256(preview2).hexdigest()

    def test_invalid_data_raises(self, qapp):
        with pytest.raises(ValueError):
            generate_preview(b"not an image")

    def test_encode_failure_raises(self, qapp, monkeypatch):
        original = _make_png_bytes(10, 10)
        monkeypatch.setattr(QImage, "save", lambda *a, **k: False)
        with pytest.raises(ValueError):
            generate_preview(original)

    def test_keeps_aspect_ratio(self, qapp):
        original = _make_png_bytes(2000, 1000)
        preview = generate_preview(original)
        img = QImage()
        img.loadFromData(QByteArray(preview))
        ratio_orig = 2000 / 1000
        ratio_result = img.width() / img.height()
        assert abs(ratio_orig - ratio_result) < 0.05
