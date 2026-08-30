"""Tests for UiPrefs / UiPrefsManager — global theme preference file (W1 D3)."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from app.domain import theme as domain_theme
from app.infrastructure.ui_prefs import config as ui_prefs_config
from app.infrastructure.ui_prefs.config import (
    UiPrefs,
    UiPrefsManager,
    default_config_file,
)


def test_default_config_file_location():
    assert default_config_file() == Path.home() / ".nri_manager" / "ui.json"


def test_manager_uses_the_module_level_default_file(tmp_path, monkeypatch):
    # The default is resolved at construction time, so tests (and the app's
    # own test isolation fixture) can redirect it.
    monkeypatch.setattr(ui_prefs_config, "CONFIG_FILE", tmp_path / "other.json")
    assert UiPrefsManager().config_file == tmp_path / "other.json"


@pytest.fixture
def prefs_file(tmp_path):
    return tmp_path / "ui.json"


@pytest.fixture
def manager(prefs_file):
    return UiPrefsManager(prefs_file)


def test_missing_file_defaults_to_dark(manager):
    assert manager.load().theme == "dark"


def test_save_light_theme_roundtrip(manager):
    manager.save(UiPrefs(theme="light"))
    assert manager.config_file.exists()
    assert manager.load().theme == "light"


def test_saved_payload_is_json_with_theme_field(manager):
    manager.save(UiPrefs(theme="light"))
    data = json.loads(manager.config_file.read_text(encoding="utf-8"))
    assert data["theme"] == "light"


def test_corrupt_file_defaults_to_dark(manager):
    manager.config_file.write_text("{not-valid-json", encoding="utf-8")
    assert manager.load().theme == "dark"


def test_non_utf8_file_defaults_to_dark(manager):
    # Spec «битый preference → тёмная тема, приложение не падает»: a file
    # damaged at the byte level must not raise UnicodeDecodeError on read.
    manager.config_file.write_bytes(b"\xff\xfe\x00{\x01\x80theme")
    assert manager.load().theme == "dark"


def test_non_dict_file_defaults_to_dark(manager):
    manager.config_file.write_text(json.dumps(["light"]), encoding="utf-8")
    assert manager.load().theme == "dark"


def test_unknown_theme_value_defaults_to_dark(manager):
    manager.config_file.write_text(json.dumps({"theme": "sepia"}), encoding="utf-8")
    assert manager.load().theme == "dark"


def test_theme_never_leaves_known_set(manager):
    assert manager.load().theme in domain_theme.THEMES


def test_theme_names_have_a_single_source():
    # The token compiler and the preference file must never drift apart.
    assert ui_prefs_config.THEMES == domain_theme.THEMES
    assert ui_prefs_config.DEFAULT_THEME == domain_theme.DEFAULT_THEME
    assert domain_theme.DEFAULT_THEME in domain_theme.THEMES
    assert set(domain_theme.THEMES) == {"dark", "light"}


def test_saved_file_has_0600_permissions(manager):
    if os.name != "posix":
        pytest.skip("chmod 0600 is a no-op on non-POSIX systems")
    manager.save(UiPrefs(theme="light"))
    mode = stat.S_IMODE(manager.config_file.stat().st_mode)
    assert mode == 0o600


def test_save_creates_missing_parent_dirs(tmp_path):
    manager = UiPrefsManager(tmp_path / "a" / "b" / "ui.json")
    manager.save(UiPrefs(theme="dark"))
    assert (tmp_path / "a" / "b" / "ui.json").exists()
