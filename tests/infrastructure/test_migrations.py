"""Tests for init_db (schema init + legacy migrations, no alembic convention).

Covers: fresh database, idempotency of a second run, the legacy
`end_date NOT NULL` rebuild (hotfix 0.9.1 scenario) with data preserved, and
the era-aware-date transfer (columns, `.bak` copy) whose keys are filled by
the python reconcile (CalendarSettingsService.reconcile_era_keys) — the SQL
era-key backfill removed in C2, design D5.
"""
from datetime import date

from sqlalchemy import text

from app.application.services.calendar_settings_service import CalendarSettingsService
from app.domain.date_era import era_key
from app.infrastructure.db.database import create_engine, create_session_factory
from app.infrastructure.db.migrations import init_db

ALL_TABLES = {
    "descriptions", "events", "organizations", "characters", "items",
    "locations", "ratings", "game_settings",
    "event_organization", "event_character", "event_item", "event_location",
    "organization_character", "organization_item", "organization_location",
    "character_item", "character_location", "character_rating",
    "item_location", "item_rating", "location_rating",
}

ERA_TABLES = ("events", "organizations", "characters", "items", "locations", "ratings")


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


# ── Era-aware dates: transfer, .bak, python key reconcile (tasks 2.2 / 2.4, C2) ──

# Pre-era ("old version") schema of the six dated tables: era columns absent,
# end_date already nullable (post-0.9.1), other old-migration columns absent
# — init_db has to re-add everything it knows.  The columns every app version
# always had (tasks/personality/image, initial schema) stay in: the startup
# key reconcile reads these tables through the ORM, so the synthetic table
# must keep the column set a real pre-era game file has.
_LEGACY_TABLE_SQL = {
    "events": """
        CREATE TABLE events (
            id INTEGER NOT NULL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            description_id INTEGER,
            start_date DATE NOT NULL,
            end_date DATE
        )
    """,
    "organizations": """
        CREATE TABLE organizations (
            id INTEGER NOT NULL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            description_id INTEGER,
            start_date DATE NOT NULL,
            end_date DATE,
            tasks TEXT,
            image TEXT
        )
    """,
    "characters": """
        CREATE TABLE characters (
            id INTEGER NOT NULL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            description_id INTEGER,
            start_date DATE NOT NULL,
            end_date DATE,
            tasks TEXT,
            personality TEXT,
            image TEXT
        )
    """,
    "items": """
        CREATE TABLE items (
            id INTEGER NOT NULL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            description_id INTEGER,
            start_date DATE NOT NULL,
            end_date DATE
        )
    """,
    "locations": """
        CREATE TABLE locations (
            id INTEGER NOT NULL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            description_id INTEGER,
            start_date DATE NOT NULL,
            end_date DATE,
            tasks TEXT,
            image TEXT
        )
    """,
    "ratings": """
        CREATE TABLE ratings (
            id INTEGER NOT NULL PRIMARY KEY,
            description_id INTEGER,
            start_date DATE NOT NULL,
            end_date DATE,
            level INTEGER NOT NULL
        )
    """,
}


async def _create_legacy_game_db(engine) -> None:
    """Synthesize a game saved by a pre-era app version, one row per table."""
    async with engine.begin() as conn:
        for table, ddl in _LEGACY_TABLE_SQL.items():
            await conn.exec_driver_sql(ddl)
        await conn.exec_driver_sql(
            "INSERT INTO events (name, start_date, end_date) "
            "VALUES ('Old war', '1200-01-01', '1200-06-01')"
        )
        await conn.exec_driver_sql(
            "INSERT INTO organizations (name, start_date, end_date) "
            "VALUES ('Old guild', '1100-01-01', '1300-01-01')"
        )
        await conn.exec_driver_sql(
            "INSERT INTO characters (name, start_date, end_date) "
            "VALUES ('Old hero', '1150-02-28', '1220-12-31')"
        )
        await conn.exec_driver_sql(
            "INSERT INTO items (name, start_date, end_date) "
            "VALUES ('Old ring', '0001-01-01', '9999-12-31')"
        )
        await conn.exec_driver_sql(
            "INSERT INTO locations (name, start_date, end_date) "
            "VALUES ('Old keep', '1000-03-01', NULL)"
        )
        await conn.exec_driver_sql(
            "INSERT INTO ratings (start_date, end_date, level) "
            "VALUES ('1180-05-05', '1190-05-05', 7)"
        )


async def _date_snapshot(engine) -> dict:
    """(start_date, end_date) rows of every dated table, order-preserved."""
    snapshot = {}
    async with engine.connect() as conn:
        for table in ERA_TABLES:
            snapshot[table] = (
                await conn.execute(
                    text(f"SELECT id, start_date, end_date FROM {table} ORDER BY id")
                )
            ).fetchall()
    return snapshot


async def _era_state(engine, table: str) -> list:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text(
                    f"SELECT id, start_date, end_date, start_bc, end_bc, "
                    f"start_key, end_key FROM {table} ORDER BY id"
                )
            )
        ).fetchall()


async def _reconcile(engine) -> int:
    """One startup python pass over the era keys (design D5) — the replacement
    of the SQL backfill removed in C2; run by Application.start() after the
    calendar load.  Returns the number of corrected rows."""
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        return await CalendarSettingsService().reconcile_era_keys(session)


async def test_old_game_transfers_to_ce_era_idempotently(tmp_path):
    """Spec «Перенос старых сохранений»: dates untouched, era «н.э.», keys
    recomputed by the python reconcile from the active calendar (design D5),
    exactly one .bak copy, second run changes nothing."""
    db_path = tmp_path / "game.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await _create_legacy_game_db(engine)
        dates_before = await _date_snapshot(engine)

        await init_db(engine)
        # Schema migration alone no longer derives keys — the python pass
        # that start() runs after the calendar load does.
        assert await _reconcile(engine) > 0

        # dates identical to the pre-transfer snapshot (no value drift)
        assert dates_before == await _date_snapshot(engine)

        for table in ERA_TABLES:
            for row_id, start, end, start_bc, end_bc, start_key, end_key in \
                    await _era_state(engine, table):
                # Everything transferred reads as our era...
                assert (start_bc, end_bc) == (0, 0), table
                # ...and the python reconcile equals the era_key (D2/D5),
                # i.e. the exact numbers the deleted SQL formula produced.
                assert start_key == era_key(date.fromisoformat(start), False), table
                if end is not None:
                    assert end_key == era_key(date.fromisoformat(end), False), table
                else:
                    assert end_key is None, table

        # A non-erasable copy appeared before the transfer
        assert (tmp_path / "game.db.bak").exists()

        # Second open: no data/key drift, no second copy, .bak untouched
        dates_after_first = await _date_snapshot(engine)
        keys_after_first = {t: await _era_state(engine, t) for t in ERA_TABLES}
        bak_bytes = (tmp_path / "game.db.bak").read_bytes()
        await init_db(engine)
        assert await _reconcile(engine) == 0  # idempotent: nothing rewritten
        assert {t: await _era_state(engine, t) for t in ERA_TABLES} == keys_after_first
        assert await _date_snapshot(engine) == dates_after_first
        assert sorted(p.name for p in tmp_path.iterdir()) == ["game.db", "game.db.bak"]
        assert (tmp_path / "game.db.bak").read_bytes() == bak_bytes
    finally:
        await engine.dispose()


async def test_fresh_new_version_game_gets_no_backup_copy(tmp_path):
    """Spec: games created by the new version get no copy without a transfer."""
    db_path = tmp_path / "game.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await init_db(engine)
        assert db_path.exists()
        assert not (tmp_path / "game.db.bak").exists()
    finally:
        await engine.dispose()


async def test_reconcile_python_matches_era_key_battery(tmp_path):
    """Design D5 battery: the python reconcile reproduces era_key at the same
    113 anchor dates of both eras (226 keys: leap/non-leap years, era borders,
    0001/9999 borders) where the deleted SQL formula was checked against the
    old scheme; the numbers-equal-old-scheme scenario itself is covered by
    tests/application/test_calendar_settings_service.py."""
    years = [1, 2, 3, 4, 5, 99, 100, 101, 1000, 1581, 1582, 1583, 1600,
             1700, 1800, 1900, 2000, 2023, 2024, 2025, 2026, 9998, 9999]
    md = [(1, 1), (2, 28), (2, 29), (3, 1), (7, 19), (12, 31)]
    samples = []
    for year in years:
        for month, day in md:
            try:
                samples.append(date(year, month, day))
            except ValueError:
                pass  # 0099/0100/1700/1800/1900/9900s are not leap years
    db_path = tmp_path / "game.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await init_db(engine)
        # Raw INSERTs bypass the ORM hooks: every row arrives key-less,
        # exactly like an old-version write (task 2.4 shapes included).
        async with engine.begin() as conn:
            for i, d in enumerate(samples):
                for is_bc in (0, 1):
                    await conn.exec_driver_sql(
                        "INSERT INTO events (name, start_date, start_bc) "
                        "VALUES (?, ?, ?)",
                        (f"probe-{i}-{is_bc}", d.isoformat(), is_bc),
                    )
            nulls = (await conn.execute(
                text("SELECT COUNT(*) FROM events WHERE start_key IS NULL")
            )).scalar()
            assert nulls == 2 * len(samples)  # nothing keyed before the run

        await init_db(engine)  # schema work no longer derives keys…
        assert await _reconcile(engine) == 2 * len(samples)  # …the python pass does

        async with engine.connect() as conn:
            rows = (await conn.execute(
                text("SELECT start_date, start_bc, start_key FROM events")
            )).fetchall()
        assert len(rows) == 2 * len(samples)
        for d_iso, is_bc, key in rows:
            assert key == era_key(date.fromisoformat(d_iso), bool(is_bc))
    finally:
        await engine.dispose()


async def test_old_version_row_is_keyed_on_next_open(tmp_path):
    """Task 2.4: a row INSERTed without keys (old-version emulation) receives
    its key from the startup reconcile Application.start() runs and takes its
    correct chronological place."""
    db_path = tmp_path / "game.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await init_db(engine)  # already-migrated schema (new-version game)

        # The old version knows neither the era columns nor the keys.
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "INSERT INTO events (name, start_date, end_date) "
                "VALUES ('Written by the old app', '0444-03-15', NULL)"
            )
            await conn.exec_driver_sql(
                "INSERT INTO events (name, start_date, end_date) "
                "VALUES ('Modern', '2026-01-01', NULL)"
            )

        await init_db(engine)  # «next open»: schema pass, then the D5 pass
        await _reconcile(engine)

        async with engine.connect() as conn:
            row = (await conn.execute(
                text("SELECT start_bc, start_key FROM events "
                     "WHERE name = 'Written by the old app'")
            )).first()
            assert row == (0, era_key(date(444, 3, 15), False))
            # Correct order in the windowed selection (keys sort, text lies)
            names = (await conn.execute(
                text("SELECT name FROM events ORDER BY start_key, id")
            )).scalars().all()
            assert names == ["Written by the old app", "Modern"]
            covered = (await conn.execute(
                text("SELECT name FROM events "
                     "WHERE start_key <= :k AND (end_key IS NULL OR end_key >= :k)"),
                {"k": era_key(date(2026, 8, 1), False)},
            )).scalars().all()
            assert "Written by the old app" in covered
    finally:
        await engine.dispose()
