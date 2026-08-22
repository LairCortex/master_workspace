"""Tests for LLM error hierarchy and status-to-message mapping."""
from __future__ import annotations

from app.infrastructure.llm.errors import (
    LlmError,
    LlmHttpError,
    LlmNetworkError,
    LlmTimeoutError,
    parse_error_message,
)


def test_error_hierarchy():
    assert issubclass(LlmHttpError, LlmError)
    assert issubclass(LlmNetworkError, LlmError)
    assert issubclass(LlmTimeoutError, LlmError)


def test_401_maps_to_invalid_key():
    err = LlmHttpError(401, "Invalid API key provided")
    assert err.status == 401
    assert err.server_message == "Invalid API key provided"
    assert "неверный ключ" in str(err).lower()


def test_403_maps_to_invalid_key():
    err = LlmHttpError(403, "")
    assert "недостаточно прав" in str(err).lower() or "неверный ключ" in str(err).lower()


def test_404_maps_to_not_found():
    err = LlmHttpError(404, "model not found")
    assert "модель или endpoint не найдены" in str(err).lower()


def test_429_maps_to_rate_limit():
    err = LlmHttpError(429, "Rate limit reached")
    assert "лимит запросов" in str(err).lower()


def test_other_status_includes_status_and_server_message():
    err = LlmHttpError(418, "Тепловоз")
    assert "418" in str(err)
    assert "Тепловоз" in str(err)


def test_other_status_without_server_message():
    err = LlmHttpError(500)
    assert "500" in str(err)


def test_timeout_error_default_message():
    assert "время ожидания" in str(LlmTimeoutError()).lower()
    assert "истекло" in str(LlmTimeoutError()).lower()


def test_network_error_default_message():
    assert "сервер llm недоступен" in str(LlmNetworkError()).lower()


def test_network_error_custom_message():
    assert "connection reset" in str(LlmNetworkError("connection reset")).lower()


def test_parse_openai_error_body():
    body = '{"error": {"message": "Invalid API key provided", "type": "auth"}}'
    assert parse_error_message(body) == "Invalid API key provided"


def test_parse_fallback_to_raw_body():
    assert parse_error_message("plain server text") == "plain server text"


def test_parse_empty_body():
    assert parse_error_message("") == ""
    assert parse_error_message(None) == ""


def test_parse_top_level_message_field():
    assert parse_error_message('{"message": "oops"}') == "oops"


def test_parse_invalid_json_returns_raw():
    assert parse_error_message("{broken") == "{broken"
