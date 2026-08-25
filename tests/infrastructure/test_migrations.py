"""Tests for init_db (schema init + legacy migrations, no alembic convention).

Covers: fresh database, idempotency of a second run, and the legacy
`end_date NOT NULL` rebuild (hotfix 0.9.1 scenario) with data preserved.
"""
from sqlalchemy import text

from app.infrastructure.db.database import create_engine, create_session_factory
from app.infrastructure.db.migrations import init_db

ALL_TABLES = {
    "descriptions", "events", "organizations", "characters", "items",
    "locations", "ratings", "game_settings", "character_sheets",
    "event_organization", "event_character", "event_item", "event_location",
    "organization_character", "organization_item", "organization_location",
    "character_item", "character_location", "character_rating",
    "item_location", "item_rating", "location_rating",
}


async def _table_names(engine) -> set:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        ).fetchall()
    return {r[0] for r in rows} - {"sqlite_sequence"}


async def _end_date_notnull(engine, table: str) -> int:
    async with engine.connect() as conn:
        rows = (await conn.exec_driver_sql(f"PRAGMA table_info({table})")).fetchall()
    for row in rows:
        if row[1] == "end_date":
            return row[3]
    raise AssertionError(f"end_date column not found in {table}")


async def test_fresh_db_creates_full_schema():
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    try:
        await init_db(engine)
        tables = await _table_names(engine)
        assert ALL_TABLES <= tables
        # Fresh schema already has nullable end_date + default rating columns
        assert await _end_date_notnull(engine, "events") == 0
    finally:
        await engine.dispose()


async def test_init_db_is_idempotent():
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    try:
        await init_db(engine)
        before = await _table_names(engine)
        # Second startup must be a no-op (ALTERs fail silently, rebuild not triggered)
        await init_db(engine)
        assert await _table_names(engine) == before
        assert await _end_date_notnull(engine, "characters") == 0
    finally:
        await engine.dispose()


async def test_legacy_notnull_end_date_is_migrated_to_nullable(tmp_path):
    db_path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = create_session_factory(engine)
    try:
        # Synthesize the pre-0.9.1 legacy schema: end_date NOT NULL
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                """
                CREATE TABLE events (
                    id INTEGER NOT NULL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    description_id INTEGER,
                    start_date DATE NOT NULL,
                    end_date DATE NOT NULL
                )
                """
            )
            await conn.exec_driver_sql(
                "INSERT INTO events (name, start_date, end_date) "
                "VALUES ('Legacy siege', '1200-01-01', '1200-06-01')"
            )

        await init_db(engine)

        # Column now nullable (the 0.9.1 hotfix behavior)
        assert await _end_date_notnull(engine, "events") == 0
        # Data survived the table rebuild
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text("SELECT name, start_date, end_date FROM events")
                )
            ).fetchall()
        assert rows == [("Legacy siege", "1200-01-01", "1200-06-01")]

        # Nullable really is gone: NULL end_date now inserts fine (indefinite event)
        factory = session_factory
        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO events (name, start_date, end_date) "
                    "VALUES ('Open war', '1300-01-01', NULL)"
                )
            )
            await session.commit()
            count = (
                await session.execute(
                    text("SELECT COUNT(*) FROM events WHERE end_date IS NULL")
                )
            ).scalar()
        assert count == 1
    finally:
        await engine.dispose()


async def test_legacy_migration_does_not_break_other_tables(tmp_path):
    db_path = tmp_path / "mixed.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.begin() as conn:
            # Legacy events (NOT NULL end_date) alongside a fresh-model characters table
            await conn.exec_driver_sql(
                """
                CREATE TABLE events (
                    id INTEGER NOT NULL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    description_id INTEGER,
                    start_date DATE NOT NULL,
                    end_date DATE NOT NULL
                )
                """
            )
            await conn.exec_driver_sql(
                "INSERT INTO events (name, start_date, end_date) "
                "VALUES ('Kept', '1200-01-01', '1200-06-01')"
            )

        await init_db(engine)
        # events migrated; full schema present; unrelated table intact
        tables = await _table_names(engine)
        assert ALL_TABLES <= tables
        async with engine.connect() as conn:
            assert (
                (await conn.execute(text("SELECT COUNT(*) FROM events"))).scalar() == 1
            )
            assert (
                (await conn.execute(text("SELECT COUNT(*) FROM characters"))).scalar() == 0
            )
    finally:
        await engine.dispose()
