"""Unit tests for GameSessionUoW — the single transaction finish point (wave 5).

Covers task 5.7: success (outer commit), error (rollback + re-raise),
non-reentrancy, and the post-write hook registry — plus the failure-mode
contracts the audit Q14 scenarios demand (hooks dropped on rollback, no
stale-hook leak when the commit itself fails, cancellation safety).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.db.models import CharacterModel
from app.infrastructure.db.uow import GameSessionUoW


def _char(name: str) -> CharacterModel:
    return CharacterModel(name=name, start_date=date(2000, 1, 1), end_date=date(2000, 1, 1))


async def _names(session: AsyncSession) -> list[str]:
    rows = await session.execute(select(CharacterModel.name))
    return sorted(rows.scalars())


async def _count(session: AsyncSession) -> int:
    return (
        await session.execute(select(func.count()).select_from(CharacterModel))
    ).scalar()


class TestSuccess:
    async def test_block_writes_are_committed_on_clean_exit(
        self, uow, async_session, async_engine
    ):
        async with uow.transaction():
            async_session.add(_char("Записана"))
        # Visible through a fresh session on the same engine: a real commit.
        factory = async_sessionmaker(async_engine, expire_on_commit=False)
        async with factory() as other:
            rows = await other.execute(select(CharacterModel.name))
            assert list(rows.scalars()) == ["Записана"]

    async def test_transaction_can_be_reopened_after_success(self, uow, async_session):
        async with uow.transaction():
            async_session.add(_char("Первая"))
        async with uow.transaction():
            async_session.add(_char("Вторая"))
        # ('В' sorts before 'П' — _names returns a sorted list.)
        assert await _names(async_session) == ["Вторая", "Первая"]


class TestError:
    async def test_exception_rolls_back_and_reraises(self, uow, async_session):
        with pytest.raises(ValueError, match="boom"):
            async with uow.transaction():
                async_session.add(_char("Сгорит"))
                raise ValueError("boom")
        # The failed row never landed; the session stayed usable.
        assert await _count(async_session) == 0


class TestNesting:
    async def test_reentry_is_refused(self, uow, async_session):
        async with uow.transaction():
            with pytest.raises(RuntimeError, match="not reentrant"):
                async with uow.transaction():
                    pass
        # The rejection is loud but harmless: the unit stays usable.
        async_session.add(_char("Цела"))
        async with uow.transaction():
            pass
        assert await _names(async_session) == ["Цела"]


class TestHooks:
    async def test_hook_runs_after_the_commit(self, uow, async_session):
        seen: list[list[str]] = []

        async def hook() -> None:
            # Registered while the transaction was open, run right after the
            # commit — the row is already durable when the hook observes it.
            rows = await async_session.execute(select(CharacterModel.name))
            seen.append(list(rows.scalars()))

        async with uow.transaction():
            async_session.add(_char("До хука"))
            uow.after_write(hook)
        assert seen == [["До хука"]]

    async def test_hooks_run_in_registration_order_and_fire_once(self, uow):
        calls: list[int] = []

        async def hook(n: int):
            calls.append(n)

        async with uow.transaction():
            uow.after_write(lambda: hook(1))
            uow.after_write(lambda: hook(2))
        assert calls == [1, 2]
        # A second transaction has no leftover hooks.
        async with uow.transaction():
            pass
        assert calls == [1, 2]

    async def test_session_work_left_by_a_hook_is_committed_by_the_unit(
        self, uow, async_session, async_engine
    ):
        async with uow.transaction():
            row = _char("Мусор")
            async_session.add(row)
        row_id = row.id  # populated by the flush inside the commit above

        async def gc() -> None:
            loaded = await async_session.get(CharacterModel, row_id)
            await async_session.delete(loaded)  # no commit inside the hook

        async with uow.transaction():
            uow.after_write(gc)
        factory = async_sessionmaker(async_engine, expire_on_commit=False)
        async with factory() as other:
            assert await _count(other) == 0

    async def test_failing_hook_is_logged_never_raised(self, uow, async_session, caplog):
        async def boom() -> None:
            raise RuntimeError("collector went boom")

        async with uow.transaction():
            async_session.add(_char("Уцелевшая"))
            uow.after_write(boom)

        # The operation succeeded, its data is written...
        assert await _names(async_session) == ["Уцелевшая"]
        # ...and the collector's failure reached the log, not the caller.
        assert "collector went boom" in caplog.text

    async def test_hooks_dropped_on_rollback(self, uow, async_session):
        ran = []

        async def hook() -> None:
            ran.append(1)

        with pytest.raises(ValueError, match="nope"):
            async with uow.transaction():
                async_session.add(_char("Сгорит"))
                uow.after_write(hook)
                raise ValueError("nope")
        assert ran == []

    async def test_after_write_requires_an_open_transaction(self, uow):
        with pytest.raises(RuntimeError, match="requires an open transaction"):
            uow.after_write(lambda: None)

    async def test_failed_commit_reraises_and_drops_hooks(
        self, uow, async_session, monkeypatch
    ):
        ran = []

        async def hook() -> None:
            ran.append(1)

        async def failing_commit():
            raise RuntimeError("commit exploded")

        monkeypatch.setattr(async_session, "commit", failing_commit)
        with pytest.raises(RuntimeError, match="commit exploded"):
            async with uow.transaction():
                async_session.add(_char("Нет"))
                uow.after_write(hook)
        # Nothing ran, and the next (working) transaction must NOT resurrect
        # the previous transaction's hooks.
        monkeypatch.undo()
        async with uow.transaction():
            pass
        assert ran == []


class TestPostWriteCommit:
    async def test_failed_post_write_commit_is_logged_not_raised(
        self, uow, async_session, monkeypatch, caplog
    ):
        row = _char("Живёт")

        async def gc() -> None:
            loaded = await async_session.get(CharacterModel, row.id)
            await async_session.delete(loaded)

        real_commit = async_session.commit
        calls = {"n": 0}

        async def commit_exploding_on_the_second_one():
            calls["n"] += 1
            if calls["n"] == 2:  # the main commit works, the hook one blows up
                raise RuntimeError("post-write commit exploded")
            return await real_commit()

        async with uow.transaction():
            async_session.add(row)

        monkeypatch.setattr(async_session, "commit", commit_exploding_on_the_second_one)
        with caplog.at_level(logging.ERROR, logger="app.db.uow"):
            async with uow.transaction():
                uow.after_write(gc)
        # The user operation already committed and was NOT reported as a
        # failure; the post-write breakage went to the log only.
        assert "post-write commit exploded" in caplog.text
        monkeypatch.undo()
        async with uow.transaction():
            async_session.add(_char("Дальше"))
        assert "Дальше" in await _names(async_session)


class TestCancellation:
    async def test_cancelled_body_rolls_back_and_frees_the_unit(
        self, uow, async_session
    ):
        async def doomed() -> None:
            async with uow.transaction():
                async_session.add(_char("Отменённая"))
                await asyncio.sleep(10)

        task = asyncio.ensure_future(doomed())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert await _count(async_session) == 0
        # The unit was freed: a new transaction over it works.
        async with uow.transaction():
            async_session.add(_char("После отмены"))
        assert await _names(async_session) == ["После отмены"]


class TestAccessors:
    def test_exposes_session_and_lock(self, async_session):
        lock = asyncio.Lock()
        unit = GameSessionUoW(async_session, lock)
        assert unit.session is async_session
        assert unit.lock is lock

    def test_owns_a_fresh_lock_when_none_given(self, async_session):
        # The wiring serializes through ``uow.lock``; a unit built without an
        # external lock must still carry a usable one.
        unit = GameSessionUoW(async_session)
        assert isinstance(unit.lock, asyncio.Lock)
