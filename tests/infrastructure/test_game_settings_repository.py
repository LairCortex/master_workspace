"""Tests for GameSettingsRepository and LlmSettingsRepository (task 6.2).

The key/value trio is now the single place the ``game_settings`` table is
touched; these unit tests pin its get/upsert/delete semantics and the typed
LLM facade over it.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import GameSettingsModel
from app.infrastructure.repositories.game_settings_repository import (
    GameSettingsRepository,
)
from app.infrastructure.repositories.llm_settings_repository import (
    FIELD_PROMPTS_KEY,
    WORLD_PROMPT_KEY,
    LlmSettingsRepository,
)


class TestGameSettingsRepository:
    async def test_get_absent_key_returns_none(self, async_session: AsyncSession):
        assert await GameSettingsRepository(async_session).get("missing") is None

    async def test_upsert_inserts_then_updates_in_place(
        self, async_session: AsyncSession
    ):
        settings = GameSettingsRepository(async_session)
        await settings.upsert("k", "one")
        assert await settings.get("k") == "one"
        await settings.upsert("k", "two")
        assert await settings.get("k") == "two"
        rows = (
            await async_session.execute(
                select(GameSettingsModel).where(GameSettingsModel.key == "k")
            )
        ).scalars().all()
        assert len(rows) == 1  # updated in place, not a second row
        assert rows[0].value == "two"

    async def test_delete_present_and_absent_are_no_crash(
        self, async_session: AsyncSession
    ):
        settings = GameSettingsRepository(async_session)
        await settings.upsert("k", "v")
        await settings.delete("k")
        assert await settings.get("k") is None
        await settings.delete("k")  # absent key: silent no-op


class TestLlmSettingsRepository:
    async def test_missing_keys_read_as_none(self, async_session: AsyncSession):
        repo = LlmSettingsRepository(async_session)
        assert await repo.load_world_prompt() is None
        assert await repo.load_field_prompts() is None

    async def test_roundtrip_through_the_shared_settings_trio(
        self, async_session: AsyncSession
    ):
        repo = LlmSettingsRepository(async_session)
        await repo.save_world_prompt('{"text": "world"}')
        await repo.save_field_prompts('{"a.b": {}}')
        assert await repo.load_world_prompt() == '{"text": "world"}'
        assert await repo.load_field_prompts() == '{"a.b": {}}'
        # the keys landed in the shared table, on the historical key names
        keys = {
            row.key
            for row in (
                await async_session.execute(select(GameSettingsModel))
            ).scalars().all()
        }
        assert keys == {WORLD_PROMPT_KEY, FIELD_PROMPTS_KEY}

    async def test_save_overwrites_previous_text(self, async_session: AsyncSession):
        repo = LlmSettingsRepository(async_session)
        await repo.save_world_prompt("first")
        await repo.save_world_prompt("second")
        assert await repo.load_world_prompt() == "second"
