"""Lucide glyphs for the Qt widgets side: the vendored SVGs as ``QIcon``s.

The QML islands draw their glyphs from the generated ``icons.js`` path data
through ``ThemeIcon``; the widget buttons need the same set as ``QIcon``s, and
this module is the ONLY place that knows where the vendored SVG files live
(one knowledge) — the same ``icons/`` directory the build-time
``scripts/vendor_lucide.py`` maintains.

F1 fix (live audit 2026-09-30): the ink is resolved at PAINT time, never at
construction.  The first mechanism rendered one tinted pixmap in the icon's
factory, so a glyph built before a theme switch kept its frozen pixels and
landed dark-on-white (contrast ≈1.2:1) after dark→light — every consumer
calls ``lucide_icon()`` in a constructor and none re-assigns.  A live audit
cannot be re-run per screen with nine manual re-assignments, so the icon
carries a ``QIconEngine`` whose ``paint``/``pixmap`` rewrite the SVG stroke
from the CURRENT theme on every request.  This Qt has no cache to invalidate
(verified by behaviour, not by guess): each ``QIcon::pixmap`` call reaches
``engine::pixmap`` again — two requests produced two engine calls — and the
bindings expose no ``pixmapKey`` to override, so the honest contract is
"never cache the tint", pinned by a live ``set_theme`` pixel test.  The
engine also keeps the W2b invariant (no hex literals, no OS-palette reads in
``views/``): the ink still travels the canonical token route (``ThemeRuntime``
+ ``compiler.token_rgb``, the precedent of ``event_types_dialog.type_dot_icon``),
because ``QSvgRenderer`` resolves ``currentColor`` to black with no theme
awareness whatsoever — left verbatim, every glyph paints black on every theme.

The ink token is a parameter, not a constant (F2): inside a chrome root the
generated sheet paints a plain ``QPushButton`` with the ``color.bg.canvas``
fill and ``color.fg.primary`` caption, so such a button's glyph keeps the
default ink; only the primary face (``QPushButton[uiRole="primary"]``, live
since the 2026-10-01 face split — before it EVERY chrome button wore the
accent fill) gets ``color.accent`` background and ``color.accent.fg``
caption, and only there does an icon read ``ACCENT_INK_TOKEN_KEY`` to match
its caption.  A disabled chrome button drops to the ``color.bg.canvas`` fill
with a ``color.fg.muted`` caption (``QPushButton:disabled`` plus its
``[uiRole="primary"]`` twin, fixed 2026-10-01 — before that the muted caption
stayed on the accent fill at ≈1.1:1), while Qt's automatic disabled pixmap
tint lands somewhere else entirely (audit: glyph (205,173,128) vs caption
(154,151,143)) — so the engine paints the Disabled mode itself with the
caption's own token ``DISABLED_INK_TOKEN_KEY``, whatever the normal ink was.

The engine-built icon stays as the fallback for an SVG the renderer refuses
to parse: a black-but-present glyph beats an empty button.  Like the probe
before it, the fallback stays observable — ``QIcon(path)`` with no SVG engine
behind it yields a null pixmap and leaves nothing more to try.

An unknown name is a programming error, never an empty icon: ``KeyError``.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from app.presentation.theme import get_default_theme
from app.presentation.theme.compiler import token_rgb

#: Single source of where the vendored Lucide SVGs live (one knowledge): the
#: same directory ``scripts/vendor_lucide.py`` regenerates from upstream.
ICONS_DIR = Path(__file__).resolve().parents[1] / "qml" / "nri" / "components" / "icons"

#: The default glyph ink: the theme's primary foreground, the exact default
#: tint of the islands' ``ThemeIcon`` — the two halves of the icon pass paint
#: the same ink from the same token.
INK_TOKEN_KEY = "color.fg.primary"

#: Ink for glyphs on primary-role buttons: only a button the catalog tagged
#: ``primary`` gets ``color.accent`` background and this caption color from
#: the compiled sheet, so its glyph must speak the same ink as its text (F2).
ACCENT_INK_TOKEN_KEY = "color.accent.fg"

#: Ink for the Disabled mode.  The chrome sheet drops a disabled button to a
#: canvas fill with this muted caption token (``QPushButton:disabled``); the
#: engine paints the glyph with the same token instead of trusting Qt's
#: automatic disabled pixmap tint, which diverges from the caption (F2).
DISABLED_INK_TOKEN_KEY = "color.fg.muted"

#: The size the SVG-icon-engine probe renders at: small, and enough to prove
#: the engine actually paints (a missing engine gives a null pixmap).
_PROBE_SIZE = 16


def lucide_icon(
    name: str, size: int = 16, ink_token: str = INK_TOKEN_KEY
) -> QIcon:
    """The Lucide glyph ``name`` as a theme-live ``QIcon``.

    ``size`` is the default glyph size (used when a caller asks for an empty
    size); every other size request renders the vector fresh.  ``ink_token``
    selects the token the normal-state glyph paints with —
    ``ACCENT_INK_TOKEN_KEY`` on accent-role buttons, the default on plain
    surfaces.

    Raises ``KeyError`` for a name that is not vendored — a typo must fail
    loudly at its call site rather than draw an empty button.
    """
    svg_path = ICONS_DIR / f"{name}.svg"
    if not svg_path.is_file():
        raise KeyError(
            f"lucide icon {name!r} is not vendored under {ICONS_DIR}; add it "
            f"to ICON_NAMES in scripts/vendor_lucide.py and re-run --fetch"
        )
    svg_text = svg_path.read_text(encoding="utf-8")
    if not _svg_renderer(svg_text, _ink_for(ink_token).name()).isValid():
        fallback = _engine_icon(svg_path)
        if fallback is not None:
            return fallback
    return QIcon(_ThemeInkIconEngine(svg_text, size, ink_token))


def _engine_icon(svg_path: Path) -> QIcon | None:
    """Last resort: ``QIcon`` built from the SVG file when an engine paints.

    Kept for the paint that cannot happen; the engine resolves
    ``currentColor`` to black regardless of the palette, so this is a
    present-but-untinted glyph, never a themed one.  Probing with
    ``pixmap()`` rather than enumerating plugin names checks exactly what
    the button will get: a null probe means no usable engine."""
    icon = QIcon(str(svg_path))
    if icon.pixmap(_PROBE_SIZE, _PROBE_SIZE).isNull():
        return None
    return icon


def _ink_for(token_key: str) -> QColor:
    """Glyph ink for one token: the live theme's value of ``token_key``.

    The canonical token read every chrome screen uses (precedent
    ``event_types_dialog._token_color``): the runtime's ``tokens``/``theme``
    through the compiler's ``token_rgb``.  With no valid skin (D7) or a
    non-hex token value the paint lands on the named Qt global ``black``
    — the same pinned off-skin degradation ``ThemeIcon`` falls to.
    """
    theme = get_default_theme()
    rgb = (
        token_rgb(theme.tokens, theme.theme, token_key)
        if theme.tokens
        else None
    )
    return QColor(*rgb) if rgb is not None else QColor(Qt.GlobalColor.black)


def _svg_renderer(svg_text: str, ink: str) -> QSvgRenderer:
    """``QSvgRenderer`` for the glyph with ``currentColor`` rewritten to ``ink``.

    The renderer resolves ``currentColor`` without any theme awareness, so
    the tint must happen in the SVG text itself; callers hand it the ink of
    the moment.  An unparseable document answers an invalid renderer, which
    ``lucide_icon`` maps to the engine-built fallback."""
    return QSvgRenderer(
        svg_text.replace('stroke="currentColor"', f'stroke="{ink}"').encode(
            "utf-8"
        )
    )


class _ThemeInkIconEngine(QIconEngine):
    """``QIconEngine`` resolving the glyph ink at paint time (F1).

    No pixmap is ever kept: ``pixmap`` renders a fresh tinted raster and
    ``paint`` draws the vector straight onto the target painter (crisper on
    a Retina backing store, and it needs no device-pixel-ratio plumbing).
    A theme switch therefore cannot leave stale pixels behind — the next
    request re-reads ``get_default_theme`` through :func:`_ink_for`.  The
    Disabled mode is painted with the disabled caption token rather than
    left to Qt's automatic tint (F2); all other modes paint with the
    configured ink.
    """

    def __init__(self, svg_text: str, size: int, ink_token: str) -> None:
        super().__init__()
        self._svg_text = svg_text
        self._size = size
        self._ink_token = ink_token

    def clone(self) -> "_ThemeInkIconEngine":
        return _ThemeInkIconEngine(self._svg_text, self._size, self._ink_token)

    def _renderer(self, mode: "QIcon.Mode") -> QSvgRenderer | None:
        key = (
            DISABLED_INK_TOKEN_KEY
            if mode == QIcon.Mode.Disabled
            else self._ink_token
        )
        renderer = _svg_renderer(self._svg_text, _ink_for(key).name())
        return renderer if renderer.isValid() else None

    def paint(self, painter, rect, mode, state, options=None) -> None:  # noqa: ANN001 — QIconEngine virtual
        renderer = self._renderer(mode)
        if renderer is None:
            return
        renderer.render(painter, QRectF(rect))

    def pixmap(self, size, mode, state):  # noqa: ANN001, ANN201 — QIconEngine virtual
        target = size if not size.isEmpty() else QSize(self._size, self._size)
        renderer = self._renderer(mode)
        if renderer is None:
            return QPixmap()
        result = QPixmap(target)
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        renderer.render(painter, QRectF(QPointF(0, 0), QSizeF(target)))
        painter.end()
        return result
