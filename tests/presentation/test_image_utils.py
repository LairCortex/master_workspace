"""Tests for image utilities — TDD."""
from __future__ import annotations

import base64

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.presentation.utils.image_utils import (
    _fit_image,
    _image_to_base64,
    base64_to_pixmap,
    base64_to_thumbnail,
    load_and_encode,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_test_image(w: int = 200, h: int = 150) -> QImage:
    """Create a solid-color test QImage."""
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(Qt.GlobalColor.red)
    return img


def _save_test_image(path: str, w: int = 200, h: int = 150) -> None:
    img = _make_test_image(w, h)
    img.save(path, "PNG")


class TestFitImage:
    def test_no_resize_if_small(self, qapp):
        img = _make_test_image(50, 50)
        result = _fit_image(img, 100)
        assert result.width() == 50
        assert result.height() == 50

    def test_resize_if_too_wide(self, qapp):
        img = _make_test_image(2000, 1000)
        result = _fit_image(img, 500)
        assert result.width() <= 500
        assert result.height() <= 500

    def test_resize_if_too_tall(self, qapp):
        img = _make_test_image(500, 2000)
        result = _fit_image(img, 500)
        assert result.width() <= 500
        assert result.height() <= 500

    def test_keeps_aspect_ratio(self, qapp):
        img = _make_test_image(2000, 1000)
        result = _fit_image(img, 500)
        ratio_orig = 2000 / 1000
        ratio_result = result.width() / result.height()
        assert abs(ratio_orig - ratio_result) < 0.1


class TestImageToBase64:
    def test_returns_valid_base64(self, qapp):
        img = _make_test_image(10, 10)
        b64 = _image_to_base64(img)
        assert isinstance(b64, str)
        # Should be valid base64
        decoded = base64.b64decode(b64)
        assert len(decoded) > 0

    def test_roundtrip(self, qapp):
        img = _make_test_image(20, 15)
        b64 = _image_to_base64(img)
        pm = base64_to_pixmap(b64, max_size=1000)
        assert not pm.isNull()
        assert pm.width() == 20
        assert pm.height() == 15


class TestLoadAndEncode:
    def test_loads_file(self, qapp, tmp_path):
        path = str(tmp_path / "test.png")
        _save_test_image(path, 100, 80)
        b64 = load_and_encode(path, max_size=1000)
        assert isinstance(b64, str)
        assert len(b64) > 0

    def test_resizes_large_image(self, qapp, tmp_path):
        path = str(tmp_path / "big.png")
        _save_test_image(path, 2000, 1500)
        b64 = load_and_encode(path, max_size=500)
        pm = base64_to_pixmap(b64, max_size=10000)
        assert pm.width() <= 500
        assert pm.height() <= 500

    def test_raises_on_invalid_file(self, qapp):
        with pytest.raises(ValueError):
            load_and_encode("/nonexistent/path.png")


class TestBase64ToPixmap:
    def test_valid_data(self, qapp):
        img = _make_test_image(30, 30)
        b64 = _image_to_base64(img)
        pm = base64_to_pixmap(b64, max_size=100)
        assert not pm.isNull()
        assert pm.width() == 30

    def test_empty_string(self, qapp):
        pm = base64_to_pixmap("", max_size=100)
        assert pm.isNull()

    def test_respects_max_size(self, qapp):
        img = _make_test_image(500, 500)
        b64 = _image_to_base64(img)
        pm = base64_to_pixmap(b64, max_size=50)
        assert pm.width() <= 50
        assert pm.height() <= 50


class TestBase64ToThumbnail:
    def test_thumbnail_size(self, qapp):
        img = _make_test_image(800, 600)
        b64 = _image_to_base64(img)
        pm = base64_to_thumbnail(b64, size=100)
        assert pm.width() <= 100
        assert pm.height() <= 100
        assert not pm.isNull()
