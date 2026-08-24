"""Tests for the image path resolver — TDD."""
from __future__ import annotations

from pathlib import Path

from app.infrastructure.images.paths import original_path, preview_path


class TestOriginalPath:
    def test_two_letter_subdirectory(self):
        p = original_path(Path("/game/images"), "abcdef1234", "png")
        assert p.parent == Path("/game/images/ab")

    def test_filename_is_hash_and_extension(self):
        p = original_path(Path("/game/images"), "abcdef1234", "png")
        assert p.name == "abcdef1234.png"

    def test_extension_reflects_real_format(self):
        p = original_path(Path("/game/images"), "abcdef1234", "jpeg")
        assert p.suffix == ".jpeg"

    def test_deterministic(self):
        p1 = original_path(Path("/game/images"), "abcdef1234", "png")
        p2 = original_path(Path("/game/images"), "abcdef1234", "png")
        assert p1 == p2


class TestPreviewPath:
    def test_two_letter_subdirectory(self):
        p = preview_path(Path("/game/images"), "abcdef1234")
        assert p.parent == Path("/game/images/ab")

    def test_filename_pattern(self):
        p = preview_path(Path("/game/images"), "abcdef1234")
        assert p.name == "abcdef1234.preview.webp"

    def test_deterministic(self):
        p1 = preview_path(Path("/game/images"), "abcdef1234")
        p2 = preview_path(Path("/game/images"), "abcdef1234")
        assert p1 == p2

    def test_different_hash_different_path(self):
        p1 = preview_path(Path("/game/images"), "aaaa1111")
        p2 = preview_path(Path("/game/images"), "bbbb2222")
        assert p1 != p2
