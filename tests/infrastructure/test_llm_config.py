"""Tests for LlmConfig and LlmConfigManager — global connection config file."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from app.infrastructure.llm.config import LlmConfig, LlmConfigManager


def test_default_config_file_location():
    mgr = LlmConfigManager()
    assert mgr.config_file == Path.home() / ".nri_manager" / "llm_config.json"


@pytest.fixture
def config_file(tmp_path):
    return tmp_path / "llm_config.json"


@pytest.fixture
def manager(config_file):
    return LlmConfigManager(config_file)


def test_load_missing_file_returns_none(manager):
    assert manager.load() is None


def test_save_creates_file_and_roundtrips(manager):
    cfg = LlmConfig(
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        api_key="sk-test",
    )
    manager.save(cfg)

    assert manager.config_file.exists()
    loaded = manager.load()
    assert loaded == cfg


def test_save_api_key_optional(manager):
    cfg = LlmConfig(base_url="http://localhost:11434/v1", model="llama3")
    manager.save(cfg)
    loaded = manager.load()
    assert loaded == cfg
    assert loaded.api_key == ""


def test_saved_file_has_0600_permissions(manager):
    if os.name != "posix":
        pytest.skip("chmod 0600 is a no-op on non-POSIX systems")
    manager.save(LlmConfig("https://api.example.com/v1", "model-x"))
    mode = stat.S_IMODE(manager.config_file.stat().st_mode)
    assert mode == 0o600


def test_save_creates_missing_parent_dirs(tmp_path):
    manager = LlmConfigManager(tmp_path / "a" / "b" / "llm_config.json")
    manager.save(LlmConfig("http://url", "m"))
    assert (tmp_path / "a" / "b" / "llm_config.json").exists()


def test_old_format_treated_as_missing(manager):
    manager.config_file.write_text(
        json.dumps({"repo": "bartowski/Qwen2.5-14B-Instruct-GGUF", "filename": "m.gguf"}),
        encoding="utf-8",
    )
    assert manager.load() is None


def test_corrupt_file_returns_none(manager):
    manager.config_file.write_text("{not-valid-json", encoding="utf-8")
    assert manager.load() is None


def test_non_dict_file_returns_none(manager):
    manager.config_file.write_text(json.dumps(["base_url"]), encoding="utf-8")
    assert manager.load() is None


def test_config_is_complete_requires_base_url_and_model():
    assert LlmConfig("", "").is_complete is False
    assert LlmConfig("http://x", "").is_complete is False
    assert LlmConfig("", "m").is_complete is False
    assert LlmConfig("  ", "m").is_complete is False
    assert LlmConfig("http://x", "m").is_complete is True
    assert LlmConfig("http://x", "m", "").is_complete is True
