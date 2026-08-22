"""Tests for LLM providers — base abstraction and remote provider config."""
from __future__ import annotations

import json

import pytest

from app.infrastructure.llm.base_provider import BaseLlmProvider
from app.infrastructure.llm.remote_provider import RemoteLlmProvider


def test_base_provider_is_abstract():
    with pytest.raises(TypeError):
        BaseLlmProvider()


def test_provider_not_configured_without_file(tmp_path):
    provider = RemoteLlmProvider(config_file=tmp_path / "missing.json")
    assert provider.is_configured() is False


def test_provider_configured_from_file(tmp_path):
    cfg = tmp_path / "llm_config.json"
    cfg.write_text(
        json.dumps({"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"}),
        encoding="utf-8",
    )
    provider = RemoteLlmProvider(config_file=cfg)
    assert provider.is_configured() is True


def test_provider_invalid_file_not_configured(tmp_path):
    cfg = tmp_path / "llm_config.json"
    cfg.write_text("{not json", encoding="utf-8")
    provider = RemoteLlmProvider(config_file=cfg)
    assert provider.is_configured() is False


def test_provider_old_format_not_configured(tmp_path):
    cfg = tmp_path / "llm_config.json"
    cfg.write_text(json.dumps({"repo": "x/y", "filename": "model.gguf"}), encoding="utf-8")
    provider = RemoteLlmProvider(config_file=cfg)
    assert provider.is_configured() is False


@pytest.mark.asyncio
async def test_generate_raises_when_not_configured(tmp_path):
    provider = RemoteLlmProvider(config_file=tmp_path / "missing.json")
    with pytest.raises(RuntimeError, match="LLM не настроен"):
        await provider.generate("sys", "usr")
