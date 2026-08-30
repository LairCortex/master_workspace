"""E2E pixel checks for the token-themed chrome (W1 acceptance D9).

Offscreen Qt: show + waitExposed + grab(); a bare chrome pixel must equal
the opaque hex of ``color.bg.canvas`` for the current theme exactly (no
golden PNGs, tolerance 0 — tokens are opaque).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel

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


# ── W2a pilots (add-widget-catalog-chrome-mechanics-w2a) ───────────────────

def token_color(key: str, theme: str) -> QColor:
    tokens = load_tokens(tokens_file_path())
    assert tokens is not None
    return QColor(tokens[key][theme])


def _contains_pixel(image, color: QColor) -> bool:
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y) == color:
                return True
    return False


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_month_dialog_hint_is_muted_token_and_edge_is_canvas(qtbot, tmp_path, theme):
    # Pilot 4.1: hint through the catalog factory (no #888), chrome attaches
    # to the dialog edge (no OS palette band).
    from PySide6.QtWidgets import QLineEdit

    from app.presentation.views.month_settings_dialog import MonthSettingsDialog

    runtime = make_runtime(tmp_path, theme)
    dlg = MonthSettingsDialog(theme=runtime)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)

    hint_label = next(w for w in dlg.chrome.findChildren(QLabel) if "стандартного" in w.text())
    assert _contains_pixel(hint_label.grab().toImage(), token_color("color.fg.muted", theme))
    # Visual parity with the pre-catalog pilot: the hint kept its 6px bottom
    # gap (restored as layout spacing), so the first field is not cramped.
    first_field = dlg.findChildren(QLineEdit)[0]
    assert first_field.y() - hint_label.geometry().bottom() - 1 >= 12

    edge = dlg.grab().toImage()
    for x, y in ((1, 1), (1, edge.height() - 2), (edge.width() - 2, 1)):
        assert edge.pixelColor(x, y) == canvas_color(theme), (x, y)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_month_dialog_fields_take_surface_token(qtbot, tmp_path, theme):
    # The field role paints from tokens: a line edit pixel equals surface
    # exactly, which the default OS widgets in this dialog do not match.
    from PySide6.QtWidgets import QLineEdit

    from app.presentation.views.month_settings_dialog import MonthSettingsDialog

    runtime = make_runtime(tmp_path, theme)
    dlg = MonthSettingsDialog(theme=runtime)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    edit = dlg.findChild(QLineEdit)
    image = edit.grab().toImage()
    surface = token_color("color.bg.surface", theme)
    probe = (image.pixelColor(image.width() - 3, image.height() // 2),
             image.pixelColor(20, image.height() // 2))
    assert any(px == surface for px in probe)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_world_snapshot_show_button_is_accent_token(qtbot, tmp_path, theme):
    # Pilot 4.2: «Показать» is a plain chrome button — accent, not #2d5a88.
    from app.presentation.views.world_snapshot_widget import WorldSnapshotWidget

    runtime = make_runtime(tmp_path, theme)
    widget = WorldSnapshotWidget(theme=runtime)
    widget.resize(420, 320)
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    image = widget.show_button.grab().toImage()
    assert image.pixelColor(image.width() - 3, image.height() // 2) == token_color(
        "color.accent", theme
    )


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_world_snapshot_title_is_primary_token_and_lg_keg(qtbot, tmp_path, theme):
    from app.presentation.views.world_snapshot_widget import WorldSnapshotWidget

    runtime = make_runtime(tmp_path, theme)
    widget = WorldSnapshotWidget(theme=runtime)
    widget.resize(420, 320)
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    label = widget.title_label
    label.ensurePolished()
    assert label.font().pixelSize() == int(
        load_tokens(tokens_file_path())["font.size.lg"][theme][:-2]
    )
    assert label.font().bold()
    assert _contains_pixel(label.grab().toImage(), token_color("color.fg.primary", theme))


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_mention_popup_surface_and_accent_selection(qtbot, tmp_path, theme):
    # Pilot 4.3: the popup list gets its skin from the app-wide popup sheet.
    from PySide6.QtWidgets import QApplication

    from app.presentation.views.mention_text_edit import _MentionPopup

    runtime = make_runtime(tmp_path, theme)
    app = QApplication.instance()
    app.setStyleSheet("")
    runtime.attach_app(app)
    runtime.apply()
    try:
        popup = _MentionPopup()
        qtbot.addWidget(popup)
        popup.show_results(
            [{"type": "character", "id": 1, "name": "Персонаж один"},
             {"type": "location", "id": 2, "name": "Локация две"}],
            popup.mapToGlobal(popup.rect().topLeft()),
        )
        popup.resize(260, 200)
        qtbot.waitExposed(popup)
        image = popup._list.grab().toImage()  # noqa: SLF001 — white-box pixel probe
        rect = popup._list.visualItemRect(popup._list.currentItem())  # noqa: SLF001
        accent = token_color("color.accent", theme)
        surface = token_color("color.bg.surface", theme)
        assert any(
            image.pixelColor(rect.center().x(), y) == accent
            for y in range(max(rect.top(), 0), rect.bottom())
        ), "selected item must paint the accent token"
        below = rect.bottom() + 20
        assert image.pixelColor(image.width() // 2, min(below, image.height() - 2)) == surface
        assert popup._list.styleSheet() == ""  # noqa: SLF001 — no inline table anymore
        # The popup container itself (not just the list) paints the surface:
        # forcing a bare container strip must not reveal the OS palette.
        assert popup.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        popup._list.setMaximumHeight(40)  # noqa: SLF001 — bare strip below the list
        popup.resize(260, 120)
        qtbot.wait(10)
        container = popup.grab().toImage()
        assert container.pixelColor(container.width() // 2, container.height() - 2) == surface
    finally:
        app.setStyleSheet("")
