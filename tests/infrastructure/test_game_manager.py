"""Tests for GameManager — TDD."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.db.game_manager import (
    create_game,
    delete_game,
    export_game,
    get_db_url,
    get_games_dir,
    import_game,
    list_games,
    read_archive_meta,
)


@pytest.fixture
def games_dir(tmp_path, monkeypatch):
    """Override the games directory to a temp folder."""
    monkeypatch.setattr(
        "app.infrastructure.db.game_manager._resolve_games_dir",
        lambda: tmp_path / "games",
    )
    return tmp_path / "games"


class TestGetGamesDir:
    def test_creates_directory(self, games_dir):
        assert not games_dir.exists()
        result = get_games_dir()
        assert result == games_dir
        assert games_dir.is_dir()

    def test_returns_existing(self, games_dir):
        games_dir.mkdir(parents=True)
        result = get_games_dir()
        assert result == games_dir


class TestListGames:
    def test_empty_directory(self, games_dir):
        assert list_games() == []

    def test_lists_db_files(self, games_dir):
        games_dir.mkdir(parents=True)
        (games_dir / "Campaign.db").touch()
        (games_dir / "Dark Forest.db").touch()
        (games_dir / "readme.txt").touch()  # non-db, ignored
        result = list_games()
        names = [g["name"] for g in result]
        assert "Campaign" in names
        assert "Dark Forest" in names
        assert len(result) == 2

    def test_game_info_fields(self, games_dir):
        games_dir.mkdir(parents=True)
        (games_dir / "Test.db").touch()
        result = list_games()
        game = result[0]
        assert game["name"] == "Test"
        assert "path" in game
        assert "modified" in game


class TestCreateGame:
    def test_creates_file(self, games_dir):
        path = create_game("My Campaign")
        assert path.exists()
        assert path.name == "My Campaign.db"

    def test_raises_on_empty_name(self, games_dir):
        with pytest.raises(ValueError):
            create_game("")

    def test_raises_on_whitespace_name(self, games_dir):
        with pytest.raises(ValueError):
            create_game("   ")

    def test_raises_on_duplicate(self, games_dir):
        create_game("Duplicate")
        with pytest.raises(FileExistsError):
            create_game("Duplicate")


class TestDeleteGame:
    def test_deletes_existing(self, games_dir):
        path = create_game("ToDelete")
        assert path.exists()
        delete_game(str(path))
        assert not path.exists()

    def test_no_error_on_missing(self, games_dir):
        delete_game("/nonexistent/path.db")

    def test_ignores_non_db(self, games_dir):
        games_dir.mkdir(parents=True)
        txt = games_dir / "notes.txt"
        txt.touch()
        delete_game(str(txt))
        assert txt.exists()  # not deleted because not .db


class TestExportGame:
    def test_export_creates_archive(self, games_dir, tmp_path):
        db_path = create_game("ExportMe")
        db_path.write_bytes(b"SQLite dummy content")
        dest = tmp_path / "export.nri"

        result = export_game(str(db_path), dest)
        assert result == dest
        assert dest.exists()

    def test_export_archive_is_valid_zip(self, games_dir, tmp_path):
        import zipfile
        db_path = create_game("ZipTest")
        db_path.write_bytes(b"data")
        dest = tmp_path / "ziptest.nri"
        export_game(str(db_path), dest)

        assert zipfile.is_zipfile(dest)
        with zipfile.ZipFile(dest) as zf:
            assert "game.db" in zf.namelist()
            assert "meta.json" in zf.namelist()

    def test_export_meta_contains_fields(self, games_dir, tmp_path):
        db_path = create_game("MetaTest")
        db_path.write_bytes(b"data")
        dest = tmp_path / "meta.nri"
        export_game(str(db_path), dest)

        meta = read_archive_meta(dest)
        assert meta["game_name"] == "MetaTest"
        assert "version" in meta
        assert "exported_at" in meta
        assert "db_size_bytes" in meta

    def test_export_raises_on_missing_db(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            export_game("/nonexistent.db", tmp_path / "out.nri")


class TestImportGame:
    def test_import_creates_db(self, games_dir, tmp_path):
        # Create and export a game first
        db_path = create_game("ImportMe")
        db_path.write_bytes(b"test db content")
        archive = tmp_path / "importme.nri"
        export_game(str(db_path), archive)

        # Delete original
        delete_game(str(db_path))
        assert not db_path.exists()

        # Import
        imported = import_game(archive)
        assert imported.exists()
        assert imported.stem == "ImportMe"
        assert imported.read_bytes() == b"test db content"

    def test_import_raises_on_duplicate(self, games_dir, tmp_path):
        db_path = create_game("Dupe")
        db_path.write_bytes(b"data")
        archive = tmp_path / "dupe.nri"
        export_game(str(db_path), archive)

        with pytest.raises(FileExistsError):
            import_game(archive)

    def test_import_raises_on_invalid_archive(self, tmp_path):
        bad = tmp_path / "bad.nri"
        bad.write_bytes(b"not a zip")
        with pytest.raises(Exception):
            import_game(bad)

    def test_import_appears_in_list(self, games_dir, tmp_path):
        db_path = create_game("Listed")
        db_path.write_bytes(b"x")
        archive = tmp_path / "listed.nri"
        export_game(str(db_path), archive)
        delete_game(str(db_path))

        import_game(archive)
        names = [g["name"] for g in list_games()]
        assert "Listed" in names


class TestReadArchiveMeta:
    def test_reads_meta(self, games_dir, tmp_path):
        db_path = create_game("ReadMeta")
        db_path.write_bytes(b"d")
        archive = tmp_path / "rm.nri"
        export_game(str(db_path), archive)

        meta = read_archive_meta(archive)
        assert meta["game_name"] == "ReadMeta"

    def test_raises_on_invalid(self, tmp_path):
        import zipfile
        bad = tmp_path / "nodb.nri"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("random.txt", "hello")
        with pytest.raises(ValueError):
            read_archive_meta(bad)


class TestGetDbUrl:
    def test_url_format(self):
        url = get_db_url("/tmp/my.db")
        assert url == "sqlite+aiosqlite:////tmp/my.db"

    def test_url_from_path_object(self):
        url = get_db_url(Path("/tmp/my.db"))
        assert url.startswith("sqlite+aiosqlite:///")
