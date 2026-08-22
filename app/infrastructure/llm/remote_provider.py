"""Remote OpenAI-compatible LLM provider (skeleton)."""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.infrastructure.llm.base_provider import BaseLlmProvider

CONFIG_DIR = Path.home() / ".nri_manager"
CONFIG_FILE = CONFIG_DIR / "llm_config.json"

CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 120.0


class RemoteLlmProvider(BaseLlmProvider):
    """Talks to an OpenAI-compatible chat/completions endpoint."""

    def __init__(self, config_file: Path | None = None) -> None:
        self._config_file = config_file or CONFIG_FILE
        self._config = self._load_config()

    def _load_config(self) -> dict:
        try:
            with open(self._config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def is_configured(self) -> bool:
        """True when non-empty base_url and model are present in the config."""
        cfg = self._config
        return bool(str(cfg.get("base_url", "")).strip()) and bool(str(cfg.get("model", "")).strip())

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 512,
    ) -> str:
        if not self.is_configured():
            raise RuntimeError("LLM не настроен. Откройте меню LLM → Настройка LLM…")

        base_url = str(self._config.get("base_url", "")).strip().rstrip("/")
        model = str(self._config.get("model", "")).strip()
        api_key = str(self._config.get("api_key", "")).strip()

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.7,
        }

        timeout = httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

        choices = data.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "").strip()
