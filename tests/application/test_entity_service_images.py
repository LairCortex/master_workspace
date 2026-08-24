"""EntityService <-> ImageStore integration: gc_after_commit on replace/remove
(design D6, task 6.2). The GC call belongs to the service, not the view —
these tests exercise EntityService.update_entity_with_relations directly.
"""
from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.entity_service import EntityService
from app.infrastructure.db.models import DescriptionModel, ImageModel, OrganizationModel
from app.infrastructure.images.store import ImageStore
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.organization_repository import OrganizationRepository

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


def _png_bytes(color=Qt.GlobalColor.red) -> bytes:
    img = QImage(20, 20, QImage.Format.Format_RGB32)
    img.fill(color)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(data.data())


async def _make_org(session: AsyncSession, image_id: int | None) -> OrganizationModel:
    desc = DescriptionModel(characteristics="c", backstory="b")
    session.add(desc)
    await session.flush()
    org = OrganizationModel(
        name="Guild", description_id=desc.id, image_id=image_id,
        start_date=D1, end_date=None,
    )
    session.add(org)
    await session.flush()
    return org


async def _svc(async_session: AsyncSession, image_dir) -> tuple[EntityService, ImageStore]:
    store = ImageStore(async_session, image_dir)
    svc = EntityService(
        OrganizationRepository(async_session),
        BaseRepository(async_session, DescriptionModel),
        image_store=store,
    )
    return svc, store


class TestReplaceImage:
    async def test_replacing_unique_image_removes_old_files(self, qapp, async_session, image_dir):
        svc, store = await _svc(async_session, image_dir)
        old_id = await store.store(_png_bytes(Qt.GlobalColor.red))
        org = await _make_org(async_session, old_id)
        await async_session.commit()

        new_id = await store.store(_png_bytes(Qt.GlobalColor.blue))
        await async_session.flush()

        result = await svc.update_entity_with_relations(
            org.id,
            field_data={"image_id": new_id},
            characteristics="c",
            backstory="b",
            related_changes={},
        )

        assert result is not None
        assert await async_session.get(ImageModel, old_id) is None  # old image GC'd
        assert await async_session.get(ImageModel, new_id) is not None

    async def test_replacing_with_still_referenced_image_keeps_it(self, qapp, async_session, image_dir):
        svc, store = await _svc(async_session, image_dir)
        old_id = await store.store(_png_bytes(Qt.GlobalColor.red))
        # A sibling org keeps referencing old_id after the swap.
        await _make_org(async_session, old_id)
        org = await _make_org(async_session, old_id)
        await async_session.commit()

        new_id = await store.store(_png_bytes(Qt.GlobalColor.green))
        await async_session.flush()

        await svc.update_entity_with_relations(
            org.id,
            field_data={"image_id": new_id},
            characteristics="c",
            backstory="b",
            related_changes={},
        )

        assert await async_session.get(ImageModel, old_id) is not None  # still shared


class TestRemoveImage:
    async def test_clearing_image_removes_unreferenced_file(self, qapp, async_session, image_dir):
        svc, store = await _svc(async_session, image_dir)
        old_id = await store.store(_png_bytes())
        org = await _make_org(async_session, old_id)
        await async_session.commit()

        result = await svc.update_entity_with_relations(
            org.id,
            field_data={"image_id": None},
            characteristics="c",
            backstory="b",
            related_changes={},
        )

        assert result is not None
        assert await async_session.get(ImageModel, old_id) is None


class TestNoOpPaths:
    async def test_unchanged_image_id_does_not_gc(self, qapp, async_session, image_dir):
        svc, store = await _svc(async_session, image_dir)
        image_id = await store.store(_png_bytes())
        org = await _make_org(async_session, image_id)
        await async_session.commit()

        await svc.update_entity_with_relations(
            org.id,
            field_data={"image_id": image_id, "rating": 5},
            characteristics="c",
            backstory="b",
            related_changes={},
        )

        assert await async_session.get(ImageModel, image_id) is not None

    async def test_entity_type_without_image_field_is_unaffected(self, qapp, async_session, image_dir):
        """field_data without "image_id" (e.g. items) must not touch ImageStore."""
        svc, _store = await _svc(async_session, image_dir)
        org = await _make_org(async_session, None)
        await async_session.commit()

        result = await svc.update_entity_with_relations(
            org.id,
            field_data={"rating": 5},
            characteristics="c",
            backstory="b",
            related_changes={},
        )
        assert result is not None
        assert result.rating == 5

    async def test_no_image_store_configured_is_safe(self, qapp, async_session, image_dir):
        svc = EntityService(
            OrganizationRepository(async_session),
            BaseRepository(async_session, DescriptionModel),
        )  # image_store=None
        org = await _make_org(async_session, None)
        await async_session.commit()

        result = await svc.update_entity_with_relations(
            org.id,
            field_data={"image_id": 999},
            characteristics="c",
            backstory="b",
            related_changes={},
        )
        assert result is not None
        assert result.image_id == 999
