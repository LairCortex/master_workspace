"""LLM error hierarchy with user-friendly (RU) messages.

``str(exc)`` of any ``LlmError`` is safe to show to the user.
"""
from __future__ import annotations

import json

_AUTH_STATUSES = (401, 403)


class LlmError(Exception):
    """Base error for LLM operations. Carries a user-facing message."""


class LlmTimeoutError(LlmError):
    """Request timed out waiting for the server."""

    def __init__(self, message: str = "Время ожидания ответа истекло") -> None:
        super().__init__(message)


class LlmNetworkError(LlmError):
    """Server unreachable / connection failure."""

    def __init__(self, message: str = "Сервер LLM недоступен") -> None:
        super().__init__(message)


class LlmHttpError(LlmError):
    """HTTP error from the LLM endpoint with a mapped user message."""

    def __init__(self, status: int, server_message: str = "") -> None:
        self.status = status
        self.server_message = server_message
        super().__init__(self._friendly_message(status, server_message))

    @staticmethod
    def _friendly_message(status: int, server_message: str) -> str:
        if status in _AUTH_STATUSES:
            return "Неверный ключ API или недостаточно прав"
        if status == 404:
            return "Модель или endpoint не найдены"
        if status == 429:
            return "Превышен лимит запросов. Попробуйте позже."
        if server_message:
            return f"Ошибка LLM (статус {status}): {server_message}"
        return f"Ошибка LLM (статус {status})"


def parse_error_message(body: str | None) -> str:
    """Extract the error text from an OpenAI-style response body.

    Looks for ``{"error": {"message": ...}}`` (also top-level ``message``)
    and falls back to the raw body text.
    """
    if not body:
        return ""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return body.strip()
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        message = data.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return body.strip()
