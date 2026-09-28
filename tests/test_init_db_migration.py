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

        for table in ("organizations", "characters", "locations", "items"):
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
        for table in ("organizations", "characters", "locations", "items"):
            assert "image_id" in await _columns(engine, table)
    finally:
        await engine.dispose()


async def test_old_db_without_item_image_id_gets_migrated(tmp_path):
    """Spec image-storage «Старая база получает колонку предмета»: a game
    saved before the item picture receives `items.image_id` at startup, its
    rows stay intact, and a repeated init_db neither fails nor duplicates."""
    db_path = tmp_path / "old_items.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        # Synthesize the pre-NRI-0022 items schema (no image_id; the shape
        # real old games have — music_url/rating already migrated in).
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                """
                CREATE TABLE items (
                    id INTEGER NOT NULL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    description_id INTEGER,
                    start_date DATE NOT NULL,
                    end_date DATE,
                    music_url TEXT,
                    rating INTEGER DEFAULT 1
                )
                """
            )
            await conn.exec_driver_sql(
                "INSERT INTO items (name, start_date) VALUES ('Old Ring', '0500-01-01')"
            )

        await init_db(engine)

        assert "image_id" in await _columns(engine, "items")

        # The migrated column declares the same ON DELETE SET NULL the fresh
        # schema carries (spec «Предмет ссылается на изображение»).
        from sqlalchemy import text
        async with engine.connect() as conn:
            fks = (await conn.exec_driver_sql("PRAGMA foreign_key_list(items)")).fetchall()
        item_fk = [fk for fk in fks if "images" in fk]
        assert item_fk, "image_id FK to images missing after migration"
        assert any(fk[-2] == "SET NULL" for fk in item_fk)

        async with engine.connect() as conn:
            row = (
                await conn.execute(text("SELECT name, image_id FROM items"))
            ).first()
        assert row == ("Old Ring", None)

        # Repeated open (PRAGMA-guarded registry): no error, single column.
        await init_db(engine)
        async with engine.connect() as conn:
            cols = (
                await conn.exec_driver_sql("PRAGMA table_info(items)")
            ).fetchall()
        assert [c[1] for c in cols].count("image_id") == 1
    finally:
        await engine.dispose()
