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
        max_tokens: int | None = None,
        on_phase: Callable[[str], None] | None = None,
        with_thinking: bool = False,
    ) -> str:
        """Generate text given system and user prompts.

        ``max_tokens=None`` asks the provider for its largest safe output
        budget; ``on_phase`` (optional) is called with "in_flight" before
        every request attempt POST and "waiting" before every retry backoff,
        so a caller can observe the retry cycle without changing policy.
        ``with_thinking`` lets a reasoning model produce its hidden thinking
        pass (quality over speed, for one-off field generations); False
        explicitly asks the server to suppress it (the parallel whole-card
        wave trades thinking for prompt, reliable answers).
        """

    async def close(self) -> None:
        """Release resources held by the provider."""
