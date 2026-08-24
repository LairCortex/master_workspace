"""Tests for ImageStore.store() — TDD (design D4)."""
from __future__ import annotations

import hashlib

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import ImageModel
from app.infrastructure.images.paths import original_path, preview_path
from app.infrastructure.images.store import ImageStore


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _png_bytes(w: int = 100, h: int = 80, color=Qt.GlobalColor.red) -> bytes:
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
    d = tmp_path / "images"
    return d


class TestStoreNormalImport:
    @pytest.mark.asyncio
    async def test_store_returns_id(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        data = _png_bytes()
        image_id = await store.store(data)
        assert isinstance(image_id, int)

    @pytest.mark.asyncio
    async def test_store_writes_original_and_preview(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        data = _png_bytes()
        image_id = await store.store(data)
        row = await async_session.get(ImageModel, image_id)

        orig = original_path(image_dir, row.sha256, row.ext)
        prev = preview_path(image_dir, row.sha256)
        assert orig.exists()
        assert prev.exists()
        assert orig.read_bytes() == data

    @pytest.mark.asyncio
    async def test_store_records_metadata(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        data = _png_bytes(120, 90)
        image_id = await store.store(data)
        row = await async_session.get(ImageModel, image_id)
        assert row.width == 120
        assert row.height == 90
        assert row.size_bytes == len(data)
        assert row.sha256 == hashlib.sha256(data).hexdigest()
        assert row.ext == "png"


class TestStoreDedup:
    @pytest.mark.asyncio
    async def test_same_bytes_return_same_id(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        data = _png_bytes()
        id1 = await store.store(data)
        id2 = await store.store(data)
        assert id1 == id2

    @pytest.mark.asyncio
    async def test_dedup_does_not_duplicate_row(self, qapp, async_session: AsyncSession, image_dir):
        from sqlalchemy import func, select
        store = ImageStore(async_session, image_dir)
        data = _png_bytes()
        await store.store(data)
        await store.store(data)
        count = (await async_session.execute(select(func.count()).select_from(ImageModel))).scalar()
        assert count == 1

    @pytest.mark.asyncio
    async def test_different_bytes_different_ids(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        id1 = await store.store(_png_bytes(50, 50, Qt.GlobalColor.red))
        id2 = await store.store(_png_bytes(50, 50, Qt.GlobalColor.blue))
        assert id1 != id2

    @pytest.mark.asyncio
    async def test_dedup_hit_regenerates_missing_files(self, qapp, async_session: AsyncSession, image_dir):
        """Row exists but files were deleted out-of-band: store() self-heals."""
        store = ImageStore(async_session, image_dir)
        data = _png_bytes()
        image_id = await store.store(data)
        row = await async_session.get(ImageModel, image_id)
        orig = original_path(image_dir, row.sha256, row.ext)
        prev = preview_path(image_dir, row.sha256)
        orig.unlink()
        prev.unlink()

        second_id = await store.store(data)
        assert second_id == image_id
        assert orig.exists()
        assert prev.exists()


class TestStoreInvalidFile:
    @pytest.mark.asyncio
    async def test_raises_value_error_on_garbage(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        with pytest.raises(ValueError):
            await store.store(b"definitely not an image")

    @pytest.mark.asyncio
    async def test_no_files_written_on_invalid(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        with pytest.raises(ValueError):
            await store.store(b"garbage")
        assert not image_dir.exists() or not any(image_dir.rglob("*"))


class TestPathResolution:
    @pytest.mark.asyncio
    async def test_original_file_path_for_existing_image(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png_bytes())
        path = await store.original_file_path(image_id)
        assert path is not None
        assert path.exists()

    @pytest.mark.asyncio
    async def test_preview_file_path_for_existing_image(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png_bytes())
        path = await store.preview_file_path(image_id)
        assert path is not None
        assert path.exists()

    @pytest.mark.asyncio
    async def test_original_file_path_missing_row_returns_none(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        assert await store.original_file_path(999999) is None

    @pytest.mark.asyncio
    async def test_preview_file_path_missing_row_returns_none(self, qapp, async_session: AsyncSession, image_dir):
        store = ImageStore(async_session, image_dir)
        assert await store.preview_file_path(999999) is None


class TestStoreRaceCondition:
    @pytest.mark.asyncio
    async def test_integrity_error_falls_back_to_select(
        self, qapp, async_session: AsyncSession, image_dir, monkeypatch,
    ):
        """Simulate a concurrent store() winning the unique-sha256 insert.

        The winning row is committed for real (so a genuine UNIQUE violation
        fires on flush); the pre-write existence check is forced to miss it
        once, to reproduce the TOCTOU window the IntegrityError branch guards.
        """
        store = ImageStore(async_session, image_dir)
        data = _png_bytes()
        sha = hashlib.sha256(data).hexdigest()

        winner = ImageModel(sha256=sha, ext="png", width=1, height=1, size_bytes=1)
        async_session.add(winner)
        await async_session.commit()
        winner_id = winner.id

        real_get_by_sha = store._get_by_sha
        call_count = {"n": 0}

        async def fake_get_by_sha(sha256):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return None  # simulate: no row visible yet at check time
            return await real_get_by_sha(sha256)

        monkeypatch.setattr(store, "_get_by_sha", fake_get_by_sha)

        result_id = await store.store(data)
        assert result_id == winner_id
        assert call_count["n"] == 2

    @pytest.mark.asyncio
    async def test_integrity_error_without_existing_row_reraises(
        self, qapp, async_session: AsyncSession, image_dir, monkeypatch,
    ):
        """If flush fails and no row can be found afterwards, propagate."""
        from sqlalchemy.exc import IntegrityError

        store = ImageStore(async_session, image_dir)
        data = _png_bytes()

        async def fake_flush(*args, **kwargs):
            raise IntegrityError("insert", {}, Exception("some other constraint"))

        monkeypatch.setattr(async_session, "flush", fake_flush)

        with pytest.raises(IntegrityError):
            await store.store(data)
