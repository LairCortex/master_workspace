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

# Alphas of the timeline tape's washes, migrated with the day-ladder scale
# (change port-event-timeline-qml-island-q2-5a, spec event-timeline «Оформление
# шкалы из токенов»): the hovered-card wash stays an ``color.accent``
# derivative at 0.25 (the retired widget's ROW_HOVER_ALPHA) and the
# drop-ghost wash at 0.35 — the spec pins the 0.35, new tokens are not being
# invented, these are compiler derivations like the button washes above.
# The wash ships as a COLOR + OPACITY token pair (not one rgba() string):
# QML's ``color`` parser is ``QColor::setNamedColor`` and does not accept
# the CSS ``rgba(…)`` form the QSS compiler embeds, so a wash must arrive at
# an island as a parseable hex color plus the scalar alpha, still computed
# only here — the QML never derives anything.
ROW_HOVER_ALPHA = 0.25
GHOST_ALPHA = 0.35

# Key names of the derived entries appended to the token dictionary. They live
# in the palette vocabulary (dot-namespaced, never colliding with a token
# key) and are the contract with the qml code, spelled out once here.
DERIVED_TOKEN_KEYS: tuple[str, ...] = (
    "color.accent.hover",
    "color.accent.pressed",
    # Consumed by TimelineRowDelegate as the hover/ghost washes (D8 of
    # port-event-timeline-qml-island-q2-5a): the wash color plus its scalar
    # alpha, both from the compiler — the QML only multiplies them at paint.
    "color.accent.rowHover",
    "color.accent.ghost",
    "opacity.accent.rowHover",
    "opacity.accent.ghost",
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
        # Timeline washes: the accent color verbatim (QML-parsable hex) plus
        # its compiler-decided alpha as a scalar — see the constants above.
        palette["color.accent.rowHover"] = palette["color.accent"]
        palette["color.accent.ghost"] = palette["color.accent"]
        palette["opacity.accent.rowHover"] = f"{ROW_HOVER_ALPHA:g}"
        palette["opacity.accent.ghost"] = f"{GHOST_ALPHA:g}"
        palette["style.mention"] = mention_style(tokens, theme)
        return palette

    def _on_theme_change(self) -> None:
        """Rebuild from the runtime state; emit only when the content changed."""
        palette = self._compile()
        if palette == self._tokens:
            return  # re-applied same theme / already off-skin: nothing to repaint
        self._tokens = palette
        self.changed.emit()
