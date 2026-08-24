"""Tests for the images-schema migration in init_db() (D3/2.2).

Covers: fresh DB gets `images` table + `image_id` columns via create_all;
a pre-existing ("old") DB without those gets them added idempotently.
"""
from __future__ import annotations

from app.infrastructure.db.database import create_engine
from app.infrastructure.db.migrations import init_db


async def _table_names(engine) -> set:
    from sqlalchemy import text
    async with engine.connect() as conn:
        rows = (
            await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        ).fetchall()
    return {r[0] for r in rows}


async def _columns(engine, table: str) -> set:
    async with engine.connect() as conn:
        rows = (await conn.exec_driver_sql(f"PRAGMA table_info({table})")).fetchall()
    return {r[1] for r in rows}


async def test_fresh_db_has_images_table_and_fk_columns():
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    try:
        await init_db(engine)
        tables = await _table_names(engine)
        assert "images" in tables

        img_cols = await _columns(engine, "images")
        assert {"id", "sha256", "ext", "width", "height", "size_bytes", "created_at"} <= img_cols

        for table in ("organizations", "characters", "locations"):
            assert "image_id" in await _columns(engine, table)
    finally:
        await engine.dispose()


async def test_old_db_without_image_id_gets_migrated(tmp_path):
    db_path = tmp_path / "old.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        # Synthesize a pre-image-storage schema for one of the three tables.
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                """
                CREATE TABLE organizations (
                    id INTEGER NOT NULL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    description_id INTEGER,
                    start_date DATE NOT NULL,
                    end_date DATE,
                    tasks TEXT,
                    music_url TEXT,
                    image TEXT,
                    rating INTEGER DEFAULT 1
                )
                """
            )
            await conn.exec_driver_sql(
                "INSERT INTO organizations (name, start_date) VALUES ('Old Guild', '1000-01-01')"
            )

        await init_db(engine)

        cols = await _columns(engine, "organizations")
        assert "image_id" in cols
        tables = await _table_names(engine)
        assert "images" in tables

        from sqlalchemy import text
        async with engine.connect() as conn:
            row = (
                await conn.execute(text("SELECT name, image_id FROM organizations"))
            ).first()
        assert row == ("Old Guild", None)
    finally:
        await engine.dispose()


async def test_migration_is_idempotent():
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    try:
        await init_db(engine)
        await init_db(engine)  # second run must not raise
        for table in ("organizations", "characters", "locations"):
            assert "image_id" in await _columns(engine, table)
    finally:
        await engine.dispose()
