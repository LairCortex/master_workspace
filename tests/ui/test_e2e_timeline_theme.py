"""W3b pixel acceptance: every scale color is a live token derivative.

The horizontal Gantt canvas is gone; the panel body is a ``QListWidget`` whose
``_RowDelegate`` paints the selection/hover wash, the date rail (day tick, month
label, span bracket) and the ``start — end · name`` line, plus a sticky ``QLabel``
band. Probes follow the W1/W2b pattern (``widget.grab()`` at device scale, zero
tolerance, no golden files): a selected row's fill must equal the ``color.accent``
token itself, an unselected row's surface the ``color.bg.surface`` token, the
hover wash the accent derivative ``accent`` at ``ROW_HOVER_ALPHA`` over that
surface, the rail ticks/brackets the ``color.border`` token, the rail month labels
the ``color.fg.muted`` token and the sticky band its surface/accent/primary tokens
— and rewriting ``color.accent`` in a copied token file must move the selection
and the wash with no screen code touched (spec «Смена accent перекрашивает
шкалу событий», «Токен-инвариант шкалы», «Вне скина» stays covered off-skin by the
``test_no_chrome_hex`` grep invariant run separately).
"""
from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import QApplication

from app.presentation.theme.compiler import tokens_file_path
from app.presentation.views.timeline_widget import (
    EMPTY_HINT_TEXT,
    ROW_HOVER_ALPHA,
    TimelineWidget,
)

from tests.ui.test_theme_grab import (
    _composite_over,
    _contains_pixel,
    make_runtime,
    token_color,
)


def _evt(id_, start, end=None, name=None):
    return SimpleNamespace(id=id_, start_date=start, end_date=end, name=name or f"E{id_}")


def _scale(view):
    """Logical→device factor of a viewport grab (dpr 2 on Retina, 1 offscreen)."""
    image = view.viewport().grab().toImage()
    return image.width() / max(view.viewport().width(), 1)


def _hover_alpha(accent: QColor) -> int:
    """The 8-bit alpha Qt gives to ``accent`` at ``ROW_HOVER_ALPHA``.

    The widget builds the wash with ``setAlphaF(ROW_HOVER_ALPHA)``; Qt rounds
    that to 64 (not the truncating ``int(0.25 * 255)`` = 63), so the expected
    composite must use the same rounding to stay pixel-exact.
    """
    tint = QColor(accent)
    tint.setAlphaF(ROW_HOVER_ALPHA)
    return tint.alpha()


def _widget(qtbot, runtime, events, size=(440, 260)):
    """A skinned TimelineWidget carrying ``events`` on the vertical scale."""
    vm = MagicMock()
    vm.events = []
    widget = TimelineWidget(vm, theme=runtime)
    qtbot.addWidget(widget)
    widget.resize(*size)
    widget.show()
    qtbot.waitExposed(widget)
    widget.update_events(events)
    qtbot.waitExposed(widget)
    return widget


def _row_right_pixel(view, idx: int, scale: float) -> QColor:
    """A no-text pixel of the row: the far right, clear of the elided text."""
    vp = view.viewport()
    rect = view.visualItemRect(view.item(idx))
    image = vp.grab().toImage()
    x = min(int((vp.width() - 6) * scale), image.width() - 1)
    y = int(rect.center().y() * scale)
    return image.pixelColor(x, y)


def _move_over_row(view, idx: int) -> None:
    vp = view.viewport()
    x = vp.width() - 6
    y = view.visualItemRect(view.item(idx)).center().y()
    QApplication.sendEvent(vp, QMouseEvent(
        QEvent.Type.MouseMove, QPointF(x, y), vp.mapToGlobal(QPoint(x, y)),
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
    ))


def _rail_has_token(view, color: QColor) -> bool:
    """True when some rail-zone pixel equals ``color`` exactly (tick/bracket/label)."""
    vp = view.viewport()
    image = vp.grab().toImage()
    rail_px = int(view.rail_width() * image.width() / max(vp.width(), 1))
    return any(
        image.pixelColor(x, y) == color
        for y in range(image.height())
        for x in range(min(rail_px, image.width()))
    )


def _tokens_with_accent(tmp_path, theme: str, new_accent: str):
    """A copied token file with ``color.accent`` retargeted for one theme."""
    tokens = json.loads(tokens_file_path().read_text(encoding="utf-8"))
    tokens["color.accent"][theme] = new_accent
    path = tmp_path / f"tokens-{theme}.json"
    path.write_text(json.dumps(tokens), encoding="utf-8")
    return path


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_selection_hover_and_surface_are_accent_derivatives(qtbot, tmp_path, theme):
    """Empty row == surface, selected row == accent, hovered row == accent wash."""
    runtime = make_runtime(tmp_path, theme)
    surface = token_color("color.bg.surface", theme)
    accent = token_color("color.accent", theme)
    widget = _widget(qtbot, runtime, [_evt(1, date(1200, 1, 1), date(1200, 1, 20), "З")])
    view = widget.rows_view
    scale = _scale(view)

    # unselected: the empty row region is the surface token (no per-row fill here)
    assert _row_right_pixel(view, 0, scale) == surface, theme
    assert _row_right_pixel(view, 1, scale) == surface, theme  # a later day, still a row

    widget.set_selected(1)
    assert _row_right_pixel(view, 0, scale) == accent, theme  # fill == accent itself

    widget.set_selected(None)
    _move_over_row(view, 0)
    qtbot.wait(0)
    expected_wash = _composite_over(surface, accent, _hover_alpha(accent))
    assert _row_right_pixel(view, 0, scale) == expected_wash, theme


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_rail_ticks_brackets_and_month_label_come_from_tokens(qtbot, tmp_path, theme):
    """The decorative rail paints border (ticks/brackets) and fg.muted (months)."""
    runtime = make_runtime(tmp_path, theme)
    widget = _widget(qtbot, runtime, [
        _evt(1, date(1200, 1, 1), date(1200, 3, 30), "многодневка"),
        _evt(2, date(1200, 2, 1), date(1200, 2, 3), "граница-месяца"),
    ])
    view = widget.rows_view

    # day ticks + the multi-day bracket are the border token
    assert _rail_has_token(view, token_color("color.border", theme)), theme

    # scroll a first-of-month event into view so its rotated label has headroom
    idx_feb = view.index_for_event(2)
    view.scrollToItem(view.item(idx_feb), view.ScrollHint.PositionAtCenter)
    qtbot.wait(0)
    assert _rail_has_token(view, token_color("color.fg.muted", theme)), theme


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_sticky_band_is_surface_accent_and_primary_tokens(qtbot, tmp_path, theme):
    """Sticky date: surface band, accent hairline, fg.primary date text."""
    runtime = make_runtime(tmp_path, theme)
    widget = _widget(qtbot, runtime, [_evt(1, date(1200, 1, 1), date(1200, 1, 20), "З")])
    sticky = widget.rows_view.sticky_label
    assert sticky.text()  # showing the top row's full game date
    image = sticky.grab().toImage()
    scale = image.width() / max(sticky.width(), 1)

    assert image.pixelColor(int(4 * scale), int(2 * scale)) == token_color(
        "color.bg.surface", theme
    ), theme
    assert _contains_pixel(image, token_color("color.fg.primary", theme)), theme
    hairline = token_color("color.accent", theme)
    bottom = image.height() - int(1 * scale)
    assert any(image.pixelColor(x, bottom) == hairline for x in range(image.width())), theme


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_accent_token_edit_recolors_the_scale_without_screen_changes(qtbot, tmp_path, theme):
    """A retargeted ``color.accent`` moves the selected fill and the hover wash."""
    new_accent = "#0f8c3c" if theme == "dark" else "#c00f2e"
    runtime = make_runtime(
        tmp_path, theme, tokens_path=_tokens_with_accent(tmp_path, theme, new_accent)
    )
    widget = _widget(qtbot, runtime, [_evt(1, date(1200, 1, 1), date(1200, 1, 20), "Бой")])
    view = widget.rows_view
    scale = _scale(view)
    surface = token_color("color.bg.surface", theme)

    widget.set_selected(1)
    assert _row_right_pixel(view, 0, scale) == QColor(new_accent), theme

    widget.set_selected(None)
    _move_over_row(view, 0)
    qtbot.wait(0)
    expected = _composite_over(surface, QColor(new_accent), _hover_alpha(QColor(new_accent)))
    assert _row_right_pixel(view, 0, scale) == expected, theme


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_empty_hint_paints_the_muted_token(qtbot, tmp_path, theme):
    """No events → the explanatory hint text renders in the fg.muted token."""
    runtime = make_runtime(tmp_path, theme)
    widget = _widget(qtbot, runtime, [])
    hint = widget.rows_view.hint_label
    assert hint.text() == EMPTY_HINT_TEXT
    assert _contains_pixel(hint.grab().toImage(), token_color("color.fg.muted", theme)), theme
