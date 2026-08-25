"""Task 7.3: character sheet templates ride the .nri game export and are
restored on import (spec «Вхождение в экспорт игры»).

The archive zips the whole game.db — this integration test proves the
template row round-trips through export/import with fields, geometry,
and stable ids intact.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.application.services.character_sheet_service import CharacterSheetService
from app.domain.entities.character_sheet import SheetField, SheetPage, SheetTemplate
from app.domain.enums.field_type import FieldType
from app.domain.enums.sheet_orientation import SheetOrientation
from app.infrastructure.db.database import create_engine, create_session_factory
from app.infrastructure.db.game_manager import delete_game, export_game, import_game
from app.infrastructure.db.migrations import init_db
from app.infrastructure.db.models import CharacterSheetModel
from app.infrastructure.repositories.character_sheet_repository import CharacterSheetRepository


@pytest.fixture
def games_dir(tmp_path, monkeypatch):
    dir_ = tmp_path / "games"
    dir_.mkdir()
    monkeypatch.setattr(
        "app.infrastructure.db.game_manager._resolve_games_dir",
        lambda: dir_,
    )
    return dir_


def _sample_template() -> SheetTemplate:
    template = SheetTemplate(
        name="Лист персонажа",
        orientation=SheetOrientation.LANDSCAPE,
        pages=[
            SheetPage(
                name="Стр 1",
                fields=[
                    SheetField(
                        id="stable-field-01",
                        type=FieldType.NUMBER,
                        x=12.5, y=33.75, w=80.0, h=24.0,
                        label="Хиты", min_value=1, max_value=40,
                    ),
                    SheetField(
                        id="stable-field-02",
                        type=FieldType.SHORT_TEXT,
                        x=120.0, y=10.0, w=200.0, h=22.0,
                        label="Имя", default_value="Гэндальф",
                    ),
                ],
            ),
            SheetPage(
                name="Стр 2",
                fields=[
                    SheetField(
                        id="stable-field-03",
                        type=FieldType.PORTRAIT,
                        x=40.0, y=60.0, w=120.0, h=150.0,
                    ),
                ],
            ),
        ],
    )
    return template


async def _stored_template(session) -> CharacterSheetModel:
    result = await session.execute(select(CharacterSheetModel))
    rows = result.scalars().all()
    assert len(rows) == 1
    return rows[0]


async def test_template_survives_nri_export_import(games_dir, tmp_path):
    # ── source game: a real DB file with the full schema and a template ──
    source_dir = games_dir / "Исходник"
    source_dir.mkdir()
    (source_dir / "images").mkdir()
    db_src = source_dir / "game.db"
    db_src.touch()

    engine = create_engine(f"sqlite+aiosqlite:///{db_src}")
    try:
        await init_db(engine, image_dir=str(source_dir / "images"))
        factory = create_session_factory(engine)
        async with factory() as session:
            template = _sample_template()
            await CharacterSheetService(CharacterSheetRepository(session)).create(template)
    finally:
        await engine.dispose()

    # ── export → (the source game leaves the library) → import ──────────
    archive = tmp_path / "sheet_game.nri"
    export_game(str(db_src), archive)
    delete_game(str(db_src))
    imported_db = import_game(archive)
    assert imported_db.name == "game.db"
    assert imported_db.parent.name == "Исходник"

    # ── the imported game opens (init_db is idempotent) and the template
    #     round-trips: all pages, fields, geometry, and stable ids intact ──
    engine2 = create_engine(f"sqlite+aiosqlite:///{imported_db}")
    try:
        await init_db(engine2, image_dir=str(imported_db.parent / "images"))
        factory2 = create_session_factory(engine2)
        async with factory2() as session2:
            row = await _stored_template(session2)
    finally:
        await engine2.dispose()

    assert row.name == "Лист персонажа"
    assert row.orientation == SheetOrientation.LANDSCAPE.value

    imported = SheetTemplate.from_dict({
        "name": row.name,
        "orientation": row.orientation,
        "pages": json.loads(row.pages),
    })
    original = _sample_template()
    assert [p.name for p in imported.pages] == [p.name for p in original.pages]
    for (imported_page, original_page) in zip(imported.pages, original.pages):
        assert [f.id for f in imported_page.fields] == [f.id for f in original_page.fields]
        for imp, org in zip(imported_page.fields, original_page.fields):
            assert (imp.x, imp.y, imp.w, imp.h) == (org.x, org.y, org.w, org.h)
            assert imp.label == org.label
            assert imp.type is org.type
            assert imp.default_value == org.default_value
