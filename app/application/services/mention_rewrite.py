"""Rewrite mention display names in text columns after a target rename.

SQL stays here (not in domain). The helper does not commit.
"""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.mentions import rewrite_display_name
from app.infrastructure.db.models import (
    CharacterModel,
    DescriptionModel,
    LocationModel,
    OrganizationModel,
)


def _like_needle(entity_type: str, entity_id: int) -> str:
    return f"%({entity_type}:{entity_id})%"


def _rewrite_columns(rows, entity_type: str, entity_id: int, new_name: str, *cols: str) -> None:
    for row in rows:
        for col in cols:
            val = getattr(row, col)
            if val:
                rewritten = rewrite_display_name(val, entity_type, entity_id, new_name)
                if rewritten != val:
                    setattr(row, col, rewritten)


async def rewrite_mentions(
    session: AsyncSession,
    entity_type: str,
    entity_id: int,
    new_name: str,
) -> None:
    needle = _like_needle(entity_type, entity_id)

    desc_rows = (
        await session.execute(
            select(DescriptionModel).where(
                or_(
                    DescriptionModel.characteristics.like(needle),
                    DescriptionModel.backstory.like(needle),
                )
            )
        )
    ).scalars().all()
    _rewrite_columns(
        desc_rows, entity_type, entity_id, new_name, "characteristics", "backstory",
    )

    char_rows = (
        await session.execute(
            select(CharacterModel).where(
                or_(
                    CharacterModel.personality.like(needle),
                    CharacterModel.tasks.like(needle),
                )
            )
        )
    ).scalars().all()
    _rewrite_columns(
        char_rows, entity_type, entity_id, new_name, "personality", "tasks",
    )

    org_rows = (
        await session.execute(
            select(OrganizationModel).where(OrganizationModel.tasks.like(needle))
        )
    ).scalars().all()
    _rewrite_columns(org_rows, entity_type, entity_id, new_name, "tasks")

    loc_rows = (
        await session.execute(
            select(LocationModel).where(LocationModel.tasks.like(needle))
        )
    ).scalars().all()
    _rewrite_columns(loc_rows, entity_type, entity_id, new_name, "tasks")
