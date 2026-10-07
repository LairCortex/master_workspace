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

from app.infrastructure.ui_prefs.config import UiPrefs, UiPrefsManager
from app.presentation.theme import ThemeRuntime
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


# ── NRI-0018 (task 1.1): the library's square glyph button is token chrome —
# re-computed pixel acceptance for the new ThemeIconButton geometry (spec
# qml-components «Квадратная мелкая кнопка действия библиотеки»): the chip is
# the plain ThemeButton skin family (border hairline + canvas fill, the same
# tokens the plain text button paints), the glyph is centered in the square
# from fg.primary, and — the point of the change — the chip is exactly the
# 32×32 gauge with zero usage-site sizing.

_ICON_BUTTON_PROBE = """
import QtQuick
import nri.components

Item {
    objectName: "iconProbeRoot"
    implicitWidth: 120
    implicitHeight: 80

    // The surround paints color.danger — a token no chip surface uses, so
    // every chip pixel below is painted, not seen through (the gallery's
    // non-vacuity convention).
    Rectangle {
        anchors.fill: parent
        color: (typeof islandPalette !== "undefined" && islandPalette !== null
                && islandPalette.tokens)
            ? islandPalette.tokens["color.danger"] : "lightgray"
    }
    ThemeIconButton {
        objectName: "probeGlyph"
        x: 20; y: 20
        text: "✕"
        Accessible.name: "Пиксельная приёмка"
    }
}
"""


def _load_icon_probe(qtbot, tmp_path, theme):
    from PySide6.QtCore import QUrl
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtQuickWidgets import QQuickWidget

    from app.presentation.qml.engine import setup_qml_shell
    from app.presentation.theme.qml_palette import QmlPalette

    runtime = make_runtime(tmp_path, theme)
    if QQuickStyle.name() != "Basic":
        QQuickStyle.setStyle("Basic")
    scene = tmp_path / "icon_probe.qml"
    scene.write_text(_ICON_BUTTON_PROBE, encoding="utf-8")
    from PySide6.QtWidgets import QApplication

    engine = setup_qml_shell(QApplication.instance(), runtime)
    widget = QQuickWidget(engine, None)
    qtbot.addWidget(widget)
    widget.resize(120, 80)
    palette = QmlPalette(runtime)
    palette.setParent(widget)
    widget.rootContext().setContextProperty("islandPalette", palette)
    widget.setSource(QUrl.fromLocalFile(str(scene)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    return widget


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_icon_button_square_is_token_chip_in_both_themes(qtbot, tmp_path, theme):
    from PySide6.QtGui import QImage

    from tests.presentation.qml_helpers import find_item

    widget = _load_icon_probe(qtbot, tmp_path, theme)
    image = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    scale = image.width() / max(widget.width(), 1)
    glyph = find_item(widget, "probeGlyph")

    # The gauge itself: 32×32 on the live item, not just as a declared value.
    assert (glyph.width(), glyph.height()) == (32, 32)
    assert (glyph.implicitWidth(), glyph.implicitHeight()) == (32, 32)

    def point_rgb(px: float, py: float):
        color = image.pixelColor(int(px * scale), int(py * scale))
        return (color.red(), color.green(), color.blue())

    def token_rgb(key: str) -> tuple[int, int, int]:
        color = token_color(key, theme)
        return (color.red(), color.green(), color.blue())

    # The chip paints the plain-theme-button skin of its theme (no fill could
    # fake the hairline: the probe background holds no border/canvas color).
    assert point_rgb(20, 36) == token_rgb("color.border")          # left edge
    assert point_rgb(24, 27) == token_rgb("color.bg.canvas")       # fill band
    # The glyph is centered and reads in fg.primary: an exact token pixel sits
    # in the middle 16×16 of the chip (the item's x,y is 20,20, the center is
    # 36,36).
    fg = token_rgb("color.fg.primary")
    assert any(
        point_rgb(x, y) == fg
        for x in range(28, 44)
        for y in range(28, 44)
    ), "центр глифа обязан краситься токеном fg.primary"


# ── NRI-0018 (task 2.3): the checkbox optical centering and the row strip —
# re-captured pixel acceptance for ThemeCheckBox (spec qml-components
# «Чекбокс ставит индикатор и подпись на один оптический центр», ui-layout-grid
# «Контролы одного ряда стоят на единой полосе высот»). The geometry suite
# (tests/presentation/test_theme_checkbox_optical.py) pins the model; this
# probe pins the PAINT: the indicator band actually on screen is the 16-row box
# at the optical place (its painted top agrees with the item's y), the painted
# center meets the caption ink center (FontMetrics.boundingRect("Х") under the
# label's font) within one raster, and the text button's painted band — the
# strip the checkbox joins through its implicit height — is that same 32 px.

_CHECKBOX_PROBE = """
import QtQuick
import nri.components

Item {
    objectName: "checkboxProbeRoot"
    implicitWidth: 140
    implicitHeight: 140

    // The surround paints color.danger: a token no checkbox or button surface
    // uses (the gallery's non-vacuity convention), so every band pixel of the
    // runs below is painted, not seen through.
    Rectangle {
        anchors.fill: parent
        color: (typeof islandPalette !== "undefined" && islandPalette !== null
                && islandPalette.tokens)
            ? islandPalette.tokens["color.danger"] : "lightgray"
    }
    // The pinning caption «Х» — one glyph, the very one whose ink center the
    // pin computes.
    ThemeCheckBox {
        objectName: "probeCheck"
        text: "Х"
        x: 12; y: 20
    }
    ThemeButton {
        objectName: "probeButton"
        text: "btn"
        x: 12; y: 80
    }
}
"""


def _load_checkbox_probe(qtbot, tmp_path, theme):
    from PySide6.QtCore import QUrl
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtQuickWidgets import QQuickWidget
    from PySide6.QtWidgets import QApplication

    from app.presentation.qml.engine import setup_qml_shell
    from app.presentation.theme.qml_palette import QmlPalette

    runtime = make_runtime(tmp_path, theme)
    if QQuickStyle.name() != "Basic":
        QQuickStyle.setStyle("Basic")
    scene = tmp_path / "checkbox_probe.qml"
    scene.write_text(_CHECKBOX_PROBE, encoding="utf-8")
    engine = setup_qml_shell(QApplication.instance(), runtime)
    widget = QQuickWidget(engine, None)
    qtbot.addWidget(widget)
    widget.resize(140, 140)
    palette = QmlPalette(runtime)
    palette.setParent(widget)
    widget.rootContext().setContextProperty("islandPalette", palette)
    widget.setSource(QUrl.fromLocalFile(str(scene)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    return widget


def _vertical_runs(image, column: int, colors: set,
                   top_row: int = 0, bottom_row: int | None = None) -> list[tuple[int, int]]:
    """Maximal device-row runs in ``column`` whose pixel color lies in ``colors``.

    The row window keeps a probe's run away from other stacked widgets' chips
    that share the column (the button below the checkbox would otherwise win
    the longest-run pick).
    """
    runs: list[tuple[int, int]] = []
    start = None
    for row in range(top_row, image.height() if bottom_row is None else bottom_row):
        c = image.pixelColor(column, row)
        inside = (c.red(), c.green(), c.blue()) in colors
        if inside and start is None:
            start = row
        elif not inside and start is not None:
            runs.append((start, row - 1))
            start = None
    if start is not None:
        runs.append((start, (image.height() if bottom_row is None else bottom_row) - 1))
    return runs


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_checkbox_indicator_and_button_band_are_painted_on_the_row(qtbot, tmp_path, theme):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QFontMetricsF, QImage

    from tests.presentation.qml_helpers import find_item

    widget = _load_checkbox_probe(qtbot, tmp_path, theme)
    image = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    scale = image.width() / max(widget.width(), 1)

    canvas = token_color("color.bg.canvas", theme)
    border = token_color("color.border", theme)
    danger = token_color("color.danger", theme)
    assert canvas != danger and border != danger  # the runs below stay non-vacuous

    chk = find_item(widget, "probeCheck")
    button = find_item(widget, "probeButton")
    box = chk.property("indicator")
    assert box is not None

    # ── the painted indicator: the 16-row box, at the modeled place. The scan
    # stops at the button's scene y so the chip below (same columns) cannot win
    # the longest-run pick.
    col = int(box.mapToScene(QPointF(box.width() / 2, 0)).x() * scale)
    band_rows_end = int(round(button.mapToScene(QPointF(0, 0)).y() * scale))
    band = {(canvas.red(), canvas.green(), canvas.blue()),
            (border.red(), border.green(), border.blue())}
    runs = _vertical_runs(image, col, band, bottom_row=band_rows_end)
    assert runs, "индикатор обязан краситься токенами"
    top, bottom = max(runs, key=lambda r: r[1] - r[0])
    painted_span = (bottom - top + 1) / scale
    assert painted_span == pytest.approx(box.height(), abs=1)
    assert abs(top / scale - box.mapToScene(QPointF(0, 0)).y()) <= 1
    painted_center = (top + bottom + 1) / (2 * scale)

    # ── painted center = the caption's ink center, to one raster (Д2).
    label = chk.property("contentItem")
    assert label is not None
    fm = QFontMetricsF(label.property("font"))
    br = fm.boundingRect("Х")
    line_top = (label.mapToScene(QPointF(0, 0)).y()
                + (label.height() - label.implicitHeight()) / 2)
    ink_center = line_top + fm.ascent() + br.top() + br.height() / 2
    assert abs(round(painted_center) - round(ink_center)) <= 1, (
        f"нарисованный центр {painted_center} vs центр чернил {ink_center}"
    )

    # ── the row band, painted: the text button's chip is the gauge (32) the
    # checkbox's implicit strip now equals — one row in every island action row.
    # The probe column sits in the button's left padding band beyond the round
    # corner's flat edge: no glyph there, and no corner antialiasing above it.
    btn_col = int((button.mapToScene(QPointF(0, 0)).x() + 7) * scale)
    chip_top, chip_bottom = max(
        _vertical_runs(image, btn_col, band), key=lambda r: r[1] - r[0]
    )
    chip_span = (chip_bottom - chip_top + 1) / scale
    assert chip_span == pytest.approx(32.0, abs=1)
    assert round(chk.implicitHeight()) == round(chip_span)


# ── QA 2026-10-01: the disabled chrome button drops to the canvas + muted ────


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_disabled_chrome_button_paints_canvas_with_muted_caption(qtbot, tmp_path, theme):
    """Pixel acceptance for the compiled chrome sheet (measured defect: the
    disabled ``QPushButton`` kept the accent fill under its muted caption —
    1.10:1 dark / 1.13:1 light, unreadable on every widget window: wizard
    «Далее», table panel «Остановить», xlsx import, LLM setup). The disabled
    button now paints the canvas token, its caption the muted token, its
    hairline the untouched border token, and no accent pixel survives on it;
    the WCAG floor is recomputed from the very tokens the pixels answered.
    After the same-day face split the ENABLED plain button wears the very
    same canvas fill and border hairline (its caption the primary ink) — the
    non-vacuity below pins that the sheet, not the OS style, painted it."""
    from PySide6.QtWidgets import QPushButton, QWidget

    from tests.presentation.test_theme_compile import _contrast_ratio

    runtime = make_runtime(tmp_path, theme)
    root = QWidget()
    qtbot.addWidget(root)
    root.setProperty("uiRole", "chrome")
    root.setStyleSheet(runtime.qss())  # the exact sheet apply() pushes to roots
    enabled = QPushButton("Вкл", root)
    enabled.setGeometry(6, 6, 96, 40)
    button = QPushButton("Далее", root)
    button.setGeometry(110, 6, 96, 40)
    button.setEnabled(False)
    root.resize(212, 52)
    root.show()
    qtbot.waitExposed(root)

    canvas = token_color("color.bg.canvas", theme)
    muted = token_color("color.fg.muted", theme)
    accent = token_color("color.accent", theme)
    border = token_color("color.border", theme)
    fg = token_color("color.fg.primary", theme)
    assert canvas != accent  # the enabled/disabled claims below must differ

    # Non-vacuity: the ENABLED sibling carries the sheet's plain face — the
    # canvas fill token AND the border-token hairline.  A root that never got
    # the sheet would show the OS button box, which paints neither.
    enabled_image = enabled.grab().toImage()
    enabled_scale = enabled_image.width() / max(enabled.width(), 1)
    assert enabled_image.pixelColor(
        int(4 * enabled_scale), enabled_image.height() // 2
    ) == canvas, theme
    assert enabled_image.pixelColor(0, enabled_image.height() // 2) == border, theme
    assert _contains_pixel(enabled_image, fg), theme

    image = button.grab().toImage()
    scale = image.width() / max(button.width(), 1)
    mid_y = image.height() // 2
    # The fill band (padding starts after the 1 px border, the caption «Далее»
    # is far from the left padding strip): the canvas token, not the accent.
    assert image.pixelColor(int(4 * scale), mid_y) == canvas, theme
    # The hairline keeps the base border token — the disabled rule re-declares
    # nothing above, so the frame survives untouched.
    assert image.pixelColor(0, mid_y) == border, theme
    # Neither channel of the accent token exists between muted and canvas, so
    # even one accent pixel anywhere on the button would betray the old fill.
    assert not _contains_pixel(image, accent), theme
    # The caption ink is the muted token itself…
    assert _contains_pixel(image, muted), theme
    # …and the pair the eye actually gets clears the WCAG AA floor.
    ratio = _contrast_ratio(
        (muted.red(), muted.green(), muted.blue()),
        (canvas.red(), canvas.green(), canvas.blue()),
    )
    assert ratio >= 4.5, (theme, ratio)


# ── QA 2026-10-01: a disabled chrome button greys its Lucide glyph with the caption ─

def _ink_line_t(pixel: QColor, base: QColor, ink: QColor, tol: int = 2):
    """Coverage ``t`` of an ``ink``-colored glyph over a ``base`` fill that
    produced ``pixel`` (anti-aliasing only varies alpha, so the channels stay
    in lockstep), or ``None`` when the pixel is no such blend.  Border hairline
    and corner AA, and Qt's palette-based automatic disabled pixmap tint, all
    land off the line — the discriminating power of the checks below."""
    ts = []
    for channel in (QColor.red, QColor.green, QColor.blue):
        b, i, p = channel(base), channel(ink), channel(pixel)
        if i == b:
            if abs(p - b) > tol:
                return None
            continue
        t = (p - b) / (i - b)
        if not -0.03 <= t <= 1.03:
            return None
        ts.append(t)
    return None if max(ts) - min(ts) > 0.08 else sum(ts) / len(ts)


def _ink_column_runs(image, base: QColor, ink: QColor, inset: int):
    """Column runs inside ``inset`` whose every non-base pixel lies on the
    base→ink line; only runs carrying at least one exact-``ink`` pixel qualify
    (border-edge AA never reaches full coverage).  Returns
    ``[(x0, x1, exact_ink_pixels), ...]`` — one run per glyph/caption cluster."""
    columns = set()
    for x in range(inset, image.width() - inset):
        for y in range(inset, image.height() - inset):
            pixel = image.pixelColor(x, y)
            if pixel == base:
                continue
            if pixel == ink or (
                (t := _ink_line_t(pixel, base, ink)) is not None and t >= 0.5
            ):
                columns.add(x)
                break
    runs = []
    for x in sorted(columns):
        if runs and x <= runs[-1][1] + 1:
            runs[-1][1] = x
        else:
            runs.append([x, x])
    qualified = []
    for x0, x1 in runs:
        exact = 0
        offenders = 0
        for x in range(x0, x1 + 1):
            for y in range(inset, image.height() - inset):
                pixel = image.pixelColor(x, y)
                if pixel == ink:
                    exact += 1
                elif pixel != base and _ink_line_t(pixel, base, ink) is None:
                    offenders += 1
        assert offenders == 0, (
            f"columns {x0}-{x1} carry {offenders} pixel(s) off the "
            f"{base.name()}→{ink.name()} ink line (Qt auto-tint or border bleed?)"
        )
        if exact:
            qualified.append((x0, x1, exact))
    return qualified


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_disabled_chrome_icon_button_glyph_follows_the_muted_caption(
    qtbot, tmp_path, theme, monkeypatch
):
    """Whole-button pixel pin for the Lucide disabled mode (F2, the surfaces
    behind «Остановить»/«Выгнать» and the wizard's rule-row buttons after the
    2026-10-01 face split).  The QColor-level pin in
    tests/presentation/test_lucide_icons.py only proves
    ``QIcon::pixmap(Disabled)``; the sibling text-button pin only proves
    fill+caption.  This one drives the real ``QPushButton`` draw route under
    the compiled chrome sheet and demands the engine's Disabled ink actually
    reaches the pixels: the disabled plain button fills with the canvas token
    while its glyph AND caption pixels all lie on the single canvas→muted
    line (Qt's automatic disabled tint, audit glyph (205,173,128) vs caption
    (154,151,143), is off that line), the enabled plain sibling pairs the same
    canvas fill with an fg.primary glyph, and the primary-role sibling
    («Открыть стол») is the one that keeps the accent fill with an accent.fg
    glyph.  The measured muted/canvas contrast clears WCAG AA from the very
    tokens the pixels answered."""
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QPushButton, QWidget

    from app.presentation.views import lucide_icons
    from app.presentation.views.lucide_icons import ACCENT_INK_TOKEN_KEY, lucide_icon
    from tests.presentation.test_theme_compile import _contrast_ratio

    runtime = make_runtime(tmp_path, theme)
    monkeypatch.setattr(lucide_icons, "get_default_theme", lambda: runtime)
    root = QWidget()
    qtbot.addWidget(root)
    root.setProperty("uiRole", "chrome")
    root.setStyleSheet(runtime.qss())  # the exact sheet apply() pushes to roots

    def icon_button(x: int, *, enabled: bool, primary: bool = False) -> QPushButton:
        # The production surfaces: icon + caption, «Остановить» exactly as the
        # table-host panel builds its plain disabled-by-default stop button,
        # and «Открыть стол» as the one primary-role button of the row.
        caption = "Открыть стол" if primary else "Остановить"
        button = QPushButton(caption, root)
        # Platform-neutral rasterization: an offscreen grab renders text with
        # whatever AA the platform's fontconfig default picks — Ubuntu CI
        # defaults to LCD subpixel, whose RGB chromatic fringes (#aadaa7,
        # #1e2a68, …) land off every base→ink line, while macOS antialias is
        # grayscale. The pin is about the ink COLOUR (engine Disabled token vs
        # Qt auto-tint), not the AA mode, so both platforms render on the same
        # grayscale footing; the line checks below stay strict on any OS.
        font = button.font()
        font.setStyleStrategy(font.styleStrategy() | QFont.NoSubpixelAntialias)
        button.setFont(font)
        if primary:
            button.setProperty("uiRole", "primary")
        button.setIcon(
            lucide_icon(
                "play" if primary else "circle-stop",
                ink_token=ACCENT_INK_TOKEN_KEY if primary else "color.fg.primary",
            )
        )
        button.setGeometry(x, 6, 150, 44)
        button.setEnabled(enabled)
        return button

    enabled = icon_button(6, enabled=True)
    disabled = icon_button(162, enabled=False)
    primary = icon_button(318, enabled=True, primary=True)
    root.resize(474, 56)
    root.show()
    qtbot.waitExposed(root)

    canvas = token_color("color.bg.canvas", theme)
    muted = token_color("color.fg.muted", theme)
    accent = token_color("color.accent", theme)
    accent_fg = token_color("color.accent.fg", theme)
    fg = token_color("color.fg.primary", theme)
    inset = 8  # clears the 1 px hairline and the 6 px radius.sm corner curve

    # ── non-vacuity: the enabled plain sibling is canvas fill + fg.primary
    # glyph (the sheet's ordinary face, not the OS box).
    enabled_image = enabled.grab().toImage()
    scale = enabled_image.width() / max(enabled.width(), 1)
    assert enabled_image.pixelColor(
        int(4 * scale), enabled_image.height() // 2
    ) == canvas, theme
    # The glyph is the leftmost cluster whose ink reaches full coverage; its
    # width is the 16 px icon box, and every pixel of it (and of every caption
    # cluster) must ride the canvas→fg.primary line — _ink_column_runs asserts
    # that while grouping.
    enabled_runs = _ink_column_runs(enabled_image, canvas, fg, int(inset * scale))
    assert enabled_runs, (theme, "no fg.primary ink cluster on the enabled button")
    en_glyph_x0, en_glyph_x1, en_glyph_exact = enabled_runs[0]
    assert 12 * scale <= en_glyph_x1 - en_glyph_x0 + 1 <= 20 * scale, (
        theme,
        en_glyph_x0,
        en_glyph_x1,
    )
    assert en_glyph_exact >= 10, (theme, en_glyph_exact)
    assert not _contains_pixel(enabled_image, muted), (
        theme, "the enabled glyph must not speak the disabled ink"
    )

    # ── the primary sibling is the one that keeps the accent fill, and its
    # glyph speaks accent.fg (the ink its caption is painted with).
    primary_image = primary.grab().toImage()
    p_scale = primary_image.width() / max(primary.width(), 1)
    assert primary_image.pixelColor(
        int(4 * p_scale), primary_image.height() // 2
    ) == accent, theme
    primary_runs = _ink_column_runs(primary_image, accent, accent_fg, int(inset * p_scale))
    assert primary_runs, (theme, "no accent.fg ink cluster on the primary button")
    assert primary_runs[0][2] >= 10, (theme, primary_runs[0])

    # ── the disabled button: canvas fill, no accent residue anywhere…
    image = disabled.grab().toImage()
    d_scale = image.width() / max(disabled.width(), 1)
    mid_y = image.height() // 2
    assert image.pixelColor(int(4 * d_scale), mid_y) == canvas, theme
    assert not _contains_pixel(image, accent), theme
    assert not _contains_pixel(image, accent_fg), (
        theme, "a surviving accent.fg pixel betrays the Qt-auto-tinted or "
        "engine-skipped glyph"
    )
    # …and EVERY painted pixel inside the inset (glyph and caption alike) is a
    # blend on the single canvas→muted line, with both clusters carrying the
    # exact muted token: one tone for glyph and caption, no third tint.
    d_inset = int(inset * d_scale)
    painted = 0
    for y in range(d_inset, image.height() - d_inset):
        for x in range(d_inset, image.width() - d_inset):
            pixel = image.pixelColor(x, y)
            if pixel == canvas:
                continue
            painted += 1
            if pixel == muted:
                continue
            assert _ink_line_t(pixel, canvas, muted) is not None, (
                theme,
                (x, y, pixel.name()),
                "disabled ink pixel off the canvas→muted line",
            )
    assert painted > 50, (theme, painted)  # the button really painted glyph+caption
    # Where the enabled sibling carried its accent.fg glyph cluster, the very
    # same columns now carry the exact muted token: the engine's Disabled ink
    # reached the glyph, not Qt's palette tint (which lands off the line).
    disabled_runs = _ink_column_runs(image, canvas, muted, d_inset)
    assert disabled_runs, (theme, "no muted ink cluster on the disabled button")
    di_glyph_x0, di_glyph_x1, di_glyph_exact = disabled_runs[0]
    assert abs(di_glyph_x0 - en_glyph_x0) <= 2 * d_scale, (theme, di_glyph_x0, en_glyph_x0)
    assert abs(di_glyph_x1 - en_glyph_x1) <= 2 * d_scale, (theme, di_glyph_x1, en_glyph_x1)
    assert di_glyph_exact >= 10, (theme, di_glyph_exact)
    ratio = _contrast_ratio(
        (muted.red(), muted.green(), muted.blue()),
        (canvas.red(), canvas.green(), canvas.blue()),
    )
    assert ratio >= 4.5, (theme, ratio)


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


# ── PR-008: the date popup's month field wears the tokens, not the OS appearance ─


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_date_popup_month_field_is_themed_not_os_drawn(qtbot, tmp_path, theme):
    """Pixel acceptance for the compiled popup sheet (live defect PR-008, spec
    ui-theme «Хром без палитры ОС»): the navigation row's month picker was the
    one OS-drawn control of the game-calendar grid, so its caption came from the
    SYSTEM appearance — on a dark-appearance macOS under the light app theme the
    live popup printed a white caption on the white native field and the field
    read as empty while its accessible value stayed «Октябрь»
    (docs/qa/assets/2026-10-03-full-run/PR-008-month-caption-invisible-light.png).
    Off-skin the same root cause is visible the other way round: the box paints
    the OS field and OS-black ink in BOTH themes, no token among its pixels.
    The themed box answers with the canvas fill, the border hairline and the
    ``color.fg.primary`` ink, and that pair clears the WCAG AA floor by the
    numbers of the very tokens the pixels answered."""
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication

    from app.presentation.views.theme_date_popup import ThemeDatePopup
    from tests.presentation.test_theme_compile import _contrast_ratio

    runtime = make_runtime(tmp_path, theme)
    app = QApplication.instance()
    app.setStyleSheet("")
    runtime.attach_app(app)
    runtime.apply()
    try:
        popup = ThemeDatePopup()
        qtbot.addWidget(popup)
        popup.open_at(QRect(40, 40, 120, 24))
        qtbot.waitExposed(popup)
        combo = popup.calendar._month_combo  # the field the report is about
        image = combo.grab().toImage()
        scale = image.width() / max(combo.width(), 1)
        mid_y = image.height() // 2

        canvas = token_color("color.bg.canvas", theme)
        fg = token_color("color.fg.primary", theme)
        border = token_color("color.border", theme)
        assert canvas != fg  # the fill/ink claims below must differ

        # The field's own face: canvas fill in the left padding band, border
        # hairline on its edge — the rule the sheet now owns, not the OS box.
        assert image.pixelColor(int(4 * scale), mid_y) == canvas, theme
        assert image.pixelColor(0, mid_y) == border, theme
        # The caption ink is the primary foreground token, and the OS ink the
        # unstyled box painted with (black text in both themes) is gone.
        assert _contains_pixel(image, fg), theme
        assert not _contains_pixel(image, QColor("#000000")), theme
        # The pair the reader actually gets, measured from the same two tokens
        # the pixels above answered with.
        ratio = _contrast_ratio(
            (fg.red(), fg.green(), fg.blue()),
            (canvas.red(), canvas.green(), canvas.blue()),
        )
        assert ratio >= 4.5, (theme, ratio)
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


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_sheet_dialogs_have_no_menu_strip_after_the_action_row_moved_in(
    qtbot, tmp_path, theme
):
    # Re-captured grab contract (NRI-0017 B2): the «Правка» QMenuBar left both
    # sheet dialogs for an action row inside the islands, so the whole window
    # edge-to-edge IS the island — the top strip that used to be native menu
    # chrome now paints the island's surface token like every other edge
    # (the launcher's «нет полосы палитры ОС» contract, spec character-sheet
    # -editor «невидимого меню на диалоге SHALL не быть»).
    from PySide6.QtWidgets import QMenuBar

    from app.presentation.views.character_sheet.editor_dialog import (
        CharacterSheetEditorDialog,
    )
    from app.presentation.views.character_sheet.fill_dialog import (
        CharacterSheetFillDialog,
    )

    runtime = make_runtime(tmp_path, theme)
    dialogs = [
        CharacterSheetEditorDialog(MagicMock(), 1, theme=runtime),
        CharacterSheetFillDialog(MagicMock(), MagicMock(), 1, theme=runtime),
    ]
    surface = token_color("color.bg.surface", theme)
    for dlg in dialogs:
        qtbot.addWidget(dlg)
        assert dlg.findChildren(QMenuBar) == []        # the menu widget is gone
        dlg.resize(800, 600)
        dlg.show()
        qtbot.waitExposed(dlg)
        image = dlg.grab().toImage()
        for x, y in ((1, 1), (2, 2), (image.width() - 2, 2)):
            assert image.pixelColor(x, y) == surface, (dlg, x, y)
        dlg.force_close()


# ── NRI-0015 P3 («Все дни» не пестрит): the «Выбор даты» popover paints no
# accent fill while the window is empty — the accent belongs to the selected
# bound alone (spec event-timeline «Панель выбора даты имеет читаемые
# состояния»). The leak this pins was the chrome-QPushButton accent rule
# reaching the popup through the stylesheet PARENT chain (a widget-parented
# top level inherits its ancestors' sheets); the popup stays parent-less, so
# these are grabs of the plain app-sheet skin, not of exact new colors and
# not through parented cells.

@pytest.mark.parametrize("theme", ["dark", "light"])
def test_date_window_popup_empty_window_paints_no_accent_fill(qtbot, tmp_path, theme):
    from datetime import date

    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication

    from app.domain.game_calendar import MonthDay
    from app.presentation.views.timeline_date_popup import _DateWindowPopup

    runtime = make_runtime(tmp_path, theme)
    app = QApplication.instance()
    app.setStyleSheet("")
    runtime.attach_app(app)
    runtime.apply()
    try:
        accent = token_color("color.accent", theme)
        popup = _DateWindowPopup()
        qtbot.addWidget(popup)
        popup.open_at(QRect(0, 0, 10, 10), None)
        image = popup.start_calendar.grab().toImage()
        assert not _contains_pixel(image, accent), (
            "пустое окно: обычная ячейка не имеет права на accent-заливку"
        )
        # The accent half survives where it belongs: the seeded bound marks
        # exactly its cell and that fill is the accent token. (A fresh popup:
        # a second open_at on a live Qt::Popup re-polishes the regenerated
        # cells lazily, and the offscreen backing store only ever painted the
        # selection on the first show — the probe pins the FIRST open state
        # of each shape, which is exactly what the user sees on open.)
        today = date.today()
        coord = MonthDay(today.year, today.month, today.day)
        marked_popup = _DateWindowPopup()
        qtbot.addWidget(marked_popup)
        marked_popup.open_at(QRect(0, 0, 10, 10), (coord, coord))
        marked = marked_popup.start_calendar.grab().toImage()
        assert _contains_pixel(marked, accent), (
            "выбранная граница обязана заливать свою клетку accent-токеном"
        )
        popup.close()
        marked_popup.close()
    finally:
        app.setStyleSheet("")


# ── NRI-0025 (task 4.1): the preview column's single-mode grab pin ───────────


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_preview_single_pane_paints_band_surface_and_card_canvas(qtbot, tmp_path, theme):
    """The zero-pins column must stay the pre-NRI-0022 markup pixel-wise
    (spec preview-pins «При отсутствии закреплений колонка SHALL выглядеть
    … как одиночная карточка на всю высоту»): the island root's surface owns
    the frame and the 32 px header band's row, the card canvas token fills
    the card inside its hairline, and no OS-palette strip may leak around
    the island (this file's launcher posture applied to the third column).
    """
    from types import SimpleNamespace

    from PySide6.QtCore import QPointF

    from app.presentation.views.entity_preview import EntityPreviewWidget
    from tests.presentation.qml_helpers import find_item

    runtime = make_runtime(tmp_path, theme)
    widget = EntityPreviewWidget(theme=runtime)
    qtbot.addWidget(widget)
    widget.resize(420, 520)
    widget.show_slots([], ("character", SimpleNamespace(
        id=4, name="Банн", rating=8,
        start_date=datetime.date(1200, 1, 1), end_date=None,
        start_bc=False, end_bc=False, description=None,
        music_url="", image_ref=None, personality=None, tasks=None,
    )))
    widget.show()
    qtbot.waitExposed(widget)
    image, factor = _grab_scaled(widget)

    surface = token_color("color.bg.surface", theme)
    canvas = canvas_color(theme)
    assert surface != canvas  # the two readings below must differ

    def sample(scene_x: float, scene_y: float) -> QColor:
        return image.pixelColor(round(scene_x * factor), round(scene_y * factor))

    # The island's own edge: root surface, not the OS palette, not QSS chrome.
    assert sample(1, 1) == surface
    assert sample(1, image.height() / factor - 2) == surface

    card = find_item(widget.quick, "previewPaneCanvas")
    pos = card.mapToScene(QPointF(0, 0))
    # Inside the hairline, outside the scroll viewport (its inset is 1 +
    # space.sm): the canvas token fills the card's margin band.
    assert sample(pos.x() + 3, pos.y() + 3) == canvas
    assert sample(pos.x() + 3, pos.y() + card.height() - 4) == canvas

    # The pane's header-band row paints on the island surface (the band is a
    # transparent strip over the root, not a second card face); sampled at
    # the far right, clear of both the caption and the ghost pin square.
    band = find_item(widget.quick, "previewPaneBand_0")
    band_pos = band.mapToScene(QPointF(0, 0))
    assert sample(band_pos.x() + band.width() - 2, band_pos.y() + band.height() / 2) == surface
