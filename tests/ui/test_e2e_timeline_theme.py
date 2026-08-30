"""W3 pixel acceptance: every canvas color is a live derivative of tokens.

Probes follow the W1/W2b pattern (``widget.grab()`` at device scale, zero
tolerance, no golden files): the selected bar must equal the ``color.accent``
token itself, the plain/hover fills the token's alpha composites over the
``color.bg.surface`` it sits on, the grid hairline the ``color.border``
composite — and rewriting ``color.accent`` in a copied token file must move
all of them with no screen code touched (spec «Смена accent перекрашивает
шкалу событий»).
"""
from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from app.presentation.theme.compiler import tokens_file_path
from app.presentation.views.timeline_widget import (
    BAR_FILL_ALPHA,
    BAR_HOVER_ALPHA,
    TimelineCanvas,
)

from tests.ui.test_theme_grab import (
    _composite_over,
    _grab_scaled,
    make_runtime,
    token_color,
)


def _evt(id_, name, start, end):
    return SimpleNamespace(id=id_, name=name, start_date=start, end_date=end)


def _canvas(qtbot, runtime, events, size=(320, 120)):
    canvas = TimelineCanvas(theme=runtime)
    canvas.resize(*size)
    qtbot.addWidget(canvas)
    canvas.set_events(events)
    canvas.show()
    qtbot.waitExposed(canvas)
    return canvas


def _probe(canvas, image, scale, logical_x, logical_y):
    return image.pixelColor(int(logical_x * scale), int(logical_y * scale))


def _move_over(canvas, x: float, y: float) -> None:
    QApplication.sendEvent(canvas, QMouseEvent(
        QEvent.Type.MouseMove, QPointF(x, y),
        canvas.mapToGlobal(QPoint(int(x), int(y))),
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
    ))


def test_accent_token_edit_recolors_the_scale_without_screen_changes(qtbot, tmp_path):
    """Both themes: the edited accent shows up in selected + hover + fill."""
    for theme in ("dark", "light"):
        new_accent = "#0f8c3c" if theme == "dark" else "#c00f2e"
        tokens = json.loads(tokens_file_path().read_text(encoding="utf-8"))
        tokens["color.accent"][theme] = new_accent
        tokens_path = tmp_path / f"tokens-{theme}.json"
        tokens_path.write_text(json.dumps(tokens), encoding="utf-8")
        runtime = make_runtime(tmp_path, theme, tokens_path=tokens_path)
        canvas = _canvas(qtbot, runtime, [_evt(1, "Бой", date(1200, 1, 1), date(1200, 1, 31))])
        image, scale = _grab_scaled(canvas)
        bar = canvas.plan.bar_for(1)
        probe_x = (bar.x0 + bar.x1) / 2.0
        probe_y = canvas.plan.metrics.axis_h + bar.height - 22.0  # below the label band
        # selected == the edited accent itself
        canvas.set_selected(1)
        image_sel, scale_sel = _grab_scaled(canvas)
        assert _probe(canvas, image_sel, scale_sel, probe_x, probe_y) == QColor(new_accent)
        # unselected fill == the edited accent at BAR_FILL_ALPHA over surface
        canvas.set_selected(None)
        image_plain, scale_plain = _grab_scaled(canvas)
        plain = _probe(canvas, image_plain, scale_plain, probe_x, probe_y)
        expected = _composite_over(
            token_color("color.bg.surface", theme),
            QColor(new_accent),
            int(BAR_FILL_ALPHA * 255),
        )
        assert plain == expected, (theme, plain.getRgb(), expected.getRgb())
        # hover fill == the token at BAR_HOVER_ALPHA
        _move_over(canvas, probe_x, probe_y)
        canvas.grab()  # repaint with the hover state
        image_hover, scale_hover = _grab_scaled(canvas)
        hovered = _probe(canvas, image_hover, scale_hover, probe_x, probe_y)
        expected_hover = _composite_over(
            token_color("color.bg.surface", theme),
            QColor(new_accent),
            int(BAR_HOVER_ALPHA * 255),
        )
        assert hovered == expected_hover, (theme, hovered.getRgb(), expected_hover.getRgb())


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_grid_hairline_is_the_border_token_composite(qtbot, tmp_path, theme):
    """A month-boundary hairline between two bars paints border over surface."""
    runtime = make_runtime(tmp_path, theme)
    events = [
        _evt(1, "Январь", date(1200, 1, 1), date(1200, 1, 10)),  # lane gap free:
        _evt(2, "Март", date(1200, 3, 20), date(1200, 3, 31)),  # Feb 1 tick is bare
    ]
    canvas = _canvas(qtbot, runtime, events, size=(420, 90))
    image, scale = _grab_scaled(canvas)
    tick_x = int(canvas.plan.x_of(date(1200, 2, 1)))
    surface = token_color("color.bg.surface", theme)
    expected = _composite_over(
        surface, token_color("color.border", theme), int(0.6 * 255)  # canvas grid alpha
    )
    bar_y = canvas.plan.metrics.axis_h + canvas.plan.lane_h - 4  # inside the lane,
    hits = [
        image.pixelColor(int((tick_x + dx) * scale), int(row * scale))
        for dx in (0, 1)
        for row in (bar_y, bar_y - 1)
    ]
    assert any(px == expected for px in hits), [px.getRgb() for px in hits]


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_empty_hint_is_the_muted_token(qtbot, tmp_path, theme):
    """The empty-range hint renders in the fg.muted token (hint role color)."""
    runtime = make_runtime(tmp_path, theme)
    canvas = _canvas(qtbot, runtime, [])
    image = canvas.grab().toImage()
    muted = token_color("color.fg.muted", theme)
    found = any(
        image.pixelColor(x, y) == muted
        for y in range(image.height())
        for x in range(image.width())
    )
    assert found, f"hint text must paint the muted token ({theme})"


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_unselected_bar_fill_is_accent_derivative_both_themes(qtbot, tmp_path, theme):
    """The plain fill and the month-free axis stay on token derivatives."""
    runtime = make_runtime(tmp_path, theme)
    canvas = _canvas(qtbot, runtime, [_evt(1, "Зима", date(1200, 1, 1), date(1200, 1, 31))])
    image, scale = _grab_scaled(canvas)
    bar = canvas.plan.bar_for(1)
    plain = _probe(
        canvas, image, scale,
        bar.x1 - 4.0,                       # clear of the label and the border
        canvas.plan.metrics.axis_h + bar.height - 22.0,
    )
    surface = token_color("color.bg.surface", theme)
    expected = _composite_over(
        surface, token_color("color.accent", theme), int(BAR_FILL_ALPHA * 255)
    )
    assert plain == expected, (plain.getRgb(), expected.getRgb())
