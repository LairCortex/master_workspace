"""Game manager — manages games as self-contained catalog directories.

Each game is ``games/<name>/`` containing ``game.db`` + ``images/`` (design
D1). Pre-upgrade flat ``games/<name>.db`` files are still listed and are
migrated into this layout the first time they are opened
(``ensure_game_directory``, wired from ``Application.start``).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import NotRequired, TypedDict

from app import __version__
from app.infrastructure.images.paths import PREVIEW_SUFFIX
from app.infrastructure.repositories.game_settings_repository import (
    DND_MODULE_DATA_VERSION,
    DND_MODULE_KEY,
    decode_dnd_module_flag,
    encode_dnd_module_flag,
)


class GameInfo(TypedDict):
    name: str
    path: str
    modified: datetime
    #: True when the game's ``dnd_module`` flag reads enabled (task 2.7) —
    #: the launcher row paints the «D&D» badge from it. NotRequired: the
    #: catalog fakes predating the badge construct the dict without the key
    #: and read as ordinary.
    dnd: NotRequired[bool]


_DB_NAME = "game.db"
_IMAGES_DIR_NAME = "images"

#: DDL of the settings table for the launcher's synchronous seed read/write —
#: the same shape the ORM model creates; the launcher runs before any engine
#: or session exists, so this stays the one hand-written copy of the shape,
#: used ONLY against a brand-new game file (init_db owns every real schema).
_GAME_SETTINGS_DDL = (
    "CREATE TABLE IF NOT EXISTS game_settings "
    "(key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')"
)


def _read_dnd_enabled(db_path: Path) -> bool:
    """Synchronous read of the game's D&D flag for the catalog (task 2.7,
    design Д8): one short ``sqlite3`` query per file, all reading rules of
    the штатный codec (a damaged value logs its reason and reads ordinary,
    an absent row or a not-yet-schematized database reads ordinary too).
    The catalog is a preview; the authoritative read stays in the game-open
    composition — this one only paints the badge. One try covers connect and
    query alike: an unopenable or not-yet-schematized file (an empty game
    touched but never opened) is simply an ordinary game here."""
    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT value FROM game_settings WHERE key = ?", (DND_MODULE_KEY,)
        ).fetchone()
    except sqlite3.Error:
        return False
    finally:
        if conn is not None:
            conn.close()
    if row is None:
        return False
    flag = decode_dnd_module_flag(row[0])
    return flag is not None and flag.enabled


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


def get_images_dir(db_path: str | Path) -> Path:
    """Return the ``images/`` directory belonging to the game at ``db_path``."""
    return Path(db_path).parent / _IMAGES_DIR_NAME


def list_games() -> list[GameInfo]:
    """Scan the games directory and return info about each game.

    Includes both catalog games (``<name>/game.db``) and not-yet-migrated
    legacy flat ``<name>.db`` files.
    """
    games_dir = get_games_dir()
    games: list[GameInfo] = []
    for entry in sorted(games_dir.iterdir()):
        if entry.is_dir():
            db_path = entry / _DB_NAME
            if db_path.is_file():
                stat = db_path.stat()
                games.append(GameInfo(
                    name=entry.name,
                    path=str(db_path),
                    modified=datetime.fromtimestamp(stat.st_mtime),
                    dnd=_read_dnd_enabled(db_path),
                ))
        elif entry.is_file() and entry.suffix == ".db":
            stat = entry.stat()
            games.append(GameInfo(
                name=entry.stem,
                path=str(entry),
                modified=datetime.fromtimestamp(stat.st_mtime),
                dnd=_read_dnd_enabled(entry),
            ))
    return games


def create_game(name: str, *, dnd: bool = False) -> Path:
    """Create a new game catalog directory and return the path to its ``game.db``.

    The database file is created empty — tables are initialized by
    ``Application.start()``. With ``dnd=True`` (task 2.6, design Д8) the
    creation additionally seeds the ``dnd_module`` flag with the current
    module data-format version: the launcher is synchronous and pre-session,
    so the seed goes through a short ``sqlite3`` write of the штатный codec's
    body; ordinary games never see the key (spec game-launcher «при «Обычная»
    ключ модуля НЕ SHALL записываться»). The pre-created settings table does
    not stop the calendar seeding on first open — ``init_db``'s freshness
    fact ignores it (see ``migrations._database_is_fresh``).
    """
    safe_name = name.strip()
    if not safe_name:
        raise ValueError("Game name cannot be empty")
    games_dir = get_games_dir()
    game_dir = games_dir / safe_name
    if game_dir.exists() or (games_dir / f"{safe_name}.db").exists():
        raise FileExistsError(f"Game '{safe_name}' already exists")
    game_dir.mkdir(parents=True)
    (game_dir / _IMAGES_DIR_NAME).mkdir()
    db_path = game_dir / _DB_NAME
    db_path.touch()
    if dnd:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(_GAME_SETTINGS_DDL)
            conn.execute(
                "INSERT INTO game_settings (key, value) VALUES (?, ?)",
                (
                    DND_MODULE_KEY,
                    encode_dnd_module_flag(True, DND_MODULE_DATA_VERSION),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    return db_path


def ensure_game_directory(path: str | Path) -> Path:
    """Migrate a legacy flat ``games/<name>.db`` file into ``games/<name>/game.db``.

    Idempotent: paths that already point at ``game.db`` are returned as-is.
    A ``path`` with no file on disk yet (a brand-new game whose ``game.db``
    hasn't been created by the caller) is not a migration — the catalog
    directory is still resolved/created so the caller can open it fresh.
    """
    p = Path(path)
    if p.name == _DB_NAME:
        return p
    game_dir = p.parent / p.stem
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / _IMAGES_DIR_NAME).mkdir(exist_ok=True)
    target = game_dir / _DB_NAME
    if not target.exists() and p.exists():
        shutil.move(str(p), str(target))
    return target


def delete_game(path: str) -> None:
    """Delete a game given the path to its ``game.db`` (or legacy flat ``.db``)."""
    p = Path(path)
    if not p.exists() or p.suffix != ".db":
        return
    if p.name == _DB_NAME:
        shutil.rmtree(p.parent)
    else:
        p.unlink()


def get_db_url(path: str | Path) -> str:
    """Build an async SQLAlchemy URL for the given database path."""
    return f"sqlite+aiosqlite:///{path}"


# ── Export / Import ───────────────────────────────────────────────────────

_ARCHIVE_VERSION = 2
_ARCHIVE_DB_NAME = "game.db"
_ARCHIVE_META_NAME = "meta.json"
_ARCHIVE_IMAGES_PREFIX = "images/"


def export_game(db_path: str | Path, dest_path: str | Path) -> Path:
    """Export a game as a .nri ZIP archive (v2): game.db + images/** + meta.json.

    Returns the path to the created archive.
    """
    db_path = Path(db_path)
    dest_path = Path(dest_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    game_dir = db_path.parent
    images_dir = game_dir / _IMAGES_DIR_NAME

    meta = {
        "game_name": game_dir.name,
        "version": __version__,
        "archive_version": _ARCHIVE_VERSION,
        "exported_at": datetime.now().isoformat(),
        "db_size_bytes": db_path.stat().st_size,
    }

    with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.write(db_path, _ARCHIVE_DB_NAME)
        if images_dir.is_dir():
            for f in sorted(images_dir.rglob("*")):
                if f.is_file():
                    arcname = f"{_IMAGES_DIR_NAME}/{f.relative_to(images_dir).as_posix()}"
                    zf.write(f, arcname)
        zf.writestr(_ARCHIVE_META_NAME, json.dumps(meta, ensure_ascii=False, indent=2))

    return dest_path


def _original_hash_from_archive_name(name: str) -> str | None:
    """Return the expected sha256 for an original image archive entry.

    Only originals are content-addressed by their own hash; preview files
    are named after the *original's* hash (design D2), so their own bytes
    cannot be verified this way — and don't need to be: previews are always
    regenerable from the original (design D5), so a corrupt preview is
    self-healed by ``ImageStore.startup_gc`` rather than blocking import.
    """
    filename = Path(name).name
    if filename.endswith(PREVIEW_SUFFIX):
        return None
    return Path(filename).stem


def import_game(archive_path: str | Path) -> Path:
    """Import a game from a .nri ZIP archive into the games directory.

    Extraction happens in a sibling temp directory (same filesystem) that is
    verified (sha256 of every ``images/**`` entry against its filename) before
    being atomically renamed into place — a failure at any point leaves
    nothing behind in the games directory (design D9).

    Returns the path to the imported ``game.db``.
    Raises ``FileExistsError`` if a game with the same name already exists.
    Raises ``ValueError`` if the archive is invalid or a file is corrupted.
    """
    archive_path = Path(archive_path)
    if not archive_path.exists():
        raise FileNotFoundError(f"Archive not found: {archive_path}")

    games_dir = get_games_dir()

    with zipfile.ZipFile(archive_path, "r") as zf:
        names = zf.namelist()
        if _ARCHIVE_DB_NAME not in names or _ARCHIVE_META_NAME not in names:
            raise ValueError("Неверный формат архива: отсутствует game.db или meta.json")

        try:
            meta = json.loads(zf.read(_ARCHIVE_META_NAME).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"Повреждён meta.json: {e}") from e

        game_name = meta.get("game_name", archive_path.stem)
        target = games_dir / game_name
        if target.exists() or (games_dir / f"{game_name}.db").exists():
            raise FileExistsError(f"Игра '{game_name}' уже существует")

        tmp_dir = games_dir / f".import-{uuid.uuid4().hex}"
        tmp_dir.mkdir()
        try:
            zf.extract(_ARCHIVE_DB_NAME, tmp_dir)

            image_names = [
                n for n in names
                if n.startswith(_ARCHIVE_IMAGES_PREFIX) and not n.endswith("/")
            ]
            for name in image_names:
                zf.extract(name, tmp_dir)
                expected = _original_hash_from_archive_name(name)
                if expected is None:
                    continue  # preview: not self-verifiable, see docstring above
                extracted = tmp_dir / name
                actual = hashlib.sha256(extracted.read_bytes()).hexdigest()
                if actual != expected:
                    raise ValueError(f"Повреждён файл в архиве: {name}")

            (tmp_dir / _IMAGES_DIR_NAME).mkdir(exist_ok=True)
            tmp_dir.rename(target)
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    return target / _DB_NAME


def read_archive_meta(archive_path: str | Path) -> dict:
    """Read meta.json from an archive without extracting the DB."""
    archive_path = Path(archive_path)
    with zipfile.ZipFile(archive_path, "r") as zf:
        if _ARCHIVE_META_NAME not in zf.namelist():
            raise ValueError("Неверный формат архива")
        return json.loads(zf.read(_ARCHIVE_META_NAME).decode("utf-8"))
