"""QmlPalette token bridge (change add-qml-shell-launcher-pilot-q1, tasks 2.1/2.3).

Spec qml-shell «Мост токенов в QML»: a flat dict whose key names are exactly
the ``tokens.json`` names, derived colors computed by the same Python compiler
that feeds QSS/CSS (never in QML/JS), an invalid token set yielding an empty
dict (bindings get ``undefined``, controls stay on the Basic style — the QML
analogue of the QSS "OS palette" off-skin), and a live theme switch arriving
as the palette's ``changed`` signal without restarting or recreating anything.
"""
from __future__ import annotations

import pytest

from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation.theme.compiler import (
    REQUIRED_TOKEN_KEYS,
    accent_rgba,
    load_tokens,
    mention_style,
    tokens_file_path,
)
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.theme.runtime import ThemeRuntime

# Derived key names are the palette's contract with the qml code (group 5
# reads them from here); spelled out literally so the test fails on a rename.
DERIVED_KEYS = frozenset({"color.accent.hover", "color.accent.pressed", "style.mention"})

# The alphas compile_qss embeds into its QPushButton:hover/:pressed rules —
# the palette must derive with the very same numbers to match QSS output.
HOVER_ALPHA = 0.85
PRESSED_ALPHA = 0.7


@pytest.fixture
def tokens_file(tmp_path):
    """A private copy of the shipped token file — corruption tests must not
    touch the real tokens.json."""
    dst = tmp_path / "tokens.json"
    dst.write_text(tokens_file_path().read_text(encoding="utf-8"), encoding="utf-8")
    return dst


@pytest.fixture
def runtime(tmp_path, tokens_file):
    return ThemeRuntime(prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=tokens_file)


def track(palette: QmlPalette) -> list:
    """Count ``changed`` emissions of a palette."""
    emits: list[int] = []
    palette.changed.connect(lambda: emits.append(1))
    return emits


# ── 2.1: dictionary content ─────────────────────────────────────────────────


def test_palette_holds_exactly_the_token_names_of_the_file(runtime):
    tokens = load_tokens(tokens_file_path())  # independent expected values
    assert tokens is not None
    palette = QmlPalette(runtime).tokens

    # Exactly the required token names — no missing, no invented renames —
    # plus the fixed derived set.
    assert set(palette) - set(REQUIRED_TOKEN_KEYS) == set(DERIVED_KEYS)
    for key in REQUIRED_TOKEN_KEYS:
        assert palette[key] == tokens[key][runtime.theme]


def test_derived_keys_match_the_qss_compiler_output(runtime):
    tokens = load_tokens(tokens_file_path())
    assert tokens is not None
    qss = runtime.qss()
    palette = QmlPalette(runtime).tokens

    assert palette["color.accent.hover"] == accent_rgba(tokens, runtime.theme, HOVER_ALPHA)
    assert palette["color.accent.pressed"] == accent_rgba(tokens, runtime.theme, PRESSED_ALPHA)
    assert palette["style.mention"] == mention_style(tokens, runtime.theme)
    # The derived strings are the exact literals compile_qss embeds in its
    # :hover/:pressed rules — no second color derivation appeared (D3).
    assert palette["color.accent.hover"] in qss
    assert palette["color.accent.pressed"] in qss


def test_invalid_token_set_gives_empty_palette_without_changes(tmp_path):
    bad = tmp_path / "tokens.json"
    bad.write_text("{not json", encoding="utf-8")
    runtime = ThemeRuntime(prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=bad)

    palette = QmlPalette(runtime)
    assert palette.tokens == {}

    emits = track(palette)
    for notify in runtime.subscribers:  # simulated theme-change notification
        notify()
    assert palette.tokens == {}
    assert emits == []  # «изменений нет»: nothing to emit, the signal stays silent

    # The theme switches are no-ops on invalid tokens (D7) and keep the palette off-skin.
    assert runtime.toggle() is False
    assert palette.tokens == {}
    assert emits == []


# ── 2.3: live retheme ────────────────────────────────────────────────────────


def test_live_switch_reemits_with_values_of_the_new_theme(runtime):
    tokens = load_tokens(tokens_file_path())
    assert tokens is not None
    palette = QmlPalette(runtime)
    emits = track(palette)
    assert runtime.theme == "dark"
    assert palette.tokens["color.bg.surface"] == tokens["color.bg.surface"]["dark"]

    assert runtime.toggle() is True  # dark → light
    assert emits == [1]
    assert palette.tokens["color.bg.surface"] == tokens["color.bg.surface"]["light"]
    assert palette.tokens["color.accent"] == tokens["color.accent"]["light"]
    assert palette.tokens["color.accent.hover"] == accent_rgba(tokens, "light", HOVER_ALPHA)
    assert palette.tokens["color.accent.hover"] in runtime.qss()

    assert runtime.toggle() is True  # light → dark (both themes proven)
    assert emits == [1, 1]
    assert palette.tokens["color.accent"] == tokens["color.accent"]["dark"]
    assert palette.tokens["color.accent.pressed"] == accent_rgba(tokens, "dark", PRESSED_ALPHA)


def test_reapplying_the_same_theme_emits_nothing(runtime):
    palette = QmlPalette(runtime)
    emits = track(palette)
    assert runtime.set_theme("dark") is True  # already dark — listeners fire
    assert emits == []  # …but the palette dictionary did not change


def test_file_corruption_empties_the_palette_on_next_notification(runtime, tokens_file):
    palette = QmlPalette(runtime)
    assert palette.tokens != {}
    emits = track(palette)

    tokens_file.write_text("{corrupted", encoding="utf-8")
    runtime.reload_tokens()
    assert runtime.is_valid is False

    assert runtime.toggle() is False  # live switches are off while tokens are broken
    assert emits == []

    for notify in runtime.subscribers:  # the palette re-reads the runtime state
        notify()
    assert len(emits) == 1  # filled → empty is a change: changed is emitted
    assert palette.tokens == {}

    for notify in runtime.subscribers:
        notify()
    assert len(emits) == 1  # afterwards: empty stays empty, «изменений нет»
