"""PyInstaller spec guard for the design tokens file (add-design-tokens-w1).

The theme runtime reads ``tokens.json`` via a module-relative path, so the
spec must bundle it at the same repo-relative location (design D8);
otherwise the frozen app silently loses its theme (falls back to OS
palette) with no way to notice until runtime.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "nri_manager.spec"
TOKENS_SRC = "app/presentation/theme/tokens.json"


def test_spec_datas_contains_theme_tokens():
    text = SPEC_PATH.read_text(encoding="utf-8")
    datas = text.split("datas=[", 1)[1].rsplit("]", 1)[0]
    assert TOKENS_SRC in datas
    assert (REPO_ROOT / TOKENS_SRC).is_file()
