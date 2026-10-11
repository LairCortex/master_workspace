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

#: Global D&D dataset library (add-dnd-module-foundation, task 3.1, design Д4):
#: one dataset lives once for ALL games as a ``<id>.json`` file plus its
#: ``<id>.meta.json`` sidecar, kept apart from every game's own database.
#: The D&D module's storage owns the file format; this constant is the one
#: source of the location (the same config home as ``ui.json``/llm_config.json).
#: Created lazily on the storage's first access, never on import.
DATASETS_DIR = NRI_MANAGER_DIR / "datasets"

#: Global D&D grimoire library (add-dnd-game-face, task 4.2, design Д8): one
#: Foundry-format spell file lives once for ALL games as ``<id>.json``, kept
#: beside the dataset shelf and apart from every game's own database. The
#: module's grimoire storage owns the file format and the id grammar; this
#: constant is the one source of the location (the same config home as
#: ``ui.json``/llm_config.json). Created lazily on the storage's first
#: access, never on import.
GRIMOIRES_DIR = NRI_MANAGER_DIR / "grimoires"
