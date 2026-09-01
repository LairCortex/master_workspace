"""Tests for theme tokens parsing and in-memory QSS/CSS compilation (W1 D1/D2/D7, W2a)."""
from __future__ import annotations

import colorsys
import json
import re

import pathlib

import pytest
from PySide6.QtGui import QColor

from app.presentation.theme.compiler import (
    CHART_TOKEN_KEYS,
    REQUIRED_TOKEN_KEYS,
    THEMES as COMPILER_THEMES,
    accent_rgba,
    compile_css_root,
    compile_popup_qss,
    compile_qss,
    css_var_name,
    load_tokens,
    token_rgb,
    tokens_file_path,
)
from app.presentation.theme.runtime import APP_CSS_PATH


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
    # Names are fixed by design D1 (W1) + W2a D4 catalog roles + the W4 chart
    # palette (ui-theme delta: «color.chart.1…8 обязательна»); change only
    # together with the design. Every key is read — by a QSS/CSS rule, a named
    # runtime reader (RUNTIME_READ_TOKENS) or the timeline/type-dialog delegate
    # (chart, W4). Unread roles (W2a review: rating endpoints, mono family) are
    # rejected: they only tighten validation, so they join with their screens.
    assert set(REQUIRED_TOKEN_KEYS) == {
        "color.bg.canvas",
        "color.bg.surface",
        "color.fg.primary",
        "color.fg.muted",
        "color.border",
        "color.accent",
        "color.accent.fg",
        "color.danger",
        "color.status.ok",
        "font.family.mono",
        "color.rating.low",
        "color.rating.high",
        "space.xs",
        "space.sm",
        "space.md",
        "radius.sm",
        "font.size.md",
        "font.size.lg",
        "font.size.xl",
        "font.weight.bold",
        *CHART_TOKEN_KEYS,
    }


# Keys read at runtime by screen code rather than by a generated stylesheet —
# each exemption must name its reader (W2b D4: rating endpoints are painted
# by ``detail_panel.rating_to_color``, not by QSS).
RUNTIME_READ_TOKENS = {
    "color.rating.low": "app.presentation.views.detail_panel",
    "color.rating.high": "app.presentation.views.detail_panel",
}


def test_every_required_token_is_read_by_a_generated_style(tokens):
    # Guard against re-introducing dead tokens: each key must appear either as
    # a literal in the compiled QSS (sheetworks embed token values), as a
    # custom property the repo app.css body actually references, or be read by
    # a named runtime reader (RUNTIME_READ_TOKENS). The chart palette is the
    # one exception fixed by the ui-theme spec (W4): its readers are the event
    # timeline and the event-types dialog, and chrome rules must *not* read it
    # (spec «Chart-токен не протёк в chrome», scan in test_chart_palette_is_not_read_by_chrome).
    # Chart keys still hand their value to the web player as a CSS custom
    # property, so :root must declare all eight.
    import importlib

    qss = compile_qss(tokens, "dark") + compile_popup_qss(tokens, "dark")
    css_root = compile_css_root(tokens, "dark")
    body = APP_CSS_PATH.read_text(encoding="utf-8")
    for key in REQUIRED_TOKEN_KEYS:
        if key in CHART_TOKEN_KEYS:
            assert f"{css_var_name(key)}:" in css_root, key
            continue
        if key in RUNTIME_READ_TOKENS:
            reader = importlib.import_module(RUNTIME_READ_TOKENS[key])
            source = pathlib.Path(reader.__file__).read_text(encoding="utf-8")
            assert f'"{key}"' in source, key
            continue
        for theme in ("light", "dark"):
            if tokens[key][theme] in qss:
                break
        else:
            var = css_var_name(key)
            assert var in css_root, key
            assert f"var({var})" in body or f"var({var}," in body, key


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


def test_qss_addresses_roles_not_object_names(tokens):
    qss = compile_qss(tokens, "dark")
    assert 'QWidget[uiRole="chrome"]' in qss
    assert 'QMenuBar[uiRole="menu"]' in qss
    # W2a D6: objectName selectors are gone — the role comes from the property.
    assert "themeChrome" not in qss
    assert "themeMenu" not in qss
    # QToolTip is a top-level popup: an attached-root rule could never reach
    # it — tooltip skinning lives in compile_popup_qss (W2a D2).
    assert "QToolTip" not in qss
    # QMenu popups are top-level windows too — out of the root sheet (D2);
    # the QMenuBar widget itself stays in the chrome sheet (not a popup).
    assert not re.search(r"\bQMenu\b(?!Bar)", qss)


def test_qss_contains_catalog_role_rules(tokens):
    qss = compile_qss(tokens, "dark")
    # Every catalog role of the ui-widget-catalog spec has a rule.
    for role in ("title", "hint", "field", "list", "card", "status-ok", "status-error"):
        assert f'[uiRole="{role}"]' in qss
    assert '[uiRole="title"][uiRoleSize="xl"]' in qss
    assert qss.index('[uiRole="title"] {') < qss.index('[uiRole="title"][uiRoleSize="xl"]')
    assert '[uiRole="hint"][uiRoleItalic="true"]' in qss
    assert '[uiRole="list"]::item:selected' in qss
    d = tokens["color.status.ok"]["dark"]
    assert f'[uiRole="status-ok"] {{\n    color: {d};' in qss
    assert f'[uiRole="status-error"] {{\n    color: {tokens["color.danger"]["dark"]};' in qss


def test_qss_role_values_come_from_the_theme(tokens):
    qss = compile_qss(tokens, "light")
    assert f'color: {tokens["color.status.ok"]["light"]};' in qss
    assert f'font-size: {tokens["font.size.lg"]["light"]};' in qss
    assert f'font-size: {tokens["font.size.xl"]["light"]};' in qss
    assert f'background: {tokens["color.bg.surface"]["light"]};' in qss


def test_qss_chrome_button_has_hover_and_pressed(tokens):
    qss = compile_qss(tokens, "dark")
    assert 'QWidget[uiRole="chrome"] QPushButton:hover' in qss
    assert 'QWidget[uiRole="chrome"] QPushButton:pressed' in qss


# ── accent-derived highlights (W2a D5) ─────────────────────────────────────

@pytest.mark.parametrize("theme", ["light", "dark"])
def test_accent_rgba_matches_the_accent_token(tokens, theme):
    accent = QColor(tokens["color.accent"][theme])
    assert accent.isValid()
    assert accent_rgba(tokens, theme, 0.85) == (
        f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.85)"
    )
    assert accent_rgba(tokens, theme, 0.7) == (
        f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.7)"
    )


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_qss_hover_pressed_highlights_are_accent_derived(tokens, theme):
    qss = compile_qss(tokens, theme)
    assert accent_rgba(tokens, theme, 0.85) in qss
    assert accent_rgba(tokens, theme, 0.7) in qss


def test_accent_rgba_falls_back_to_raw_value_when_not_hex():
    fake = {"color.accent": {"light": "not-a-color", "dark": "not-a-color"}}
    assert accent_rgba(fake, "light", 0.5) == "not-a-color"


# ── popup sheet (W2a D2) ────────────────────────────────────────────────────

@pytest.mark.parametrize("theme", ["light", "dark"])
def test_popup_sheet_covers_every_popup_category(tokens, theme):
    sheet = compile_popup_qss(tokens, theme)
    assert "QToolTip" in sheet               # tooltips
    assert "QMenu" in sheet                  # menus (menu-bar popups included)
    assert "QComboBox QAbstractItemView" in sheet   # combo dropdowns
    assert "QCalendarWidget" in sheet        # the date picker
    # the mention popup: container background *and* list items (both classes)
    assert "_MentionPopup {" in sheet
    assert "MentionPopupListView" in sheet
    # the timeline filter popover (W3b D9): container + named reset button
    # (the sheet must stay free of generic QPushButton rules)
    assert "_DateFilterPopup {" in sheet
    assert "_DateFilterResetButton {" in sheet


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_popup_menu_selection_is_not_washed_out_by_hover(tokens, theme):
    # A hovered QMenu item is already :selected for Qt; an ::item:hover rule on
    # top would repaint the accent selection with a translucent accent (W2a
    # review), so menu selection stays a single opaque rule.
    sheet = compile_popup_qss(tokens, theme)
    assert "QMenu::item:selected" in sheet
    assert "QMenu::item:hover" not in sheet
    assert accent_rgba(tokens, theme, 0.35) not in sheet


def test_popup_sheet_is_not_the_chrome_sheet(tokens):
    sheet = compile_popup_qss(tokens, "dark")
    # No generic chrome rules leak into the application-wide sheet: that is
    # how the canvas (QGraphicsProxyWidget fields) stays untouched (D2).
    assert 'uiRole="chrome"' not in sheet
    assert "QLineEdit" not in sheet
    assert "QPushButton" not in sheet


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_chrome_and_popup_sheets_split_without_overlap(tokens, theme):
    chrome = compile_qss(tokens, theme)
    popup = compile_popup_qss(tokens, theme)
    for popup_only in ("QToolTip", "QComboBox QAbstractItemView",
                       "QCalendarWidget", "MentionPopupListView"):
        assert popup_only not in chrome
        assert popup_only in popup
    assert not re.search(r"\bQMenu\b(?!Bar)", chrome)  # only the QMenuBar widget stays


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


# ── chart palette (W4 ui-theme delta: «color.chart.1…8» обязательна) ─────────

# Design D6 thresholds, fixed as constants here (the "pixel test" of the
# spec scenario «Chart-палитра обязательна и различима»): a category color
# must separate from its theme's surface by more than a WCAG-style contrast
# floor; the eight hues must stay eye-separable, with lightness variation;
# and a key's light/dark pair must keep the same hue (color meaning).
MIN_CONTRAST_ON_SURFACE = 3.0
MIN_HUE_SEPARATION = 30.0
MIN_LIGHTNESS_SPREAD = 10.0
MAX_LIGHT_DARK_HUE_SHIFT = 15.0


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def chan(c: int) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def _contrast_ratio(rgb_a, rgb_b) -> float:
    l1, l2 = sorted((_relative_luminance(rgb_a), _relative_luminance(rgb_b)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def _hue_lightness(rgb: tuple[int, int, int]) -> tuple[float, float]:
    """``(r, g, b)`` → ``(hue degrees, lightness 0..100)``."""
    h, l, _s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    return h * 360, l * 100


def _hue_distance(a: float, b: float) -> float:
    diff = abs(a - b) % 360
    return min(diff, 360 - diff)


# 1.1 — the generator round-trips all eight pairs in both themes: parse →
# token_rgb (the delegate's reader) → compiled CSS custom property.
def test_chart_palette_round_trips_through_the_generator(tokens):
    assert CHART_TOKEN_KEYS == tuple(f"color.chart.{i}" for i in range(1, 9))
    for key in CHART_TOKEN_KEYS:
        assert key in tokens
        for theme in ("light", "dark"):
            value = tokens[key][theme]
            color = QColor(value)
            assert color.isValid(), (key, theme, value)
            assert token_rgb(tokens, theme, key) == (color.red(), color.green(), color.blue())
            css_root = compile_css_root(tokens, theme)
            assert f"  {css_var_name(key)}: {value};" in css_root


# 1.2 — readability: every chart value has a contrast floor against its own
# theme's ``color.bg.surface`` (spec «различимы на фоне color.bg.surface»).
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_chart_colors_contrast_with_their_surface(tokens, theme):
    surface = token_rgb(tokens, theme, "color.bg.surface")
    assert surface is not None
    for key in CHART_TOKEN_KEYS:
        rgb = token_rgb(tokens, theme, key)
        assert rgb is not None, (key, theme)
        assert _contrast_ratio(rgb, surface) > MIN_CONTRAST_ON_SURFACE, (key, theme)


# 1.2 — the eight are mutually separable: hue spread + lightness variation
# (design D6 a), and a key's pair keeps its hue across themes (D6 c).
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_chart_hues_are_spread_and_lightness_varies(tokens, theme):
    hls = [_hue_lightness(token_rgb(tokens, theme, key)) for key in CHART_TOKEN_KEYS]
    hues = sorted(h for h, _l in hls)
    gaps = [
        _hue_distance(hues[i], hues[i + 1]) for i in range(len(hues) - 1)
    ] + [_hue_distance(hues[-1], hues[0])]
    assert min(gaps) >= MIN_HUE_SEPARATION
    lightnesses = [l for _h, l in hls]
    assert max(lightnesses) - min(lightnesses) >= MIN_LIGHTNESS_SPREAD


def test_chart_pairs_keep_their_hue_across_themes(tokens):
    for key in CHART_TOKEN_KEYS:
        hue_light = _hue_lightness(token_rgb(tokens, "light", key))[0]
        hue_dark = _hue_lightness(token_rgb(tokens, "dark", key))[0]
        assert _hue_distance(hue_light, hue_dark) <= MAX_LIGHT_DARK_HUE_SHIFT, key


# 1.2 — spec «Chart-токен не протёк в chrome»: neither chrome sheet embeds a
# chart value, and the repo CSS body never references a chart property — the
# palette is eaten only by the event timeline and the event-types dialog.
# Values are kept distinct, so a literal substring scan is unambiguous.
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_chart_palette_is_not_read_by_chrome(tokens, theme):
    all_values = [tokens[key][name] for key in CHART_TOKEN_KEYS for name in ("light", "dark")]
    assert len(set(all_values)) == 2 * len(CHART_TOKEN_KEYS)  # distinct scan targets
    chrome = compile_qss(tokens, theme) + compile_popup_qss(tokens, theme)
    body = APP_CSS_PATH.read_text(encoding="utf-8")
    css_root = compile_css_root(tokens, theme)
    for key in CHART_TOKEN_KEYS:
        for name in ("light", "dark"):
            assert tokens[key][name] not in chrome, (key, name)
        var = css_var_name(key)
        assert var not in body, key
        # the value still reaches the web player through the generated :root
        assert f"{var}: {tokens[key][theme]};" in css_root


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


@pytest.mark.parametrize("dropped_key", REQUIRED_TOKEN_KEYS)
def test_dropping_any_required_token_invalidates_the_whole_set(tmp_path, dropped_key):
    # W2a (spec «битые токены»): every required token — the six new catalog
    # ones included — invalidates the set completely, no partial skin.
    path = tmp_path / "tokens.json"
    data = {k: {"light": "#fff", "dark": "#000"} for k in REQUIRED_TOKEN_KEYS}
    del data[dropped_key]
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


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda d: d.pop("color.chart.5"),                      # chart токена нет
        lambda d: d["color.chart.3"].pop("light"),             # пары light/dark неполная
        lambda d: d["color.chart.8"].__setitem__("dark", 7),   # не строка
        lambda d: d.__setitem__("color.chart.1", "#c62828"),   # не объект
    ],
)
def test_missing_or_broken_chart_token_invalidates_the_whole_theme(tmp_path, corrupt):
    # W4 ui-theme delta: chart-палитра обязательна — отсутствие или порча
    # любого color.chart.* гасит тему по общей судьбе «Битые токены» (D7).
    path = tmp_path / "tokens.json"
    data = {k: {"light": "#fff", "dark": "#000"} for k in REQUIRED_TOKEN_KEYS}
    corrupt(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    assert load_tokens(path) is None


def test_top_level_not_object_is_invalid(tmp_path):
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps([{"light": "#fff", "dark": "#000"}]), encoding="utf-8")
    assert load_tokens(path) is None


def test_accent_rgba_expands_short_hex():
    fake = {"color.accent": {"light": "#7ae", "dark": "#7ae"}}
    assert accent_rgba(fake, "light", 0.5) == "rgba(119, 170, 238, 0.5)"


def test_field_role_mono_rule_uses_the_mono_token(tokens):
    """W2b: ``[field][uiRoleMono=true]`` draws its family from the token."""
    for theme in ("light", "dark"):
        qss = compile_qss(tokens, theme)
        assert '[uiRole="field"][uiRoleMono="true"]' in qss
        assert f"font-family: {tokens['font.family.mono'][theme]}" in qss
