"""The Lucide QIcon bridge for the widget side (widgets icon pass).

Pins the production behaviours offscreen. Since the F1 fix (live audit
2026-09-30) the primary path is a ``QIconEngine`` that resolves the glyph ink
at PAINT time from the live theme — the earlier one-shot pixmap froze the
ink at construction and went invisible after a dark→light switch:

* a vendored name yields an icon whose ``pixmap(size)`` is non-null and
  actually paints, tinted with the live theme's ``color.fg.primary`` token
  (the manual paint is the primary path: the native SVG engine resolves
  ``currentColor`` to black and ignores the theme, painting black glyphs
  on the dark theme; and an OS-palette read is barred in ``views/`` by
  test_no_chrome_hex, so the token route is the only honest ink);
* a LIVE theme switch through ``ThemeRuntime.set_theme`` repaints the SAME
  ``QIcon`` with the NEW theme's ink — dark→light and back, pixel-pinned —
  because no tint is ever cached (behaviour-probed: every ``QIcon::pixmap``
  call reaches the engine again);
* an accent-role icon paints ``color.accent.fg``, matching the caption the
  compiled sheet paints on chrome buttons, and its Disabled mode paints the
  disabled caption token ``color.fg.muted``, matching the caption's own
  disabled color (F2);
* the requested size is respected, and an empty size request falls back to
  the icon's own default size;
* an unknown name raises ``KeyError`` naming the glyph and the remedy, never
  a silently empty icon;
* an SVG the renderer refuses (unparseable) hands the icon to the
  engine-built fallback when an engine paints — and an engine built on the
  same broken text paints nothing (null pixmap, silent paint);
* the engine probe returns ``None`` for a file no engine paints (the exact
  line a plugin-less environment plus a broken SVG would take);
* off-skin (invalid tokens) and a non-hex token value degrade to the named
  Qt global ``black``, the same pinned landing ``ThemeIcon`` degrades to.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation.theme import ThemeRuntime, get_default_theme
from app.presentation.theme.compiler import token_rgb, tokens_file_path
from app.presentation.views import lucide_icons
from app.presentation.views.lucide_icons import (
    ACCENT_INK_TOKEN_KEY,
    DISABLED_INK_TOKEN_KEY,
    INK_TOKEN_KEY,
    lucide_icon,
)


def _painted_pixels(pixmap) -> int:
    image = pixmap.toImage()
    return sum(
        1
        for y in range(pixmap.height())
        for x in range(pixmap.width())
        if image.pixelColor(x, y).alpha() > 0
    )


def _carries_ink(pixmap, color: QColor) -> bool:
    """Any pixel whose RGB is exactly the ink (anti-aliasing only changes
    alpha here, so an edge pixel still reads the ink's name)."""
    image = pixmap.toImage()
    return any(
        image.pixelColor(x, y).name() == color.name()
        for y in range(pixmap.height())
        for x in range(pixmap.width())
    )


def _live_runtime(tmp_path) -> ThemeRuntime:
    """A real-token runtime over throwaway prefs — the switch surface the
    live audit drove (set_theme dark/light with a compiled sheet behind it)."""
    runtime = ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"),
        tokens_path=tokens_file_path(),
    )
    assert runtime.tokens is not None
    return runtime


def test_vendored_name_yields_a_painting_icon():
    icon = lucide_icon("plus")
    pixmap = icon.pixmap(16, 16)
    assert not pixmap.isNull()
    assert _painted_pixels(pixmap) > 0


def test_primary_paint_is_the_theme_ink_not_the_engines_black():
    """The dark-theme fix (2026-09-30): the primary path is the manual paint,
    so the glyph carries the live theme's ``color.fg.primary`` — the SVG
    engine would resolve currentColor to black and ignore the theme entirely
    (and an OS-palette read is barred in views/ by test_no_chrome_hex)."""
    theme = get_default_theme()
    expected = QColor(*token_rgb(theme.tokens, theme.theme, INK_TOKEN_KEY))
    pixmap = lucide_icon("plus", size=24).pixmap(24, 24)
    assert not pixmap.isNull()
    image = pixmap.toImage()
    assert any(
        image.pixelColor(x, y).name() == expected.name()
        for y in range(24)
        for x in range(24)
    ), f"the primary paint must follow {expected.name()} (the token), not raw currentColor"


def _has_nonblack_opaque_pixel(image) -> bool:
    return any(
        image.pixelColor(x, y).name() != "#000000"
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() == 255
    )


def test_off_skin_paint_degrades_to_the_named_black(tmp_path, monkeypatch):
    """D7: with no valid skin the ink lands on the named Qt global black —
    the same pinned degradation ThemeIcon's guarded lookup falls to."""
    off = ThemeRuntime(tokens_path=tmp_path / "no-such-tokens.json")
    assert off.tokens is None
    monkeypatch.setattr(lucide_icons, "get_default_theme", lambda: off)
    pixmap = lucide_icon("plus", size=24).pixmap(24, 24)
    assert not pixmap.isNull() and _painted_pixels(pixmap) > 0
    assert not _has_nonblack_opaque_pixel(pixmap.toImage())


def test_non_hex_token_value_falls_back_like_off_skin(monkeypatch):
    """token_rgb answers None for a value it cannot read as hex; the ink
    degrades to the same named black instead of inventing or crashing on a
    color (D7)."""
    skinless = SimpleNamespace(
        theme="dark",
        tokens={INK_TOKEN_KEY: {"dark": "tomato"}},
    )
    monkeypatch.setattr(lucide_icons, "get_default_theme", lambda: skinless)
    pixmap = lucide_icon("plus", size=24).pixmap(24, 24)
    assert not pixmap.isNull() and _painted_pixels(pixmap) > 0
    assert not _has_nonblack_opaque_pixel(pixmap.toImage())


# ── F1: the live theme switch repaints the SAME icon ─────────────────────────


def test_live_theme_switch_repaints_the_same_icon(tmp_path, monkeypatch):
    """The stale-pixel regression (F1) is impossible by construction: every
    request re-reads the runtime, so after ``set_theme`` the same ``QIcon``
    answers the NEW theme's ink and shows none of the old one. Both
    directions, pixel-exact."""
    runtime = _live_runtime(tmp_path)
    assert runtime.set_theme("dark")
    monkeypatch.setattr(lucide_icons, "get_default_theme", lambda: runtime)
    tokens = runtime.tokens
    dark = QColor(*token_rgb(tokens, "dark", INK_TOKEN_KEY))
    light = QColor(*token_rgb(tokens, "light", INK_TOKEN_KEY))
    icon = lucide_icon("plus", size=24)
    assert _carries_ink(icon.pixmap(24, 24), dark)

    assert runtime.set_theme("light") is True
    after = icon.pixmap(24, 24)
    assert _carries_ink(after, light), "the pixmap must follow the new theme"
    assert not _carries_ink(after, dark), "no frozen pixels of the old theme"

    assert runtime.set_theme("dark") is True  # the reverse direction
    assert _carries_ink(icon.pixmap(24, 24), dark)
    assert not _carries_ink(icon.pixmap(24, 24), light)


def test_direct_paint_path_follows_the_live_theme(tmp_path, monkeypatch):
    """The other half of the consumer surface: styles that paint the icon
    directly (``QIcon::paint`` → ``engine::paint``) re-read the runtime too,
    so the F1 reproduction (open surface, toggle theme, reopen) cannot leave
    a stale glyph on any of the draw routes."""
    runtime = _live_runtime(tmp_path)
    assert runtime.set_theme("dark")
    monkeypatch.setattr(lucide_icons, "get_default_theme", lambda: runtime)
    tokens = runtime.tokens
    dark = QColor(*token_rgb(tokens, "dark", INK_TOKEN_KEY))
    light = QColor(*token_rgb(tokens, "light", INK_TOKEN_KEY))
    icon = lucide_icon("chevron-left")
    canvas = QPixmap(48, 48)
    canvas.fill(Qt.GlobalColor.white)
    painter = QPainter(canvas)
    icon.paint(painter, QRect(0, 0, 16, 16))
    painter.end()
    assert _carries_ink(canvas, dark)

    assert runtime.set_theme("light")
    canvas.fill(Qt.GlobalColor.white)
    painter = QPainter(canvas)
    icon.paint(painter, QRect(0, 0, 16, 16))  # the style's direct-paint path
    painter.end()
    assert _carries_ink(canvas, light)
    assert not _carries_ink(canvas, dark)


# ── F2: ink token per button role, disabled follows the caption ──────────────


def test_accent_ink_token_paints_the_accent_caption_color(tmp_path, monkeypatch):
    """Glyphs on primary-role buttons (the ones the catalog tagged ``primary``,
    the only chrome buttons the compiled sheet fills with the accent) carry
    ``color.accent.fg`` — the exact ink of the caption the sheet paints there,
    not the fg token they used to argue with."""
    runtime = _live_runtime(tmp_path)
    assert runtime.set_theme("dark")
    monkeypatch.setattr(lucide_icons, "get_default_theme", lambda: runtime)
    tokens = runtime.tokens
    expected = QColor(*token_rgb(tokens, "dark", ACCENT_INK_TOKEN_KEY))
    fg = QColor(*token_rgb(tokens, "dark", INK_TOKEN_KEY))
    assert expected.name() != fg.name()  # the pair F1/F2 observed diverging
    pixmap = lucide_icon("play", ink_token=ACCENT_INK_TOKEN_KEY).pixmap(16, 16)
    assert _carries_ink(pixmap, expected)
    assert not _carries_ink(pixmap, fg)


def test_disabled_mode_paints_the_disabled_caption_token(tmp_path, monkeypatch):
    """A disabled chrome button greys its caption with ``color.fg.muted``
    (compiler QPushButton:disabled); Qt's automatic disabled pixmap tint
    lands elsewhere (audit: glyph (205,173,128) vs caption (154,151,143)),
    so the engine paints Disabled with the caption's own token."""
    runtime = _live_runtime(tmp_path)
    assert runtime.set_theme("dark")
    monkeypatch.setattr(lucide_icons, "get_default_theme", lambda: runtime)
    tokens = runtime.tokens
    muted = QColor(*token_rgb(tokens, "dark", DISABLED_INK_TOKEN_KEY))
    normal_accent = QColor(*token_rgb(tokens, "dark", ACCENT_INK_TOKEN_KEY))
    icon = lucide_icon("circle-stop", ink_token=ACCENT_INK_TOKEN_KEY)
    disabled = icon.pixmap(16, 16, QIcon.Mode.Disabled)
    assert _carries_ink(disabled, muted)
    assert not _carries_ink(disabled, normal_accent)
    # the normal state stays on the configured ink — the swap is mode-scoped
    assert _carries_ink(icon.pixmap(16, 16), normal_accent)


@pytest.mark.parametrize("size", [16, 24])
def test_requested_size_is_respected(size):
    pixmap = lucide_icon("plus", size=size).pixmap(size, size)
    assert not pixmap.isNull()
    assert (pixmap.width(), pixmap.height()) == (size, size)


def test_empty_size_request_falls_back_to_the_icon_size():
    engine = lucide_icons._ThemeInkIconEngine(
        (lucide_icons.ICONS_DIR / "plus.svg").read_text(encoding="utf-8"),
        24,
        INK_TOKEN_KEY,
    )
    pixmap = engine.pixmap(QSize(), QIcon.Mode.Normal, QIcon.State.Off)
    assert (pixmap.width(), pixmap.height()) == (24, 24)


def test_clone_keeps_the_same_glyph_and_ink():
    icon = lucide_icon("plus", size=24, ink_token=ACCENT_INK_TOKEN_KEY)
    engine = lucide_icons._ThemeInkIconEngine(
        (lucide_icons.ICONS_DIR / "plus.svg").read_text(encoding="utf-8"),
        24,
        ACCENT_INK_TOKEN_KEY,
    )
    clone = engine.clone()
    theme = get_default_theme()
    expected = QColor(*token_rgb(theme.tokens, theme.theme, ACCENT_INK_TOKEN_KEY))
    assert _carries_ink(clone.pixmap(QSize(24, 24), QIcon.Mode.Normal, QIcon.State.Off), expected)
    assert _carries_ink(icon.pixmap(24, 24), expected)


def test_unknown_name_raises_key_error_with_the_remedy():
    with pytest.raises(KeyError) as caught:
        lucide_icon("no-such-glyph")
    message = str(caught.value)
    assert "no-such-glyph" in message
    assert "vendor_lucide" in message


def test_engine_probe_gives_up_on_an_unpaintable_path():
    # The exact branch a plugin-less environment takes: QIcon paints nothing
    # from a path with no SVG behind it, so the probe answers None and
    # nothing is left to try after the paint failed too.
    assert lucide_icons._engine_icon(Path("definitely-not-vendored.svg")) is None


def test_paint_refuses_an_svg_the_renderer_cannot_parse(tmp_path):
    broken = tmp_path / "broken.svg"
    broken.write_text("this is not an svg document", encoding="utf-8")
    assert not QSvgRenderer(broken.read_bytes()).isValid()
    # The engine built on the same broken text is silent, never a crash:
    # a null raster from ``pixmap``, a no-op from ``paint``.
    engine = lucide_icons._ThemeInkIconEngine(
        broken.read_text(encoding="utf-8"), 16, INK_TOKEN_KEY
    )
    assert engine.pixmap(QSize(16, 16), QIcon.Mode.Normal, QIcon.State.Off).isNull()
    canvas = QPixmap(16, 16)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    engine.paint(painter, QRect(0, 0, 16, 16), QIcon.Mode.Normal, QIcon.State.Off)
    painter.end()
    assert _painted_pixels(canvas) == 0


def test_engine_fallback_takes_over_when_the_paint_refuses(monkeypatch):
    # The swapped order's other half: when the manual renderer answers
    # invalid the engine-built icon still ships the glyph (this environment
    # ships the engine) — a present-but-untinted glyph beats an empty button.
    monkeypatch.setattr(
        lucide_icons, "_svg_renderer", lambda svg_text, ink: QSvgRenderer(b"")
    )
    icon = lucide_icon("plus")
    assert icon is not None
    assert not icon.pixmap(16, 16).isNull()


# ── the engine never caches a tint (F1's mechanism, behaviour-probed) ────────


def test_engine_resolves_ink_on_every_request(monkeypatch):
    """Every ``QIcon::pixmap`` call reaches the engine (Qt keeps no pixmap
    cache in front of an ``QIconEngine``, and this binding has no
    ``pixmapKey`` to consult) — so there is no cache whose invalidation a
    theme switch could miss."""
    calls = []
    real_svg_renderer = lucide_icons._svg_renderer

    def counting(svg_text, ink):
        calls.append(ink)
        return real_svg_renderer(svg_text, ink)

    icon = lucide_icon("plus")
    monkeypatch.setattr(lucide_icons, "_svg_renderer", counting)
    icon.pixmap(16, 16)
    icon.pixmap(16, 16)
    icon.pixmap(24, 24)
    assert len(calls) == 3, "each request must re-resolve the ink"
    assert all(ink == real_ink() for ink in calls)


def real_ink() -> str:
    theme = get_default_theme()
    return QColor(*token_rgb(theme.tokens, theme.theme, INK_TOKEN_KEY)).name()
