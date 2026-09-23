"""Per-game LLM prompt settings (audit B2, task 6.2).

The two ``game_settings`` keys used to live in the presentation layer
(``presentation/llm_viewmodel.py``) while ``Application`` hand-rolled the
``game_settings`` CRUD around them; both moved here — the keys and the
storage access now sit in infrastructure, and the view model only receives
already-decoded texts.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories.game_settings_repository import (
    GameSettingsRepository,
)

WORLD_PROMPT_KEY = "llm_world_prompt"
FIELD_PROMPTS_KEY = "llm_field_prompts"


class LlmSettingsRepository:
    """Typed storage access for the two per-game LLM prompt keys.

    The values are opaque JSON texts owned by :class:`LlmViewModel`; this
    repository only reads and writes the strings through the shared
    :class:`GameSettingsRepository` trio (no second CRUD copy — task 6.2).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._settings = GameSettingsRepository(session)

    async def load_world_prompt(self) -> str | None:
        return await self._settings.get(WORLD_PROMPT_KEY)

    async def load_field_prompts(self) -> str | None:
        return await self._settings.get(FIELD_PROMPTS_KEY)

    async def save_world_prompt(self, value: str) -> None:
        await self._settings.upsert(WORLD_PROMPT_KEY, value)

    async def save_field_prompts(self, value: str) -> None:
        await self._settings.upsert(FIELD_PROMPTS_KEY, value)
