"""The encounter repository (add-dnd-game-face task 11.1).

Same discipline as every other repository here, kernel and module alike: it
moves rows, it never commits — the transaction finish belongs to the service
through ``GameSessionUoW.transaction()`` (coding principle 3). The composition
column travels through the module codec (``encode_composition`` /
``decode_composition``); the domain rebuild of a decoded row re-runs the same
clean-entry shape the codec guarantees (the codec already dropped whatever it
could not read honestly).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dd.domain.encounter import DdEncounter, EncounterEntry
from app.dd.infrastructure.db.dd_models import (
    DdEncounterModel,
    decode_composition,
)


def encounter_to_domain(row: DdEncounterModel) -> DdEncounter:
    """Row → frozen value: the JSON body decodes through the module codec
    (a corrupt body reads as no rows with a journal line, never a crash —
    the posture of every module codec)."""
    return DdEncounter(
        event_id=row.event_id,
        entries=tuple(
            EncounterEntry(
                monster_id=entry["monster_id"],
                count=entry["count"],
                name_snapshot=entry["name"],
            )
            for entry in decode_composition(row.composition)
        ),
        note=row.note,
    )


class DdEncounterRepository:
    """Row face of ``dd_encounter``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_row(self, event_id: int) -> DdEncounterModel | None:
        return await self._session.get(DdEncounterModel, event_id)

    async def list_rows(self) -> list[DdEncounterModel]:
        """The whole overlay table in event order — small by product shape
        (one row per encounter-marked event), so the source's marks cache
        rides this one read."""
        result = await self._session.execute(
            select(DdEncounterModel).order_by(DdEncounterModel.event_id)
        )
        return list(result.scalars().all())

    async def insert_row(self, event_id: int) -> DdEncounterModel:
        """The overlay appears on the first save of the «Встреча» tab; flush
        only — the service's transaction commits."""
        row = DdEncounterModel(event_id=event_id, note="")
        self._session.add(row)
        await self._session.flush()
        return row

    async def delete_row(self, row: DdEncounterModel) -> None:
        """«Пустой состав = нет встречи» at the storage floor."""
        await self._session.delete(row)
        await self._session.flush()
