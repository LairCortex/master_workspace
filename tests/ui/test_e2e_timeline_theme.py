"""Pixel acceptance for the day-ladder tape: every color is a live token.

redesign-timeline-day-ladder (task 3.1) rewrote the delegate: the rail probes
(ticks/ties/month labels) retired with the rail. Painted now and probed
here: the event card wash (surface / accent selection / accent-derivative
hover), the type dot — exactly ``color.chart.k`` of the live theme (spec
«Цвет типа равен токену») with untyped events landing on ``color.fg.muted``
(spec «Метка типа на карточке»), the muted placeholder/gap/counter captions,
the sticky band (surface + accent hairline + fg.primary caption) and the
empty-state hint. Rewriting ``color.accent`` in a copied token file must move
the selection and the hover wash with no screen code touched (spec «Смена
accent перекрашивает шкалу», «Токен-инвариант шкалы»; the «Вне скина» grep
invariant lives in ``test_no_chrome_hex``).
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
from app.presentation.views.timeline_rows import (
    EmptyDayRow, GapCollapsedRow, PeriodCardRow, ScaleUnit,
)
from app.presentation.views.timeline_widget import (
    DOT_SIZE,
    EMPTY_HINT_TEXT,
    ROW_HOVER_ALPHA,
    TEXT_LEFT_PAD,
    TimelineWidget,
)

from tests.ui.test_theme_grab import (
    _composite_over,
    _contains_pixel,
    make_runtime,
    token_color,
)


def _evt(id_, start, end=None, name=None, color_index=None):
    event = SimpleNamespace(id=id_, start_date=start, end_date=end, name=name or f"E{id_}")
    event.event_type = None if color_index is None else SimpleNamespace(color_index=color_index)
    return event


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
    """A skinned TimelineWidget carrying ``events`` on the day-ladder tape."""
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


def _type_dot_pixel(view, idx: int, scale: float) -> QColor:
    """The pixel at the center of the type dot of the card at ``idx``."""
    vp = view.viewport()
    rect = view.visualItemRect(view.item(idx))
    image = vp.grab().toImage()
    x = int((TEXT_LEFT_PAD + DOT_SIZE // 2) * scale)
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


def _row_contains(view, idx: int, color: QColor) -> bool:
    """True when any pixel of row ``idx`` equals ``color`` exactly."""
    vp = view.viewport()
    rect = view.visualItemRect(view.item(idx))
    image = vp.grab().toImage()
    scale = image.width() / max(vp.width(), 1)
    top = int(rect.top() * scale)
    bottom = min(int(rect.bottom() * scale), image.height() - 1)
    return any(
        image.pixelColor(x, y) == color
        for y in range(top, bottom + 1)
        for x in range(image.width())
    )


def _tokens_with_accent(tmp_path, theme: str, new_accent: str):
    """A copied token file with ``color.accent`` retargeted for one theme."""
    tokens = json.loads(tokens_file_path().read_text(encoding="utf-8"))
    tokens["color.accent"][theme] = new_accent
    path = tmp_path / f"tokens-{theme}.json"
    path.write_text(json.dumps(tokens), encoding="utf-8")
    return path


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_surface_selection_and_hover_are_accent_derivatives(qtbot, tmp_path, theme):
    """Header/card surface == surface token, selected card == accent, hovered
    card == the accent derivative wash (spec «Токен-инвариант шкалы»)."""
    runtime = make_runtime(tmp_path, theme)
    surface = token_color("color.bg.surface", theme)
    accent = token_color("color.accent", theme)
    widget = _widget(qtbot, runtime, [_evt(1, date(1200, 1, 1), date(1200, 1, 20), "З")])
    view = widget.rows_view
    scale = _scale(view)
    card = view.index_for_event(1)  # row 0 is the day header
    assert card == 1

    # unselected: neither the header nor the card paints a wash — surface
    assert _row_right_pixel(view, 0, scale) == surface, theme
    assert _row_right_pixel(view, card, scale) == surface, theme

    widget.set_selected(1)
    assert _row_right_pixel(view, card, scale) == accent, theme  # accent itself

    widget.set_selected(None)
    _move_over_row(view, card)
    qtbot.wait(0)
    expected_wash = _composite_over(surface, accent, _hover_alpha(accent))
    assert _row_right_pixel(view, card, scale) == expected_wash, theme


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_type_dot_is_the_chart_token_muted_when_untyped(qtbot, tmp_path, theme):
    """Spec «Цвет типа равен токену» / «Метка типа на карточке»: the dot of a
    type-k card == color.chart.k of the live theme; no type → fg.muted dot."""
    runtime = make_runtime(tmp_path, theme)
    widget = _widget(qtbot, runtime, [
        _evt(1, date(1200, 1, 1), date(1200, 1, 1), "Слух", color_index=3),
        _evt(2, date(1200, 1, 2), date(1200, 1, 2), "Без типа"),
    ])
    view = widget.rows_view
    scale = _scale(view)
    typed = view.index_for_event(1)
    untyped = view.index_for_event(2)
    assert _type_dot_pixel(view, typed, scale) == token_color("color.chart.3", theme), theme
    assert _type_dot_pixel(view, untyped, scale) == token_color("color.fg.muted", theme), theme


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_empty_placeholder_gap_and_counter_captions_use_the_muted_token(qtbot, tmp_path, theme):
    """«нет события» / collapsed-gap / «нет событий» rows paint fg.muted text."""
    runtime = make_runtime(tmp_path, theme)
    widget = _widget(qtbot, runtime, [
        _evt(1, date(1200, 1, 1), date(1200, 1, 1)),
        _evt(2, date(1200, 1, 3), date(1200, 1, 3)),
        _evt(3, date(1200, 3, 1), date(1200, 3, 1)),  # gap Jan 4 … Feb 29
    ])
    view = widget.rows_view
    muted = token_color("color.fg.muted", theme)
    empty_idx = next(i for i, r in enumerate(view.rows) if isinstance(r, EmptyDayRow))
    gap_idx = next(i for i, r in enumerate(view.rows) if isinstance(r, GapCollapsedRow))
    assert _row_contains(view, empty_idx, muted), theme
    assert _row_contains(view, gap_idx, muted), theme

    view.set_knobs(level=ScaleUnit.MONTH)
    qtbot.wait(0)
    empty_period = next(
        i for i, r in enumerate(view.rows)
        if isinstance(r, PeriodCardRow) and r.count == 0
    )
    assert _row_contains(view, empty_period, muted), theme


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
    card = view.index_for_event(1)

    widget.set_selected(1)
    assert _row_right_pixel(view, card, scale) == QColor(new_accent), theme

    widget.set_selected(None)
    _move_over_row(view, card)
    qtbot.wait(0)
    expected = _composite_over(surface, QColor(new_accent), _hover_alpha(QColor(new_accent)))
    assert _row_right_pixel(view, card, scale) == expected, theme


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_empty_hint_paints_the_muted_token(qtbot, tmp_path, theme):
    """No events → the explanatory hint text renders in the fg.muted token."""
    runtime = make_runtime(tmp_path, theme)
    widget = _widget(qtbot, runtime, [])
    hint = widget.rows_view.hint_label
    assert hint.text() == EMPTY_HINT_TEXT
    assert _contains_pixel(hint.grab().toImage(), token_color("color.fg.muted", theme)), theme
