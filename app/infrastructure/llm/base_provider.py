"""Abstract base class for LLM providers."""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseLlmProvider(ABC):
    """Interface for all LLM backends (local GGUF, cloud APIs, etc.)."""

    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 512,
    ) -> str:
        """Generate text given system and user prompts."""

    @abstractmethod
    def is_ready(self) -> bool:
        """Return True when the provider can accept generate() calls."""

    @abstractmethod
    async def load_model(self) -> None:
        """Load / initialise the underlying model."""

    @abstractmethod
    async def unload_model(self) -> None:
        """Release resources held by the model."""
