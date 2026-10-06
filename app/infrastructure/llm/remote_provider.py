"""Remote OpenAI-compatible LLM provider.

Covers cloud backends (OpenAI, OpenRouter, Groq, …) and local
OpenAI-compatible servers (Ollama, vLLM, LM Studio, llama.cpp server)
via ``POST {base_url}/chat/completions``.

Reasoning models (Qwen3 et al.) burn the whole ``max_tokens`` budget on
hidden thinking and answer with empty content — which field of a
whole-card wave comes back empty was decided by each attempt's thinking
length (owner report 2026-10-06). The provider answers this on two axes:
the caller states per request whether thinking is allowed (single-field
generations think, the parallel wave does not), and every request sends
the largest output budget the server itself reported, not a fixed 512.
The context limit is discovered with one cheap oversized request whose
rejection names the limit; servers that never reveal it keep the
historical fallback.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Callable

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
#: One answer = text or error (PR-023): no choices, or empty/null/blank
#: content — incl. finish_reason="length" — is this same provider error.
EMPTY_ANSWER_MESSAGE = "LLM вернул пустой ответ. Попробуйте позже."
#: Share of the server's context the app may ask to be filled with output
#: (thinking + answer); the rest is reserved for the prompt.
OUTPUT_BUDGET_SHARE = 0.7
#: Output size large enough that any server with a context check rejects
#: it by name, revealing the limit in the refusal text.
PROBE_MAX_OUTPUT_TOKENS = 1_000_000
#: Budget of the pre-discovery era, kept as the fallback for servers that
#: neither reject the probe nor answer within it.
FALLBACK_MAX_TOKENS = 512
#: Wordings under which known OpenAI-compatible servers name their
#: context length in a rejection (Bifrost/vLLM, vLLM proper, llama.cpp).
_CONTEXT_LIMIT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"max_model_len\s*=\s*(?:max_total_tokens\s*=\s*)?(\d+)"),
    re.compile(r"maximum context length is (\d+)"),
    re.compile(r"context size is (\d+)"),
)


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
        #: Largest output budget derived from the server's context limit;
        #: None while unknown (probe pending or uninformative).
        self._output_budget: int | None = None
        #: The probe runs at most once per provider (config change rebuilds
        #: it), even when it learned nothing — no per-request penalty.
        self._budget_probed = False
        self._budget_lock = asyncio.Lock()

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
        max_tokens: int | None = None,
        on_phase: Callable[[str], None] | None = None,
        with_thinking: bool = False,
    ) -> str:
        if max_tokens is None:
            budget = await self.output_budget()
            max_tokens = budget if budget is not None else FALLBACK_MAX_TOKENS
        return await self._request(system_prompt, user_prompt, max_tokens=max_tokens,
                                   on_phase=on_phase, enable_thinking=with_thinking)

    async def check_connection(self, max_tokens: int = 1, on_phase: Callable[[str], None] | None = None) -> str:
        """Minimal test request (single token); raises LlmError on failure.

        Doubles as the moment the app learns the server's output budget:
        the probe rides the connection the user just verified, so the
        first real generation does not pay for it.
        """
        await self.output_budget()
        return await self._request("Тест подключения.", "Ответь одним словом.", max_tokens=max_tokens,
                                   on_phase=on_phase)

    async def output_budget(self) -> int | None:
        """Largest safe output token count the server allows, or None.

        Discovered once (guarded against a parallel wave racing to the
        probe); None means the server never revealed its limit, so the
        caller falls back to the historical constant.
        """
        if not self.is_configured():
            return None
        if self._budget_probed:
            return self._output_budget
        # No re-check inside the lock: on this single-loop model the path
        # from the check above to the flag set below holds no suspension
        # point (an uncontended ``asyncio.Lock`` acquire never yields), so a
        # caller that read the flag False can only ever find the lock free —
        # the check above already carries the whole single-probe guarantee
        # the parallel-wave test pins.
        async with self._budget_lock:
            self._budget_probed = True
            limit = await self._probe_context_limit()
            if limit is not None:
                self._output_budget = max(1, int(limit * OUTPUT_BUDGET_SHARE))
            return self._output_budget

    async def _probe_context_limit(self) -> int | None:
        """One oversized request that reveals the server's context limit.

        A server that checks its context answers the oversized request
        with a refusal naming the size; a lenient server accepts it and
        the answer stops at its own end (the probe asks for one word).
        Any transport failure or an unparsable refusal means unknown.
        """
        payload = {
            "model": self._config.model.strip(),
            "messages": [
                {"role": "system", "content": "Тест."},
                {"role": "user", "content": "Ответь одним словом: ОК"},
            ],
            "max_tokens": PROBE_MAX_OUTPUT_TOKENS,
            "temperature": TEMPERATURE,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        try:
            response = await self._http.client.post(
                self._chat_url(), json=payload, headers=self._headers()
            )
        except httpx.HTTPError:
            log.warning("LLM context-limit probe failed", exc_info=True)
            return None
        if response.status_code < 400:
            # Accepted: the server clamps output itself, the probe size is
            # a legal ask, so the same size minus the prompt share is safe.
            return PROBE_MAX_OUTPUT_TOKENS
        for pattern in _CONTEXT_LIMIT_PATTERNS:
            match = pattern.search(response.text)
            if match:
                return int(match.group(1))
        return None

    def _chat_url(self) -> str:
        return self._config.base_url.strip().rstrip("/") + CHAT_COMPLETIONS_PATH

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        api_key = self._config.api_key.strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    async def _request(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int,
        on_phase: Callable[[str], None] | None = None,
        enable_thinking: bool = False,
    ) -> str:
        if not self.is_configured():
            raise LlmError("LLM не настроен. Откройте меню LLM → Настройка LLM…")

        url = self._chat_url()
        headers = self._headers()

        payload = {
            "model": self._config.model.strip(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": TEMPERATURE,
            # Stated explicitly in both directions: servers whose chat
            # template defaults to thinking ON must also be able to be
            # switched off, and vLLM/llama.cpp honour this extension while
            # lenient frontends ignore the unknown field (strict OpenAI
            # proper would reject it — a conscious trade for the
            # local-server target of this app).
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
        }

        error: LlmError | None = None
        response: httpx.Response | None = None
        for attempt in range(MAX_RETRIES + 1):
            if on_phase is not None:
                on_phase("in_flight")
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
                if on_phase is not None:
                    on_phase("waiting")
                await asyncio.sleep(delay)
            else:
                raise error
        assert response is not None
        try:
            data = response.json()
        except ValueError:
            raise LlmError("LLM вернул некорректный ответ. Попробуйте позже.") from None
        return self._extract_content(data)

    @staticmethod
    def _extract_content(data: dict) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LlmError(EMPTY_ANSWER_MESSAGE)
        content = choices[0].get("message", {}).get("content", "")
        text = (content or "").strip()
        if not text:
            # PR-023: an empty answer is never a success — reaching the
            # caller with "" would silently wipe the field it writes.
            raise LlmError(EMPTY_ANSWER_MESSAGE)
        return text
