"""Tests for file-based image_utils (design D10, task 5.1)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.presentation.utils import image_utils


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _write_png(path: Path, size: int = 20, color=Qt.GlobalColor.red) -> None:
    img = QImage(size, size, QImage.Format.Format_RGB32)
    img.fill(color)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    path.write_bytes(bytes(data.data()))


class TestLoadPreview:
    def test_present_file_loads(self, qapp, tmp_path):
        p = tmp_path / "preview.png"
        _write_png(p, size=800)
        pm = image_utils.load_preview(p, slot_size=100)
        assert not pm.isNull()
        assert pm.width() <= 100 and pm.height() <= 100

    def test_missing_path_is_null_safe(self, qapp, tmp_path):
        pm = image_utils.load_preview(tmp_path / "nope.png", slot_size=100)
        assert pm.isNull()

    def test_none_path_is_null_safe(self, qapp):
        assert image_utils.load_preview(None, slot_size=100).isNull()

    def test_empty_string_path_is_null_safe(self, qapp):
        assert image_utils.load_preview("", slot_size=100).isNull()

    def test_corrupt_file_is_null_safe(self, qapp, tmp_path):
        p = tmp_path / "corrupt.png"
        p.write_bytes(b"not an image")
        assert image_utils.load_preview(p, slot_size=100).isNull()

    def test_small_image_not_upscaled_beyond_original(self, qapp, tmp_path):
        p = tmp_path / "small.png"
        _write_png(p, size=10)
        pm = image_utils.load_preview(p, slot_size=100)
        assert pm.width() == 10 and pm.height() == 10


class TestLoadOriginal:
    def test_present_file_loads_full_size(self, qapp, tmp_path):
        p = tmp_path / "original.png"
        _write_png(p, size=600)
        pm = image_utils.load_original(p)
        assert not pm.isNull()
        assert pm.width() == 600 and pm.height() == 600

    def test_missing_path_is_null_safe(self, qapp, tmp_path):
        assert image_utils.load_original(tmp_path / "nope.png").isNull()

    def test_none_path_is_null_safe(self, qapp):
        assert image_utils.load_original(None).isNull()

    def test_corrupt_file_is_null_safe(self, qapp, tmp_path):
        p = tmp_path / "corrupt.png"
        p.write_bytes(b"garbage")
        assert image_utils.load_original(p).isNull()


class TestImageDirGlobalState:
    def teardown_method(self):
        image_utils.set_image_dir(None)

    def test_set_and_get(self, tmp_path):
        image_utils.set_image_dir(tmp_path)
        assert image_utils.get_image_dir() == tmp_path

    def test_set_none_clears(self, tmp_path):
        image_utils.set_image_dir(tmp_path)
        image_utils.set_image_dir(None)
        assert image_utils.get_image_dir() is None

    def test_accepts_str(self, tmp_path):
        image_utils.set_image_dir(str(tmp_path))
        assert image_utils.get_image_dir() == tmp_path


class TestResolvePaths:
    def teardown_method(self):
        image_utils.set_image_dir(None)

    def _entity(self, sha256="ab" * 32, ext="png", has_image=True):
        image_ref = SimpleNamespace(sha256=sha256, ext=ext) if has_image else None
        return SimpleNamespace(image_ref=image_ref)

    def test_resolve_preview_path(self, tmp_path):
        image_utils.set_image_dir(tmp_path)
        entity = self._entity()
        p = image_utils.resolve_preview_path(entity)
        assert p == tmp_path / "ab" / f"{'ab' * 32}.preview.webp"

    def test_resolve_original_path(self, tmp_path):
        image_utils.set_image_dir(tmp_path)
        entity = self._entity(ext="jpeg")
        p = image_utils.resolve_original_path(entity)
        assert p == tmp_path / "ab" / f"{'ab' * 32}.jpeg"

    def test_resolve_preview_path_no_image_ref(self, tmp_path):
        image_utils.set_image_dir(tmp_path)
        entity = self._entity(has_image=False)
        assert image_utils.resolve_preview_path(entity) is None

    def test_resolve_original_path_no_image_ref(self, tmp_path):
        image_utils.set_image_dir(tmp_path)
        entity = self._entity(has_image=False)
        assert image_utils.resolve_original_path(entity) is None

    def test_resolve_preview_path_no_image_dir_set(self):
        entity = self._entity()
        assert image_utils.resolve_preview_path(entity) is None

    def test_resolve_original_path_no_image_dir_set(self):
        entity = self._entity()
        assert image_utils.resolve_original_path(entity) is None

    def test_entity_missing_image_ref_attribute_entirely(self, tmp_path):
        image_utils.set_image_dir(tmp_path)
        assert image_utils.resolve_preview_path(SimpleNamespace()) is None
        assert image_utils.resolve_original_path(SimpleNamespace()) is None


class TestLoadEntityConvenience:
    def teardown_method(self):
        image_utils.set_image_dir(None)

    def test_load_entity_preview_end_to_end(self, qapp, tmp_path):
        image_utils.set_image_dir(tmp_path)
        sha = "cd" * 32
        original = tmp_path / "cd" / f"{sha}.png"
        original.parent.mkdir(parents=True)
        preview = tmp_path / "cd" / f"{sha}.preview.webp"
        _write_png(preview, size=50)  # content format doesn't matter for this test
        entity = SimpleNamespace(image_ref=SimpleNamespace(sha256=sha, ext="png"))

        pm = image_utils.load_entity_preview(entity, slot_size=24)
        assert not pm.isNull()
        assert pm.width() <= 24 and pm.height() <= 24

    def test_load_entity_original_end_to_end(self, qapp, tmp_path):
        image_utils.set_image_dir(tmp_path)
        sha = "ef" * 32
        original = tmp_path / "ef" / f"{sha}.png"
        original.parent.mkdir(parents=True)
        _write_png(original, size=300)
        entity = SimpleNamespace(image_ref=SimpleNamespace(sha256=sha, ext="png"))

        pm = image_utils.load_entity_original(entity)
        assert not pm.isNull()
        assert pm.width() == 300

    def test_load_entity_preview_no_image(self, qapp, tmp_path):
        image_utils.set_image_dir(tmp_path)
        entity = SimpleNamespace(image_ref=None)
        assert image_utils.load_entity_preview(entity, slot_size=24).isNull()

    def test_load_entity_original_no_image(self, qapp, tmp_path):
        image_utils.set_image_dir(tmp_path)
        entity = SimpleNamespace(image_ref=None)
        assert image_utils.load_entity_original(entity).isNull()
