"""E2E pixel checks for the token-themed chrome (W1 acceptance D9).

Offscreen Qt: show + waitExposed + grab(); a bare chrome pixel must equal
the opaque hex of ``color.bg.canvas`` for the current theme exactly (no
golden PNGs, tolerance 0 — tokens are opaque).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtGui import QColor

from app.infrastructure.ui_prefs.config import UiPrefs, UiPrefsManager
from app.presentation.theme import ThemeRuntime
from app.presentation.theme.compiler import load_tokens, tokens_file_path
from app.presentation.views.game_launcher_dialog import GameLauncherDialog
from app.presentation.views.main_window import MainWindow


def canvas_color(theme: str) -> QColor:
    tokens = load_tokens(tokens_file_path())
    assert tokens is not None
    return QColor(tokens["color.bg.canvas"][theme])


def make_runtime(tmp_path, theme: str) -> ThemeRuntime:
    prefs = UiPrefsManager(tmp_path / "ui.json")
    if theme != "dark":  # dark is the fallback with no file at all
        prefs.save(UiPrefs(theme=theme))
    return ThemeRuntime(prefs=prefs, tokens_path=tokens_file_path())


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_launcher_chrome_pixel_is_canvas_token(qtbot, tmp_path, theme):
    runtime = make_runtime(tmp_path, theme)
    dlg = GameLauncherDialog(theme=runtime)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    image = dlg.chrome.grab().toImage()
    # Inside chrome's own 8px layout margin: background, never a child widget.
    assert image.pixelColor(4, 4) == canvas_color(theme)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_launcher_shows_no_os_palette_band_around_chrome(qtbot, tmp_path, theme):
    # Design D4: the chrome container covers the whole dialog layout. Any
    # default layout margin would show the OS palette as a frame — the
    # chrome-only pixel check above cannot see that strip.
    runtime = make_runtime(tmp_path, theme)
    dlg = GameLauncherDialog(theme=runtime)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    image = dlg.grab().toImage()
    for x, y in ((0, 0), (1, 1), (1, image.height() - 2), (image.width() - 2, 1)):
        assert image.pixelColor(x, y) == canvas_color(theme), (x, y)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_main_window_central_pixel_is_canvas_token(qtbot, tmp_path, theme):
    runtime = make_runtime(tmp_path, theme)
    window = MainWindow(
        timeline_vm=MagicMock(),
        detail_vm=MagicMock(),
        search_vm=MagicMock(),
        theme=runtime,
    )
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    central = window.centralWidget()
    image = central.grab().toImage()
    # Central layout margins are 4px: (2, 2) is bare chrome background.
    assert image.pixelColor(2, 2) == canvas_color(theme)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_main_window_top_left_pixel_is_themed(qtbot, tmp_path, theme):
    # The window's own strip (menu bar) must not leak the OS palette either.
    runtime = make_runtime(tmp_path, theme)
    window = MainWindow(
        timeline_vm=MagicMock(),
        detail_vm=MagicMock(),
        search_vm=MagicMock(),
        theme=runtime,
    )
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    image = window.grab().toImage()
    assert image.pixelColor(1, 1) == canvas_color(theme)
