"""The one ``~/.nri_manager`` application root (audit A5).

Every global configuration file lives under this directory: the LLM
connection config (``llm_config.json``), the UI preferences (``ui.json``)
and the app log. The path was previously spelled out in three modules;
this is the single source the config family builds on.
"""
from __future__ import annotations

from pathlib import Path

#: Root directory of all machine-global app configuration.
NRI_MANAGER_DIR = Path.home() / ".nri_manager"
