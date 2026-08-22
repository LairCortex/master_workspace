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
from app.infrastructure.llm.remote_provider import (
    MAX_RETRIES,
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
        await provider.generate("s", "u")
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
        await provider.generate("s", "u")
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
            await provider.generate("s", "u")
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
            await provider.generate("s", "u")
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
        result = await provider.generate("s", "u")
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
        result = await provider.generate("s", "u")
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
            await provider.generate("s", "u")
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
            await provider.generate("s", "u")
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
            await provider.generate("s", "u")
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
            await provider.generate("s", "u")
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
            await provider.generate("s", "u")
    finally:
        await http.close()


def test_base_provider_is_abstract():
    from app.infrastructure.llm.base_provider import BaseLlmProvider

    with pytest.raises(TypeError):
        BaseLlmProvider()
