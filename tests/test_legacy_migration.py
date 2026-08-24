"""Tests for legacy base64 -> file-storage migration in init_db() (design D8)."""
from __future__ import annotations

import base64

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage
from sqlalchemy import text

from app.infrastructure.db.database import create_engine
from app.infrastructure.db.migrations import init_db
from app.infrastructure.images.paths import original_path, preview_path


def _png_b64(color=Qt.GlobalColor.red) -> str:
    img = QImage(20, 15, QImage.Format.Format_RGB32)
    img.fill(color)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return base64.b64encode(bytes(data.data())).decode("ascii")


async def _insert_legacy_org(engine, name: str, image_b64: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO organizations (name, start_date, end_date, image, rating) "
                "VALUES (:name, '1000-01-01', '1500-01-01', :image, 1)"
            ),
            {"name": name, "image": image_b64},
        )


async def _insert_legacy_char(engine, name: str, image_b64: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO characters (name, start_date, end_date, image, rating) "
                "VALUES (:name, '1100-01-01', '1200-01-01', :image, 1)"
            ),
            {"name": name, "image": image_b64},
        )


class TestLegacyImageMigration:
    async def test_first_open_migrates_images_to_files(self, qapp, tmp_path):
        db_path = tmp_path / "game" / "game.db"
        db_path.parent.mkdir(parents=True)
        image_dir = db_path.parent / "images"
        engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
        try:
            await init_db(engine)  # schema only, no legacy rows yet

            b64_org = _png_b64(Qt.GlobalColor.red)
            b64_char = _png_b64(Qt.GlobalColor.blue)
            await _insert_legacy_org(engine, "Guild", b64_org)
            await _insert_legacy_char(engine, "Hero", b64_char)

            await init_db(engine, image_dir=image_dir)

            async with engine.connect() as conn:
                org_row = (
                    await conn.execute(text("SELECT image, image_id FROM organizations"))
                ).first()
                char_row = (
                    await conn.execute(text("SELECT image, image_id FROM characters"))
                ).first()
            assert org_row == (None, org_row[1])
            assert org_row[1] is not None
            assert char_row == (None, char_row[1])
            assert char_row[1] is not None

            # Files actually exist on disk.
            async with engine.connect() as conn:
                sha_org = (
                    await conn.execute(text("SELECT sha256, ext FROM images WHERE id=:id"), {"id": org_row[1]})
                ).first()
            orig = original_path(image_dir, sha_org[0], sha_org[1])
            prev = preview_path(image_dir, sha_org[0])
            assert orig.exists()
            assert prev.exists()
        finally:
            await engine.dispose()

    async def test_second_open_does_not_remigrate(self, qapp, tmp_path):
        db_path = tmp_path / "game" / "game.db"
        db_path.parent.mkdir(parents=True)
        image_dir = db_path.parent / "images"
        engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
        try:
            await init_db(engine)
            await _insert_legacy_org(engine, "Guild", _png_b64())
            await init_db(engine, image_dir=image_dir)

            async with engine.connect() as conn:
                before = (await conn.execute(text("SELECT COUNT(*) FROM images"))).scalar()

            await init_db(engine, image_dir=image_dir)  # second open: no-op

            async with engine.connect() as conn:
                after = (await conn.execute(text("SELECT COUNT(*) FROM images"))).scalar()
            assert before == after == 1
        finally:
            await engine.dispose()

    async def test_no_legacy_data_is_a_noop(self, qapp, tmp_path):
        db_path = tmp_path / "game" / "game.db"
        db_path.parent.mkdir(parents=True)
        image_dir = db_path.parent / "images"
        engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
        try:
            await init_db(engine, image_dir=image_dir)  # fresh DB, nothing to migrate
            async with engine.connect() as conn:
                count = (await conn.execute(text("SELECT COUNT(*) FROM images"))).scalar()
            assert count == 0
        finally:
            await engine.dispose()

    async def test_without_image_dir_migration_is_skipped(self, qapp, tmp_path):
        db_path = tmp_path / "skip.db"
        engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
        try:
            await init_db(engine)
            await _insert_legacy_org(engine, "Guild", _png_b64())

            await init_db(engine)  # no image_dir passed: migration skipped

            async with engine.connect() as conn:
                row = (await conn.execute(text("SELECT image, image_id FROM organizations"))).first()
            assert row[0] is not None  # legacy value untouched
            assert row[1] is None
        finally:
            await engine.dispose()

    async def test_empty_string_image_is_not_treated_as_legacy(self, qapp, tmp_path):
        db_path = tmp_path / "game" / "game.db"
        db_path.parent.mkdir(parents=True)
        image_dir = db_path.parent / "images"
        engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
        try:
            await init_db(engine)
            await _insert_legacy_org(engine, "NoImage", "")

            await init_db(engine, image_dir=image_dir)  # must not raise on empty string

            async with engine.connect() as conn:
                count = (await conn.execute(text("SELECT COUNT(*) FROM images"))).scalar()
            assert count == 0
        finally:
            await engine.dispose()
