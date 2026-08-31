"""Design tokens: parsing and in-memory QSS/CSS compilation (W1, extended W2a).

``tokens.json`` (design D1) maps a semantic role to ``{"light": ..., "dark":
...}``. The compiler (D2) produces QSS (literals only) and the CSS ``:root``
block in memory — generated artifacts are never written to disk. An
unparsable or incomplete token file makes the whole set invalid (D7):
``load_tokens`` returns ``None``, callers log and degrade to the OS palette.

W2a (add-widget-catalog-chrome-mechanics-w2a): chrome rules address widgets
through ``[uiRole="..."]`` dynamic properties instead of objectNames (D6),
catalog roles (title/hint/field/list/card/status-*) are emitted as standalone
rules (D1), and top-level popups get their own application-wide sheet
``compile_popup_qss`` (D2) — chrome-scoped rules could never reach them.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from app.domain.theme import THEMES

log = logging.getLogger(__name__)

# Semantic role names are fixed by design D1 (changes/add-design-tokens-w1)
# and extended by W2a (add-widget-catalog-chrome-mechanics-w2a D4). A role is
# only added here once something actually reads it (compiler rule, catalog
# role or CSS body): "declared but unread" tokens would tighten validation
# (absence kills the whole theme) for zero benefit. ``font.family.mono``
# joins the set in W2b together with the ``[field]+mono`` rule that reads it
# (it was dropped from W2a as dead — nothing consumed it back then).
#
# Namespaces are load-bearing: every key becomes a CSS custom property for the
# web player (``compile_css_root``), so a value lives under the namespace that
# describes it. The monospace family is a font, hence ``font.family.mono``
# (never ``color.font.family.mono`` → ``--color-font-family-mono``), and
# ``color.rating.low/high`` are real colors — the content tints that
# ``detail_panel.rating_to_color`` paints from.
REQUIRED_TOKEN_KEYS: tuple[str, ...] = (
    "color.bg.canvas",
    "color.bg.surface",
    "color.fg.primary",
    "color.fg.muted",
    "color.border",
    "color.accent",
    "color.accent.fg",
    "color.danger",
    "color.status.ok",
    "color.rating.low",
    "color.rating.high",
    "space.xs",
    "space.sm",
    "space.md",
    "radius.sm",
    "font.family.mono",
    "font.size.md",
    "font.size.lg",
    "font.size.xl",
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


def _hex_rgb(color: str) -> Optional[tuple[int, int, int]]:
    """``#rgb`` / ``#rrggbb`` → ``(r, g, b)``; anything else → ``None``."""
    s = color.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in s):
        return None
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def accent_rgba(tokens: Tokens, theme: str, alpha: float) -> str:
    """``color.accent`` as ``rgba(r, g, b, a)`` (W2a D5 — no rgba tokens).

    Used for hover/pressed/selection highlights; when the token is not a hex
    color the raw value is returned so the stylesheet stays at least valid.
    """
    value = tokens["color.accent"][theme]
    rgb = _hex_rgb(value)
    if rgb is None:
        return value
    return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {alpha:g})"


def token_rgb(tokens: Tokens, theme: str, key: str) -> Optional[tuple[int, int, int]]:
    """Token color as ``(r, g, b)`` for QPainter code outside QSS (W3 D4).

    The timeline delegate paints rows/rail/brackets with a QPen/QBrush, where
    QSS roles do not reach — the screen asks the compiler for the token's RGB
    and composes alphas itself (the same derivations ``accent_rgba`` spells for
    sheets, no new tokens). ``None`` when the value is not a hex color: the
    caller falls back to a neutral paint instead of inventing a color (D7).
    """
    return _hex_rgb(tokens[key][theme])


def mention_style(tokens: Tokens, theme: str) -> str:
    """Inline-HTML style for ``@mention`` anchors (W2b D2/Q8-a).

    Rich text inside a ``QTextEdit`` cannot inherit QSS: the anchor's
    ``style`` attribute is part of the document, so the screen asks the
    compiler instead of keeping its own literal hex. The color is the
    ``color.accent`` token of the current theme; screens re-render their
    documents through the runtime's retheme callback on a live switch.
    """
    return (
        f"color:{tokens['color.accent'][theme]};"
        f"font-weight:{tokens['font.weight.bold'][theme]};"
        "text-decoration:none;"
    )


def compile_qss(tokens: Tokens, theme: str) -> str:
    """Qt stylesheet for attached roots and catalog roles (literals only).

    W2a D6: rules address roles through ``[uiRole="..."]`` dynamic properties
    instead of objectNames, so one generated sheet is pushed verbatim to every
    registered root. A property selector matches only the widget that actually
    carries the property (Qt does not propagate it to children), so nested
    widgets without a role keep the OS palette. ``QToolTip``/``QMenu``/combo
    popups are absent here: as top-level popups they have no attached ancestor
    and could never match — they live in ``compile_popup_qss`` (D2).
    """
    t = {key: values[theme] for key, values in tokens.items()}
    hover = accent_rgba(tokens, theme, 0.85)
    pressed = accent_rgba(tokens, theme, 0.7)
    # Item views honor the widget palette's AlternateBase even when QSS sets
    # the base background — ``setAlternatingRowColors`` would keep painting OS
    # grey stripes. The alternate shade is an accent wash over the surface
    # (token-derived, mirrors the hover/pressed derivations). Visible in lists
    # of plain items (timeline, search results); a list whose rows are item
    # widgets (detail_panel cards) paints over it — there the card's own frame
    # separates the rows.
    alternate = accent_rgba(tokens, theme, 0.06)
    return f"""
QWidget[uiRole="chrome"], QMenuBar[uiRole="menu"] {{
    background: {t['color.bg.canvas']};
    color: {t['color.fg.primary']};
    font-size: {t['font.size.md']};
}}
QMenuBar[uiRole="menu"]::item {{
    padding: {t['space.xs']} {t['space.sm']};
    background: transparent;
    color: {t['color.fg.primary']};
}}
QMenuBar[uiRole="menu"]::item:selected {{
    background: {t['color.bg.surface']};
}}
QWidget[uiRole="chrome"] QPushButton {{
    background: {t['color.accent']};
    color: {t['color.accent.fg']};
    font-weight: {t['font.weight.bold']};
    border: 1px solid {t['color.border']};
    border-radius: {t['radius.sm']};
    padding: {t['space.xs']} {t['space.sm']};
}}
QWidget[uiRole="chrome"] QPushButton:hover {{
    background: {hover};
}}
QWidget[uiRole="chrome"] QPushButton:pressed {{
    background: {pressed};
}}
QWidget[uiRole="chrome"] QPushButton:disabled {{
    color: {t['color.fg.muted']};
}}
QWidget[uiRole="chrome"] QListWidget,
QWidget[uiRole="chrome"] QTreeView,
QWidget[uiRole="chrome"] QPlainTextEdit {{
    background: {t['color.bg.surface']};
    color: {t['color.fg.primary']};
    border: 1px solid {t['color.border']};
}}
[uiRole="title"] {{
    font-size: {t['font.size.lg']};
    font-weight: {t['font.weight.bold']};
    color: {t['color.fg.primary']};
}}
[uiRole="title"][uiRoleSize="xl"] {{
    font-size: {t['font.size.xl']};
}}
[uiRole="hint"] {{
    color: {t['color.fg.muted']};
}}
[uiRole="hint"][uiRoleItalic="true"] {{
    font-style: italic;
}}
[uiRole="field"] {{
    background: {t['color.bg.surface']};
    color: {t['color.fg.primary']};
    border: 1px solid {t['color.border']};
    border-radius: {t['radius.sm']};
    padding: {t['space.xs']} {t['space.sm']};
    selection-background-color: {t['color.accent']};
    selection-color: {t['color.accent.fg']};
}}
[uiRole="field"][uiRoleMono="true"] {{
    font-family: {t['font.family.mono']};
}}
[uiRole="list"] {{
    background: {t['color.bg.surface']};
    color: {t['color.fg.primary']};
    border: 1px solid {t['color.border']};
    alternate-background-color: {alternate};
    outline: 0;
}}
[uiRole="list"]::item {{
    padding: {t['space.xs']} {t['space.sm']};
}}
[uiRole="list"]::item:selected {{
    background: {t['color.accent']};
    color: {t['color.accent.fg']};
}}
[uiRole="splitter"]::handle {{
    background: {t['color.border']};
}}
[uiRole="card"] {{
    background: {t['color.bg.surface']};
    border: 1px solid {t['color.border']};
    border-radius: {t['radius.sm']};
    padding: {t['space.sm']};
}}
[uiRole="status-ok"] {{
    color: {t['color.status.ok']};
}}
[uiRole="status-error"] {{
    color: {t['color.danger']};
}}
""".strip()


def compile_popup_qss(tokens: Tokens, theme: str) -> str:
    """Application-wide sheet for top-level popups only (W2a D2).

    Tooltips, menus, combo/calendar dropdowns and the mention list are
    separate top-level windows: an attached-root stylesheet cannot reach them,
    so this sheet is set on ``QApplication``. It deliberately contains *no*
    generic chrome rules — anything with a class selector (``QLineEdit`` etc.)
    would also skin the widgets embedded in the sheet canvas
    (``QGraphicsProxyWidget``) which W2a must not touch.

    Menu items have no ``:hover`` rule on purpose: a hovered ``QMenu`` item is
    already ``:selected`` for Qt, so an extra alpha-hover would only wash the
    accent selection out under the cursor (W2a review).

    The mention popup is skinned on both of its classes: ``_MentionPopup`` (the
    top-level container, whose own background shows wherever the list does not
    reach) and ``MentionPopupListView`` (items/selection) — a rule for the list
    alone would leave an OS-palette strip inside the popup.

    The timeline date-filter popover (W3b D9) follows the same recipe: the
    ``_DateFilterPopup`` container and its ``_DateFilterResetButton`` are named
    classes (a generic ``QPushButton`` rule must never enter this sheet — the
    canvas proxies would pick it up), the embedded ``_CustomCalendar``s are
    already covered by the ``QCalendarWidget`` rules above.
    """
    t = {key: values[theme] for key, values in tokens.items()}
    return f"""
QToolTip {{
    background: {t['color.bg.surface']};
    color: {t['color.fg.primary']};
    border: 1px solid {t['color.border']};
    padding: {t['space.xs']} {t['space.sm']};
}}
QMenu {{
    background: {t['color.bg.surface']};
    color: {t['color.fg.primary']};
    border: 1px solid {t['color.border']};
}}
QMenu::item {{
    padding: {t['space.xs']} {t['space.sm']};
}}
QMenu::item:selected {{
    background: {t['color.accent']};
    color: {t['color.accent.fg']};
}}
QComboBox QAbstractItemView {{
    background: {t['color.bg.surface']};
    color: {t['color.fg.primary']};
    border: 1px solid {t['color.border']};
    selection-background-color: {t['color.accent']};
    selection-color: {t['color.accent.fg']};
}}
QCalendarWidget {{
    background: {t['color.bg.surface']};
    color: {t['color.fg.primary']};
}}
QCalendarWidget QToolButton {{
    background: {t['color.bg.surface']};
    color: {t['color.fg.primary']};
}}
QCalendarWidget QAbstractItemView {{
    background: {t['color.bg.surface']};
    color: {t['color.fg.primary']};
    selection-background-color: {t['color.accent']};
    selection-color: {t['color.accent.fg']};
}}
_MentionPopup {{
    background: {t['color.bg.surface']};
}}
MentionPopupListView {{
    background: {t['color.bg.surface']};
    color: {t['color.fg.primary']};
    border: 1px solid {t['color.border']};
    font-size: {t['font.size.md']};
    outline: 0;
}}
MentionPopupListView::item {{
    padding: {t['space.xs']} {t['space.sm']};
}}
MentionPopupListView::item:selected {{
    background: {t['color.accent']};
    color: {t['color.accent.fg']};
}}
_DateFilterPopup {{
    background: {t['color.bg.surface']};
    border: 1px solid {t['color.border']};
}}
_DateFilterPopup QLabel {{
    background: transparent;
    color: {t['color.fg.muted']};
}}
_DateFilterResetButton {{
    background: {t['color.bg.surface']};
    color: {t['color.fg.primary']};
    border: 1px solid {t['color.border']};
    border-radius: {t['radius.sm']};
    padding: {t['space.xs']} {t['space.sm']};
}}
""".strip()


def compile_css_root(tokens: Tokens, theme: str) -> str:
    """``:root`` block with one custom property per token (design D1)."""
    lines = [
        f"  {css_var_name(key)}: {values[theme]};"
        for key, values in tokens.items()
    ]
    return ":root {\n" + "\n".join(lines) + "\n}"
