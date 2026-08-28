"""ImageStore references from character-sheet pages JSON (design D6, task 3.1).

Sheet image fields reference ``images`` only through the ``pages`` JSON
(``image_id``) — no FK column. refcount, startup_gc and the after-commit GC
must count those references so a file shared by a sheet and an entity is not
deleted, and a file referenced only by a sheet field is deleted when the
field is cleared / the sheet deleted / the template row is dropped.
"""
from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.character_sheet_service import CharacterSheetService
from app.domain.entities.character_sheet import FieldType
from app.infrastructure.db.models import CharacterModel, ImageModel
from app.infrastructure.images.paths import original_path
from app.infrastructure.images.store import ImageStore
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)

D1 = date(1300, 1, 1)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def image_dir(tmp_path):
    return tmp_path / "images"


def _png(color=Qt.GlobalColor.red) -> bytes:
    img = QImage(20, 20, QImage.Format.Format_RGB32)
    img.fill(color)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba.data())


async def _sheet_with_image_field(
    async_session: AsyncSession,
    store: ImageStore,
    image_id: int,
    name: str = "Лист",
) -> tuple[CharacterSheetService, int]:
    """A sheet whose single page holds one image field on ``image_id``."""
    svc = CharacterSheetService(CharacterSheetRepository(async_session), image_store=store)
    row = await svc.create(name)
    template = await svc.load(row.id)
    f = template.add_field(FieldType.IMAGE, (10.0, 10.0))
    f.image_id = image_id
    await svc.update_pages(row.id, template)
    return svc, row.id


async def _add_character(
    async_session: AsyncSession, name: str, image_id: int | None
) -> CharacterModel:
    char = CharacterModel(name=name, start_date=D1, image_id=image_id)
    async_session.add(char)
    await async_session.commit()
    return char


class TestRefcount:
    async def test_refcount_counts_sheet_image_fields(self, qapp, async_session, image_dir):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png())
        await async_session.commit()
        await _sheet_with_image_field(async_session, store, image_id)

        assert await store.refcount(image_id) == 1

    async def test_refcount_counts_two_fields_on_two_pages(self, qapp, async_session, image_dir):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png())
        svc = CharacterSheetService(
            CharacterSheetRepository(async_session), image_store=store
        )
        row = await svc.create("Два")
        template = await svc.load(row.id)
        template.add_page()
        f1 = template.add_field(FieldType.IMAGE, (10.0, 10.0), page_index=0)
        f2 = template.add_field(FieldType.IMAGE, (40.0, 10.0), page_index=1)
        f1.image_id = image_id
        f2.image_id = image_id
        await svc.update_pages(row.id, template)

        assert await store.refcount(image_id) == 2

    async def test_sheet_and_character_share_file_deleting_character_keeps_it(
        self, qapp, async_session, image_dir
    ):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png())
        await async_session.commit()
        svc, sheet_id = await _sheet_with_image_field(async_session, store, image_id)
        char = await _add_character(async_session, "Иван", image_id)

        assert await store.refcount(image_id) == 2  # character + sheet field

        # entity-side removal (the update path runs gc_after_commit with the
        # old id after commit) must not touch the shared file
        await async_session.delete(char)
        await async_session.commit()
        await store.gc_after_commit(image_id)

        assert await store.refcount(image_id) == 1    # only the sheet field
        img_row = await async_session.get(ImageModel, image_id)
        assert img_row is not None
        assert original_path(image_dir, img_row.sha256, img_row.ext).exists()
        loaded = await svc.load(sheet_id)
        assert loaded.pages[0].fields[0].image_id == image_id  # still shows it


class TestGcOnSave:
    async def test_clearing_image_field_then_save_deletes_orphan(
        self, qapp, async_session, image_dir
    ):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png())
        svc, sheet_id = await _sheet_with_image_field(async_session, store, image_id)
        row_img = await async_session.get(ImageModel, image_id)
        orig = original_path(image_dir, row_img.sha256, row_img.ext)
        assert orig.exists()

        template = await svc.load(sheet_id)
        template.pages[0].fields[0].image_id = None
        await svc.update_pages(sheet_id, template)

        assert not orig.exists()
        assert await async_session.get(ImageModel, image_id) is None

    async def test_replacing_image_gc_old_when_unreferenced(
        self, qapp, async_session, image_dir
    ):
        store = ImageStore(async_session, image_dir)
        old_id = await store.store(_png(Qt.GlobalColor.red))
        new_id = await store.store(_png(Qt.GlobalColor.blue))
        svc, sheet_id = await _sheet_with_image_field(async_session, store, old_id)
        row_old = await async_session.get(ImageModel, old_id)
        orig_old = original_path(image_dir, row_old.sha256, row_old.ext)

        template = await svc.load(sheet_id)
        template.pages[0].fields[0].image_id = new_id
        await svc.update_pages(sheet_id, template)

        assert not orig_old.exists()
        assert await async_session.get(ImageModel, old_id) is None
        assert await async_session.get(ImageModel, new_id) is not None

    async def test_clearing_field_keeps_file_shared_with_character(
        self, qapp, async_session, image_dir
    ):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png())
        svc, sheet_id = await _sheet_with_image_field(async_session, store, image_id)
        await _add_character(async_session, "Иван", image_id)
        row_img = await async_session.get(ImageModel, image_id)
        orig = original_path(image_dir, row_img.sha256, row_img.ext)

        template = await svc.load(sheet_id)
        template.pages[0].fields[0].image_id = None
        await svc.update_pages(sheet_id, template)

        assert await store.refcount(image_id) == 1
        assert orig.exists()
        assert await async_session.get(ImageModel, image_id) is not None


class TestGcOnDelete:
    async def test_deleting_sheet_deletes_orphan_image(
        self, qapp, async_session, image_dir
    ):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png())
        svc, sheet_id = await _sheet_with_image_field(async_session, store, image_id)
        row_img = await async_session.get(ImageModel, image_id)
        orig = original_path(image_dir, row_img.sha256, row_img.ext)

        assert await svc.delete(sheet_id) is True
        assert not orig.exists()
        assert await async_session.get(ImageModel, image_id) is None

    async def test_deleting_sheet_keeps_file_referenced_by_character(
        self, qapp, async_session, image_dir
    ):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png())
        svc, sheet_id = await _sheet_with_image_field(async_session, store, image_id)
        await _add_character(async_session, "Иван", image_id)
        row_img = await async_session.get(ImageModel, image_id)
        orig = original_path(image_dir, row_img.sha256, row_img.ext)

        await svc.delete(sheet_id)

        assert orig.exists()
        assert await async_session.get(ImageModel, image_id) is not None


class TestStartupGc:
    async def test_row_referenced_only_by_sheet_survives_startup_gc(
        self, qapp, async_session, image_dir
    ):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png())
        await _sheet_with_image_field(async_session, store, image_id)

        await store.startup_gc()

        assert await async_session.get(ImageModel, image_id) is not None
        row = await async_session.get(ImageModel, image_id)
        assert original_path(image_dir, row.sha256, row.ext).exists()

    async def test_unreferenced_row_still_removed(self, qapp, async_session, image_dir):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png())
        await async_session.commit()

        await store.startup_gc()

        assert await async_session.get(ImageModel, image_id) is None

    async def test_startup_gc_drops_row_without_original_and_clears_sheet_field(
        self, qapp, async_session, image_dir
    ):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png())
        svc, sheet_id = await _sheet_with_image_field(async_session, store, image_id)
        row_img = await async_session.get(ImageModel, image_id)
        original_path(image_dir, row_img.sha256, row_img.ext).unlink()

        await store.startup_gc()

        assert await async_session.get(ImageModel, image_id) is None
        template = await svc.load(sheet_id)
        assert template.pages[0].fields[0].image_id is None
