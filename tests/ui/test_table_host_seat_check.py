"""Pixel pin for the seat tick — ``TableHostSeatCheck`` (paintEvent).

The desk's seating rows must SHOW a checkmark when checked, not just the
solid accent fill Qt QSS is able to paint. The tick is QPainter content:
two ``color.accent.fg`` legs over the accent fill, geometry taken from the
QML library's ``ThemeCheckBox`` ``tickLegs`` (short leg down-right into the
elbow, long leg up-right; the box is the framed token indicator the sheet
paints — 16 px + the 1 px border). This file grabs the real skinned
indicator offscreen and pins, zero tolerance on the colors:

* unchecked — no tick ink anywhere;
* checked — the accent fill is under the tick AND exact tick pixels sit on
  both legs' center lines at the QML fractions (the marker occupies the
  QML's rows/columns extent, not just some stray pixel);
* off-skin (D7) — the subclass paints EXACTLY what a stock ``QCheckBox``
  paints: the native indicator with the native tick, no token ink added.

The same recipe as ``tests/ui/test_theme_grab.py``: ``widget.grab()``; all
sample math rides on the actually painted accent bbox, so it holds at any
device pixel ratio.
"""
from __future__ import annotations

import math

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QCheckBox, QWidget

from app.presentation.theme import ThemeRuntime
from app.presentation.theme.catalog import attach_theme
from app.presentation.views.table_host import panel as panel_module
from app.presentation.views.table_host.panel import (
    SEAT_TICK_TOKEN_KEY,
    TableHostSeatCheck,
)
from tests.ui.test_theme_grab import make_runtime, token_color

# The QML tickLegs geometry (ThemeCheckBox.qml:119–147), as the production
# class reads it — imported from the module so the pin rides every fix there.
_LEGS = panel_module._SEAT_TICK_LEGS


def _count(image, color: QColor) -> int:
    return sum(
        image.pixelColor(x, y) == color
        for y in range(image.height())
        for x in range(image.width())
    )


def _bbox(image, color: QColor) -> tuple[int, int, int, int]:
    """Bounding box of exact ``color`` pixels as ``(x0, x1, y0, y1)``."""
    xs = [
        x for y in range(image.height()) for x in range(image.width())
        if image.pixelColor(x, y) == color
    ]
    assert xs, f"ни одного пикселя {color.name()}"
    ys = [
        y for y in range(image.height()) for x in range(image.width())
        if image.pixelColor(x, y) == color
    ]
    return min(xs), max(xs), min(ys), max(ys)


def _has_exact_pixel_near(image, x: int, y: int, ink: QColor) -> bool:
    """An exact ``ink`` pixel within one device pixel of ``(x, y)`` — the
    window absorbs the antialiased leg center line's sub-pixel landing."""
    return any(
        image.pixelColor(px, py) == ink
        for px in range(x - 1, x + 2)
        for py in range(y - 1, y + 2)
        if 0 <= px < image.width() and 0 <= py < image.height()
    )


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_checked_seat_wears_the_tick_on_the_accent_fill(qtbot, tmp_path, theme, monkeypatch):
    runtime = make_runtime(tmp_path, theme)
    monkeypatch.setattr(panel_module, "get_default_theme", lambda: runtime)
    root = attach_theme(QWidget(), runtime)
    runtime.apply()
    qtbot.addWidget(root)
    box = TableHostSeatCheck("Лист A", root)
    box.resize(box.sizeHint())
    root.show()
    qtbot.waitExposed(root)

    accent = token_color("color.accent", theme)
    ink = token_color(SEAT_TICK_TOKEN_KEY, theme)
    assert accent != ink  # the pin below is vacuous if a theme ever ties them

    box.setChecked(False)
    QApplication.processEvents()
    image = box.grab().toImage()
    assert _count(image, ink) == 0, "на неотмеченном чекбоксе галочки быть не должно"

    box.setChecked(True)
    QApplication.processEvents()
    image = box.grab().toImage()
    # The checked indicator: the frame and the fill are the one accent token,
    # so its bbox is the authoritative painted box — the tick must live inside
    # THIS rect (the sheet's 16 px + 1 px border), on the QML legs' fractions.
    x0, x1, y0, y1 = _bbox(image, accent)
    w, h = x1 - x0 + 1, y1 - y0 + 1
    # the production class rotates each leg around its TOP-LEFT corner (the
    # QML transformOrigin), so the bar's center line rides half a thickness
    # off the pivot along the rotated normal — the sampler walks the very
    # local point (t·L, thickness/2) through the same rotation
    thickness = 2.0 * w / 16.0
    for x_ratio, y_ratio, length_ratio, angle in _LEGS:
        theta = math.radians(angle)
        length = w * length_ratio
        for t in (0.35, 0.7, 0.95):
            lx, ly = t * length, thickness / 2.0
            x = int(round(x0 + w * x_ratio + lx * math.cos(theta) - ly * math.sin(theta)))
            y = int(round(y0 + h * y_ratio + lx * math.sin(theta) + ly * math.cos(theta)))
            assert _has_exact_pixel_near(image, x, y, ink), (
                f"ножка галочки не дотягивает до ({x}, {y}) при {t=}"
            )
    # a stray pixel could pass single samples; the tick is a real marker only
    # if its ink spans the QML legs' extent in both axes
    painted_rows = [
        y for y in range(image.height())
        if any(image.pixelColor(x, y) == ink for x in range(image.width()))
    ]
    painted_cols = [
        x for x in range(image.width())
        if any(image.pixelColor(x, y) == ink for y in range(image.height()))
    ]
    assert len(painted_rows) >= 4, f"галочка не развёрнута по вертикали: {painted_rows}"
    assert len(painted_cols) >= 4, f"галочка не развёрнута по горизонтали: {painted_cols}"
    # and the marker never escapes the box the sheet painted
    assert x0 <= min(painted_cols) and max(painted_cols) <= x1
    assert y0 <= min(painted_rows) and max(painted_rows) <= y1


def test_off_skin_seat_check_paints_exactly_like_the_stock_checkbox(qtbot, tmp_path, monkeypatch):
    # D7 / ui-widget-catalog «Off-skin не ломается»: with no valid skin the
    # subclass adds NOTHING on top of super() — the same pixels a plain
    # QCheckBox paints, native tick included (no invented token colors).
    off = ThemeRuntime(tokens_path=tmp_path / "no-such-tokens.json")
    assert off.tokens is None
    monkeypatch.setattr(panel_module, "get_default_theme", lambda: off)
    ours = TableHostSeatCheck("Лист A")
    stock = QCheckBox("Лист A")
    qtbot.addWidget(ours)
    qtbot.addWidget(stock)
    for box in (ours, stock):
        box.setChecked(True)
        box.resize(box.sizeHint())
    ours_image = ours.grab().toImage()
    stock_image = stock.grab().toImage()
    assert ours_image.size() == stock_image.size()
    assert ours_image == stock_image, (
        "off-skin подкласс дорисовывает что-то поверх нативного индикатора — "
        "штатная галка ОС должна сохраняться нетронутой"
    )
