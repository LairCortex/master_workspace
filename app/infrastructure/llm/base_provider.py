"""Abstract base class for LLM providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable


class BaseLlmProvider(ABC):
    """Interface for LLM backends (remote OpenAI-compatible APIs)."""

    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 512,
        on_phase: Callable[[str], None] | None = None,
    ) -> str:
        """Generate text given system and user prompts.

        ``on_phase`` (optional) is called with "in_flight" before every
        request attempt POST and "waiting" before every retry backoff, so
        a caller can observe the retry cycle without changing policy.
        """

    async def close(self) -> None:
        """Release resources held by the provider."""
