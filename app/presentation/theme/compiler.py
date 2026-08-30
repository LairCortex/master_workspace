"""Design tokens: parsing and in-memory QSS/CSS compilation (W1).

``tokens.json`` (design D1) maps a semantic role to ``{"light": ..., "dark":
...}``. The compiler (D2) produces QSS (literals only) and the CSS ``:root``
block in memory — generated artifacts are never written to disk. An
unparsable or incomplete token file makes the whole set invalid (D7):
``load_tokens`` returns ``None``, callers log and degrade to the OS palette.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from app.domain.theme import THEMES

log = logging.getLogger(__name__)

# Semantic role names are fixed by design D1 (changes/add-design-tokens-w1).
REQUIRED_TOKEN_KEYS: tuple[str, ...] = (
    "color.bg.canvas",
    "color.bg.surface",
    "color.fg.primary",
    "color.fg.muted",
    "color.border",
    "color.accent",
    "color.accent.fg",
    "color.danger",
    "space.xs",
    "space.sm",
    "space.md",
    "radius.sm",
    "font.size.md",
    "font.weight.bold",
)

Tokens = dict[str, dict[str, str]]


def tokens_file_path() -> Path:
    """Token file next to this module (bundle-relative path, D8)."""
    return Path(__file__).resolve().parent / "tokens.json"


def css_var_name(token_key: str) -> str:
    """``color.bg.canvas`` → ``--color-bg-canvas`` (design D1)."""
    return "--" + token_key.replace(".", "-")


def load_tokens(path: Path) -> Optional[Tokens]:
    """Parse and validate the token file; ``None`` when invalid as a whole."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        log.warning("Файл токенов недоступен: %s (%s)", path, exc)
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("Файл токенов разбит: %s (%s)", path, exc)
        return None
    if not isinstance(data, dict):
        log.warning("Файл токенов не объект: %s", path)
        return None
    tokens: Tokens = {}
    for key in REQUIRED_TOKEN_KEYS:
        entry = data.get(key)
        if not isinstance(entry, dict):
            log.warning("Токен %r отсутствует или не объект в %s", key, path)
            return None
        if not all(
            isinstance(entry.get(theme), str) and entry.get(theme)
            for theme in THEMES
        ):
            log.warning("Токен %r должен задавать строки light и dark в %s", key, path)
            return None
        tokens[key] = {
            theme: entry[theme]
            for theme in entry
            if theme in THEMES and isinstance(entry[theme], str)
        }
    return tokens


def compile_qss(tokens: Tokens, theme: str) -> str:
    """Qt stylesheet for the chrome containers (D1/D2/D4 — literals only).

    Rules are scoped to ``QWidget#themeChrome`` / ``QMenuBar#themeMenu`` so a
    dialog that is a child of the main window does not inherit the skin (D4).
    ``QToolTip`` is deliberately absent: tooltips are top-level popups with no
    chrome ancestor, so a chrome-scoped rule for them could never match
    (tooltip skinning needs an application-wide sheet — W2).
    """
    t = {key: values[theme] for key, values in tokens.items()}
    return f"""
QWidget#themeChrome, QMenuBar#themeMenu {{
    background: {t['color.bg.canvas']};
    color: {t['color.fg.primary']};
    font-size: {t['font.size.md']};
}}
QMenuBar#themeMenu::item {{
    padding: {t['space.xs']} {t['space.sm']};
    background: transparent;
    color: {t['color.fg.primary']};
}}
QMenuBar#themeMenu::item:selected {{
    background: {t['color.bg.surface']};
}}
QWidget#themeChrome QPushButton {{
    background: {t['color.accent']};
    color: {t['color.accent.fg']};
    font-weight: {t['font.weight.bold']};
    border: 1px solid {t['color.border']};
    border-radius: {t['radius.sm']};
    padding: {t['space.xs']} {t['space.sm']};
}}
QWidget#themeChrome QListWidget,
QWidget#themeChrome QTreeView,
QWidget#themeChrome QPlainTextEdit {{
    background: {t['color.bg.surface']};
    color: {t['color.fg.primary']};
    border: 1px solid {t['color.border']};
}}
QMenu {{
    background: {t['color.bg.surface']};
    color: {t['color.fg.primary']};
    border: 1px solid {t['color.border']};
}}
""".strip()


def compile_css_root(tokens: Tokens, theme: str) -> str:
    """``:root`` block with one custom property per token (design D1)."""
    lines = [
        f"  {css_var_name(key)}: {values[theme]};"
        for key, values in tokens.items()
    ]
    return ":root {\n" + "\n".join(lines) + "\n}"
