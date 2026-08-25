"""Tests for the character_sheets table: new table, old-DB migration path,
name uniqueness (task 3.1)."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.infrastructure.db.database import create_engine
from app.infrastructure.db.migrations import init_db
from app.infrastructure.db.models import Base, CharacterSheetModel


async def _table_names(engine) -> set:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        ).fetchall()
    return {r[0] for r in rows} - {"sqlite_sequence"}


async def test_create_all_creates_character_sheets_on_fresh_db():
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        assert "character_sheets" in await _table_names(engine)
    finally:
        await engine.dispose()


async def test_old_db_gets_character_sheets_from_init_db_without_data_loss(tmp_path):
    """A pre-feature game database must gain the table on next startup."""
    db_path = tmp_path / "old_game.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        # Synthesize a legacy game database (no character_sheets table)
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                """
                CREATE TABLE events (
                    id INTEGER NOT NULL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    description_id INTEGER,
                    start_date DATE NOT NULL,
                    end_date DATE
                )
                """
            )
            await conn.exec_driver_sql(
                "INSERT INTO events (name, start_date) VALUES ('Осада', '1200-01-01')"
            )

        await init_db(engine)

        # New table exists…
        assert "character_sheets" in await _table_names(engine)
        # …and is usable…
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "INSERT INTO character_sheets "
                "(name, orientation, pages, created_at, updated_at) "
                "VALUES ('Лист', 'portrait', '[{\"name\": \"ОСН\", \"fields\": []}]', "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        # …and the legacy data survived untouched
        async with engine.connect() as conn:
            rows = (await conn.execute(text("SELECT name, start_date FROM events"))).fetchall()
        assert rows == [("Осада", "1200-01-01")]
    finally:
        await engine.dispose()


async def test_sheet_name_is_unique(async_session):
    first = CharacterSheetModel(name="Лист", orientation="portrait", pages="[]")
    async_session.add(first)
    await async_session.commit()

    duplicate = CharacterSheetModel(name="Лист", orientation="landscape", pages="[]")
    async_session.add(duplicate)
    try:
        with pytest.raises(IntegrityError):
            await async_session.commit()
    finally:
        await async_session.rollback()


async def test_sheet_round_trip_columns(async_session):
    row = CharacterSheetModel(name="Лист", orientation="landscape", pages='[{"name": "ОСН", "fields": []}]')
    async_session.add(row)
    await async_session.commit()

    fetched = (
        await async_session.execute(text("SELECT name, orientation FROM character_sheets"))
    ).fetchone()
    assert fetched == ("Лист", "landscape")
    assert row.created_at is not None and row.updated_at is not None
