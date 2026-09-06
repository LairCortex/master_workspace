"""Pixel-precise and structural checks for the token-themed chrome.

Two probe shapes are used, both with zero tolerance:

* ``widget.grab()`` for widgets that paint their own pixels — a bare pixel must
  equal the exact token color (or the QPainter composite of a token color with
  an alpha over its backdrop token, so translucent states are pinned by pixels
  instead of grepping a stylesheet for a color substring); coordinates coming
  from Qt (item rects, child offsets) are logical while ``grab()`` renders at
  device pixels (dpr 2 on Retina) — ``_grab_scaled`` returns the image together
  with the factor to scale them by;
* dynamic properties / Qt properties for states a screenshot cannot attribute
  to a rule (the ``aiState`` marker, the off-skin contract of D7).

No golden PNGs: tokens are opaque, so a golden file would only hide drift.
"""
from __future__ import annotations

import datetime
from pathlib import Path
import json
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from app.infrastructure.ui_prefs.config import UiPrefs, UiPrefsManager
from app.presentation.theme import ThemeRuntime
from app.presentation.theme.catalog import attach_theme
from app.presentation.theme.compiler import load_tokens, tokens_file_path
from app.presentation.views.game_launcher_dialog import GameLauncherDialog
from app.presentation.views.main_window import MainWindow


def canvas_color(theme: str) -> QColor:
    tokens = load_tokens(tokens_file_path())
    assert tokens is not None
    return QColor(tokens["color.bg.canvas"][theme])


def make_runtime(tmp_path, theme: str, tokens_path=None) -> ThemeRuntime:
    prefs = UiPrefsManager(tmp_path / "ui.json")
    if theme != "dark":  # dark is the fallback with no file at all
        prefs.save(UiPrefs(theme=theme))
    return ThemeRuntime(prefs=prefs, tokens_path=tokens_path or tokens_file_path())


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


def _grab_scaled(widget) -> tuple[QImage, float]:
    """Grab ``widget`` and report the logical→device pixel factor."""
    image = widget.grab().toImage()
    return image, image.width() / max(widget.width(), 1)


def _composite_over(backdrop: QColor, color: QColor, alpha: int) -> QColor:
    """``color`` with ``alpha`` over an opaque ``backdrop`` (Qt's own blend)."""
    canvas = QImage(8, 8, QImage.Format.Format_RGB32)
    canvas.fill(backdrop)
    painter = QPainter(canvas)
    tint = QColor(color)
    tint.setAlpha(alpha)
    painter.fillRect(canvas.rect(), tint)
    painter.end()
    return canvas.pixelColor(4, 4)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_launcher_shows_no_os_palette_band_around_qml_island(qtbot, tmp_path, theme):
    # spec ui-theme «Лаунчер без полосы палитры ОС» (Q1): the content is a
    # QQuickWidget island skinned by the palette for QML. The wrapper pins
    # the dialog layout margins to 0, so the *dialog's own edge pixels* must
    # already be the island background (color.bg.surface) — a leftover
    # layout margin or widgets chrome would expose the OS palette as a
    # frame strip (and a QSS leak would paint canvas, not surface).
    runtime = make_runtime(tmp_path, theme)
    dlg = GameLauncherDialog(theme=runtime)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    image = dlg.grab().toImage()
    surface = token_color("color.bg.surface", theme)
    assert surface != canvas_color(theme)  # the two checks below must differ
    for x, y in ((0, 0), (1, 1), (1, image.height() - 2), (image.width() - 2, 1)):
        assert image.pixelColor(x, y) == surface, (x, y)


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

@pytest.mark.parametrize("theme", ["dark", "light"])
def test_mention_popup_surface_and_accent_selection(qtbot, tmp_path, theme):
    # Pilot 4.3: the popup list gets its skin from the app-wide popup sheet.
    from PySide6.QtWidgets import QApplication

    from app.presentation.views.mention_popup import _MentionPopup

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
        # grab() renders at device pixels (dpr 2 on Retina) while visualItemRect
        # is logical — probe the image in one coordinate space, or the "below
        # the item" point silently lands inside the selection when fonts grow.
        scale = image.width() / max(popup._list.width(), 1)  # noqa: SLF001
        accent = token_color("color.accent", theme)
        surface = token_color("color.bg.surface", theme)
        center_x = min(int(rect.center().x() * scale), image.width() - 1)
        assert any(
            image.pixelColor(center_x, y) == accent
            for y in range(max(int(rect.top() * scale), 0), int(rect.bottom() * scale))
        ), "selected item must paint the accent token"
        # The selected item's text paints accent.fg over the accent fill —
        # both halves of the selection color come from tokens.
        selected_crop = image.copy(
            0, max(int(rect.top() * scale), 0),
            image.width(), max(int((rect.bottom() - rect.top()) * scale), 1),
        )
        assert _contains_pixel(selected_crop, token_color("color.accent.fg", theme))
        below = int((rect.bottom() + 10) * scale)
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


# ── W2b: rating card endpoints come from theme tokens (detail_panel) ────────

def _rating_theme(tmp_path, theme: str, high_hex: str) -> ThemeRuntime:
    """Runtime over a copied token file with ``color.rating.high`` overridden."""
    tokens = json.loads(tokens_file_path().read_text(encoding="utf-8"))
    tokens["color.rating.high"][theme] = high_hex
    tokens_path = tmp_path / "tokens.json"
    tokens_path.write_text(json.dumps(tokens), encoding="utf-8")
    return make_runtime(tmp_path, theme, tokens_path=tokens_path)


def _detail_rating_tint(qtbot, runtime: ThemeRuntime):
    """Render-ready tint published by the detail panel's Python model."""
    from types import SimpleNamespace

    from app.presentation.views.detail_panel import DetailPanel

    class _VM:  # DetailPanel only stores the view model
        pass

    panel = DetailPanel(_VM(), theme=runtime)
    qtbot.addWidget(panel)
    entity = SimpleNamespace(
        id=1, name="Герой", rating=20, description=None, personality=None, tasks=None,
    )
    event = SimpleNamespace(
        id=1, name="С", start_date=datetime.date(2020, 1, 1), end_date=None,
        organizations=[entity], characters=[], items=[], locations=[],
    )
    panel.show_event(event)
    model = panel.vm.organizations
    return QColor(model.data(model.index(0, 0), model.RatingTintRole))


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_detail_rating_role_equals_token_tint(qtbot, tmp_path, theme):
    high = "#123456"
    tint = _detail_rating_tint(qtbot, _rating_theme(tmp_path, theme, high))
    assert tint == QColor(0x12, 0x34, 0x56, 220)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_detail_rating_role_follows_token_change(qtbot, tmp_path, theme):
    red = _detail_rating_tint(qtbot, _rating_theme(tmp_path, theme, "#c00000"))
    blue = _detail_rating_tint(qtbot, _rating_theme(tmp_path, theme, "#0000c0"))
    assert red != blue


def test_detail_root_delegates_card_chrome_to_library():
    from app.presentation.qml.engine import QML_IMPORT_PATH

    source = (Path(QML_IMPORT_PATH) / "DetailPanelRoot.qml").read_text(encoding="utf-8")
    assert "ThemeRatingCard {" in source
    assert "rating_to_color" not in source


# ── W2b (re-pinned by Q3b 3.4): char-sheet chrome is themed, the sheet
# scene keeps its own colors — the widgets canvas being gone, the scene half
# is pinned from the island's unthemed constants (D8: paper/gutter are fixed
# content colors in SheetCanvas.qml, off the token skin by design); the QML
# pixel acceptance lands with the group-4.3 island grab suite.

@pytest.mark.parametrize("theme", ["dark", "light"])
def test_editor_chrome_is_tokens_and_canvas_keeps_its_own_colors(qtbot, tmp_path, theme):
    """Spec «Диалог character_sheet темизирован, канвас нет»."""
    import re

    from app.presentation.qml.engine import QML_IMPORT_PATH
    from app.presentation.views.character_sheet.editor_dialog import (
        CharacterSheetEditorDialog,
    )

    runtime = make_runtime(tmp_path, theme)
    dlg = CharacterSheetEditorDialog(MagicMock(), 1, theme=runtime)
    qtbot.addWidget(dlg)
    dlg.resize(900, 600)
    dlg.show()
    qtbot.waitExposed(dlg)

    # Chrome: the island loads Ready on this dialog's token bridge (its root
    # exists and the scene was built; the pixel probe «токен = пиксель» for
    # islands is part of the 4.3 island-grab acceptance).
    assert dlg._root is not None

    # Scene: the gutter constant is a fixed qml value with no theme branch —
    # identical for both themes (the chrome skin never reaches the paper
    # layer); its pixels are pinned by test_sheet_canvas_island's paper pass.
    qml = (Path(QML_IMPORT_PATH) / "SheetCanvas.qml").read_text(encoding="utf-8")
    m = re.search(r'gutterColor:\s*"(#[0-9a-fA-F]{6})"', qml)
    assert m is not None, "SheetCanvas.qml must carry the gutter constant"
    assert QColor(m.group(1)).isValid()
