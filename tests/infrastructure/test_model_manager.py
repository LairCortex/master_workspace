"""Tests for ModelManager — download, path resolution, delete."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.llm.model_manager import ModelManager


@pytest.fixture
def tmp_models_dir(tmp_path):
    return tmp_path / "models"


@pytest.fixture
def manager(tmp_models_dir):
    return ModelManager(
        repo_id="test/repo",
        filename="test-model.gguf",
        models_dir=tmp_models_dir,
    )


def test_get_model_path_not_exists(manager):
    assert manager.get_model_path() is None


def test_get_model_path_exists(manager, tmp_models_dir):
    tmp_models_dir.mkdir(parents=True)
    model_file = tmp_models_dir / "test-model.gguf"
    model_file.write_text("fake model data")
    assert manager.get_model_path() == model_file


@pytest.mark.asyncio
async def test_download_model_calls_hf_hub(manager, tmp_models_dir):
    tmp_models_dir.mkdir(parents=True)
    dest = tmp_models_dir / "test-model.gguf"
    dest.write_text("downloaded")

    mock_hf = MagicMock()
    mock_hf.hf_hub_download.return_value = str(dest)
    mock_hf.HfApi.return_value.model_info.return_value.siblings = []
    with patch.dict("sys.modules", {"huggingface_hub": mock_hf, "tqdm": MagicMock()}):
        result = await manager.download_model()
        mock_hf.hf_hub_download.assert_called_once()
        call_kwargs = mock_hf.hf_hub_download.call_args
        assert call_kwargs.kwargs["repo_id"] == "test/repo"
        assert call_kwargs.kwargs["filename"] == "test-model.gguf"
        assert call_kwargs.kwargs["local_dir"] == str(tmp_models_dir)
        assert result == dest


@pytest.mark.asyncio
async def test_download_model_progress_callback(manager, tmp_models_dir):
    tmp_models_dir.mkdir(parents=True)
    dest = tmp_models_dir / "test-model.gguf"
    dest.write_text("downloaded")

    callback = MagicMock()
    mock_hf = MagicMock()
    mock_hf.hf_hub_download.return_value = str(dest)
    with patch.dict("sys.modules", {"huggingface_hub": mock_hf}):
        await manager.download_model(progress_callback=callback)
        callback.assert_called_with(1.0)


def test_delete_model_removes_file(manager, tmp_models_dir):
    tmp_models_dir.mkdir(parents=True)
    model_file = tmp_models_dir / "test-model.gguf"
    model_file.write_text("data")
    assert model_file.exists()

    result = manager.delete_model()
    assert result is True
    assert not model_file.exists()


def test_delete_model_returns_false_if_missing(manager):
    assert manager.delete_model() is False


def test_save_and_load_config(manager, tmp_path):
    with patch("app.infrastructure.llm.model_manager._CONFIG_DIR", tmp_path):
        with patch("app.infrastructure.llm.model_manager._CONFIG_FILE", tmp_path / "llm_config.json"):
            manager.save_config(provider_type="local")
            config = ModelManager.load_config()
            # load_config reads from _CONFIG_FILE which we patched
            cfg_file = tmp_path / "llm_config.json"
            assert cfg_file.exists()
            data = json.loads(cfg_file.read_text())
            assert data["provider_type"] == "local"
            assert data["repo_id"] == "test/repo"
