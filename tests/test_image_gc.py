"""Tests for ImageStore.refcount / gc_after_commit / startup_gc (design D6/D7)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import CharacterModel, DescriptionModel, ImageModel, OrganizationModel
from app.infrastructure.images.paths import original_path, preview_path
from app.infrastructure.images.store import ImageStore


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _png_bytes(w: int = 40, h: int = 30, color=Qt.GlobalColor.red) -> bytes:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(color)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(data.data())


@pytest.fixture
def image_dir(tmp_path):
    return tmp_path / "images"


async def _make_org(session: AsyncSession, image_id: int | None = None) -> OrganizationModel:
    desc = DescriptionModel(characteristics="o", backstory="o")
    session.add(desc)
    await session.flush()
    org = OrganizationModel(
        name="Guild", description_id=desc.id, image_id=image_id,
        start_date=date(1000, 1, 1), end_date=date(1500, 1, 1),
    )
    session.add(org)
    await session.flush()
    return org


class TestRefcount:
    @pytest.mark.asyncio
    async def test_zero_when_unreferenced(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png_bytes())
        assert await store.refcount(image_id) == 0

    @pytest.mark.asyncio
    async def test_counts_across_tables(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png_bytes())
        await _make_org(async_session, image_id)

        desc = DescriptionModel(characteristics="c", backstory="c")
        async_session.add(desc)
        await async_session.flush()
        char = CharacterModel(
            name="Hero", description_id=desc.id, image_id=image_id,
            start_date=date(1100, 1, 1), end_date=date(1200, 1, 1),
        )
        async_session.add(char)
        await async_session.flush()

        assert await store.refcount(image_id) == 2


class TestGcAfterCommit:
    @pytest.mark.asyncio
    async def test_unreferenced_image_is_removed(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png_bytes())
        row = await async_session.get(ImageModel, image_id)
        orig = original_path(image_dir, row.sha256, row.ext)
        prev = preview_path(image_dir, row.sha256)
        await async_session.commit()

        await store.gc_after_commit(image_id)

        assert not orig.exists()
        assert not prev.exists()
        assert await async_session.get(ImageModel, image_id) is None

    @pytest.mark.asyncio
    async def test_shared_image_not_removed(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png_bytes())
        await _make_org(async_session, image_id)
        await async_session.commit()

        await store.gc_after_commit(image_id)

        assert await async_session.get(ImageModel, image_id) is not None

    @pytest.mark.asyncio
    async def test_none_and_falsy_ids_are_skipped(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        await store.gc_after_commit(None, 0)  # must not raise

    @pytest.mark.asyncio
    async def test_missing_row_is_skipped(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        await store.gc_after_commit(999999)  # no such row — no-op

    @pytest.mark.asyncio
    async def test_already_missing_file_is_not_an_error(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png_bytes())
        row = await async_session.get(ImageModel, image_id)
        preview_path(image_dir, row.sha256).unlink()  # simulate partial manual cleanup
        await async_session.commit()

        await store.gc_after_commit(image_id)

        assert await async_session.get(ImageModel, image_id) is None

    @pytest.mark.asyncio
    async def test_unlink_failure_keeps_row(self, qapp, async_session: AsyncSession, image_dir, monkeypatch):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png_bytes())
        await async_session.commit()

        def failing_unlink(self):
            raise OSError("disk error")

        monkeypatch.setattr(Path, "unlink", failing_unlink)
        await store.gc_after_commit(image_id)

        # Row survives — the operation is retried by the next startup_gc.
        assert await async_session.get(ImageModel, image_id) is not None


class TestStartupGc:
    @pytest.mark.asyncio
    async def test_orphan_file_is_removed(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        image_dir.mkdir(parents=True)
        orphan_dir = image_dir / "ab"
        orphan_dir.mkdir()
        orphan_file = orphan_dir / "abcdef.png"
        orphan_file.write_bytes(b"stale")

        await store.startup_gc()

        assert not orphan_file.exists()

    @pytest.mark.asyncio
    async def test_row_without_original_is_dropped_and_refs_nulled(
        self, qapp, async_session: AsyncSession, image_dir,
    ):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png_bytes())
        org = await _make_org(async_session, image_id)
        await async_session.commit()

        row = await async_session.get(ImageModel, image_id)
        original_path(image_dir, row.sha256, row.ext).unlink()

        await store.startup_gc()

        assert await async_session.get(ImageModel, image_id) is None
        await async_session.refresh(org)
        assert org.image_id is None

    @pytest.mark.asyncio
    async def test_row_without_original_drops_leftover_preview_too(
        self, qapp, async_session: AsyncSession, image_dir,
    ):
        """Original missing while the preview survives on disk: the preview is
        an orphan the moment the row is dropped, so it must go in the same
        pass — a leftover would only be cleaned on the next startup, breaking
        the «repeated runs do not change the storage» invariant."""
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png_bytes())
        await _make_org(async_session, image_id)
        await async_session.commit()

        row = await async_session.get(ImageModel, image_id)
        prev = preview_path(image_dir, row.sha256)
        assert prev.exists()
        original_path(image_dir, row.sha256, row.ext).unlink()

        await store.startup_gc()

        assert await async_session.get(ImageModel, image_id) is None
        assert not prev.exists()

        await store.startup_gc()  # second run: state unchanged
        assert not prev.exists()

    @pytest.mark.asyncio
    async def test_missing_preview_is_regenerated(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png_bytes())
        await _make_org(async_session, image_id)
        await async_session.commit()

        row = await async_session.get(ImageModel, image_id)
        prev = preview_path(image_dir, row.sha256)
        prev.unlink()
        assert not prev.exists()

        await store.startup_gc()

        assert prev.exists()
        assert await async_session.get(ImageModel, image_id) is not None

    @pytest.mark.asyncio
    async def test_preview_regeneration_failure_is_logged_not_raised(
        self, qapp, async_session: AsyncSession, image_dir, monkeypatch,
    ):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png_bytes())
        await _make_org(async_session, image_id)
        await async_session.commit()

        row = await async_session.get(ImageModel, image_id)
        preview_path(image_dir, row.sha256).unlink()

        monkeypatch.setattr(
            "app.infrastructure.images.store.generate_preview",
            lambda data: (_ for _ in ()).throw(ValueError("corrupt")),
        )

        await store.startup_gc()  # must not raise
        # Row (and reference) survive: original still readable, only preview failed.
        assert await async_session.get(ImageModel, image_id) is not None

    @pytest.mark.asyncio
    async def test_unreferenced_row_removed(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png_bytes())
        await async_session.commit()

        await store.startup_gc()

        assert await async_session.get(ImageModel, image_id) is None

    @pytest.mark.asyncio
    async def test_referenced_row_with_files_untouched(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png_bytes())
        await _make_org(async_session, image_id)
        await async_session.commit()
        row = await async_session.get(ImageModel, image_id)
        orig = original_path(image_dir, row.sha256, row.ext)
        prev = preview_path(image_dir, row.sha256)

        await store.startup_gc()

        assert orig.exists()
        assert prev.exists()
        assert await async_session.get(ImageModel, image_id) is not None

    @pytest.mark.asyncio
    async def test_tmp_leftovers_are_removed(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        image_dir.mkdir(parents=True)
        sub = image_dir / "ab"
        sub.mkdir()
        leftover = sub / "abcdef.png.tmp-12345"
        leftover.write_bytes(b"partial")

        await store.startup_gc()

        assert not leftover.exists()

    @pytest.mark.asyncio
    async def test_runs_cleanly_when_images_dir_does_not_exist_yet(
        self, qapp, async_session: AsyncSession, image_dir,
    ):
        store = ImageStore(async_session, image_dir)
        assert not image_dir.exists()
        await store.startup_gc()  # must not raise

    @pytest.mark.asyncio
    async def test_idempotent_second_run_no_changes(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png_bytes())
        await _make_org(async_session, image_id)
        await async_session.commit()

        await store.startup_gc()
        row = await async_session.get(ImageModel, image_id)
        orig = original_path(image_dir, row.sha256, row.ext)
        prev = preview_path(image_dir, row.sha256)
        assert orig.exists() and prev.exists()

        await store.startup_gc()  # second run: no-op

        assert orig.exists() and prev.exists()
        assert await async_session.get(ImageModel, image_id) is not None
