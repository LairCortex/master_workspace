"""Tests for ImageModel and image_id FK on Organization/Character/Location."""
from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.database import create_engine
from app.infrastructure.db.models import (
    Base, CharacterModel, DescriptionModel, ImageModel, LocationModel, OrganizationModel,
)


class TestImageModelSchema:
    @pytest.mark.asyncio
    async def test_create_image_row(self, async_session: AsyncSession):
        img = ImageModel(
            sha256="a" * 64, ext="png", width=100, height=80, size_bytes=1234,
            created_at=datetime(2024, 1, 1),
        )
        async_session.add(img)
        await async_session.commit()

        result = await async_session.get(ImageModel, img.id)
        assert result is not None
        assert result.sha256 == "a" * 64
        assert result.ext == "png"
        assert result.width == 100
        assert result.height == 80
        assert result.size_bytes == 1234

    @pytest.mark.asyncio
    async def test_sha256_unique_constraint(self, async_session: AsyncSession):
        img1 = ImageModel(sha256="b" * 64, ext="png", width=1, height=1, size_bytes=1)
        async_session.add(img1)
        await async_session.commit()

        img2 = ImageModel(sha256="b" * 64, ext="jpg", width=2, height=2, size_bytes=2)
        async_session.add(img2)
        with pytest.raises(Exception):
            await async_session.commit()
        await async_session.rollback()


class TestEntityImageIdColumn:
    @pytest.mark.asyncio
    async def test_organization_image_id_defaults_none(self, async_session: AsyncSession):
        desc = DescriptionModel(characteristics="o", backstory="o")
        async_session.add(desc)
        await async_session.flush()
        org = OrganizationModel(
            name="Guild", description_id=desc.id,
            start_date=date(1000, 1, 1), end_date=date(1500, 1, 1),
        )
        async_session.add(org)
        await async_session.commit()
        assert org.image_id is None

    @pytest.mark.asyncio
    async def test_organization_can_link_to_image(self, async_session: AsyncSession):
        img = ImageModel(sha256="c" * 64, ext="png", width=1, height=1, size_bytes=1)
        async_session.add(img)
        await async_session.flush()

        desc = DescriptionModel(characteristics="o", backstory="o")
        async_session.add(desc)
        await async_session.flush()
        org = OrganizationModel(
            name="Guild", description_id=desc.id, image_id=img.id,
            start_date=date(1000, 1, 1), end_date=date(1500, 1, 1),
        )
        async_session.add(org)
        await async_session.commit()

        result = await async_session.get(OrganizationModel, org.id)
        assert result.image_id == img.id

    @pytest.mark.asyncio
    async def test_character_can_link_to_image(self, async_session: AsyncSession):
        img = ImageModel(sha256="d" * 64, ext="png", width=1, height=1, size_bytes=1)
        async_session.add(img)
        await async_session.flush()
        desc = DescriptionModel(characteristics="c", backstory="c")
        async_session.add(desc)
        await async_session.flush()
        char = CharacterModel(
            name="Hero", description_id=desc.id, image_id=img.id,
            start_date=date(1100, 1, 1), end_date=date(1200, 1, 1),
        )
        async_session.add(char)
        await async_session.commit()
        result = await async_session.get(CharacterModel, char.id)
        assert result.image_id == img.id

    @pytest.mark.asyncio
    async def test_location_can_link_to_image(self, async_session: AsyncSession):
        img = ImageModel(sha256="e" * 64, ext="png", width=1, height=1, size_bytes=1)
        async_session.add(img)
        await async_session.flush()
        desc = DescriptionModel(characteristics="l", backstory="l")
        async_session.add(desc)
        await async_session.flush()
        loc = LocationModel(
            name="Fort", description_id=desc.id, image_id=img.id,
            start_date=date(100, 1, 1), end_date=date(3000, 1, 1),
        )
        async_session.add(loc)
        await async_session.commit()
        result = await async_session.get(LocationModel, loc.id)
        assert result.image_id == img.id


class TestImageIdForeignKeySetNullDdl:
    """DDL-level check: image_id FKs declare ON DELETE SET NULL (design D3).

    Production GC code enforces this explicitly (SQLite FK enforcement is a
    per-connection PRAGMA the app does not force globally); this test checks
    the schema itself declares the correct constraint by enabling FK
    enforcement on an isolated connection and exercising the cascade.
    """

    @pytest.mark.asyncio
    async def test_deleting_image_nulls_organization_reference(self):
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                await conn.execute(
                    text(
                        "INSERT INTO images (id, sha256, ext, width, height, size_bytes, created_at) "
                        "VALUES (1, :sha, 'png', 1, 1, 1, :now)"
                    ),
                    {"sha": "f" * 64, "now": datetime(2024, 1, 1)},
                )
                await conn.execute(
                    text(
                        "INSERT INTO organizations (id, name, start_date, end_date, image_id, rating) "
                        "VALUES (1, 'Org', '1000-01-01', '1500-01-01', 1, 1)"
                    )
                )
                await conn.execute(text("DELETE FROM images WHERE id=1"))
                row = (
                    await conn.execute(text("SELECT image_id FROM organizations WHERE id=1"))
                ).first()
                assert row[0] is None
        finally:
            await engine.dispose()
