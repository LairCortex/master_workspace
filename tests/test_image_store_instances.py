"""ImageStore references from filled-sheet ``values`` JSON (design D6, task 4.1).

Instance image fields reference ``images`` only through the values map
(``image_id`` int). refcount, startup_gc and after-commit GC must count
those so a file shared with a character is kept, and a file referenced
only by an instance is dropped on clear/delete / kept by startup_gc.
"""
from __future__ import annotations

import json
from datetime import date

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.character_sheet_instance_service import (
    CharacterSheetInstanceService,
)
from app.application.services.character_sheet_service import CharacterSheetService
from app.infrastructure.db.models import CharacterModel, ImageModel
from app.infrastructure.images.paths import original_path
from app.infrastructure.images.store import ImageStore
from app.infrastructure.repositories.character_sheet_instance_repository import (
    CharacterSheetInstanceRepository,
)
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


async def _instance_with_image(
    async_session: AsyncSession,
    store: ImageStore,
    image_id: int,
    name: str = "Лист",
):
    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, image_store=store, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc, image_store=store)
    template_row = await sheet_svc.create(f"T-{name}")
    row = await inst_repo.create(
        name=name,
        template_id=template_row.id,
        values=json.dumps({"port": image_id}),
    )
    await async_session.commit()
    return inst_svc, row.id


async def _add_character(
    async_session: AsyncSession, name: str, image_id: int | None
) -> CharacterModel:
    char = CharacterModel(name=name, start_date=D1, image_id=image_id)
    async_session.add(char)
    await async_session.commit()
    return char


class TestRefcount:
    async def test_refcount_counts_instance_image_ids(self, qapp, async_session, image_dir):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png())
        await async_session.commit()
        await _instance_with_image(async_session, store, image_id)
        assert await store.refcount(image_id) == 1

    async def test_instance_and_character_share_file_deleting_character_keeps_it(
        self, qapp, async_session, image_dir
    ):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png())
        await async_session.commit()
        inst_svc, instance_id = await _instance_with_image(async_session, store, image_id)
        char = await _add_character(async_session, "Иван", image_id)

        assert await store.refcount(image_id) == 2

        await async_session.delete(char)
        await async_session.commit()
        await store.gc_after_commit(image_id)

        assert await store.refcount(image_id) == 1
        img_row = await async_session.get(ImageModel, image_id)
        assert img_row is not None
        assert original_path(image_dir, img_row.sha256, img_row.ext).exists()
        row = await inst_svc.get(instance_id)
        assert json.loads(row.values)["port"] == image_id


class TestGcOnSaveAndDelete:
    async def test_clear_image_then_save_deletes_orphan(self, qapp, async_session, image_dir):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png())
        inst_svc, instance_id = await _instance_with_image(async_session, store, image_id)
        row_img = await async_session.get(ImageModel, image_id)
        orig = original_path(image_dir, row_img.sha256, row_img.ext)
        assert orig.exists()

        await inst_svc.update_values(instance_id, {"port": None})

        assert not orig.exists()
        assert await async_session.get(ImageModel, image_id) is None

    async def test_delete_instance_deletes_orphan_image(self, qapp, async_session, image_dir):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png())
        inst_svc, instance_id = await _instance_with_image(async_session, store, image_id)
        row_img = await async_session.get(ImageModel, image_id)
        orig = original_path(image_dir, row_img.sha256, row_img.ext)

        assert await inst_svc.delete(instance_id) is True
        assert not orig.exists()
        assert await async_session.get(ImageModel, image_id) is None


class TestStartupGc:
    async def test_row_referenced_only_by_instance_survives_startup_gc(
        self, qapp, async_session, image_dir
    ):
        store = ImageStore(async_session, image_dir)
        image_id = await store.store(_png())
        await _instance_with_image(async_session, store, image_id)

        await store.startup_gc()

        assert await async_session.get(ImageModel, image_id) is not None
        row = await async_session.get(ImageModel, image_id)
        assert original_path(image_dir, row.sha256, row.ext).exists()
