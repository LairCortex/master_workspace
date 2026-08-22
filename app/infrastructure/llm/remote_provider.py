"""Remote OpenAI-compatible LLM provider.

Covers cloud backends (OpenAI, OpenRouter, Groq, …) and local
OpenAI-compatible servers (Ollama, vLLM, LM Studio, llama.cpp server)
via ``POST {base_url}/chat/completions``.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from app.infrastructure.http import AppHttpClient
from app.infrastructure.llm.base_provider import BaseLlmProvider
from app.infrastructure.llm.config import LlmConfig
from app.infrastructure.llm.errors import (
    LlmError,
    LlmHttpError,
    LlmNetworkError,
    LlmTimeoutError,
    parse_error_message,
)

log = logging.getLogger(__name__)

#: Retries after the first attempt (up to 3 total attempts).
MAX_RETRIES = 2
#: Backoff delays before retry attempts, seconds (exponential).
RETRY_BACKOFFS: tuple[float, ...] = (0.5, 1.0)
#: Generation temperature — fixed constant, no UI.
TEMPERATURE = 0.7
#: Endpoint path appended to the user-provided base URL.
CHAT_COMPLETIONS_PATH = "/chat/completions"


def _is_retryable_status(status_code: int) -> bool:
    """Only 429 and 5xx responses are retried; other 4xx fail immediately."""
    return status_code == 429 or 500 <= status_code < 600


class RemoteLlmProvider(BaseLlmProvider):
    """Sends chat-completion requests to an OpenAI-compatible endpoint."""

    def __init__(
        self,
        config: LlmConfig,
        http: AppHttpClient,
        backoffs: tuple[float, ...] = RETRY_BACKOFFS,
    ) -> None:
        self._config = config
        self._http = http
        self._backoffs = backoffs

    @property
    def config(self) -> LlmConfig:
        return self._config

    def is_configured(self) -> bool:
        """True when non-empty base_url and model are set (no network)."""
        return self._config.is_complete

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 512,
    ) -> str:
        return await self._request(system_prompt, user_prompt, max_tokens=max_tokens)

    async def check_connection(self, max_tokens: int = 1) -> str:
        """Minimal test request (single token); raises LlmError on failure."""
        return await self._request("Тест подключения.", "Ответь одним словом.", max_tokens=max_tokens)

    async def _request(self, system_prompt: str, user_prompt: str, *, max_tokens: int) -> str:
        if not self.is_configured():
            raise LlmError("LLM не настроен. Откройте меню LLM → Настройка LLM…")

        url = self._config.base_url.strip().rstrip("/") + CHAT_COMPLETIONS_PATH
        headers = {"Content-Type": "application/json"}
        api_key = self._config.api_key.strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": self._config.model.strip(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": TEMPERATURE,
        }

        error: LlmError | None = None
        response: httpx.Response | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await self._http.client.post(url, json=payload, headers=headers)
            except httpx.TimeoutException:
                log.warning("LLM request timed out (attempt %d)", attempt + 1)
                error = LlmTimeoutError()
            except httpx.HTTPError as exc:
                log.warning("LLM request failed (attempt %d): %s", attempt + 1, exc)
                error = LlmNetworkError()
            else:
                if response.status_code < 400:
                    break
                error = LlmHttpError(response.status_code, parse_error_message(response.text))
                if not _is_retryable_status(response.status_code):
                    raise error

            if attempt < MAX_RETRIES:
                delay = self._backoffs[min(attempt, len(self._backoffs) - 1)]
                log.info("Retrying LLM request in %.1f s (attempt %d)", delay, attempt + 2)
                await asyncio.sleep(delay)
            else:
                raise error
        assert response is not None
        return self._extract_content(response.json())

    @staticmethod
    def _extract_content(data: dict) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LlmError("LLM вернул пустой ответ. Попробуйте позже.")
        content = choices[0].get("message", {}).get("content", "")
        return (content or "").strip()
