"""The dd-card-redesign task 2.2 migration floors (design Д6).

Three floors, each through its own door:

* a game whose module predates the redesign — a kernel schema plus the
  OLD-shape ``dd_character_ext`` row written before this version existed —
  opens under ``init_db`` and gains the ten nullable mechanics columns and
  the ``dd_character_feat_link`` table, its stored row read on intact
  (spec «чтение без потерь»);
* a second (and third) ``init_db`` pass over the same file neither fails
  nor duplicates anything (spec «повторный запуск идемпотентен»);
* a file without the module's table stays byte-for-byte untouched — the
  guard returns before any DDL, so the kernel migration is DDL-neutral for
  ordinary games.

The pre-states are built through the bootstrap test's idiom — create the
kernel tables filtered by name — so no process-level import of ``app.dd``
can leak the NEW-shape module tables into a synthesized old game; in the
isolated per-module run this very file imports no module code until the
last test, which is what makes the kernel-created feat table honest there.
That last test then pins the hand-written DDL (the kernel must not import
``app.dd``, the layers stay one-way) column-for-column against the module's
model declarations and walks both migrated tables through the module's own
ORM doors.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import text

from app.infrastructure.db.database import create_engine
from app.infrastructure.db.migrations import _migrate_dd_character_mechanics, init_db
from app.infrastructure.db.models import Base

#: The pre-redesign ``dd_character_ext`` exactly as the previous release's
#: module door created it — five link triples, level, sheet id, raw document,
#: text blocks; no mechanics columns. The feat link table simply did not
#: exist in that world.
_OLD_EXT_DDL = """
CREATE TABLE dd_character_ext (
    character_id INTEGER NOT NULL,
    race_source_key VARCHAR NOT NULL,
    race_ref_id VARCHAR NOT NULL,
    race_snapshot_name VARCHAR NOT NULL,
    subrace_source_key VARCHAR NOT NULL,
    subrace_ref_id VARCHAR NOT NULL,
    subrace_snapshot_name VARCHAR NOT NULL,
    class_source_key VARCHAR NOT NULL,
    class_ref_id VARCHAR NOT NULL,
    class_snapshot_name VARCHAR NOT NULL,
    subclass_source_key VARCHAR NOT NULL,
    subclass_ref_id VARCHAR NOT NULL,
    subclass_snapshot_name VARCHAR NOT NULL,
    background_source_key VARCHAR NOT NULL,
    background_ref_id VARCHAR NOT NULL,
    background_snapshot_name VARCHAR NOT NULL,
    level INTEGER,
    lss_sheet_id TEXT,
    raw_document TEXT,
    text_blocks TEXT,
    PRIMARY KEY (character_id),
    FOREIGN KEY (character_id) REFERENCES characters (id) ON DELETE CASCADE
)
"""

_MECHANICS_COLUMNS = (
    "strength",
    "dexterity",
    "constitution",
    "intelligence",
    "wisdom",
    "charisma",
    "speed",
    "alignment",
    "slots_json",
    "prof_json",
)


async def _table_names(engine) -> set[str]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        ).fetchall()
    return {row[0] for row in rows}


async def _columns(engine, table: str) -> list[str]:
    async with engine.connect() as conn:
        rows = (await conn.exec_driver_sql(f"PRAGMA table_info({table})")).fetchall()
    return [row[1] for row in rows]


async def _create_kernel_schema(engine) -> None:
    """The kernel tables alone, filtered by name (the bootstrap floor's
    idiom from ``tests/dd/test_character_extension.py``): the synthesized
    old game carries module tables ONLY as this file writes them."""
    kernel_tables = [
        table
        for name, table in Base.metadata.tables.items()
        if not name.startswith("dd_")
    ]
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=kernel_tables, checkfirst=True
            )
        )


async def _make_old_module_game(db_path) -> int:
    """The game file as the previous release left it: kernel schema, one
    character, one old-shape D&D face with real stored values. Returns the
    character id of the stored row."""
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await _create_kernel_schema(engine)
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "INSERT INTO characters (name, start_date) VALUES ('Грог', '1300-01-01')"
            )
            char_id = (await conn.exec_driver_sql("SELECT last_insert_rowid()")).scalar()
            await conn.exec_driver_sql(_OLD_EXT_DDL)
            await conn.exec_driver_sql(
                "INSERT INTO dd_character_ext (character_id, race_source_key, "
                "race_ref_id, race_snapshot_name, subrace_source_key, subrace_ref_id, "
                "subrace_snapshot_name, class_source_key, class_ref_id, "
                "class_snapshot_name, subclass_source_key, subclass_ref_id, "
                "subclass_snapshot_name, background_source_key, background_ref_id, "
                "background_snapshot_name, level, lss_sheet_id, raw_document, "
                "text_blocks) VALUES (?, 'srd', 'orc', 'Орк', '', '', '', 'srd', "
                "'fighter', 'Воин', '', '', '', '', '', '', 7, 'sheet-42', "
                "'{\"jsonType\": \"character\"}', '{\"Биография\": \"Из племени\"}')",
                (char_id,),
            )
        return char_id
    finally:
        await engine.dispose()


async def test_old_module_game_gains_columns_and_feat_table_with_data_intact(tmp_path):
    db_path = tmp_path / "old_dd_game.db"
    char_id = await _make_old_module_game(db_path)

    # The pre-migration state: the old columns only, no feat table in sight.
    check = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        assert not set(_MECHANICS_COLUMNS) & set(await _columns(check, "dd_character_ext"))
        assert "dd_character_feat_link" not in await _table_names(check)
    finally:
        await check.dispose()

    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await init_db(engine)  # the new version opens the old game

        columns = await _columns(engine, "dd_character_ext")
        assert set(_MECHANICS_COLUMNS) <= set(columns)
        tables = await _table_names(engine)
        assert "dd_character_feat_link" in tables
        feat_columns = await _columns(engine, "dd_character_feat_link")
        assert feat_columns == ["id", "character_id", "source_key", "ref_id", "snapshot_name"]

        # «Чтение без потерь»: the stored face keeps every old value; the
        # new columns are NULLs — «не задано», not fabricated defaults.
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT race_ref_id, class_snapshot_name, level, lss_sheet_id, "
                        "raw_document, text_blocks, strength, speed, alignment, "
                        "slots_json, prof_json FROM dd_character_ext "
                        "WHERE character_id = :char_id"
                    ),
                    {"char_id": char_id},
                )
            ).first()
        assert row == (
            "orc",
            "Воин",
            7,
            "sheet-42",
            '{"jsonType": "character"}',
            '{"Биография": "Из племени"}',
            None,
            None,
            None,
            None,
            None,
        )
    finally:
        await engine.dispose()


async def test_repeated_init_db_is_idempotent_and_data_safe(tmp_path):
    db_path = tmp_path / "old_dd_game2.db"
    char_id = await _make_old_module_game(db_path)

    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await init_db(engine)
        first_columns = await _columns(engine, "dd_character_ext")
        first_tables = await _table_names(engine)

        # A restart, then another — the PRAGMA-decided column skips and the
        # presence-decided table guard: no failure, no duplicate column, no
        # second table, no touched row.
        await init_db(engine)
        await init_db(engine)

        assert await _columns(engine, "dd_character_ext") == first_columns
        assert await _table_names(engine) == first_tables
        assert first_columns.count("strength") == 1
        async with engine.connect() as conn:
            level, snapshot = (
                await conn.execute(
                    text(
                        "SELECT level, race_snapshot_name FROM dd_character_ext "
                        "WHERE character_id = :char_id"
                    ),
                    {"char_id": char_id},
                )
            ).first()
        assert (level, snapshot) == (7, "Орк")
    finally:
        await engine.dispose()


async def test_migration_is_ddl_neutral_without_the_module_table(tmp_path):
    """The guard branch: the module was never enabled on this game, so its
    own table is absent and the migration must not create anything — an
    ordinary game's schema stays exactly what create_all alone made."""
    db_path = tmp_path / "ordinary_game.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await _create_kernel_schema(engine)
        before = await _table_names(engine)
        async with engine.begin() as conn:
            await _migrate_dd_character_mechanics(conn)
        assert await _table_names(engine) == before
        assert not {
            "dd_character_ext",
            "dd_character_feat_link",
            "dd_character_spell_link",
        } & before
    finally:
        await engine.dispose()


async def test_migrated_tables_are_the_module_orm_shape_read_and_write(tmp_path):
    """The pin that the kernel's hand-written DDL matches the module's ORM
    declarations: after the migration the module's own doors read the
    migrated ``dd_character_ext`` (the old row survives the ORM read, its
    never-written mechanics as the empty block) and insert through
    ``dd_character_feat_link``. The module is imported here, inside the
    LAST test: until then this process never saw the module, which is what
    made the kernel DDL above the only possible creator of the feat table."""
    db_path = tmp_path / "old_dd_game3.db"
    old_char_id = await _make_old_module_game(db_path)
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await init_db(engine)

        from app.dd.application.dnd_character_extension_service import (
            DndCharacterExtensionService,
        )
        from app.dd.domain.character import DdFeatLink
        from app.dd.domain.character_mechanics import empty_mechanics
        from app.dd.infrastructure.db.dd_models import (
            DdCharacterExtModel,
            DdCharacterFeatLinkModel,
        )
        from app.infrastructure.db.database import create_session_factory
        from app.infrastructure.db.models import CharacterModel
        from app.infrastructure.db.uow import GameSessionUoW

        # Column-for-column parity of both migrated shapes with the models.
        feat_model_columns = [
            column.name for column in DdCharacterFeatLinkModel.__table__.columns
        ]
        assert await _columns(engine, "dd_character_feat_link") == feat_model_columns
        ext_model_columns = [
            column.name for column in DdCharacterExtModel.__table__.columns
        ]
        assert set(ext_model_columns) <= set(await _columns(engine, "dd_character_ext"))

        factory = create_session_factory(engine)
        async with factory() as session:
            unit = GameSessionUoW(session)
            service = DndCharacterExtensionService(unit)

            # The old face reads through the new ORM mapping…
            ext = await service.get_ext(old_char_id)
            assert ext.level == 7
            assert ext.links["class"].snapshot_name == "Воин"
            # …and its never-written mechanics read as the empty block.
            assert await service.get_mechanics(old_char_id) == empty_mechanics()

            # The migrated feat table serves the model's writes/reads: the
            # idempotent add keeps one row per pair, order preserved.
            async with unit.transaction():
                fresh = CharacterModel(name="Мия", start_date=date(1301, 1, 1))
                session.add(fresh)
            await service.add_feat_link(
                fresh.id, DdFeatLink("srd-2014", "feat-alert", "Настороженность")
            )
            await service.add_feat_link(
                fresh.id, DdFeatLink("srd-2014", "feat-alert", "Настороженность")
            )
            await service.add_feat_link(fresh.id, DdFeatLink("grim", "42", "Своя черта"))
            assert await service.get_feat_links(fresh.id) == [
                DdFeatLink("srd-2014", "feat-alert", "Настороженность"),
                DdFeatLink("grim", "42", "Своя черта"),
            ]
            # The old character never gains a feat from the other's writes.
            assert await service.get_feat_links(old_char_id) == []
    finally:
        await engine.dispose()
