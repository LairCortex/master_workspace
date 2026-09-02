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


def _rating_card(qtbot, runtime: ThemeRuntime):
    """DetailPanel showing one event whose only organization is rating 20."""
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
    panel.resize(400, 300)
    panel.show()
    qtbot.waitExposed(panel)
    return panel.org_list.itemWidget(panel.org_list.item(0))


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_rating_card_pixel_equals_token_composite(qtbot, tmp_path, theme):
    """Card pixel = the token tint (unchanged 80..220 alpha ramp → 220 at
    rating 20) over the surface token the card role paints underneath."""
    high = "#123456"
    card = _rating_card(qtbot, _rating_theme(tmp_path, theme, high))
    image = card.grab().toImage()
    pixel = image.pixelColor(card.width() - 8, card.height() - 4)
    expected = _composite_over(token_color("color.bg.surface", theme), QColor(high), 220)
    assert pixel == expected, (pixel.getRgb(), expected.getRgb())


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_rating_card_follows_token_change_without_screen_edits(qtbot, tmp_path, theme):
    """Changing ``color.rating.high`` must move the pixel with no code change."""
    from PySide6.QtTest import QTest

    red = _rating_card(qtbot, _rating_theme(tmp_path, theme, "#c00000"))
    QTest.qWait(0)
    red_image = red.grab().toImage()
    red_pixel = red_image.pixelColor(red.width() - 8, red.height() - 4)
    blue = _rating_card(qtbot, _rating_theme(tmp_path, theme, "#0000c0"))
    QTest.qWait(0)
    blue_image = blue.grab().toImage()
    blue_pixel = blue_image.pixelColor(blue.width() - 8, blue.height() - 4)
    assert red_pixel != blue_pixel


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_rating_card_keeps_its_frame_and_row_separation(qtbot, tmp_path, theme):
    """The card frame (border token) survives the rating tint: painting the
    whole ``rect()`` wiped it and left the related-list rows separated by
    nothing but the tint (W2b review — the card role's frame is the separator)."""
    from PySide6.QtTest import QTest

    border = token_color("color.border", theme)
    card = _rating_card(qtbot, _rating_theme(tmp_path, theme, "#c00000"))
    QTest.qWait(0)
    image = card.grab().toImage()
    mid_y = card.height() // 2
    assert image.pixelColor(0, mid_y) == border, "left card frame must survive"
    assert image.pixelColor(card.width() - 1, mid_y) == border, "right card frame must survive"
    assert image.pixelColor(card.width() // 2, 0) == border, "top card frame must survive"
    # the tint paints inside the frame, up to the last inset pixel
    assert image.pixelColor(3, mid_y) != border


# ── W2b: char-sheet editor chrome is themed, canvas pixels are not ──────────

@pytest.mark.parametrize("theme", ["dark", "light"])
def test_editor_chrome_is_tokens_and_canvas_keeps_its_own_colors(qtbot, tmp_path, theme):
    """Spec «Диалог character_sheet темизирован, канвас нет»."""
    from app.presentation.views.character_sheet.canvas import GUTTER_BACKGROUND
    from app.presentation.views.character_sheet.editor_dialog import (
        CharacterSheetEditorDialog,
    )

    runtime = make_runtime(tmp_path, theme)
    dlg = CharacterSheetEditorDialog(MagicMock(), 1, theme=runtime)
    qtbot.addWidget(dlg)
    dlg.resize(900, 600)
    dlg.show()
    qtbot.waitExposed(dlg)

    # Chrome: the save button paints the accent token of the current theme.
    button = dlg.save_button.grab().toImage()
    accent = token_color("color.accent", theme)
    assert any(
        button.pixelColor(x, button.height() // 2) == accent
        for x in range(button.width())
    ), "editor chrome must paint the accent token"

    # Canvas: the gutter pixel is the QPainter constant — identical in both
    # themes (the chrome sheet must not reach into the QGraphicsView scene).
    canvas = dlg.canvas.viewport().grab().toImage()
    gutter = QColor(GUTTER_BACKGROUND)
    gutter.setAlpha(255)
    assert canvas.pixelColor(canvas.width() // 2, canvas.height() - 4) == gutter


# ── W2b final acceptance (specs ui-theme): one accent token drives them all ─

@pytest.mark.parametrize("theme", ["dark", "light"])
def test_accent_token_change_moves_mention_ai_and_selection_together(qtbot, tmp_path, theme):
    """Changing ``color.accent`` in tokens alone recolors mentions, the AI
    active state, list selections and the «Показать» button — no screen edits
    (the «разделитель и выделение» / «упоминание и AI через токен» scenarios).

    The AI state is pinned by its marker and by a pixel, never by grepping a
    color substring out of a stylesheet (spec «Состояние AI-кнопки»)."""
    from PySide6.QtWidgets import QApplication, QLineEdit

    from app.presentation.views.ai_assist_button import AI_STATE_ACTIVE, AiAssistButton, ai_state_is
    from app.presentation.views.mention_text_edit import MentionTextEdit
    from app.presentation.views.world_snapshot_widget import WorldSnapshotWidget

    new_accent = "#0f8c3c"
    tokens = json.loads(tokens_file_path().read_text(encoding="utf-8"))
    tokens["color.accent"][theme] = new_accent
    tokens_path = tmp_path / "tokens.json"
    tokens_path.write_text(json.dumps(tokens), encoding="utf-8")
    runtime = make_runtime(tmp_path, theme, tokens_path=tokens_path)

    app = QApplication.instance()
    app.setStyleSheet("")
    runtime.attach_app(app)
    try:
        # 1) mention markup carries the new accent through the compiler.
        edit = MentionTextEdit(theme=runtime)
        qtbot.addWidget(edit)
        edit.setContent("@[A](character:1)")
        assert f"color:{new_accent}" in edit.toHtml()

        # 2) AI-active: the marker says active, the pixel says the accent
        #    derivative (accent at 0.25 over the chrome canvas it sits on).
        chrome = QWidget()
        chrome.setObjectName("accentChrome")
        chrome.resize(240, 80)
        qtbot.addWidget(chrome)
        row = QHBoxLayout(chrome)
        field = QLineEdit()
        ai = AiAssistButton(field, "character", "backstory", "П", parent=chrome, theme=runtime)
        row.addWidget(field)
        row.addWidget(ai)
        attach_theme(chrome, runtime)
        runtime.apply()
        ai.update_llm_state("ready", True)
        assert ai_state_is(ai, AI_STATE_ACTIVE)
        chrome.show()
        qtbot.waitExposed(chrome)
        image, scale = _grab_scaled(chrome)
        # QSS "rgba(…, 0.25)" reaches Qt as an 8-bit 0.25 * 255 alpha.
        expected = _composite_over(canvas_color(theme), QColor(new_accent), int(0.25 * 255))
        area = ai.geometry()
        hits = [
            (x, y)
            for y in range(int(area.top() * scale), min(int(area.bottom() * scale) + 1, image.height()))
            for x in range(int(area.left() * scale), min(int(area.right() * scale) + 1, image.width()))
            if image.pixelColor(x, y) == expected
        ]
        assert hits, (
            "AI-active must paint the accent derivative of the token",
            expected.getRgb(),
        )

        # 3) «Показать» (chrome button) follows the accent token. List selections
        #    are the same QSS accent (popup-surface test above pins the pixel).
        widget = WorldSnapshotWidget(theme=runtime)
        widget.resize(420, 320)
        qtbot.addWidget(widget)
        widget.show()
        qtbot.waitExposed(widget)
        image = widget.show_button.grab().toImage()
        assert image.pixelColor(image.width() - 3, image.height() // 2) == QColor(new_accent)
    finally:
        # The popup sheet of a personalized token set must not survive the test:
        # it lives on the QApplication and would paint every later test with an
        # accent nobody shipped. Cleaned here and not by a global autouse
        # fixture: clearing the application sheet makes the next push different
        # from what the app carries, so every apply() re-polishes the whole
        # process tree — the ×6 offscreen slowdown W2a removed.
        app.setStyleSheet("")
