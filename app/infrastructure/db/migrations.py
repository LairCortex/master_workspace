"""Database schema initialization and legacy migrations.

Project convention (no alembic): schema changes live in init_db() and run
at startup — create_all for fresh databases, inline ALTER-based migrations
for existing ones.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
]


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

    ``image_dir`` is the game's ``images/`` directory (design D8); when
    omitted, legacy-base64 migration is skipped — used by schema-only tests
    and callers with no on-disk game directory to migrate into.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Migrate missing columns for existing databases
    async with engine.begin() as conn:
        for table, column, col_type in _MIGRATIONS:
            try:
                await conn.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                )
            except Exception:
                pass  # column already exists

    # Migrate end_date NOT NULL → nullable
    async with engine.begin() as conn:
        await _migrate_nullable_end_dates(conn)

    if image_dir is not None:
        await _migrate_legacy_images(engine, Path(image_dir))
