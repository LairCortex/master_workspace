"""Theme runtime: preferences + compiled styles + chrome registration (W1).

No Qt imports: widgets are registered duck-typed (anything with
``setStyleSheet``), so the same object also feeds the table-host ``/app.css``
handler (design D6 — one compiler for Qt and web). Invalid tokens (D7)
make ``qss()``/``css()`` empty and every apply/toggle a no-op; the app keeps
the OS palette and logs the reason.

The runtime outlives dialogs (one instance per process), so both the chrome
widget registry and the change listeners are weak: a closed launcher must
not stay alive — or keep being repainted — because of the theme.

W2a (D2): the application object may be attached once (``attach_app``); the
popup sheet — tooltips/menus/combo-lists are top-level windows no container
stylesheet can reach — is pushed to it whenever its compiled text changes.
Only the popup-specific sheet is ever set on the application, so nothing
generic leaks into the character-sheet canvas (the risk that ruled out
skinning the app wholesale). The push is deduplicated: Qt re-polishes every
live widget of the whole application (not only the popups) on each
``setStyleSheet``, so re-pushing an unchanged sheet would make every widget
construction that calls ``apply()`` repaint the process — quadratic over a
long-living session (found by the W2a review as a x6 slowdown of the
offscreen suite). The sheet is only pushed again when its text differs from
what that application already has.
"""
from __future__ import annotations

import inspect
import logging
import weakref
from pathlib import Path
from typing import Callable, Optional

from app.infrastructure.ui_prefs.config import UiPrefs, UiPrefsManager
from app.presentation.theme.compiler import (
    Tokens,
    compile_css_root,
    compile_popup_qss,
    compile_qss,
    load_tokens,
    tokens_file_path,
)

log = logging.getLogger(__name__)

# The web stylesheet body ships next to the table-host static assets; the
# runtime only prepends the compiled ``:root`` block (D6).
APP_CSS_PATH = (
    Path(__file__).resolve().parent.parent
    / "views" / "table_host" / "web" / "app.css"
)

class ThemeRuntime:
    """Single source of the compiled theme for Qt chrome and web CSS."""

    def __init__(
        self,
        prefs: UiPrefsManager | None = None,
        tokens_path: Path | None = None,
        app_css_path: Path | None = None,
    ) -> None:
        self._prefs = prefs if prefs is not None else UiPrefsManager()
        self._tokens_path = tokens_path or tokens_file_path()
        self._app_css_path = app_css_path or APP_CSS_PATH
        self._tokens: Optional[Tokens] = None
        # Read once at startup: qss()/css() run on every repaint and on every
        # GET /app.css, and only set_theme() may change the value.
        self._theme = self._prefs.load().theme
        self._widgets: list = []
        self._listeners: list = []
        self._app_ref = None  # weakref to QApplication, set by attach_app (W2a)
        self.reload_tokens()

    # ---- state ----

    def reload_tokens(self) -> None:
        self._tokens = load_tokens(self._tokens_path)
        if self._tokens is None:
            log.warning(
                "Тема отключена: токены оформления не загружены из %s",
                self._tokens_path,
            )

    @property
    def is_valid(self) -> bool:
        return self._tokens is not None

    @property
    def theme(self) -> str:
        return self._theme

    @property
    def prefs(self) -> UiPrefsManager:
        return self._prefs

    # ---- compiled styles ----

    def qss(self) -> str:
        """QSS for the chrome containers, empty when tokens are invalid."""
        if self._tokens is None:
            return ""
        return compile_qss(self._tokens, self.theme)

    def popup_qss(self) -> str:
        """App-wide popup sheet, empty (off-skin) when tokens are invalid (D7)."""
        if self._tokens is None:
            return ""
        return compile_popup_qss(self._tokens, self.theme)

    def attach_app(self, app) -> None:
        """Remember the QApplication (weakly) to receive the popup sheet (W2a D2).

        Optional on purpose: unit tests construct widgets without an
        application object, and there ``apply()`` simply skips the push.
        Calling it again with the same application is harmless (``apply()``
        compares against the sheet that application already carries).
        """
        self._app_ref = weakref.ref(app)

    def _push_popup_sheet(self, app) -> None:
        """Set the popup sheet on ``app`` only when its text actually changed.

        ``QApplication.setStyleSheet`` re-polishes every live widget in the
        process, so an identical re-push is pure waste — and with dozens of
        attached windows/dialogs per session it degrades quadraticly.
        Comparing against the application's own sheet (instead of a local
        cache) also picks up sheets that were replaced from the outside.
        """
        sheet = self.popup_qss()
        if app.styleSheet() != sheet:
            app.setStyleSheet(sheet)

    def css(self) -> str:
        """``:root`` of the current theme + the repo ``app.css`` body (D6).

        Empty when the tokens are invalid: a body full of unresolved ``var()``
        would be a stylesheet with no colors at all, exactly the half-broken
        output D7 tells us to avoid on the Qt side.
        """
        if self._tokens is None:
            return ""
        try:
            body = self._app_css_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            log.warning("Не удалось прочитать %s", self._app_css_path)
            return ""
        return compile_css_root(self._tokens, self.theme) + "\n" + body

    # ---- chrome widgets ----

    @property
    def registered(self) -> tuple:
        """Alive chrome widgets that receive the QSS (dead refs are pruned)."""
        alive = [widget for widget in (ref() for ref in self._widgets) if widget is not None]
        self._widgets = [weakref.ref(widget) for widget in alive]
        return tuple(alive)

    def register(self, widget) -> None:
        """Remember a chrome widget weakly; setStyleSheet happens in apply()."""
        if not any(ref() is widget for ref in self._widgets):
            self._widgets.append(weakref.ref(widget))

    def unregister(self, widget) -> None:
        """Stop repainting ``widget`` (dialogs can drop out on their own)."""
        self._widgets = [ref for ref in self._widgets if ref() is not widget]

    # ---- change notifications ----

    def add_listener(self, callback: Callable[[], None]) -> None:
        """Call ``callback()`` after a theme change was applied.

        Held weakly (bound methods included), so a closed window never keeps
        the subscription — nor is kept alive by it.
        """
        ref = weakref.WeakMethod(callback) if inspect.ismethod(callback) else weakref.ref(callback)
        self._listeners.append(ref)

    @property
    def subscribers(self) -> tuple:
        """Currently alive change listeners (dead ones simply disappear)."""
        return tuple(callback for callback in (ref() for ref in self._listeners) if callback is not None)

    def _notify_listeners(self) -> None:
        alive: list = []
        for ref in self._listeners:
            callback = ref()
            if callback is None:
                continue  # the window/dialog behind it is gone
            alive.append(ref)
            callback()
        self._listeners = alive

    def apply(self) -> None:
        """Push the compiled QSS to every registered chrome widget (no-op if broken).

        Both pushes are deduplicated against what the target already carries:
        an application-level ``setStyleSheet`` re-polishes the whole live
        widget tree, so re-pushing an unchanged sheet made every screen
        construction that ends in ``apply()`` repaint the process (W2a review:
        x6 slowdown and offscreen flakes of the full suite). Invalid tokens
        still clear the app sheet — an empty sheet differs from the stale one
        (D7: off-skin, never a half-applied theme).
        """
        app = self._app_ref() if self._app_ref is not None else None
        if app is not None:
            try:
                self._push_popup_sheet(app)
            except RuntimeError:  # the wrapped application is gone
                self._app_ref = None
        if self._tokens is None:
            return
        qss = self.qss()
        for widget in self.registered:
            try:
                if widget.styleSheet() != qss:
                    widget.setStyleSheet(qss)
            except RuntimeError:  # wrapped C++ object already deleted
                self.unregister(widget)

    # ---- toggling ----

    def set_theme(self, theme: str) -> bool:
        """Persist and apply; no-op on invalid tokens (D7). True if applied."""
        if self._tokens is None:
            log.warning("Тема не переключена: токены невалидны")
            return False
        self._prefs.save(UiPrefs(theme=theme))
        self._theme = theme
        self.apply()
        self._notify_listeners()
        return True

    def toggle(self) -> bool:
        other = "light" if self.theme == "dark" else "dark"
        return self.set_theme(other)

