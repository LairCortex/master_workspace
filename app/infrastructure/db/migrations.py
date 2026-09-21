"""Database schema initialization and legacy migrations.

Project convention (no alembic): schema changes live in init_db() and run
at startup — create_all for fresh databases, inline ALTER-based migrations
for existing ones.
"""
from __future__ import annotations

import base64
import re
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.game_calendar import (
    CALENDAR_SETTINGS_KEY,
    CALENDAR_WIZARD_SEEN_KEY,
    CALENDAR_WIZARD_SEEN_NO,
    StandardCalendar,
    encode_calendar,
)
from app.infrastructure.db.models import Base, CharacterModel, LocationModel, OrganizationModel
from app.infrastructure.images.store import ImageStore

_LEGACY_IMAGE_MODELS = (OrganizationModel, CharacterModel, LocationModel)


async def _migrate_nullable_end_dates(conn):
    """Make end_date columns nullable in existing databases (SQLite table rebuild)."""
    tables = ["events", "organizations", "characters", "items", "locations", "ratings"]
    for table in tables:
        try:
            rows = (await conn.exec_driver_sql(f"PRAGMA table_info({table})")).fetchall()
        except Exception:
            continue
        for row in rows:
            # row: (cid, name, type, notnull, dflt_value, pk)
            if row[1] == "end_date" and row[3] == 1:  # notnull == 1 → needs fix
                sql_result = (await conn.exec_driver_sql(
                    f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'"
                )).scalar()
                if not sql_result:
                    break
                new_sql = re.sub(
                    r'(end_date\s+\w+)\s+NOT\s+NULL',
                    r'\1',
                    sql_result,
                    flags=re.IGNORECASE,
                )
                tmp = f"__{table}_tmp"
                new_sql = (
                    new_sql.replace(f'"{table}"', f'"{tmp}"', 1)
                    .replace(f" {table} ", f" {tmp} ", 1)
                    .replace(f" {table}(", f" {tmp}(", 1)
                )
                if tmp not in new_sql:
                    new_sql = new_sql.replace(table, tmp, 1)
                col_names = ", ".join(r[1] for r in rows)
                await conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
                await conn.exec_driver_sql(new_sql)
                await conn.exec_driver_sql(
                    f"INSERT INTO {tmp} ({col_names}) SELECT {col_names} FROM {table}"
                )
                await conn.exec_driver_sql(f"DROP TABLE {table}")
                await conn.exec_driver_sql(f"ALTER TABLE {tmp} RENAME TO {table}")
                await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                break


# Tables holding a (start_date, end_date) pair — every one of them carries
# the era-aware date columns (add-era-aware-dates, design D3).
_ERA_TABLES = ("events", "organizations", "characters", "items", "locations", "ratings")

# ADD COLUMN migrations for pre-existing databases (hotfix 0.9.x era schema)
_MIGRATIONS = [
    ("organizations", "rating", "INTEGER DEFAULT 1"),
    ("characters", "rating", "INTEGER DEFAULT 1"),
    ("items", "rating", "INTEGER DEFAULT 1"),
    ("locations", "rating", "INTEGER DEFAULT 1"),
    ("organizations", "image", "TEXT"),
    ("organizations", "music_url", "TEXT"),
    ("characters", "music_url", "TEXT"),
    ("items", "music_url", "TEXT"),
    ("locations", "music_url", "TEXT"),
    ("organizations", "image_id", "INTEGER REFERENCES images(id)"),
    ("characters", "image_id", "INTEGER REFERENCES images(id)"),
    ("locations", "image_id", "INTEGER REFERENCES images(id)"),
    ("events", "event_type_id", "INTEGER REFERENCES event_types(id) ON DELETE SET NULL"),
    # Era-aware dates (design D3): flags default to 0 so pre-era rows and any
    # INSERT that predates the feature read as «н.э.»; the derived keys are
    # nullable on purpose — old app versions write dates without them, and
    # the python reconcile started from Application.start() (design D5)
    # recomputes them on the next open.
    *[(t, "start_bc", "INTEGER NOT NULL DEFAULT 0") for t in _ERA_TABLES],
    *[(t, "end_bc", "INTEGER NOT NULL DEFAULT 0") for t in _ERA_TABLES],
    *[(t, "start_key", "INTEGER") for t in _ERA_TABLES],
    *[(t, "end_key", "INTEGER") for t in _ERA_TABLES],
    # Game-coordinate slots (piece C3a, design D1): nullable TEXT added with
    # the same cheap ALTER as every other column — no table rebuild, and a
    # pre-C3a game simply receives them empty ("the dates live in the date
    # columns"), exactly like a fresh create_all game.
    *[(t, "start_coord", "TEXT") for t in _ERA_TABLES],
    *[(t, "end_coord", "TEXT") for t in _ERA_TABLES],
]

# NRI defaults seeded once per game into an empty `event_types` set (W4).
# color_index is a 1-based index into the color.chart.1..8 token palette.
_DEFAULT_EVENT_TYPES = ("Сюжет", "Побочное", "Слух", "Встреча", "Ров будней", "Находка")


def _db_file_from_url(database: str | None) -> Path | None:
    """The SQLite file behind an engine URL; ``None`` for memory/temporary DBs."""
    if not database or database == ":memory:" or database.startswith("file:"):
        return None
    return Path(database)


async def _backup_before_first_era_migration(conn, database: str | None) -> None:
    """Copy the game file to ``<db>.bak`` once, before the first era transfer.

    Design D5: the missing ``start_bc`` column is the "never migrated" marker
    (a game created by this version already has it via ``create_all``), so a
    copy appears ONLY for a real first transfer and is never overwritten —
    repeated opens leave exactly one untouched ``.bak``.
    """
    db_file = _db_file_from_url(database)
    if db_file is None or not db_file.exists():
        return
    rows = (await conn.exec_driver_sql("PRAGMA table_info(events)")).fetchall()
    if not rows or any(row[1] == "start_bc" for row in rows):
        return  # fresh or already migrated — no transfer, no copy
    backup = db_file.with_name(db_file.name + ".bak")
    if not backup.exists():
        shutil.copy2(db_file, backup)


async def _seed_default_event_types(conn) -> None:
    """Seed the six default event types, but only into an empty table.

    Guard «только пустая таблица»: user edits (renames, deletions down to a
    single remaining type) are never overwritten on later startups.
    """
    count = (await conn.exec_driver_sql("SELECT COUNT(*) FROM event_types")).scalar()
    if count:
        return
    for i, name in enumerate(_DEFAULT_EVENT_TYPES):
        await conn.exec_driver_sql(
            "INSERT INTO event_types (name, color_index, sort_order) VALUES (?, ?, ?)",
            (name, i + 1, i),
        )


# ── C4 seeding: the two calendar keys of a brand-new game (design D7) ─────

async def _database_is_fresh(conn) -> bool:
    """Whether ``conn``'s database has no user tables yet — the "we are about
    to build the schema" fact that separates a new game from a migration.

    The launcher's ``create_game`` leaves an empty file behind and never opens
    a database, so "fresh" covers exactly the games whose schema this version
    creates (spec «Новая игра рождается с посевом»); a game that already has
    tables was built by some earlier version and must stay keyless.
    """
    rows = (
        await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' LIMIT 1"
        )
    ).fetchall()
    return not rows


async def _seed_new_game_calendar_keys(conn) -> None:
    """Seed the two C4 keys into a freshly created schema (design D7).

    Written straight through SQL because the game session layers are not
    wired yet while ``init_db`` runs.  The preset value is produced by the
    domain codec, not hand-written JSON, so a future storage-version bump
    cannot leave new games behind on the stale shape.  Guard is "fresh
    schema", not "empty key row": an old game never gets here, and a second
    ``init_db`` over the same file is a migration pass — no re-seed, no
    overwritten user choice (spec «Старую игру посев не догоняет»).
    """
    await conn.exec_driver_sql(
        "INSERT OR IGNORE INTO game_settings (key, value) VALUES (?, ?)",
        (CALENDAR_SETTINGS_KEY, encode_calendar(StandardCalendar())),
    )
    await conn.exec_driver_sql(
        "INSERT OR IGNORE INTO game_settings (key, value) VALUES (?, ?)",
        (CALENDAR_WIZARD_SEEN_KEY, CALENDAR_WIZARD_SEEN_NO),
    )


async def _migrate_legacy_images(engine, image_dir: Path) -> None:
    """Move legacy base64 images (`image` column) into file storage (design D8).

    One row committed at a time: a crash mid-migration leaves only that row
    to retry on the next startup (legacy value is still non-NULL until the
    file + `images` row + FK are all in place). `VACUUM` runs once, only if
    at least one row was actually migrated.
    """
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    migrated = 0
    for model in _LEGACY_IMAGE_MODELS:
        while True:
            async with session_factory() as session:
                result = await session.execute(
                    select(model)
                    .where(model.image.isnot(None), model.image != "")
                    .limit(1)
                )
                row = result.scalars().first()
                if row is None:
                    break
                store = ImageStore(session, image_dir)
                data = base64.b64decode(row.image)
                row.image_id = await store.store(data)
                row.image = None
                await session.commit()
                migrated += 1

    if migrated:
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.exec_driver_sql("VACUUM")


async def init_db(engine, image_dir: Path | str | None = None) -> None:
    """Create tables if they don't exist, and migrate missing columns/data.

    Era-aware dates (add-era-aware-dates): a game file that is about to
    receive the era columns for the first time is copied to ``<db>.bak``
    beforehand (D5).  Era keys are NOT derived here anymore: the schema is
    the only business left — key reconciliation is a pure-python pass over
    the active calendar, run by ``CalendarSettingsService.reconcile_era_keys``
    from ``Application.start()`` right after the calendar load (C2, design D5).

    ``image_dir`` is the game's ``images/`` directory (design D8); when
    omitted, legacy-base64 migration is skipped — used by schema-only tests
    and callers with no on-disk game directory to migrate into.

    A database whose tables are created right here is a *new* game, so the
    two calendar keys (preset + «мастер не показан») are seeded into it, and
    never into a game that already had a schema (C4, design D7).
    """
    async with engine.begin() as conn:
        is_new_database = await _database_is_fresh(conn)
        await conn.run_sync(Base.metadata.create_all)

    # Era-aware dates: snapshot the file before the very first era transfer (D5)
    async with engine.begin() as conn:
        await _backup_before_first_era_migration(conn, engine.url.database)

    # Migrate missing columns for existing databases; idempotence is decided
    # by PRAGMA table_info — already-present columns (fresh create_all schema
    # included) are skipped instead of re-ALTERed-and-swallowed, and a second
    # init_db over the same file can neither fail nor duplicate a column.
    async with engine.begin() as conn:
        for table, column, col_type in _MIGRATIONS:
            existing = {
                row[1]
                for row in (await conn.exec_driver_sql(f"PRAGMA table_info({table})")).fetchall()
            }
            if column in existing:
                continue
            await conn.exec_driver_sql(
                f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
            )

    # Migrate end_date NOT NULL → nullable
    async with engine.begin() as conn:
        await _migrate_nullable_end_dates(conn)

    # Seed the six default event types into an empty set (W4, idempotent)
    async with engine.begin() as conn:
        await _seed_default_event_types(conn)

    # Seed the two calendar keys of a newly created game (C4, design D7).
    # The freshness fact was captured before ``create_all``: only the very
    # first pass over the file counts as a new game, so both the migration
    # path and any repeated ``init_db`` stay untouched by the seeding.
    if is_new_database:
        async with engine.begin() as conn:
            await _seed_new_game_calendar_keys(conn)

    if image_dir is not None:
        await _migrate_legacy_images(engine, Path(image_dir))
