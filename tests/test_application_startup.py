"""Application.start() startup order (design D1/D7/D8, task 4.2).

Covers the seam between ``ensure_game_directory`` → ``init_db(image_dir=...)``
→ ``ImageStore.startup_gc()`` → UI, end-to-end through the real ``Application``.
"""
from __future__ import annotations

import base64
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage
from sqlalchemy import text

from app.infrastructure.db.database import create_engine
from app.infrastructure.db.migrations import init_db as raw_init_db
from app.infrastructure.images.paths import original_path, preview_path
from app.infrastructure.images.store import ImageStore
from app.main import Application


def _png_b64() -> str:
    img = QImage(16, 16, QImage.Format.Format_RGB32)
    img.fill(Qt.GlobalColor.green)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return base64.b64encode(bytes(data.data())).decode("ascii")


async def _seed_legacy_flat_db(flat_path: Path) -> None:
    """Simulate a pre-image-storage game: schema only, one legacy base64 row."""
    engine = create_engine(f"sqlite+aiosqlite:///{flat_path}")
    try:
        await raw_init_db(engine)  # no image_dir: schema only, no migration
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO organizations (name, start_date, end_date, image, rating) "
                    "VALUES ('Guild', '1000-01-01', '1500-01-01', :image, 1)"
                ),
                {"image": _png_b64()},
            )
    finally:
        await engine.dispose()


class TestApplicationStartupOrder:
    async def test_legacy_flat_db_migrated_and_images_on_disk(self, qapp, tmp_path):
        flat_path = tmp_path / "legacy.db"
        await _seed_legacy_flat_db(flat_path)

        application = Application(qapp)
        window = await application.start(str(flat_path))
        try:
            # ensure_game_directory ran first: catalog dir, game name = "legacy"
            assert application._db_path == str(tmp_path / "legacy" / "game.db")
            assert Path(application._db_path).exists()
            assert not flat_path.exists()
            assert "legacy" in window.windowTitle()

            # legacy base64 -> file storage happened inside init_db()
            async with application.engine.connect() as conn:
                row = (
                    await conn.execute(text("SELECT image, image_id FROM organizations"))
                ).first()
            assert row == (None, row[1])
            assert row[1] is not None

            image_dir = Path(application._db_path).parent / "images"
            async with application.engine.connect() as conn:
                sha, ext = (
                    await conn.execute(
                        text("SELECT sha256, ext FROM images WHERE id=:id"), {"id": row[1]}
                    )
                ).first()
            assert original_path(image_dir, sha, ext).exists()
            assert preview_path(image_dir, sha).exists()

            # DI'd ImageStore is usable post-start (bound to the same session/dir)
            assert isinstance(application._image_store, ImageStore)
            assert await application._image_store.original_file_path(row[1]) == original_path(
                image_dir, sha, ext
            )
        finally:
            window.close()
            await application.shutdown()
            assert application._image_store is None  # cleared on shutdown

    async def test_startup_gc_runs_and_cleans_orphan_before_ui_shown(self, qapp, tmp_path):
        """An orphan file (no DB row) left in images/ is swept by startup_gc
        before the window is shown — proves the ordering, not just presence
        of the call."""
        db_path = tmp_path / "Orphaned" / "game.db"
        db_path.parent.mkdir(parents=True)
        images_dir = db_path.parent / "images"
        orphan = images_dir / "de" / "deadbeef.png"
        orphan.parent.mkdir(parents=True)
        orphan.write_bytes(b"not-a-real-image-but-orphaned")

        application = Application(qapp)
        window = await application.start(str(db_path))
        try:
            assert window is not None
            assert not orphan.exists()  # startup_gc removed it before UI was shown
        finally:
            window.close()
            await application.shutdown()
