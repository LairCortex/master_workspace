"""The bestiary repository (add-dnd-game-face task 10.1).

Same discipline as every other repository here, kernel and module alike: it
moves rows, it never commits — the transaction finish belongs to the service
through ``GameSessionUoW.transaction()`` (coding principle 3). The block
column travels through the group-9 codec (``encode_text_blocks`` /
``decode_text_blocks``) — one codec for every named-blocks column of the
module (one knowledge, one place).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dd.domain.monster import DdMonster
from app.dd.infrastructure.db.dd_models import (
    DdMonsterModel,
    decode_text_blocks,
)


def monster_to_domain(row: DdMonsterModel) -> DdMonster:
    """Row → frozen value: the JSON body decodes through the module codec
    (a corrupt body reads as no blocks with a journal line, never a crash —
    the posture of every module codec)."""
    return DdMonster(
        id=row.id,
        name=row.name,
        rating=row.rating,
        blocks=decode_text_blocks(row.blocks),
        image_id=row.image_id,
    )


class DdMonsterRepository:
    """Row face of ``dd_monster``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_rows(self) -> list[DdMonsterModel]:
        """The whole bestiary in creation order (id): the list is small by
        product shape — hand-written monsters, no SRD import (spec
        «автоматического импорта SRD-бестиария НЕ SHALL быть») — so the
        filter and the source cache ride this one read."""
        result = await self._session.execute(
            select(DdMonsterModel).order_by(DdMonsterModel.id)
        )
        return list(result.scalars().all())

    async def get_row(self, monster_id: int) -> DdMonsterModel | None:
        return await self._session.get(DdMonsterModel, monster_id)

    async def insert_row(self, name: str) -> DdMonsterModel:
        """The monster appears on the first save of the creation card;
        flush only — the service's transaction commits."""
        row = DdMonsterModel(name=name)
        self._session.add(row)
        await self._session.flush()
        return row
