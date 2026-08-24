"""Tests for .nri export v2: game.db + images/** + meta.json (design D9)."""
from __future__ import annotations

import zipfile

import pytest

from app.infrastructure.db.game_manager import create_game, export_game, read_archive_meta


@pytest.fixture
def games_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.infrastructure.db.game_manager._resolve_games_dir",
        lambda: tmp_path / "games",
    )
    return tmp_path / "games"


class TestExportWithImages:
    def test_archive_contains_db_images_and_meta(self, games_dir, tmp_path):
        db_path = create_game("WithImages")
        db_path.write_bytes(b"sqlite data")
        images_dir = db_path.parent / "images"
        (images_dir / "ab").mkdir(parents=True)
        (images_dir / "ab" / "abcdef.png").write_bytes(b"orig-bytes")
        (images_dir / "ab" / "abcdef.preview.webp").write_bytes(b"preview-bytes")

        dest = tmp_path / "export.nri"
        export_game(str(db_path), dest)

        with zipfile.ZipFile(dest) as zf:
            names = set(zf.namelist())
            assert "game.db" in names
            assert "meta.json" in names
            assert "images/ab/abcdef.png" in names
            assert "images/ab/abcdef.preview.webp" in names
            assert zf.read("images/ab/abcdef.png") == b"orig-bytes"

    def test_meta_has_archive_version_2(self, games_dir, tmp_path):
        db_path = create_game("MetaV2")
        db_path.write_bytes(b"data")
        dest = tmp_path / "meta.nri"
        export_game(str(db_path), dest)

        meta = read_archive_meta(dest)
        assert meta["archive_version"] == 2
        assert meta["game_name"] == "MetaV2"
        assert "version" in meta
        assert "exported_at" in meta
        assert "db_size_bytes" in meta


class TestExportWithoutImages:
    def test_empty_images_dir_not_required_in_archive(self, games_dir, tmp_path):
        db_path = create_game("NoImages")
        db_path.write_bytes(b"data")
        dest = tmp_path / "noimg.nri"

        export_game(str(db_path), dest)

        with zipfile.ZipFile(dest) as zf:
            names = zf.namelist()
            assert "game.db" in names
            assert "meta.json" in names
            assert not any(n.startswith("images/") for n in names)

        meta = read_archive_meta(dest)
        assert meta["archive_version"] == 2

    def test_missing_images_directory_does_not_fail(self, games_dir, tmp_path):
        db_path = create_game("NoImagesDirAtAll")
        db_path.write_bytes(b"data")
        import shutil
        shutil.rmtree(db_path.parent / "images")

        dest = tmp_path / "noimgdir.nri"
        export_game(str(db_path), dest)  # must not raise
        assert dest.exists()


class TestExportErrors:
    def test_raises_on_missing_db(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            export_game(tmp_path / "nowhere" / "game.db", tmp_path / "out.nri")
