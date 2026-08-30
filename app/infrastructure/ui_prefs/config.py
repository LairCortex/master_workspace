"""Global UI preferences — ~/.nri_manager/ui.json (design D3).

Pattern mirrors LlmConfigManager (separate file on purpose, per D3: the
theme preference must not mix into the LLM connection config). The file
is written with 0600 permissions so only the current user can read or
write it (best-effort on non-POSIX systems).

A missing, unreadable, corrupt or semantically invalid file yields the
default theme: dark.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from app.domain.theme import DEFAULT_THEME, THEMES

CONFIG_DIR = Path.home() / ".nri_manager"


def default_config_file() -> Path:
    """Location of the global UI preference file (design D3)."""
    return CONFIG_DIR / "ui.json"


# Resolved at construction time (and patchable in tests), like the LLM config.
CONFIG_FILE: Path = default_config_file()


@dataclass
class UiPrefs:
    """Global UI preference. In W1 the only field is the theme name."""

    theme: str = DEFAULT_THEME


class UiPrefsManager:
    """Reads and writes the global UI preference file.

    Unknown theme values fall back to dark, matching the spec scenario for
    a corrupt preference file.
    """

    def __init__(self, config_file: Path | None = None) -> None:
        self._config_file = Path(config_file) if config_file is not None else CONFIG_FILE

    @property
    def config_file(self) -> Path:
        return self._config_file

    def load(self) -> UiPrefs:
        """Return the stored preference; dark when absent or unreadable.

        ``ValueError`` covers both a broken JSON document and a file that is
        not valid UTF-8 (``UnicodeDecodeError``): byte-level damage must not
        break application start (spec «битый preference»).
        """
        try:
            data = json.loads(self._config_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return UiPrefs(DEFAULT_THEME)
        if not isinstance(data, dict):
            return UiPrefs(DEFAULT_THEME)
        theme = data.get("theme")
        if theme not in THEMES:
            return UiPrefs(DEFAULT_THEME)
        return UiPrefs(theme=theme)

    def save(self, prefs: UiPrefs) -> None:
        self._config_file.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(prefs), ensure_ascii=False, indent=2) + "\n"
        self._config_file.write_text(payload, encoding="utf-8")
        os.chmod(self._config_file, 0o600)
