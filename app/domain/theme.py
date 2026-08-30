"""Theme identifiers shared by the token compiler and the UI preference file.

Single source on purpose: the token file, the QSS/CSS compiler and
``~/.nri_manager/ui.json`` must never drift apart when a theme is added (W2).
"""
from __future__ import annotations

THEMES: tuple[str, ...] = ("light", "dark")
DEFAULT_THEME: str = "dark"
