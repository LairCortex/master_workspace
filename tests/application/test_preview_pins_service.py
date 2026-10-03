"""PreviewPinsService (NRI-0025 task 1.2, design Д3).

Pins the thin storage face: ``get_pins`` is a plain read of the saved list
(order preserved, absent key = empty list, no transaction opened), and
``save_pins`` finishes through exactly one ``GameSessionUoW.transaction()``
per call — the repository itself never commits.  A failed write leaves no
partial list behind.
"""
from __future__ import annotations

import logging

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.preview_pins_service import PreviewPinsService
from app.infrastructure.db.models import GameSettingsModel
from app.infrastructure.db.uow import GameSessionUoW
from app.infrastructure.repositories.game_settings_repository import (
    PREVIEW_PINS_KEY,
)

# Order and a deliberate duplicate — the two properties the wire must keep.
PINS = [("character", 3), ("item", 1), ("character", 3)]


async def _stored_text(session: AsyncSession) -> str | None:
    return (
        await session.execute(
            select(GameSettingsModel.value).where(
                GameSettingsModel.key == PREVIEW_PINS_KEY
            )
        )
    ).scalars().first()


class TestGetPins:
    async def test_absent_key_reads_empty_list_without_a_transaction(
        self,
        async_session: AsyncSession,
        uow: GameSessionUoW,
        monkeypatch,
        caplog,
    ):
        # spec «отсутствие ключа = пустой список» on the service face, and
        # the read opens no transaction (same discipline as load «сейчас»)
        transactions = []
        real_transaction = uow.transaction
        monkeypatch.setattr(
            uow,
            "transaction",
            lambda: transactions.append(1) or real_transaction(),
        )
        with caplog.at_level(logging.WARNING):
            assert await PreviewPinsService(uow).get_pins() == []
        assert transactions == []  # a read opens no transaction
        assert not caplog.records  # absence is silent, not corruption

    async def test_reads_the_saved_order_through_a_fresh_holder(
        self, uow: GameSessionUoW
    ):
        # «сохранение/чтение порядка»: the second holder (the restart's
        # connector) sees the first one's list, pairs and order intact
        await PreviewPinsService(uow).save_pins(PINS)
        assert await PreviewPinsService(uow).get_pins() == PINS

    async def test_corrupted_value_serves_empty_list_with_the_journal_entry(
        self, async_session: AsyncSession, uow: GameSessionUoW, caplog
    ):
        # the codec's journal entry surfaces through the service read; the
        # caller then lives by the absence rule (empty list)
        raw = "не json"
        async_session.add(GameSettingsModel(key=PREVIEW_PINS_KEY, value=raw))
        await async_session.commit()
        with caplog.at_level(logging.WARNING):
            assert await PreviewPinsService(uow).get_pins() == []
        assert any(PREVIEW_PINS_KEY in r.getMessage() for r in caplog.records)
        assert await _stored_text(async_session) == raw


class TestSavePins:
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

        await PreviewPinsService(uow).save_pins(PINS)

        assert len(transactions) == 1  # ровно одна транзакция UoW на запись
        assert len(commits) == 1  # …and it finishes through the single point
        assert await PreviewPinsService(uow).get_pins() == PINS

    async def test_empty_list_is_a_persisted_clean_state(
        self, async_session: AsyncSession, uow: GameSessionUoW
    ):
        # «пустой список»: the last unpin persists as an explicit empty list
        await PreviewPinsService(uow).save_pins(PINS)
        await PreviewPinsService(uow).save_pins([])
        assert await PreviewPinsService(uow).get_pins() == []
        assert await _stored_text(async_session) == "[]"

    async def test_refuses_to_join_an_already_open_transaction(
        self, uow: GameSessionUoW
    ):
        # The service finishes its write itself, always in its own single
        # transaction — a nested open is the UoW's loud reentry refusal.
        service = PreviewPinsService(uow)
        with pytest.raises(RuntimeError):
            async with uow.transaction():
                await service.save_pins(PINS)

    async def test_failed_commit_persists_nothing(
        self, async_session: AsyncSession, uow: GameSessionUoW, monkeypatch
    ):
        async def broken_commit():
            raise OSError("commit failed")

        monkeypatch.setattr(async_session, "commit", broken_commit)
        with pytest.raises(OSError):
            await PreviewPinsService(uow).save_pins(PINS)
        monkeypatch.undo()
        # the rollback left no key behind (repository itself never committed)
        assert await _stored_text(async_session) is None
        assert await PreviewPinsService(uow).get_pins() == []
