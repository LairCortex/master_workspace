"""Tests for the event-types migration in init_db() (W4, task 2.2).

Covers: old DB (no `event_types` table, no `events.event_type_id`) gets both
via init_db(); exactly six NRI defaults seeded in order with color_index
1..6; existing events keep event_type_id NULL; a second init_db() run is
idempotent (no re-seed, no duplicated column).
"""
from __future__ import annotations

from sqlalchemy import text

from app.infrastructure.db.database import create_engine
from app.infrastructure.db.migrations import init_db

EXPECTED_DEFAULTS = [
    ("Сюжет", 1),
    ("Побочное", 2),
    ("Слух", 3),
    ("Встреча", 4),
    ("Ров будней", 5),
    ("Находка", 6),
]


async def _table_names(engine) -> set:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        ).fetchall()
    return {r[0] for r in rows} - {"sqlite_sequence"}


async def _columns(engine, table: str) -> set:
    async with engine.connect() as conn:
        rows = (await conn.exec_driver_sql(f"PRAGMA table_info({table})")).fetchall()
    return {r[1] for r in rows}


async def _seeded_types(engine) -> list[tuple[str, int, int]]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT name, color_index, sort_order FROM event_types ORDER BY sort_order, id")
            )
        ).fetchall()
    return [tuple(r) for r in rows]


async def _make_old_db(engine) -> None:
    """Pre-W4 schema for `events`: no event_type_id, no event_types table."""
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
            """
            CREATE TABLE events (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description_id INTEGER REFERENCES descriptions(id),
                start_date DATE NOT NULL,
                end_date DATE
            )
            """
        )
        await conn.exec_driver_sql(
            "INSERT INTO events (name, start_date, end_date) VALUES ('Old Event', '1200-01-01', NULL)"
        )


async def test_old_db_gets_event_types_table_column_and_seed(tmp_path):
    db_path = tmp_path / "old.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await _make_old_db(engine)

        await init_db(engine)

        # Table created, nullable FK column added
        assert "event_types" in await _table_names(engine)
        assert "event_type_id" in await _columns(engine, "events")

        # Existing event survives with NULL type
        async with engine.connect() as conn:
            row = (
                await conn.execute(text("SELECT name, event_type_id FROM events"))
            ).first()
        assert row == ("Old Event", None)

        # Exactly the six defaults, seeded in the documented order
        seeded = await _seeded_types(engine)
        assert [(name, color) for name, color, _ in seeded] == EXPECTED_DEFAULTS
        assert [so for _, _, so in seeded] == [0, 1, 2, 3, 4, 5]
    finally:
        await engine.dispose()


async def test_seed_is_exactly_six_rows(tmp_path):
    db_path = tmp_path / "fresh.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await init_db(engine)
        async with engine.connect() as conn:
            count = (
                await conn.execute(text("SELECT COUNT(*) FROM event_types"))
            ).scalar()
        assert count == 6
        assert "event_type_id" in await _columns(engine, "events")
    finally:
        await engine.dispose()


async def test_repeated_init_db_does_not_reseed(tmp_path):
    db_path = tmp_path / "old.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await _make_old_db(engine)
        await init_db(engine)
        first = await _seeded_types(engine)

        await init_db(engine)  # second startup must be a no-op
        second = await _seeded_types(engine)
        assert second == first
        assert len(second) == 6
    finally:
        await engine.dispose()


async def test_seed_guard_respects_non_empty_user_edits(tmp_path):
    """A game whose set was edited down to a single row is not reseeded."""
    db_path = tmp_path / "edited.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await init_db(engine)
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM event_types WHERE name != 'Слух'"))
            await conn.execute(
                text("UPDATE event_types SET name = 'Мой слух', color_index = 8")
            )

        await init_db(engine)

        seeded = await _seeded_types(engine)
        # Single surviving row keeps its (renamed) identity and original slot
        assert seeded == [("Мой слух", 8, 2)]
    finally:
        await engine.dispose()
