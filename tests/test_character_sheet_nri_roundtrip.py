"""Character-sheet templates through .nri export/import (task 8.2).

Templates live in ``game.db`` → the v2 export/import must carry every row
(name, schema_version, orientation, pages) unchanged, with no code change in
the export pipeline (design D7). A sheet image field references ``images``
by row id (design D6): the .nri must carry both the reference (in ``pages``)
and the files (``images/**``).
"""
from __future__ import annotations

import base64
import json
import sqlite3

from app.application.services.character_sheet_service import CharacterSheetService
from app.domain.enums.field_type import FieldType
from app.infrastructure.db.database import create_engine, create_session_factory
from app.infrastructure.db.game_manager import (
    create_game,
    delete_game,
    export_game,
    import_game,
    get_db_url,
)
from app.infrastructure.db.migrations import init_db
from app.infrastructure.images.store import ImageStore
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)

_COLUMNS = "name, schema_version, orientation, pages"

# A 1x1 PNG — decodable by the ImageStore pipeline without any test assets.
_PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _rows(db_path) -> list[tuple]:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            f"SELECT {_COLUMNS} FROM character_sheets ORDER BY name"
        ).fetchall()
    finally:
        conn.close()


_IMG_COLUMNS = "id, sha256, ext, width, height, size_bytes, created_at"


def _img_rows(db_path) -> list[tuple]:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            f"SELECT {_IMG_COLUMNS} FROM images ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


async def test_templates_survive_nri_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.infrastructure.db.game_manager.get_games_dir",
        lambda: tmp_path / "games",
    )

    db_path = create_game("Сюжет")
    engine = create_engine(get_db_url(db_path))
    factory = create_session_factory(engine)
    try:
        await init_db(engine, image_dir=db_path.parent / "images")
        session = factory()
        try:
            service = CharacterSheetService(CharacterSheetRepository(session))
            row = await service.create("Иван")
            await service.create("Дракон")

            # Give one template a real layout (label + textarea).
            template = await service.load(row.id)
            template.add_field(FieldType.LABEL, (100.0, 100.0))
            template.add_field(FieldType.TEXTAREA, (100.0, 150.0))
            await service.update_pages(row.id, template)
        finally:
            await session.close()
    finally:
        await engine.dispose()

    original = _rows(db_path)
    assert {r[0] for r in original} == {"Иван", "Дракон"}
    # create and update_pages both persist the current schema (design D3)
    assert all(r[1] == 2 for r in original)
    assert all(r[2] == "portrait" for r in original)

    dest = tmp_path / "сюжет.nri"
    export_game(str(db_path), dest)

    # The importer lands in the same games dir: the "other side" has no
    # original game, so delete it before importing.
    delete_game(str(db_path))
    imported = import_game(dest)
    assert imported.is_file()

    assert _rows(imported) == original


# ── A-playable: an image field on a sheet page (design D6) ─────────────────


async def test_sheet_image_survives_nri_roundtrip(tmp_path, monkeypatch):
    """A sheet with an image field must keep both the reference (in ``pages``)
    and the files (``images/**``) across .nri export/import — the imported
    game's field resolves the same image row (task 19 / 7.2)."""
    monkeypatch.setattr(
        "app.infrastructure.db.game_manager.get_games_dir",
        lambda: tmp_path / "games",
    )

    db_path = create_game("Картинка")
    images_dir = db_path.parent / "images"
    engine = create_engine(get_db_url(db_path))
    factory = create_session_factory(engine)
    try:
        await init_db(engine, image_dir=images_dir)
        session = factory()
        try:
            store = ImageStore(session, images_dir)
            service = CharacterSheetService(
                CharacterSheetRepository(session), image_store=store
            )
            row = await service.create("Герой")
            template = await service.load(row.id)
            field = template.add_field(FieldType.IMAGE, (100.0, 100.0))
            image_id = await store.store(_PNG_1PX)
            field.image_id = image_id
            await service.update_pages(row.id, template)

            # committed: exactly one referrer (the sheet field) and the files
            assert await store.refcount(image_id) == 1
            assert (await store.original_file_path(image_id)).exists()
        finally:
            await session.close()
    finally:
        await engine.dispose()

    pages_before = _rows(db_path)[0][3]
    data_before = json.loads(pages_before)
    image_field_before = next(
        f for f in data_before[0]["fields"] if f["type"] == "image"
    )

    dest = tmp_path / "картинка.nri"
    export_game(str(db_path), dest)
    delete_game(str(db_path))
    imported = import_game(dest)
    assert imported.is_file()

    # 1) the row and its pages JSON ride through unchanged
    rows = _rows(imported)
    assert len(rows) == 1
    assert rows[0][0] == "Герой"
    assert rows[0][1] == 2
    data = json.loads(rows[0][3])
    image_field = next(f for f in data[0]["fields"] if f["type"] == "image")
    # same field id and same image reference
    assert image_field["id"] == image_field_before["id"]
    assert image_field["image_id"] == image_field_before["image_id"]
    assert image_field["image_id"] is not None

    # 2) the image row resolves in the imported game's DB
    img_rows = _img_rows(imported)
    assert len(img_rows) == 1
    (img_id, sha, ext, w, h, size, _created) = img_rows[0]
    assert img_id == image_field["image_id"]
    assert (w, h) == (1, 1) and size == len(_PNG_1PX)

    # 3) original + preview files are present under the imported images/
    images_dir_in = imported.parent / "images"
    orig = images_dir_in / sha[:2] / f"{sha}.{ext}"
    preview = images_dir_in / sha[:2] / f"{sha}.preview.webp"
    assert orig.exists() and orig.read_bytes() == _PNG_1PX
    assert preview.exists()
