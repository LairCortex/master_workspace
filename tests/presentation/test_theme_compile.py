"""Tests for theme tokens parsing and in-memory QSS/CSS compilation (W1 D1/D2/D7)."""
from __future__ import annotations

import json

import pytest

from app.presentation.theme.compiler import (
    REQUIRED_TOKEN_KEYS,
    THEMES as COMPILER_THEMES,
    compile_css_root,
    compile_qss,
    css_var_name,
    load_tokens,
    tokens_file_path,
)


# ── token file itself ──────────────────────────────────────────────────────

def test_tokens_file_ships_in_repo():
    assert tokens_file_path().is_file()


def test_repo_tokens_parse_and_cover_all_d1_keys():
    tokens = load_tokens(tokens_file_path())
    assert tokens is not None
    for key in REQUIRED_TOKEN_KEYS:
        assert key in tokens
        assert set(tokens[key]) == {"light", "dark"}
        assert isinstance(tokens[key]["light"], str) and tokens[key]["light"]
        assert isinstance(tokens[key]["dark"], str) and tokens[key]["dark"]


def test_d1_key_list_is_exact():
    # Names are fixed by design D1; change only together with the design.
    assert set(REQUIRED_TOKEN_KEYS) == {
        "color.bg.canvas",
        "color.bg.surface",
        "color.fg.primary",
        "color.fg.muted",
        "color.border",
        "color.accent",
        "color.accent.fg",
        "color.danger",
        "space.xs",
        "space.sm",
        "space.md",
        "radius.sm",
        "font.size.md",
        "font.weight.bold",
    }


# ── QSS compilation ────────────────────────────────────────────────────────

@pytest.fixture
def tokens():
    parsed = load_tokens(tokens_file_path())
    assert parsed is not None
    return parsed


def test_qss_light_and_dark_embed_different_canvas(tokens):
    qss_light = compile_qss(tokens, "light")
    qss_dark = compile_qss(tokens, "dark")
    canvas_light = tokens["color.bg.canvas"]["light"]
    canvas_dark = tokens["color.bg.canvas"]["dark"]
    assert canvas_light != canvas_dark
    assert canvas_light in qss_light
    assert canvas_dark in qss_dark
    assert qss_light != qss_dark


def test_qss_is_written_with_literals_not_css_vars(tokens):
    # D2: QSS embeds token literals — CSS variables are unreliable in Qt.
    qss = compile_qss(tokens, "dark")
    assert "var(--" not in qss
    assert tokens["color.accent"]["dark"] in qss


def test_qss_scoped_to_theme_chrome_objects(tokens):
    qss = compile_qss(tokens, "dark")
    assert "themeChrome" in qss
    assert "themeMenu" in qss
    # QToolTip is a top-level popup: a chrome-scoped rule could never reach
    # it, so emitting one would be dead CSS (tooltip skinning is W2 work).
    assert "QToolTip" not in qss


# ── CSS compilation ────────────────────────────────────────────────────────

def test_css_var_name_dot_to_dash():
    assert css_var_name("color.bg.canvas") == "--color-bg-canvas"
    assert css_var_name("font.weight.bold") == "--font-weight-bold"


def test_css_root_declares_token_vars(tokens):
    css = compile_css_root(tokens, "dark")
    canvas_dark = tokens["color.bg.canvas"]["dark"]
    assert ":root" in css
    assert f"--color-bg-canvas: {canvas_dark};" in css
    assert "--color-fg-primary:" in css
    assert "--space-md:" in css


def test_css_root_switches_theme(tokens):
    css_light = compile_css_root(tokens, "light")
    assert f"--color-bg-canvas: {tokens['color.bg.canvas']['light']};" in css_light


# ── invalid token files (D7: invalid as a whole) ─────────────────────────────

def test_missing_file_is_invalid(tmp_path):
    assert load_tokens(tmp_path / "nope.json") is None


def test_non_utf8_file_is_invalid(tmp_path):
    # Byte-level damage must invalidate the set (D7), not raise.
    path = tmp_path / "tokens.json"
    path.write_bytes(b"\xff\xfe\x00{\x01\x80")
    assert load_tokens(path) is None


def test_theme_names_come_from_the_domain_constants():
    from app.domain import theme as domain_theme

    assert COMPILER_THEMES == domain_theme.THEMES


def test_broken_json_is_invalid(tmp_path):
    path = tmp_path / "tokens.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_tokens(path) is None


def test_leaky_json_missing_key_is_invalid(tmp_path):
    path = tmp_path / "tokens.json"
    data = {k: {"light": "#fff", "dark": "#000"} for k in REQUIRED_TOKEN_KEYS}
    del data["color.danger"]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert load_tokens(path) is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.__setitem__("color.accent", "#123456"),          # not an object
        lambda d: d["color.accent"].pop("dark"),                     # missing dark
        lambda d: d["color.border"].__setitem__("light", 42),         # not a string
        lambda d: d.__setitem__("color.bg.canvas", {"light": "#fff", "dark": 0}),
    ],
)
def test_token_value_not_light_dark_strings_is_invalid(tmp_path, mutate):
    path = tmp_path / "tokens.json"
    data = {k: {"light": "#fff", "dark": "#000"} for k in REQUIRED_TOKEN_KEYS}
    mutate(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    assert load_tokens(path) is None


def test_top_level_not_object_is_invalid(tmp_path):
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps([{"light": "#fff", "dark": "#000"}]), encoding="utf-8")
    assert load_tokens(path) is None
