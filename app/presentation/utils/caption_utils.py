"""Caption escape for the button/menu family (add-dnd-game-face 12.1/12.4).

The button family (QPushButton/QCheckBox/QTabBar tabs/QAction, and QMenu
titles printed in the menu bar) consumes a single '&' in its text as a
mnemonic marker: the character vanishes from the paint and ``QAccessible``
answers the stripped string as the name — the module menu group titled
«D&D» reached the live screen as «DD» and «Датасеты D&D…» as «Датасеты DD…»
(live audit 2026-10-10; offscreen ``text()`` keeps the raw string, so only
the display/AX face betrays the loss). Doubling the ampersand is Qt's own
idiom for a literal one: screen and name slot then carry the caption
verbatim. Plain labels (QLabel, message boxes, combo popups, QML text) do
NOT consume mnemonics — their captions must stay raw, so this escape
belongs only at button/menu constructors.
"""
from __future__ import annotations


def button_caption(caption: str) -> str:
    """Return ``caption`` safe for a button/menu-family text: '&' doubled.

    Captions without an ampersand (the overwhelming majority) pass through
    untouched, so existing text()-equality pins keep holding.
    """
    return caption.replace("&", "&&")
