"""Caption escape for the module's widget buttons (add-dnd-game-face 12.1).

The escape itself is kernel presentation knowledge (mnemonics are a Qt
widget-family trait, not a D&D one) and lives in
:func:`app.presentation.utils.caption_utils.button_caption`; this module
re-exports it so the module's sheets keep importing their local helper.
"""
from __future__ import annotations

from app.presentation.utils.caption_utils import button_caption

__all__ = ["button_caption"]
