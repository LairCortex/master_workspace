"""QML token bridge (Q1 design D3): ``ThemeRuntime`` → QML context palette.

A thin QObject exposing the current theme as one flat ``tokens`` dictionary
(QML reads it as ``palette.tokens["color.accent"]``). Key names are exactly
the ``tokens.json`` names; on top of them the Python compiler's own
derivations are added (hover/pressed washes of ``color.accent``, the
@mention inline style), so QML never computes a color and a third style
generator never appears — the same ``accent_rgba``/``mention_style`` calls
that ``compile_qss`` embeds as literals feed this dictionary verbatim.

Invalid tokens (D7) empty the dictionary: QML bindings then resolve to
``undefined`` and the controls stay on the plain Basic style — the QML
analogue of the QSS branch keeping the OS palette. Emissions are deduplicated
against the previous content, so re-applying the same theme (the runtime
notifies listeners anyway) never redraws a live island.

Subscription is the runtime's weak listener: a palette dropped by its owner
stops being refreshed without any unregister call (mirrors the chrome-widget
registry). This module is the Qt side of the theme package; ``runtime.py``
and ``compiler.py`` deliberately stay Qt-free.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Property, Signal

from app.presentation.theme.compiler import accent_rgba, mention_style
from app.presentation.theme.runtime import ThemeRuntime

# The alphas compile_qss uses for its QPushButton:hover/:pressed washes —
# kept as named constants here (the compiler inlines them in the sheet).
# tests/presentation/test_qml_palette.py pins both numbers against the QSS
# output, so a drift on either side fails the suite.
HOVER_ALPHA = 0.85
PRESSED_ALPHA = 0.7

# Key names of the derived entries appended to the token dictionary. They live
# in the palette vocabulary (dot-namespaced, never colliding with a token
# key) and are the contract with the qml code, spelled out once here.
DERIVED_TOKEN_KEYS: tuple[str, ...] = (
    "color.accent.hover",
    "color.accent.pressed",
    "style.mention",
)


class QmlPalette(QObject):
    """Flat token dictionary for QML, rebuilt on every theme-change signal."""

    changed = Signal()

    def __init__(self, runtime: ThemeRuntime, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._runtime = runtime
        self._tokens: dict[str, str] = self._compile()
        # Weak listener held by the runtime: dies with this palette.
        runtime.add_listener(self._on_theme_change)

    # ---- QML surface ----

    def _get_tokens(self) -> dict[str, str]:
        return self._tokens

    tokens = Property(dict, _get_tokens, notify=changed)

    # ---- internals ----

    def _compile(self) -> dict[str, str]:
        """Current-theme values + compiler derivations; ``{}`` when invalid."""
        tokens = self._runtime.tokens
        if tokens is None:
            return {}  # off-skin (D7): bindings get undefined, Controls stay Basic
        theme = self._runtime.theme
        palette = {key: values[theme] for key, values in tokens.items()}
        palette["color.accent.hover"] = accent_rgba(tokens, theme, HOVER_ALPHA)
        palette["color.accent.pressed"] = accent_rgba(tokens, theme, PRESSED_ALPHA)
        palette["style.mention"] = mention_style(tokens, theme)
        return palette

    def _on_theme_change(self) -> None:
        """Rebuild from the runtime state; emit only when the content changed."""
        palette = self._compile()
        if palette == self._tokens:
            return  # re-applied same theme / already off-skin: nothing to repaint
        self._tokens = palette
        self.changed.emit()
