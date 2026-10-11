"""Creating the module's tables — the Д6 door, additive and idempotent.

Design Д6: the tables are created BY THE MODULE, never by the kernel's
migration machinery (``_MIGRATIONS`` would move module DDL into the kernel —
explicitly rejected). Two callers, both module doors:

* :meth:`app.dd.application.module_settings_service.ModuleSettingsService.enable`
  — the confirmed enable creates the tables inside the SAME unit-of-work
  transaction as the flag write (one operation, one transaction finish; spec
  «Включение модуля на открытой игре»);
* :func:`ensure_dd_tables` at the game-open bootstrap — an existing D&D game
  (one whose flag predates this change, or any game whose tables were never
  created) gains them additively before its first window.

``checkfirst`` is what makes both routes safe over the same file: a present
table is left exactly as it is — rows, schema, data (spec «Данные переживают
выключение модуля»). The DDL rides the caller's transaction: on SQLite DDL is
transactional, so a failed enable rolls back the flag row AND the tables it
would have created (coding principle 3: no partial result).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.dd.infrastructure.db.dd_models import DD_TABLES
from app.infrastructure.db.models import Base

if TYPE_CHECKING:
    from app.infrastructure.db.uow import GameSessionUoW


def create_dd_tables(session: Session) -> None:
    """The sync half (the ``Session.run_sync`` callable): create only the
    module's tables, skipping every present one — on the CALLER's connection,
    inside the caller's transaction (no second connection is opened)."""
    Base.metadata.create_all(session.connection(), tables=DD_TABLES, checkfirst=True)


async def ensure_dd_tables(uow: "GameSessionUoW") -> None:
    """The bootstrap door (design Д6 «bootstrap при старте D&D-игры»): one
    unit-of-work transaction around the additive create. Callers that are
    ALREADY inside a transaction (enable) call :func:`create_dd_tables`
    through ``run_sync`` themselves — the unit refuses reentry."""
    async with uow.transaction():
        await uow.session.run_sync(create_dd_tables)
