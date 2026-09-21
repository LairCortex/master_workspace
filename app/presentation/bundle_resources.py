"""Resolve read-only bundled resources in a dev checkout vs a PyInstaller bundle.

One resolver behind every shipped data directory/file: ``docs/`` (the README
/ CHANGELOG viewers). In development the resource lives under the repository
root; in a frozen build it is looked up in the layouts ``nri_manager.spec``
datas deploy it into (next to the exe, under ``_internal/``, macOS .app
Contents/Resources|Frameworks).
"""
from __future__ import annotations

import sys
from pathlib import Path


def _repo_root() -> Path:
    # app/presentation/bundle_resources.py -> repository root
    return Path(__file__).resolve().parents[2]


def bundle_resource_path(*parts: str) -> Path:
    """Path of a bundled resource (directory or file) below the resource root.

    Mirrors the previous ``main_window._docs_dir`` logic: dev resolves against
    the repository tree; a frozen build scans the datas destinations and
    falls back to the canonical ``_internal/`` location even when the resource
    is missing (the caller reports the absence).
    """
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        relative = Path(*parts)
        candidates = [
            exe.parent / "_internal" / relative,
            exe.parent / relative,
            exe.parent.parent / "Resources" / relative,
            exe.parent.parent / "Frameworks" / relative,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return exe.parent / "_internal" / relative  # fallback
    return _repo_root() / Path(*parts)
