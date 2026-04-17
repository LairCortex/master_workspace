"""Tests for LLM providers — base abstraction and local GGUF provider."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.infrastructure.llm.base_provider import BaseLlmProvider
from app.infrastructure.llm.local_provider import LocalGgufProvider


def test_base_provider_is_abstract():
    with pytest.raises(TypeError):
        BaseLlmProvider()


def test_local_provider_not_ready_before_load(tmp_path):
    provider = LocalGgufProvider(model_path=tmp_path / "nonexistent.gguf")
    assert provider.is_ready() is False


@pytest.mark.asyncio
async def test_local_provider_load_model_file_not_found(tmp_path):
    provider = LocalGgufProvider(model_path=tmp_path / "missing.gguf")
    with pytest.raises(FileNotFoundError):
        await provider.load_model()


@pytest.mark.asyncio
async def test_local_provider_generate(tmp_path):
    model_file = tmp_path / "test.gguf"
    model_file.write_text("fake")
    provider = LocalGgufProvider(model_path=model_file)

    mock_llm = MagicMock()
    mock_llm.create_chat_completion.return_value = {
        "choices": [{"message": {"content": "Generated text"}}]
    }

    with patch.object(provider, "_create_llm", return_value=mock_llm):
        await provider.load_model()
        assert provider.is_ready()

        result = await provider.generate("system", "user")
        assert result == "Generated text"
        mock_llm.create_chat_completion.assert_called_once()


@pytest.mark.asyncio
async def test_local_provider_generate_not_loaded():
    provider = LocalGgufProvider()
    with pytest.raises(RuntimeError, match="Model not loaded"):
        await provider.generate("sys", "usr")


@pytest.mark.asyncio
async def test_local_provider_unload(tmp_path):
    model_file = tmp_path / "test.gguf"
    model_file.write_text("fake")
    provider = LocalGgufProvider(model_path=model_file)

    mock_llm = MagicMock()
    with patch.object(provider, "_create_llm", return_value=mock_llm):
        await provider.load_model()
        assert provider.is_ready()
        await provider.unload_model()
        assert not provider.is_ready()


@pytest.mark.asyncio
async def test_local_provider_generate_empty_choices(tmp_path):
    model_file = tmp_path / "test.gguf"
    model_file.write_text("fake")
    provider = LocalGgufProvider(model_path=model_file)

    mock_llm = MagicMock()
    mock_llm.create_chat_completion.return_value = {"choices": []}

    with patch.object(provider, "_create_llm", return_value=mock_llm):
        await provider.load_model()
        result = await provider.generate("system", "user")
        assert result == ""
