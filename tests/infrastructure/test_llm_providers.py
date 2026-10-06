"""Tests for RemoteLlmProvider — request, retries, errors (no network)."""
from __future__ import annotations

import json

import httpx
import pytest

from app.infrastructure.http import AppHttpClient
from app.infrastructure.llm.config import LlmConfig
from app.infrastructure.llm.errors import (
    LlmError,
    LlmHttpError,
    LlmNetworkError,
    LlmTimeoutError,
)
import asyncio

from app.infrastructure.llm.remote_provider import (
    FALLBACK_MAX_TOKENS,
    MAX_RETRIES,
    OUTPUT_BUDGET_SHARE,
    PROBE_MAX_OUTPUT_TOKENS,
    RemoteLlmProvider,
)


def make_provider(handler, **config_overrides):
    """Build provider + http holder around a MockTransport handler."""
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    http = AppHttpClient(client=client)
    kwargs = dict(base_url="https://llm.test/v1", model="test-model")
    kwargs.update(config_overrides)
    config = LlmConfig(**kwargs)
    provider = RemoteLlmProvider(config, http, backoffs=(0.0, 0.0))
    return provider, http


def ok_response(content="hello"):
    return httpx.Response(
        200, json={"choices": [{"message": {"content": f" {content} "}}]}
    )


def error_response(status, message="some server error"):
    return httpx.Response(status, json={"error": {"message": message, "type": "test"}})


# --- success path ---------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_success():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.content)
        return ok_response("Привет, мир")

    provider, http = make_provider(handler)
    try:
        result = await provider.generate("Система", "Пользователь", max_tokens=128)
    finally:
        await http.close()

    assert result == "Привет, мир"
    assert seen["method"] == "POST"
    assert seen["url"] == "https://llm.test/v1/chat/completions"
    assert seen["payload"]["model"] == "test-model"
    assert seen["payload"]["max_tokens"] == 128
    # Reasoning models burn the whole max_tokens budget on hidden thinking
    # and answer empty — every request must carry the disable switch.
    assert seen["payload"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert seen["payload"]["messages"][0] == {"role": "system", "content": "Система"}
    assert seen["payload"]["messages"][1] == {"role": "user", "content": "Пользователь"}


@pytest.mark.asyncio
async def test_no_auth_header_without_api_key():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        return ok_response()

    provider, http = make_provider(handler, api_key="")
    try:
        await provider.generate("s", "u", max_tokens=10)
    finally:
        await http.close()
    assert "authorization" not in seen["headers"]


@pytest.mark.asyncio
async def test_bearer_auth_header_with_api_key():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        return ok_response()

    provider, http = make_provider(handler, api_key="sk-123")
    try:
        await provider.generate("s", "u", max_tokens=10)
    finally:
        await http.close()
    assert seen["headers"].get("authorization") == "Bearer sk-123"


@pytest.mark.asyncio
async def test_check_connection_sends_single_token():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return ok_response("ок")

    provider, http = make_provider(handler)
    try:
        result = await provider.check_connection()
    finally:
        await http.close()
    assert result == "ок"
    assert seen["payload"]["max_tokens"] == 1
    assert seen["payload"]["chat_template_kwargs"] == {"enable_thinking": False}


# --- non-retryable 4xx ----------------------------------------------------


@pytest.mark.asyncio
async def test_401_raises_without_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return error_response(401, "Invalid API key provided")

    provider, http = make_provider(handler, api_key="bad")
    try:
        with pytest.raises(LlmHttpError) as excinfo:
            await provider.generate("s", "u", max_tokens=10)
    finally:
        await http.close()

    assert calls["n"] == 1
    assert excinfo.value.status == 401
    assert "неверный ключ" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_404_raises_without_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return error_response(404)

    provider, http = make_provider(handler)
    try:
        with pytest.raises(LlmHttpError) as excinfo:
            await provider.generate("s", "u", max_tokens=10)
    finally:
        await http.close()

    assert calls["n"] == 1
    assert "не найдены" in str(excinfo.value).lower()


# --- retries --------------------------------------------------------------


@pytest.mark.asyncio
async def test_503_then_success():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return error_response(503, "unavailable")
        return ok_response("ok")

    provider, http = make_provider(handler)
    try:
        result = await provider.generate("s", "u", max_tokens=10)
    finally:
        await http.close()

    assert result == "ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_429_then_success():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return error_response(429, "rate limited")
        return ok_response("ok")

    provider, http = make_provider(handler)
    try:
        result = await provider.generate("s", "u", max_tokens=10)
    finally:
        await http.close()

    assert result == "ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_429_exhausts_retries():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return error_response(429, "rate limited")

    provider, http = make_provider(handler)
    try:
        with pytest.raises(LlmHttpError) as excinfo:
            await provider.generate("s", "u", max_tokens=10)
    finally:
        await http.close()

    assert calls["n"] == MAX_RETRIES + 1
    assert "лимит запросов" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_timeout_exhausts_retries():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("read timed out")

    provider, http = make_provider(handler)
    try:
        with pytest.raises(LlmTimeoutError) as excinfo:
            await provider.generate("s", "u", max_tokens=10)
    finally:
        await http.close()

    assert calls["n"] == MAX_RETRIES + 1
    assert "время ожидания" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_connection_error_raises_network():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("network unreachable")

    provider, http = make_provider(handler)
    try:
        with pytest.raises(LlmNetworkError) as excinfo:
            await provider.generate("s", "u", max_tokens=10)
    finally:
        await http.close()

    assert calls["n"] == MAX_RETRIES + 1
    assert "сервер llm недоступен" in str(excinfo.value).lower()


# --- config edge cases ----------------------------------------------------


@pytest.mark.asyncio
async def test_not_configured_raises_without_request():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return ok_response()

    provider, http = make_provider(handler, base_url="", model="")
    try:
        assert provider.is_configured() is False
        with pytest.raises(LlmError, match="LLM не настроен"):
            await provider.generate("s", "u", max_tokens=10)
    finally:
        await http.close()

    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_empty_choices_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    provider, http = make_provider(handler)
    try:
        with pytest.raises(LlmError, match="пустой ответ"):
            await provider.generate("s", "u", max_tokens=10)
    finally:
        await http.close()


# PR-023: an HTTP 200 whose answer text is empty is a provider-answer error,
# not a success: RU LlmError, field never receives "", exactly ONE request
# (empty is not timeout/network/429/5xx — the retry policy does not cover it).


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["", None, "   \n "])
async def test_empty_content_raises_ru_error_without_retry(content):
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}]},
        )

    provider, http = make_provider(handler)
    try:
        with pytest.raises(LlmError, match="пустой ответ"):
            await provider.generate("s", "u", max_tokens=10)
    finally:
        await http.close()

    assert attempts["n"] == 1


@pytest.mark.asyncio
async def test_finish_reason_length_with_empty_content_raises_without_retry():
    """The live PR-023 shape: reasoning ate the budget, HTTP 200, empty content."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": ""}, "finish_reason": "length"}]},
        )

    provider, http = make_provider(handler)
    try:
        with pytest.raises(LlmError, match="пустой ответ"):
            await provider.generate("s", "u", max_tokens=10)
    finally:
        await http.close()

    assert attempts["n"] == 1


@pytest.mark.asyncio
async def test_check_connection_empty_content_raises_ru_error_without_retry():
    """Same single rule at the provider boundary: one answer = text or error."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if payload["max_tokens"] == PROBE_MAX_OUTPUT_TOKENS:
            return ok_response("ОК")  # the budget probe — not what we count
        attempts["n"] += 1
        return httpx.Response(
            200, json={"choices": [{"message": {"content": None}, "finish_reason": "stop"}]}
        )

    provider, http = make_provider(handler)
    try:
        with pytest.raises(LlmError, match="пустой ответ"):
            await provider.check_connection()
    finally:
        await http.close()

    assert attempts["n"] == 1


@pytest.mark.asyncio
async def test_malformed_200_body_raises_ru_error():
    """A 200 with an unparseable body is a provider answer problem, not a
    retryable one: a plain RU LlmError, no retries."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(200, text="{not-json")

    provider, http = make_provider(handler)
    try:
        with pytest.raises(LlmError, match="некорректный ответ"):
            await provider.generate("s", "u", max_tokens=10)
    finally:
        await http.close()

    assert attempts["n"] == 1


def test_base_provider_is_abstract():
    from app.infrastructure.llm.base_provider import BaseLlmProvider

    with pytest.raises(TypeError):
        BaseLlmProvider()


# --- on_phase hook (design D2 of add-generate-entity) -----------------------
#
# The optional hook observes the retry cycle from outside: "in_flight"
# before every POST, "waiting" before every retry backoff.


@pytest.mark.asyncio
async def test_on_phase_reports_in_flight_before_post_waiting_before_backoff():
    """503 → 200: the hook sees in_flight, waiting, in_flight."""
    phases: list[str] = []
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return error_response(503, "unavailable")
        return ok_response("ok")

    provider, http = make_provider(handler)
    try:
        result = await provider.generate("s", "u", max_tokens=10, on_phase=phases.append)
    finally:
        await http.close()

    assert result == "ok"
    assert calls["n"] == 2
    assert phases == ["in_flight", "waiting", "in_flight"]


@pytest.mark.asyncio
async def test_on_phase_single_attempt_reports_in_flight_once():
    phases: list[str] = []
    provider, http = make_provider(lambda request: ok_response("hi"))
    try:
        await provider.generate("s", "u", max_tokens=10, on_phase=phases.append)
    finally:
        await http.close()
    assert phases == ["in_flight"]


@pytest.mark.asyncio
async def test_on_phase_on_exhausted_retries():
    """Every attempt reports in_flight; each backoff reports waiting first."""
    phases: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return error_response(429, "rate limited")

    provider, http = make_provider(handler)
    try:
        with pytest.raises(LlmHttpError):
            await provider.generate("s", "u", max_tokens=10, on_phase=phases.append)
    finally:
        await http.close()
    # 3 attempts, 2 backoffs in between
    assert phases == ["in_flight", "waiting", "in_flight", "waiting", "in_flight"]


@pytest.mark.asyncio
async def test_generate_without_phase_hook_is_unchanged():
    """The hook is optional (default None) and does not alter behavior."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return error_response(503, "unavailable")
        return ok_response("ok-after-retry")

    provider, http = make_provider(handler)
    try:
        result = await provider.generate("s", "u", max_tokens=10)
    finally:
        await http.close()
    assert result == "ok-after-retry"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_check_connection_accepts_phase_hook():
    phases: list[str] = []
    provider, http = make_provider(lambda request: ok_response("ок"))
    try:
        result = await provider.check_connection(on_phase=phases.append)
    finally:
        await http.close()
    assert result == "ок"
    assert phases == ["in_flight"]


# --- thinking switch and output budget discovery ---------------------------
#
# 2026-10-06 incident: a reasoning model ate the whole 512-token budget on
# hidden thinking and the wave came back with random empty fields. Since then
# the caller states per request whether thinking is allowed, and requests
# carry the largest output budget the server itself reported.

BIFROST_REFUSAL = (
    '{"error":{"message":"max_completion_tokens=1000000 cannot be greater '
    'than max_model_len=max_total_tokens=262144. Please request fewer '
    'output tokens."}}'
)


def is_probe(request: httpx.Request) -> bool:
    return json.loads(request.content)["max_tokens"] == PROBE_MAX_OUTPUT_TOKENS


@pytest.mark.asyncio
async def test_generate_with_thinking_sends_true_switch():
    """One field: the model may reason — the request says so explicitly."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return ok_response("думающий ответ")

    provider, http = make_provider(handler)
    try:
        await provider.generate("s", "u", max_tokens=4096, with_thinking=True)
    finally:
        await http.close()
    assert seen["payload"]["chat_template_kwargs"] == {"enable_thinking": True}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "refusal_text,limit",
    [
        (BIFROST_REFUSAL, 262144),
        (
            "{\"error\":{\"message\":\"This model's maximum context length is "
            "32768 tokens, however you requested 1000001 tokens.\"}}",
            32768,
        ),
        ("the model's context size is 8192, reduce n_ctx", 8192),
    ],
)
async def test_budget_learned_from_refusal_names_the_server_wording(refusal_text, limit):
    seen: dict = {"payloads": []}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen["payloads"].append(payload)
        if payload["max_tokens"] == PROBE_MAX_OUTPUT_TOKENS:
            return httpx.Response(400, text=refusal_text)
        return ok_response("ok")

    provider, http = make_provider(handler)
    try:
        result = await provider.generate("s", "u")
    finally:
        await http.close()

    assert result == "ok"
    assert len(seen["payloads"]) == 2  # one probe, one answer
    # 30 % of the context stays reserved for the prompt.
    assert seen["payloads"][1]["max_tokens"] == int(limit * OUTPUT_BUDGET_SHARE)


@pytest.mark.asyncio
async def test_accepted_probe_becomes_the_budget_and_never_repeats():
    seen: dict = {"payloads": []}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen["payloads"].append(payload)
        return ok_response("ok")

    provider, http = make_provider(handler)
    try:
        await provider.generate("s", "u")
        await provider.generate("s", "u2")
    finally:
        await http.close()

    probes = [p for p in seen["payloads"] if p["max_tokens"] == PROBE_MAX_OUTPUT_TOKENS]
    mains = [p for p in seen["payloads"] if p["max_tokens"] != PROBE_MAX_OUTPUT_TOKENS]
    assert len(probes) == 1  # one discovery per provider
    assert [p["max_tokens"] for p in mains] == [
        int(PROBE_MAX_OUTPUT_TOKENS * OUTPUT_BUDGET_SHARE)
    ] * 2


@pytest.mark.asyncio
async def test_probe_network_error_falls_back_and_is_not_repeated():
    seen: dict = {"payloads": []}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen["payloads"].append(payload)
        if payload["max_tokens"] == PROBE_MAX_OUTPUT_TOKENS:
            raise httpx.ConnectError("unreachable")
        return ok_response("ok")

    provider, http = make_provider(handler)
    try:
        await provider.generate("s", "u")
        await provider.generate("s", "u2")
    finally:
        await http.close()

    probes = [p for p in seen["payloads"] if p["max_tokens"] == PROBE_MAX_OUTPUT_TOKENS]
    mains = [p for p in seen["payloads"] if p["max_tokens"] != PROBE_MAX_OUTPUT_TOKENS]
    assert len(probes) == 1  # no per-request penalty for a dead probe
    assert [p["max_tokens"] for p in mains] == [FALLBACK_MAX_TOKENS] * 2


@pytest.mark.asyncio
async def test_probe_unparsable_refusal_falls_back_to_historical_budget():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if payload["max_tokens"] == PROBE_MAX_OUTPUT_TOKENS:
            return httpx.Response(400, text='{"error":{"message":"no numbers"}}')
        assert payload["max_tokens"] == FALLBACK_MAX_TOKENS
        return ok_response("ok")

    provider, http = make_provider(handler)
    try:
        assert await provider.generate("s", "u") == "ok"
    finally:
        await http.close()


@pytest.mark.asyncio
async def test_parallel_generations_trigger_a_single_probe():
    """A whole-card wave races to the probe; the lock lets exactly one in."""
    probes = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if is_probe(request):
            probes["n"] += 1
            return httpx.Response(400, text=BIFROST_REFUSAL)
        assert json.loads(request.content)["max_tokens"] == int(262144 * OUTPUT_BUDGET_SHARE)
        return ok_response("ok")

    provider, http = make_provider(handler)
    try:
        results = await asyncio.gather(
            provider.generate("s", "u1"),
            provider.generate("s", "u2"),
            provider.generate("s", "u3"),
        )
    finally:
        await http.close()

    assert list(results) == ["ok"] * 3
    assert probes["n"] == 1


@pytest.mark.asyncio
async def test_check_connection_probes_then_tests_then_budget_is_known():
    """«На старте коннекта» is where the app learns the budget — for free."""
    order: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        order.append(payload["max_tokens"])
        if payload["max_tokens"] == PROBE_MAX_OUTPUT_TOKENS:
            return httpx.Response(400, text=BIFROST_REFUSAL)
        return ok_response("ок")

    provider, http = make_provider(handler)
    try:
        assert await provider.check_connection() == "ок"
        assert order == [PROBE_MAX_OUTPUT_TOKENS, 1]
        await provider.generate("s", "u")
        assert order[-1] == int(262144 * OUTPUT_BUDGET_SHARE)
        assert order.count(PROBE_MAX_OUTPUT_TOKENS) == 1
    finally:
        await http.close()


@pytest.mark.asyncio
async def test_output_budget_without_config_answers_none_no_request():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return ok_response()

    provider, http = make_provider(handler, base_url="", model="")
    try:
        assert await provider.output_budget() is None
    finally:
        await http.close()
    assert calls["n"] == 0
