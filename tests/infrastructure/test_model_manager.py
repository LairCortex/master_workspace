"""Tests for ModelManager — download, path resolution, delete."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

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
            cfg_file = tmp_path / "llm_config.json"
            assert cfg_file.exists()
            data = json.loads(cfg_file.read_text())
            assert data["provider_type"] == "local"
            assert data["repo_id"] == "test/repo"


def test_are_llm_packages_installed_true():
    with patch("importlib.util.find_spec", return_value=MagicMock()):
        assert ModelManager.are_llm_packages_installed() is True


def test_are_llm_packages_installed_false():
    def _find_spec(name):
        if name == "llama_cpp":
            return None
        return MagicMock()

    with patch("importlib.util.find_spec", side_effect=_find_spec):
        assert ModelManager.are_llm_packages_installed() is False


@pytest.mark.asyncio
async def test_install_llm_packages_calls_pip(manager):
    with patch.object(ModelManager, "are_llm_packages_installed", return_value=False):
        with patch.object(ModelManager, "_install_packages_sync") as mock_install:
            cb = MagicMock()
            await manager.install_llm_packages(status_callback=cb)
            mock_install.assert_called_once()
            cb.assert_called_once_with("Установка необходимых пакетов…")


@pytest.mark.asyncio
async def test_install_llm_packages_skips_if_installed(manager):
    with patch.object(ModelManager, "are_llm_packages_installed", return_value=True):
        with patch.object(ModelManager, "_install_packages_sync") as mock_install:
            await manager.install_llm_packages()
            mock_install.assert_not_called()


def test_install_packages_sync_runs_pip():
    with patch("subprocess.check_call") as mock_call:
        ModelManager._install_packages_sync()
        mock_call.assert_called_once()
        args = mock_call.call_args[0][0]
        assert args[0] == sys.executable
        assert "-m" in args
        assert "pip" in args
        assert "install" in args
        assert "llama-cpp-python" in args
