"""Tests for atomic, sha256-verified .nri import (design D9) — v2 and v1 archives."""
from __future__ import annotations

import hashlib
import json
import zipfile

import pytest

from app.infrastructure.db.game_manager import (
    create_game,
    delete_game,
    export_game,
    import_game,
    list_games,
)


@pytest.fixture
def games_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.infrastructure.db.game_manager._resolve_games_dir",
        lambda: tmp_path / "games",
    )
    return tmp_path / "games"


def _build_v2_archive(path, game_name: str, image_content: bytes = b"orig-bytes") -> str:
    """Build a valid v2 archive with one correctly-hashed image file."""
    sha = hashlib.sha256(image_content).hexdigest()
    meta = {
        "game_name": game_name,
        "version": "0.15.0",
        "archive_version": 2,
        "exported_at": "2024-01-01T00:00:00",
        "db_size_bytes": 4,
    }
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("game.db", b"sqlite-content")
        zf.writestr(f"images/{sha[:2]}/{sha}.png", image_content)
        zf.writestr("meta.json", json.dumps(meta))
    return sha


class TestSuccessfulImportV2:
    def test_import_creates_game_with_images(self, games_dir, tmp_path):
        archive = tmp_path / "good.nri"
        sha = _build_v2_archive(archive, "GoodGame")

        result = import_game(archive)

        assert result.name == "game.db"
        assert result.exists()
        assert result.read_bytes() == b"sqlite-content"
        img_file = result.parent / "images" / sha[:2] / f"{sha}.png"
        assert img_file.exists()
        assert hashlib.sha256(img_file.read_bytes()).hexdigest() == sha

    def test_imported_game_appears_in_list(self, games_dir, tmp_path):
        archive = tmp_path / "listed.nri"
        _build_v2_archive(archive, "ListedGame")
        import_game(archive)
        names = [g["name"] for g in list_games()]
        assert "ListedGame" in names

    def test_export_then_reimport_roundtrip(self, games_dir, tmp_path):
        db_path = create_game("RoundTrip")
        db_path.write_bytes(b"real db bytes")
        images_dir = db_path.parent / "images"
        (images_dir / "cd").mkdir(parents=True)
        content = b"picture-bytes"
        sha = hashlib.sha256(content).hexdigest()
        (images_dir / "cd" / f"{sha}.jpg").write_bytes(content)
        (images_dir / "cd" / f"{sha}.preview.webp").write_bytes(b"preview")

        archive = tmp_path / "rt.nri"
        export_game(str(db_path), archive)
        delete_game(str(db_path))
        assert not db_path.parent.exists()

        imported = import_game(archive)
        assert imported.read_bytes() == b"real db bytes"
        assert (imported.parent / "images" / "cd" / f"{sha}.jpg").read_bytes() == content
        assert (imported.parent / "images" / "cd" / f"{sha}.preview.webp").exists()


class TestCorruptedFile:
    def test_corrupted_image_aborts_import(self, games_dir, tmp_path):
        archive = tmp_path / "corrupt.nri"
        sha = hashlib.sha256(b"real-content").hexdigest()
        meta = {"game_name": "Corrupt", "archive_version": 2}
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("game.db", b"db")
            # Content doesn't match the hash encoded in the filename.
            zf.writestr(f"images/{sha[:2]}/{sha}.png", b"tampered-content")
            zf.writestr("meta.json", json.dumps(meta))

        with pytest.raises(ValueError):
            import_game(archive)

        assert list_games() == []
        assert not (games_dir / "Corrupt").exists()

    def test_no_partial_leftovers_after_corruption(self, games_dir, tmp_path):
        archive = tmp_path / "corrupt2.nri"
        sha = hashlib.sha256(b"aaa").hexdigest()
        meta = {"game_name": "Partial", "archive_version": 2}
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("game.db", b"db")
            zf.writestr(f"images/{sha[:2]}/{sha}.png", b"bbb")  # wrong content for sha
            zf.writestr("meta.json", json.dumps(meta))

        with pytest.raises(ValueError):
            import_game(archive)

        # No stray temp/import directories left behind.
        assert list(games_dir.iterdir()) == [] if games_dir.exists() else True


class TestNameConflict:
    def test_existing_game_name_rejected(self, games_dir, tmp_path):
        create_game("Taken")
        archive = tmp_path / "dupe.nri"
        _build_v2_archive(archive, "Taken")

        with pytest.raises(FileExistsError):
            import_game(archive)

    def test_existing_game_untouched_on_conflict(self, games_dir, tmp_path):
        db_path = create_game("Taken")
        db_path.write_bytes(b"original content")
        archive = tmp_path / "dupe2.nri"
        _build_v2_archive(archive, "Taken")

        with pytest.raises(FileExistsError):
            import_game(archive)

        assert db_path.read_bytes() == b"original content"


class TestMetaJsonErrors:
    def test_missing_meta_json_rejected(self, games_dir, tmp_path):
        archive = tmp_path / "nometa.nri"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("game.db", b"db")
        with pytest.raises(ValueError):
            import_game(archive)

    def test_missing_game_db_rejected(self, games_dir, tmp_path):
        archive = tmp_path / "nodb.nri"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("meta.json", json.dumps({"game_name": "X"}))
        with pytest.raises(ValueError):
            import_game(archive)

    def test_corrupt_meta_json_rejected(self, games_dir, tmp_path):
        archive = tmp_path / "badmeta.nri"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("game.db", b"db")
            zf.writestr("meta.json", "{not valid json")
        with pytest.raises(ValueError):
            import_game(archive)

    def test_missing_archive_raises_file_not_found(self, games_dir, tmp_path):
        with pytest.raises(FileNotFoundError):
            import_game(tmp_path / "nowhere.nri")


class TestV1Compatibility:
    def test_v1_archive_without_images_imports(self, games_dir, tmp_path):
        """A v1 archive (game.db + meta.json, no images/) imports cleanly."""
        archive = tmp_path / "v1.nri"
        meta = {
            "game_name": "LegacyGame",
            "version": "0.6",
            "exported_at": "2023-01-01T00:00:00",
            "db_size_bytes": 2,
        }
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("game.db", b"legacy db content")
            zf.writestr("meta.json", json.dumps(meta))

        result = import_game(archive)

        assert result.exists()
        assert result.read_bytes() == b"legacy db content"
        assert (result.parent / "images").is_dir()
        assert list(result.parent.glob("images/**/*")) == []

    def test_v1_import_appears_in_list(self, games_dir, tmp_path):
        archive = tmp_path / "v1_listed.nri"
        meta = {"game_name": "V1Listed"}
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("game.db", b"d")
            zf.writestr("meta.json", json.dumps(meta))

        import_game(archive)
        names = [g["name"] for g in list_games()]
        assert "V1Listed" in names

    def test_v1_duplicate_name_rejected(self, games_dir, tmp_path):
        create_game("V1Dupe")
        archive = tmp_path / "v1_dupe.nri"
        meta = {"game_name": "V1Dupe"}
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("game.db", b"d")
            zf.writestr("meta.json", json.dumps(meta))
        with pytest.raises(FileExistsError):
            import_game(archive)
