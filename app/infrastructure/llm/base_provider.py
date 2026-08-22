"""Abstract base class for LLM providers."""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseLlmProvider(ABC):
    """Interface for LLM backends (remote OpenAI-compatible APIs)."""

    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 512,
    ) -> str:
        """Generate text given system and user prompts."""

    async def close(self) -> None:
        """Release resources held by the provider."""
