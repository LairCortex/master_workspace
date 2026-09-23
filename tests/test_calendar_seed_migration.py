"""Tests for the calendar-key seeding in init_db() (piece C4, task 4.4, design D7).

Covers the game-launcher delta spec «Создание новой игры»: a database whose
schema is created by this version gets exactly the two keys —
``game_calendar`` (the «Стандартный» preset) and ``calendar_wizard_seen``
(«не показан»); a game that already had a schema (the migration path, old
games included) never catches the seeding on a later open; and a repeated
init_db over the same file is a no-op that cannot duplicate the keys.
"""
from __future__ import annotations

from sqlalchemy import text

from app.domain.game_calendar import (
    StandardCalendar,
)
from app.infrastructure.calendar_storage import (
    encode_calendar,
)
from app.infrastructure.repositories.game_settings_repository import (
    CALENDAR_SETTINGS_KEY,
    CALENDAR_WIZARD_SEEN_KEY,
    CALENDAR_WIZARD_SEEN_NO,
)
from app.infrastructure.db.database import create_engine
from app.infrastructure.db.migrations import init_db

EXPECTED_SEED = {
    CALENDAR_SETTINGS_KEY: encode_calendar(StandardCalendar()),
    CALENDAR_WIZARD_SEEN_KEY: CALENDAR_WIZARD_SEEN_NO,
}


async def _settings_rows(engine) -> dict[str, str]:
    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT key, value FROM game_settings"))).fetchall()
    return {row[0]: row[1] for row in rows}


async def _make_old_db(engine) -> None:
    """Pre-C2-shaped database: the schema exists (so init_db sees a game, not
    a blank file), but neither calendar key was ever written."""
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
            "CREATE TABLE game_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')"
        )
        await conn.exec_driver_sql(
            "INSERT INTO events (name, start_date, end_date) VALUES ('Old Event', '1200-01-01', NULL)"
        )


async def test_fresh_schema_is_seeded_with_the_two_keys(tmp_path):
    # scenario «Новая игра рождается с посевом»: the launcher's empty file
    # (touch, no schema) opens for the first time → init_db creates the
    # schema and seeds exactly the two keys, nothing else
    db_path = tmp_path / "new.db"  # nonexistent file == the launcher's blank game.db
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await init_db(engine)

        rows = await _settings_rows(engine)
        assert rows == EXPECTED_SEED
    finally:
        await engine.dispose()


async def test_old_game_on_the_migration_path_is_never_seeded(tmp_path):
    # scenario «Старую игру посев не догоняет»: an existing schema stays
    # keyless through init_db — and stays keyless when opened repeatedly
    db_path = tmp_path / "old.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await _make_old_db(engine)

        await init_db(engine)
        assert await _settings_rows(engine) == {}

        await init_db(engine)  # repeated open of the old game
        assert await _settings_rows(engine) == {}
        # the old row survived the migration passes untouched
        async with engine.connect() as conn:
            event = (
                await conn.execute(text("SELECT name FROM events"))
            ).scalars().all()
        assert event == ["Old Event"]
    finally:
        await engine.dispose()


async def test_repeated_init_db_does_not_reseed_or_overwrite(tmp_path):
    db_path = tmp_path / "new.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await init_db(engine)
        first = await _settings_rows(engine)

        # a player already promoted a custom calendar meanwhile (the C4
        # wizard wrote the key) — a second init_db must not roll it back
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "UPDATE game_settings SET value = ? WHERE key = ?",
                ('{"v": 1, "kind": "custom", "months": ['
                 '{"name": "Черновершь", "length": 12}],'
                 ' "week_names": ["а", "б"], "intercalary": []}',
                 CALENDAR_SETTINGS_KEY),
            )
            await conn.exec_driver_sql(
                "UPDATE game_settings SET value = ? WHERE key = ?",
                ("1", CALENDAR_WIZARD_SEEN_KEY),
            )

        await init_db(engine)  # second startup of the same game
        after = await _settings_rows(engine)

        assert after[CALENDAR_SETTINGS_KEY].find("Черновершь") != -1  # user choice kept
        assert after[CALENDAR_WIZARD_SEEN_KEY] == "1"
        # and nothing was duplicated even in the untouched seed pass
        await init_db(engine)
        rows_again = await _settings_rows(engine)
        assert len(rows_again) == 2
        assert rows_again[CALENDAR_WIZARD_SEEN_KEY] == "1"
        assert first[CALENDAR_SETTINGS_KEY] != after[CALENDAR_SETTINGS_KEY]
    finally:
        await engine.dispose()
