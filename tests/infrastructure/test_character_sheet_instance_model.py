"""Tests for the character_sheet_instances schema — TDD: red first.

Covers task 2.1: create_all creates the table with expected columns and
constraints (name UNIQUE, unique character_id allowing several NULLs,
FK RESTRICT on template, FK SET NULL on character); init_db() on an old
DB adds the table without harming existing data.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.infrastructure.db.database import create_engine as app_create_engine
from app.infrastructure.db.migrations import init_db
from app.infrastructure.db.models import Base

EXPECTED_COLUMNS = {
    "id", "name", "template_id", "character_id", "values", "created_at", "updated_at",
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


async def _fk_list(engine, table: str) -> list:
    async with engine.connect() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        return (await conn.exec_driver_sql(f"PRAGMA foreign_key_list({table})")).fetchall()


async def test_create_all_fresh_db_has_character_sheet_instances():
    engine = app_create_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        tables = await _table_names(engine)
        assert "character_sheet_instances" in tables

        cols = await _columns(engine, "character_sheet_instances")
        assert EXPECTED_COLUMNS <= cols

        ddl = await _table_ddl(engine, "character_sheet_instances")
        assert "UNIQUE" in ddl.upper()
    finally:
        await engine.dispose()


async def test_init_db_adds_table_to_old_db_and_preserves_data(tmp_path):
    db_path = tmp_path / "old.db"
    engine = app_create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
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
        assert "character_sheet_instances" in tables
        assert "descriptions" in tables

        cols = await _columns(engine, "character_sheet_instances")
        assert EXPECTED_COLUMNS <= cols

        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT characteristics, backstory FROM descriptions")
                )
            ).first()
        assert row == ("c", "b")
    finally:
        await engine.dispose()


class TestInstanceConstraints:
    async def _engine(self):
        engine = app_create_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        return engine

    async def _seed_template(self, conn, template_id: int = 1) -> None:
        await conn.execute(
            text(
                "INSERT INTO character_sheets "
                "(id, name, schema_version, orientation, pages, created_at, updated_at) "
                "VALUES (:id, :name, 2, 'portrait', :pages, :now, :now)"
            ),
            {
                "id": template_id,
                "name": f"T{template_id}",
                "pages": '[{"name": "Страница 1", "fields": []}]',
                "now": datetime(2024, 1, 1),
            },
        )

    async def _seed_character(self, conn, character_id: int = 1) -> None:
        await conn.execute(
            text(
                "INSERT INTO characters (id, name, start_date, rating) "
                "VALUES (:id, :name, :start, 1)"
            ),
            {
                "id": character_id,
                "name": f"C{character_id}",
                "start": date(1300, 1, 1),
            },
        )

    async def test_unique_name(self):
        engine = await self._engine()
        try:
            async with engine.begin() as conn:
                await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                await self._seed_template(conn)
                await conn.execute(
                    text(
                        "INSERT INTO character_sheet_instances "
                        '(name, template_id, "values", created_at, updated_at) '
                        "VALUES ('Лист', 1, '{}', :now, :now)"
                    ),
                    {"now": datetime(2024, 1, 1)},
                )
                with pytest.raises(IntegrityError):
                    await conn.execute(
                        text(
                            "INSERT INTO character_sheet_instances "
                            '(name, template_id, "values", created_at, updated_at) '
                            "VALUES ('Лист', 1, '{}', :now, :now)"
                        ),
                        {"now": datetime(2024, 1, 1)},
                    )
        finally:
            await engine.dispose()

    async def test_unique_character_id_allows_several_nulls(self):
        engine = await self._engine()
        try:
            async with engine.begin() as conn:
                await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                await self._seed_template(conn)
                now = datetime(2024, 1, 1)
                await conn.execute(
                    text(
                        "INSERT INTO character_sheet_instances "
                        '(name, template_id, character_id, "values", created_at, updated_at) '
                        "VALUES ('A', 1, NULL, '{}', :now, :now)"
                    ),
                    {"now": now},
                )
                await conn.execute(
                    text(
                        "INSERT INTO character_sheet_instances "
                        '(name, template_id, character_id, "values", created_at, updated_at) '
                        "VALUES ('B', 1, NULL, '{}', :now, :now)"
                    ),
                    {"now": now},
                )
                count = (
                    await conn.execute(text("SELECT COUNT(*) FROM character_sheet_instances"))
                ).scalar()
                assert count == 2
        finally:
            await engine.dispose()

    async def test_unique_character_id_rejects_duplicate_non_null(self):
        engine = await self._engine()
        try:
            async with engine.begin() as conn:
                await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                await self._seed_template(conn)
                await self._seed_character(conn, 1)
                now = datetime(2024, 1, 1)
                await conn.execute(
                    text(
                        "INSERT INTO character_sheet_instances "
                        '(name, template_id, character_id, "values", created_at, updated_at) '
                        "VALUES ('A', 1, 1, '{}', :now, :now)"
                    ),
                    {"now": now},
                )
                with pytest.raises(IntegrityError):
                    await conn.execute(
                        text(
                            "INSERT INTO character_sheet_instances "
                            '(name, template_id, character_id, "values", created_at, updated_at) '
                            "VALUES ('B', 1, 1, '{}', :now, :now)"
                        ),
                        {"now": now},
                    )
        finally:
            await engine.dispose()

    async def test_fk_restrict_on_template(self):
        engine = await self._engine()
        try:
            async with engine.begin() as conn:
                await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                await self._seed_template(conn)
                now = datetime(2024, 1, 1)
                await conn.execute(
                    text(
                        "INSERT INTO character_sheet_instances "
                        '(name, template_id, "values", created_at, updated_at) '
                        "VALUES ('A', 1, '{}', :now, :now)"
                    ),
                    {"now": now},
                )
                with pytest.raises(IntegrityError):
                    await conn.execute(text("DELETE FROM character_sheets WHERE id=1"))
        finally:
            await engine.dispose()

    async def test_fk_set_null_on_character(self):
        engine = await self._engine()
        try:
            async with engine.begin() as conn:
                await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                await self._seed_template(conn)
                await self._seed_character(conn, 1)
                now = datetime(2024, 1, 1)
                await conn.execute(
                    text(
                        "INSERT INTO character_sheet_instances "
                        '(name, template_id, character_id, "values", created_at, updated_at) '
                        "VALUES ('A', 1, 1, '{}', :now, :now)"
                    ),
                    {"now": now},
                )
                await conn.execute(text("DELETE FROM characters WHERE id=1"))
                row = (
                    await conn.execute(
                        text("SELECT character_id FROM character_sheet_instances WHERE name='A'")
                    )
                ).first()
                assert row[0] is None
        finally:
            await engine.dispose()

    async def test_fk_ddl_actions(self):
        engine = app_create_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            fks = await _fk_list(engine, "character_sheet_instances")
            by_from = {row[3]: row for row in fks}  # from column
            assert by_from["template_id"][2] == "character_sheets"
            assert by_from["template_id"][6].upper() == "RESTRICT"
            assert by_from["character_id"][2] == "characters"
            assert by_from["character_id"][6].upper() == "SET NULL"
        finally:
            await engine.dispose()
