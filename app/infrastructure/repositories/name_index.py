"""Name-occurrence queries for the xlsx import (audit B6, design D6).

The import's pre-analysis needs, per entity type, which lower(name)s are
ambiguous in the DB and which model rows carry its wanted names.  That was
raw ``select``/``group_by`` SQL issued by the service over all five ORM
entity models (finding B6); the queries now live in the repository layer,
next to the type↔ORM map they already read, and the service assembles the
plan structures from these raw results.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums.entity_type import EntityType
from app.infrastructure.repositories import ORM_MODEL_BY_ENTITY_TYPE


async def query_lower_name_index(
    session: AsyncSession, entity_type_key: str, lower_names: set[str]
) -> tuple[set[str], dict[str, list[Any]]]:
    """``(ambiguous lower(name)s, candidate models per lower(name))`` for
    the wanted set of one entity type.

    One grouped count query + one candidate query per type (never per
    row): ambiguity via ``GROUP BY lower(name) HAVING COUNT(*) > 1``
    (only the wanted names are reported), candidates via a
    ``lower(name) IN`` lookup. The SQL is exactly what the import service
    used to issue itself.
    """
    model = ORM_MODEL_BY_ENTITY_TYPE[EntityType(entity_type_key)]
    lower_name = func.lower(model.name)
    grouped = (
        select(lower_name.label("lower_name"), func.count().label("row_count"))
        .group_by(lower_name)
        .having(func.count() > 1)
    )
    ambiguous = {
        r.lower_name
        for r in (await session.execute(grouped)).all()
        if r.lower_name in lower_names
    }
    candidates = (
        await session.execute(select(model).where(lower_name.in_(sorted(lower_names))))
    ).scalars().all()
    by_lower: dict[str, list[Any]] = {}
    for obj in candidates:
        by_lower.setdefault(str(obj.name).lower(), []).append(obj)
    return ambiguous, by_lower
