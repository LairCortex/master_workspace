"""Game manager — manages multiple game databases as separate SQLite files."""
from __future__ import annotations

import json
import os
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import TypedDict


class GameInfo(TypedDict):
    name: str
    path: str
    modified: datetime


def _resolve_games_dir() -> Path:
    """Determine the games directory.

    In frozen (PyInstaller) builds the directory sits next to the executable.
    In development mode it sits at the project root.
    """
    if getattr(sys, "frozen", False):
        # PyInstaller: executable directory
        base = Path(sys.executable).resolve().parent
    else:
        # Dev: project root (4 levels up from this file)
        base = Path(__file__).resolve().parent.parent.parent.parent
    return base / "games"


def get_games_dir() -> Path:
    """Return the games directory, creating it if it doesn't exist."""
    d = _resolve_games_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_games() -> list[GameInfo]:
    """Scan the games directory and return info about each game."""
    games_dir = get_games_dir()
    games: list[GameInfo] = []
    for f in sorted(games_dir.iterdir()):
        if f.suffix == ".db" and f.is_file():
            stat = f.stat()
            games.append(GameInfo(
                name=f.stem,
                path=str(f),
                modified=datetime.fromtimestamp(stat.st_mtime),
            ))
    return games


def create_game(name: str) -> Path:
    """Create a new game database file and return its path.

    The file is created empty — tables will be initialized by Application.start().
    """
    games_dir = get_games_dir()
    safe_name = name.strip()
    if not safe_name:
        raise ValueError("Game name cannot be empty")
    db_path = games_dir / f"{safe_name}.db"
    if db_path.exists():
        raise FileExistsError(f"Game '{safe_name}' already exists")
    db_path.touch()
    return db_path


def delete_game(path: str) -> None:
    """Delete a game database file."""
    p = Path(path)
    if p.exists() and p.suffix == ".db":
        p.unlink()


def get_db_url(path: str | Path) -> str:
    """Build an async SQLAlchemy URL for the given database path."""
    return f"sqlite+aiosqlite:///{path}"


# ── Export / Import ───────────────────────────────────────────────────────

_APP_VERSION = "0.6"
_ARCHIVE_DB_NAME = "game.db"
_ARCHIVE_META_NAME = "meta.json"


def export_game(db_path: str | Path, dest_path: str | Path) -> Path:
    """Export a game database as a .nri ZIP archive with metadata.

    Returns the path to the created archive.
    """
    db_path = Path(db_path)
    dest_path = Path(dest_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    meta = {
        "game_name": db_path.stem,
        "version": _APP_VERSION,
        "exported_at": datetime.now().isoformat(),
        "db_size_bytes": db_path.stat().st_size,
    }

    with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.write(db_path, _ARCHIVE_DB_NAME)
        zf.writestr(_ARCHIVE_META_NAME, json.dumps(meta, ensure_ascii=False, indent=2))

    return dest_path


def import_game(archive_path: str | Path) -> Path:
    """Import a game from a .nri ZIP archive into the games directory.

    Returns the path to the imported database file.
    Raises FileExistsError if a game with the same name already exists.
    Raises ValueError if the archive is invalid.
    """
    archive_path = Path(archive_path)
    if not archive_path.exists():
        raise FileNotFoundError(f"Archive not found: {archive_path}")

    with zipfile.ZipFile(archive_path, "r") as zf:
        names = zf.namelist()
        if _ARCHIVE_DB_NAME not in names or _ARCHIVE_META_NAME not in names:
            raise ValueError("Неверный формат архива: отсутствует game.db или meta.json")

        meta_raw = zf.read(_ARCHIVE_META_NAME).decode("utf-8")
        meta = json.loads(meta_raw)
        game_name = meta.get("game_name", archive_path.stem)

        games_dir = get_games_dir()
        target = games_dir / f"{game_name}.db"
        if target.exists():
            raise FileExistsError(f"Игра '{game_name}' уже существует")

        zf.extract(_ARCHIVE_DB_NAME, games_dir)
        extracted = games_dir / _ARCHIVE_DB_NAME
        extracted.rename(target)

    return target


def read_archive_meta(archive_path: str | Path) -> dict:
    """Read meta.json from an archive without extracting the DB."""
    archive_path = Path(archive_path)
    with zipfile.ZipFile(archive_path, "r") as zf:
        if _ARCHIVE_META_NAME not in zf.namelist():
            raise ValueError("Неверный формат архива")
        return json.loads(zf.read(_ARCHIVE_META_NAME).decode("utf-8"))
