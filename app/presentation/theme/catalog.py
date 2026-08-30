"""Widget-role catalog: attach a screen root to the theme, tag catalog roles.

W2a (add-widget-catalog-chrome-mechanics-w2a D1): the generated QSS addresses
widgets through ``[uiRole="..."]`` dynamic properties. This module is the only
place allowed to stamp those properties:

* ``attach_theme(root)`` — one call per screen: marks the root as the chrome
  (or menu) container, registers it with a `ThemeRuntime` for live swaps and
  re-polishes so the sheet applies immediately;
* ``set_role(widget, role)`` — tags a widget with a catalog role (``title``,
  ``hint``, ``field``, ``list``, ``card``, ``status-ok``, ``status-error``);
  modifiers are separate properties (``uiRoleSize``, ``uiRoleItalic``) so QSS
  needs no logic;
* ``title(...)`` / ``hint(...)`` — factories for the frequent one-liner
  labels, no wrapper subclasses (composition over hierarchies).

Nested widgets without a role are never recolored: a Qt property selector
matches only the widget that actually carries the property, so unmigrated
screens keep the OS palette (spec «немигрированный диалог не затронут»).
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMenuBar, QWidget

from app.presentation.theme.runtime import ThemeRuntime

#: Roles accepted by ``set_role`` (mirrors the rules of ``compile_qss``).
CATALOG_ROLES: frozenset[str] = frozenset(
    {
        "title", "hint", "field", "list", "card", "splitter",
        "status-ok", "status-error",
    }
)

#: Title size modifiers; "md" is the base rule and needs no property value.
TITLE_SIZES: frozenset[str] = frozenset({"md", "xl"})


def _repolish(widget: QWidget) -> None:
    """Re-evaluate the style sheets after a dynamic property changed."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def attach_theme(
    widget: QWidget,
    runtime: ThemeRuntime | None = None,
    *,
    on_retheme: Callable[[], None] | None = None,
) -> QWidget:
    """Connect a screen root to the theme; returns ``widget`` for chaining.

    Marks the root ``chrome`` (``menu`` for a QMenuBar), registers it for live
    theme swaps and re-polishes. Registering twice is harmless (the runtime
    de-duplicates), so repeated calls are idempotent. Without ``runtime`` the
    process-wide default runtime is used (call sites in tests inject one).

    ``on_retheme`` (W2b D2) subscribes a callback that runs after every theme
    switch the runtime applies — for content painted outside QSS (rating tints,
    item background brushes, inline HTML in a rich-text document) that must
    repaint itself. It is the root-level sugar over
    ``ThemeRuntime.add_listener``, which is what a content widget that is not a
    chrome root (e.g. ``MentionTextEdit``) calls directly. Held weakly by the
    runtime, so a closed dialog never keeps the subscription.
    """
    from app.presentation.theme import get_default_theme

    runtime = runtime if runtime is not None else get_default_theme()
    role = "menu" if isinstance(widget, QMenuBar) else "chrome"
    widget.setProperty("uiRole", role)
    # A plain QWidget only paints its QSS background when styled-background
    # is on; harmless on every other container.
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    runtime.register(widget)
    if on_retheme is not None:
        runtime.add_listener(on_retheme)
    _repolish(widget)
    return widget


def set_role(
    widget: QWidget,
    role: str,
    *,
    size: str | None = None,
    italic: bool = False,
    mono: bool = False,
) -> QWidget:
    """Tag ``widget`` with a catalog ``role``; returns it for chaining.

    Modifiers live in their own properties: ``uiRoleSize="xl"``,
    ``uiRoleItalic="true"`` and ``uiRoleMono="true"`` — cleared (empty string
    = selector no-match) when absent, so toggling a role never leaves a stale
    modifier behind.
    """
    if role not in CATALOG_ROLES:
        raise ValueError(f"unknown catalog role: {role!r}")
    widget.setProperty("uiRole", role)
    widget.setProperty("uiRoleSize", size if size and size != "md" else "")
    widget.setProperty("uiRoleItalic", "true" if italic else "")
    widget.setProperty("uiRoleMono", "true" if mono else "")
    _repolish(widget)
    return widget


def title(text: str, *, size: str = "md") -> QLabel:
    """Section title label: base ``font.size.lg``, bold, ``size="xl"`` grows it."""
    if size not in TITLE_SIZES:
        raise ValueError(f"unknown title size: {size!r}")
    label = QLabel(text)
    set_role(label, "title", size=size)
    return label


def hint(text: str, *, italic: bool = False) -> QLabel:
    """Hint label in the muted foreground color, optional italic modifier."""
    label = QLabel(text)
    set_role(label, "hint", italic=italic)
    return label
