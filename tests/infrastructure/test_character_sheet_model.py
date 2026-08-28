"""Tests for the character_sheets schema — TDD: red first.

Covers task 2.1: create_all on a fresh DB creates ``character_sheets`` with the
expected columns (name UNIQUE, schema_version, orientation, pages, timestamps);
init_db() on an "old" DB lacking the table adds it without harming existing data.
"""
from __future__ import annotations

from sqlalchemy import text

from app.infrastructure.db.database import create_engine as app_create_engine
from app.infrastructure.db.migrations import init_db
from app.infrastructure.db.models import Base

EXPECTED_COLUMNS = {
    "id", "name", "schema_version", "orientation", "pages", "created_at", "updated_at",
}


async def _table_names(engine) -> set:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        ).fetchall()
    return {r[0] for r in rows}


async def _columns(engine, table: str) -> set:
    async with engine.connect() as conn:
        rows = (await conn.exec_driver_sql(f"PRAGMA table_info({table})")).fetchall()
    return {r[1] for r in rows}


async def _table_ddl(engine, table: str) -> str:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:t"),
                {"t": table},
            )
        ).scalar() or ""


async def test_create_all_fresh_db_has_character_sheets():
    engine = app_create_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        tables = await _table_names(engine)
        assert "character_sheets" in tables

        cols = await _columns(engine, "character_sheets")
        assert EXPECTED_COLUMNS <= cols

        # name must carry a UNIQUE constraint
        ddl = await _table_ddl(engine, "character_sheets")
        assert "UNIQUE" in ddl.upper()
    finally:
        await engine.dispose()


async def test_init_db_adds_table_to_old_db_and_preserves_data(tmp_path):
    db_path = tmp_path / "old.db"
    engine = app_create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        # Synthesize a pre-feature database that already has one entity table.
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                """
                CREATE TABLE descriptions (
                    id INTEGER NOT NULL PRIMARY KEY,
                    characteristics TEXT,
                    backstory TEXT
                )
                """
            )
            await conn.exec_driver_sql(
                "INSERT INTO descriptions (characteristics, backstory) VALUES ('c', 'b')"
            )

        await init_db(engine)

        tables = await _table_names(engine)
        assert "character_sheets" in tables
        assert "descriptions" in tables

        cols = await _columns(engine, "character_sheets")
        assert EXPECTED_COLUMNS <= cols

        # Pre-existing row survived the migration untouched.
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT characteristics, backstory FROM descriptions")
                )
            ).first()
        assert row == ("c", "b")
    finally:
        await engine.dispose()
