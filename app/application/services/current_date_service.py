"""Game-bound «now» date service (NRI-0021 task 2.2, design Д2).

One instance per opened game (the composition root builds it right after
:meth:`CalendarSettingsService.load_and_apply`, so the coordinate is read
against the calendar the game actually lives on).  The service is the sole
holder of the value and its sole write path:

* :meth:`CurrentDateService.load` reads ``game_settings.current_date``; an
  absent (or corrupted — the storage wrapper already logged and answered
  ``None``) value seeds the in-memory «now» with the real today translated
  through ``as_game_coord``, WITHOUT writing any key (spec «Пока игра не
  имеет сохранённого значения…»).  The date is injectable for tests.
* :meth:`CurrentDateService.set_now` is the first write: exactly one
  ``GameSessionUoW.transaction()`` around the repository upsert — the
  repository itself never commits (design Д1), and the in-memory value plus
  the change counter move only after that transaction committed, so a
  failed write leaves the served «now» at its previous value.

No Qt here (Д2): presentation subscribes through its own sync view model,
``revision`` being the monotonic edit counter it mirrors.
"""
from __future__ import annotations

from datetime import date

from app.domain.game_calendar import GameCoord, as_game_coord
from app.infrastructure.db.uow import GameSessionUoW
from app.infrastructure.repositories.game_settings_repository import (
    CurrentDateRepository,
    CurrentDateValue,
)


class CurrentDateService:
    """Holds the game's «now» (:class:`CurrentDateValue`) and its change
    counter; every edit finishes through the game's single unit of work."""

    def __init__(self, uow: GameSessionUoW) -> None:
        self._uow = uow
        self._value: CurrentDateValue | None = None
        self._revision = 0

    @property
    def value(self) -> CurrentDateValue | None:
        """The served «now» — ``None`` until :meth:`load` has run."""
        return self._value

    @property
    def revision(self) -> int:
        """Monotonic counter of applied :meth:`set_now` edits (Д2)."""
        return self._revision

    async def load(self, today: date | None = None) -> CurrentDateValue:
        """Read the stored value or seed the real today in memory (no write).

        ``today`` is injectable so tests freeze "the real today" (spec «Новая
        игра стартует сегодняшним днём»); production passes nothing and the
        system date is read here, at game open — never stored anywhere.  The
        seeded value carries no hour (spec «без часа»): «час не выставлен» is
        the state of every untouched game, and the read wrapper has already
        dropped a stored hour a narrowed day no longer hosts (design Д5).
        """
        stored = await CurrentDateRepository(self._uow.session).load()
        if stored is None:
            stored = CurrentDateValue(
                coord=as_game_coord(today or date.today()), is_bc=False
            )
        self._value = stored
        return stored

    async def set_now(
        self, coord: GameCoord, is_bc: bool = False, hour: int | None = None
    ) -> None:
        """Persist the master's edit: one transaction, one upsert (Д1/Д2).

        ``hour`` is the NRI-0023 optional «сейчас» hour (design Д5); ``None``
        — the default — writes the pre-0023 value without the ``h`` key, so a
        date-only edit stays byte-identical.  Any error rolls the write back
        and re-raises with the served value untouched — the counter and the
        in-memory «now» only follow a committed transaction."""
        async with self._uow.transaction():
            await CurrentDateRepository(self._uow.session).save(coord, is_bc, hour)
        self._value = CurrentDateValue(coord=coord, is_bc=is_bc, hour=hour)
        self._revision += 1
