"""Local GGUF provider backed by llama-cpp-python."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from app.infrastructure.llm.base_provider import BaseLlmProvider


class LocalGgufProvider(BaseLlmProvider):
    """Runs a GGUF model locally via llama_cpp."""

    def __init__(self, model_path: Path | None = None) -> None:
        self._model_path = model_path
        self._llm = None

    @property
    def model_path(self) -> Path | None:
        return self._model_path

    @model_path.setter
    def model_path(self, value: Path | None) -> None:
        self._model_path = value

    def is_ready(self) -> bool:
        return self._llm is not None

    async def load_model(self) -> None:
        if self._model_path is None or not self._model_path.exists():
            raise FileNotFoundError(f"Model file not found: {self._model_path}")
        self._llm = await asyncio.to_thread(self._create_llm)

    def _create_llm(self):
        from llama_cpp import Llama

        n_threads = max(1, (os.cpu_count() or 4) // 2)
        return Llama(
            model_path=str(self._model_path),
            n_ctx=4096,
            n_gpu_layers=0,
            n_threads=n_threads,
            verbose=False,
        )

    async def unload_model(self) -> None:
        if self._llm is not None:
            del self._llm
            self._llm = None

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 512,
    ) -> str:
        if self._llm is None:
            raise RuntimeError("Model not loaded")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        result = await asyncio.to_thread(
            self._llm.create_chat_completion,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
        )

        choices = result.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "").strip()
