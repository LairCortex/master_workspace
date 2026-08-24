"""Tests for catalog-based game directories (design D1) — create/list/delete."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.db.game_manager import (
    create_game,
    delete_game,
    ensure_game_directory,
    get_db_url,
    get_images_dir,
    list_games,
)


@pytest.fixture
def games_dir(tmp_path, monkeypatch):
    """Override the games directory to a temp folder."""
    monkeypatch.setattr(
        "app.infrastructure.db.game_manager._resolve_games_dir",
        lambda: tmp_path / "games",
    )
    return tmp_path / "games"


class TestCreateGame:
    def test_creates_directory_with_db_and_images(self, games_dir):
        db_path = create_game("My Campaign")
        game_dir = games_dir / "My Campaign"
        assert db_path == game_dir / "game.db"
        assert db_path.exists()
        assert (game_dir / "images").is_dir()

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

    def test_raises_on_duplicate_legacy_flat_file(self, games_dir):
        games_dir.mkdir(parents=True)
        (games_dir / "Legacy.db").touch()
        with pytest.raises(FileExistsError):
            create_game("Legacy")


class TestListGames:
    def test_empty_directory(self, games_dir):
        assert list_games() == []

    def test_lists_catalog_games(self, games_dir):
        create_game("Campaign")
        create_game("Dark Forest")
        result = list_games()
        names = {g["name"] for g in result}
        assert names == {"Campaign", "Dark Forest"}
        for g in result:
            assert g["path"].endswith("game.db")

    def test_lists_legacy_flat_files_too(self, games_dir):
        games_dir.mkdir(parents=True)
        (games_dir / "OldGame.db").touch()
        result = list_games()
        assert len(result) == 1
        assert result[0]["name"] == "OldGame"
        assert result[0]["path"].endswith("OldGame.db")

    def test_ignores_directories_without_game_db(self, games_dir):
        games_dir.mkdir(parents=True)
        (games_dir / "Empty").mkdir()
        assert list_games() == []

    def test_ignores_non_db_files(self, games_dir):
        games_dir.mkdir(parents=True)
        (games_dir / "readme.txt").touch()
        assert list_games() == []

    def test_game_info_fields(self, games_dir):
        create_game("Test")
        game = list_games()[0]
        assert game["name"] == "Test"
        assert "path" in game
        assert "modified" in game


class TestDeleteGame:
    def test_deletes_catalog_game_directory(self, games_dir):
        db_path = create_game("ToDelete")
        game_dir = db_path.parent
        assert game_dir.exists()
        delete_game(str(db_path))
        assert not game_dir.exists()

    def test_deletes_legacy_flat_file(self, games_dir):
        games_dir.mkdir(parents=True)
        legacy = games_dir / "Legacy.db"
        legacy.touch()
        delete_game(str(legacy))
        assert not legacy.exists()

    def test_no_error_on_missing(self, games_dir):
        delete_game("/nonexistent/path.db")

    def test_ignores_non_db(self, games_dir):
        games_dir.mkdir(parents=True)
        txt = games_dir / "notes.txt"
        txt.touch()
        delete_game(str(txt))
        assert txt.exists()


class TestEnsureGameDirectory:
    def test_already_catalog_path_is_noop(self, games_dir):
        db_path = create_game("Already")
        result = ensure_game_directory(db_path)
        assert result == db_path

    def test_migrates_legacy_flat_file(self, games_dir):
        games_dir.mkdir(parents=True)
        legacy = games_dir / "Legacy.db"
        legacy.write_bytes(b"sqlite data")

        result = ensure_game_directory(legacy)

        assert result == games_dir / "Legacy" / "game.db"
        assert result.exists()
        assert result.read_bytes() == b"sqlite data"
        assert not legacy.exists()
        assert (games_dir / "Legacy" / "images").is_dir()

    def test_idempotent_second_call(self, games_dir):
        games_dir.mkdir(parents=True)
        legacy = games_dir / "Legacy.db"
        legacy.write_bytes(b"data")
        migrated = ensure_game_directory(legacy)

        result2 = ensure_game_directory(migrated)
        assert result2 == migrated
        assert result2.exists()


class TestGetImagesDir:
    def test_derives_images_dir_from_db_path(self, games_dir):
        db_path = create_game("WithImages")
        assert get_images_dir(db_path) == db_path.parent / "images"


class TestGetDbUrl:
    def test_url_format(self):
        url = get_db_url("/tmp/game/game.db")
        assert url == "sqlite+aiosqlite:////tmp/game/game.db"

    def test_url_from_path_object(self):
        url = get_db_url(Path("/tmp/game/game.db"))
        assert url.startswith("sqlite+aiosqlite:///")
