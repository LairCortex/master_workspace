"""CurrentDateService (NRI-0021 task 2.2, design Д2).

Pins the seeding rule (no key → injected real today, nothing written), the
one-transaction write discipline of ``set_now`` (exactly one UoW transaction
and one commit; the repository itself never commits), the post-commit-only
movement of the served value and its counter, and the read of a stored —
including corrupted — value.
"""
from __future__ import annotations

import json
import logging
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.current_date_service import CurrentDateService
from app.domain.game_calendar import (
    MonthDay,
    reset_current_calendar,
)
from app.infrastructure.db.models import GameSettingsModel
from app.infrastructure.db.uow import GameSessionUoW
from app.infrastructure.repositories.game_settings_repository import (
    CURRENT_DATE_KEY,
    CurrentDateRepository,
    CurrentDateValue,
)

TODAY = date(2027, 3, 14)


@pytest.fixture(autouse=True)
def _fresh_active_calendar():
    """The storage wrapper checks the value against the active calendar."""
    reset_current_calendar()
    yield
    reset_current_calendar()


async def _stored_text(session: AsyncSession) -> str | None:
    return (
        await session.execute(
            select(GameSettingsModel.value).where(
                GameSettingsModel.key == CURRENT_DATE_KEY
            )
        )
    ).scalars().first()


async def _put_raw(session: AsyncSession, value: str) -> None:
    session.add(GameSettingsModel(key=CURRENT_DATE_KEY, value=value))
    await session.commit()


class TestLoad:
    async def test_absent_key_seeds_injected_today_without_writing(
        self, async_session: AsyncSession, uow: GameSessionUoW
    ):
        service = CurrentDateService(uow)
        value = await service.load(TODAY)
        assert value == CurrentDateValue(MonthDay(2027, 3, 14), False)
        # the value is served…
        assert service.value == value
        assert service.revision == 0
        # …but no key was written: absence stays absence (spec «первое
        # изменение значения SHALL записать его» — only an edit writes).
        assert await _stored_text(async_session) is None

    async def test_stored_value_wins_over_the_injected_today(
        self, async_session: AsyncSession, uow: GameSessionUoW
    ):
        await CurrentDateRepository(async_session).save(MonthDay(2088, 5, 1), True)
        await async_session.commit()
        service = CurrentDateService(uow)
        assert await service.load(TODAY) == CurrentDateValue(MonthDay(2088, 5, 1), True)

    async def test_corrupted_value_lives_by_the_absence_rule(
        self, async_session: AsyncSession, uow: GameSessionUoW, caplog
    ):
        # Д1: a damaged row (the wrapper logged it in its own tests) reads as
        # absent here — the game opens on the real today, the row survives.
        raw = "{сломанный json"
        await _put_raw(async_session, raw)
        service = CurrentDateService(uow)
        with caplog.at_level(logging.WARNING):
            value = await service.load(TODAY)
        assert value == CurrentDateValue(MonthDay(2027, 3, 14), False)
        assert service.value == value
        assert any(CURRENT_DATE_KEY in r.getMessage() for r in caplog.records)
        assert await _stored_text(async_session) == raw

    async def test_load_before_load_has_run_serves_none(
        self, uow: GameSessionUoW
    ):
        service = CurrentDateService(uow)
        assert service.value is None


class TestSetNow:
    async def test_opens_exactly_one_transaction_and_commits_once(
        self, async_session: AsyncSession, uow: GameSessionUoW, monkeypatch
    ):
        transactions = []
        real_transaction = uow.transaction
        monkeypatch.setattr(
            uow,
            "transaction",
            lambda: transactions.append(1) or real_transaction(),
        )
        commits = []
        real_commit = async_session.commit

        async def counting_commit():
            commits.append(1)
            return await real_commit()

        monkeypatch.setattr(async_session, "commit", counting_commit)

        service = CurrentDateService(uow)
        await service.load(TODAY)
        transactions.clear()
        commits.clear()

        await service.set_now(MonthDay(44, 11, 3), True)

        assert len(transactions) == 1  # ровно одна транзакция UoW на правку
        assert len(commits) == 1  # …and it finishes through the single point
        # the edit is the first write of the key (spec «первое изменение…»)
        assert await _stored_text(async_session) is not None
        assert await CurrentDateRepository(async_session).load() == (
            CurrentDateValue(MonthDay(44, 11, 3), True)
        )
        assert service.value == CurrentDateValue(MonthDay(44, 11, 3), True)
        assert service.revision == 1

    async def test_refuses_to_join_an_already_open_transaction(
        self, uow: GameSessionUoW
    ):
        # The service finishes its write itself, always in its own single
        # transaction — a nested open is the UoW's loud reentry refusal.
        service = CurrentDateService(uow)
        with pytest.raises(RuntimeError):
            async with uow.transaction():
                await service.set_now(MonthDay(2088, 5, 1))

    async def test_failed_write_leaves_value_and_counter_untouched(
        self, async_session: AsyncSession, uow: GameSessionUoW, monkeypatch
    ):
        service = CurrentDateService(uow)
        await service.load(TODAY)

        async def broken_commit():
            raise OSError("commit failed")

        monkeypatch.setattr(async_session, "commit", broken_commit)
        with pytest.raises(OSError):
            await service.set_now(MonthDay(44, 11, 3))
        # the served «now» never moved to the uncommitted value…
        assert service.value == CurrentDateValue(MonthDay(2027, 3, 14), False)
        assert service.revision == 0
        # …and the rollback left no key behind (repository itself never
        # committed — the transaction owns the finish).
        monkeypatch.undo()
        assert await _stored_text(async_session) is None

    async def test_revision_counts_applied_edits_only(
        self, async_session: AsyncSession, uow: GameSessionUoW
    ):
        service = CurrentDateService(uow)
        await service.load(TODAY)  # seeding is not an edit
        assert service.revision == 0
        await service.set_now(MonthDay(2088, 5, 1))
        await service.set_now(MonthDay(2089, 5, 1), True)
        assert service.revision == 2
        # a reload re-reads the last edit and keeps serving it per game open
        reopened = CurrentDateService(uow)
        assert await reopened.load(TODAY) == CurrentDateValue(MonthDay(2089, 5, 1), True)
        assert reopened.revision == 0  # per-holder counter, per-game holder

    # ── NRI-0023 task 2.3: час «сейчас» (design Д5) ─────────────────────────

    async def test_set_now_with_hour_writes_it_and_serves_it(
        self, async_session: AsyncSession, uow: GameSessionUoW
    ):
        # сценарий «Час помнится после перезапуска» на стороне записи: тот же
        # один транзакционный upsert, в JSON добавлен только ключ «h».
        service = CurrentDateService(uow)
        await service.load(TODAY)
        await service.set_now(MonthDay(44, 11, 3), False, 14)
        assert json.loads(await _stored_text(async_session)) == {
            "coord": "M:44:11:3",
            "bc": 0,
            "h": 14,
        }
        assert service.value == CurrentDateValue(MonthDay(44, 11, 3), False, 14)
        reopened = CurrentDateService(uow)
        assert await reopened.load(TODAY) == CurrentDateValue(
            MonthDay(44, 11, 3), False, 14
        )

    async def test_set_now_without_hour_keeps_the_pre_0023_wire(
        self, async_session: AsyncSession, uow: GameSessionUoW
    ):
        # отсутствие ключа — поведение как прежде: дата-only правка пишет
        # прежний двухключевой JSON и читается без часа
        service = CurrentDateService(uow)
        await service.load(TODAY)
        await service.set_now(MonthDay(44, 11, 3))
        assert await _stored_text(async_session) == '{"coord": "M:44:11:3", "bc": 0}'
        reopened = CurrentDateService(uow)
        assert await reopened.load(TODAY) == CurrentDateValue(MonthDay(44, 11, 3), False)
