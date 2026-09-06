"""Unit coverage for the neutral rating tint helper (R4 tasks 1.1-1.2)."""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtGui import QColor

from app.presentation.theme.rating import rating_to_color


def _runtime(theme: str = "light"):
    return SimpleNamespace(
        theme=theme,
        tokens={
            "color.rating.low": {"light": "#102030", "dark": "#405060"},
            "color.rating.high": {"light": "#a0b0c0", "dark": "#d0e0f0"},
        },
    )


def test_rating_endpoints_and_clamp():
    runtime = _runtime()
    assert rating_to_color(1, runtime) == QColor(0x10, 0x20, 0x30, 80)
    assert rating_to_color(20, runtime) == QColor(0xA0, 0xB0, 0xC0, 220)
    assert rating_to_color(-100, runtime) == rating_to_color(1, runtime)
    assert rating_to_color(100, runtime) == rating_to_color(20, runtime)


def test_rating_interpolates_rgb_and_alpha():
    color = rating_to_color(10, _runtime())
    t = 9 / 19
    assert color == QColor(
        int(0x10 + t * (0xA0 - 0x10)),
        int(0x20 + t * (0xB0 - 0x20)),
        int(0x30 + t * (0xC0 - 0x30)),
        int(80 + t * 140),
    )


def test_rating_uses_active_light_and_dark_tokens():
    assert rating_to_color(1, _runtime("light")) == QColor(0x10, 0x20, 0x30, 80)
    assert rating_to_color(20, _runtime("dark")) == QColor(0xD0, 0xE0, 0xF0, 220)


def test_rating_is_transparent_without_valid_skin():
    missing_tokens = SimpleNamespace(theme="light", tokens={})
    invalid_tokens = SimpleNamespace(
        theme="light",
        tokens={
            "color.rating.low": {"light": "not-a-color"},
            "color.rating.high": {"light": "#ffffff"},
        },
    )
    assert rating_to_color(10).alpha() == 0
    assert rating_to_color(10, missing_tokens).alpha() == 0
    assert rating_to_color(10, invalid_tokens).alpha() == 0
