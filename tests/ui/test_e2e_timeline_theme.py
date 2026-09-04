"""Pixel acceptance for the QML day-ladder island (task 6.2 mirror of the
retired widgets theme e2e): every color is a live token.

The panel moved to a ``QQuickWidget`` island (change port-event-timeline-qml-
island-q2-5a); the probe moved with it: pixels are read from ``quick.grab()``
at positions mapped through the visual tree (``walk_items`` + ``mapToScene``,
the same machinery the launcher island tests established). Painted now and
probed here: the event card wash (surface / accent selection / accent-
derivative hover — the wash pair the compiler derives, D8), the type dot —
exactly ``color.chart.k`` of the live theme (spec «Цвет типа равен токену»)
with untyped events landing on ``color.fg.muted`` (spec «Метка типа на
карточке»), the muted placeholder/gap/counter captions, the sticky band
(surface + accent hairline + fg.primary caption), the empty-state hint and
the live re-theme that keeps selection and scroll (spec «Живая ре-тема»).
Rewriting ``color.accent`` in a copied token file moves the selection and
the hover wash with no screen code touched (spec «Токен-инвариант шкалы»,
«Смена accent перекрашивает шкалу»; the «Вне скина» grep invariant lives in
``test_no_chrome_hex``).
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.presentation.theme.compiler import tokens_file_path
from app.presentation.viewmodels.timeline_viewmodel import TimelineViewModel
from app.presentation.views.timeline_island import TimelineWidget
from app.presentation.views.timeline_rows import ScaleUnit

from tests.presentation.qml_helpers import find_items, walk_items
from tests.ui.test_theme_grab import (
    _composite_over,
    _contains_pixel,
    make_runtime,
    token_color,
)

ROW_HOVER_ALPHA = 0.25  # the migrated wash alpha (qml_palette pin)


def _evt(id_, start, end=None, name=None, color_index=None):
    event = SimpleNamespace(id=id_, start_date=start, end_date=end, name=name or f"E{id_}")
    event.event_type = None if color_index is None else SimpleNamespace(color_index=color_index)
    return event


class _Service:
    def __init__(self, events):
        self._events = list(events)

    async def get_all_events(self):
        return list(self._events)


def _island(qtbot, runtime, events, size=(440, 260)):
    """A skinned island tape carrying ``events`` (seeded VM, no scheduler —
    the ``test_timeline_island`` pattern under a real QML root)."""
    vm = TimelineViewModel(_Service(events))
    vm._all_events = list(events)
    vm.events = list(events)
    vm._rebuild_rows()
    widget = TimelineWidget(vm, theme=runtime)
    qtbot.addWidget(widget)
    widget.resize(*size)
    widget.show()
    qtbot.waitExposed(widget)
    QTest.qWait(30)
    QApplication.processEvents()
    assert widget.quick.status() == widget.quick.Status.Ready, widget.quick.errors()
    # Park the synthetic cursor over inert chrome and balance a possible
    # stale held button bit from earlier tests in the process: with the
    # global state down, HoverHandler reads every synthetic move as a drag
    # and the card under the cursor never goes ``hovered``.
    QTest.mousePress(widget.quick, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, QPoint(1, 1))
    QTest.mouseRelease(widget.quick, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier, QPoint(1, 1))
    QTest.mouseMove(widget.quick, QPoint(1, 1))
    QTest.qWait(10)
    QApplication.processEvents()
    assert QApplication.instance().mouseButtons() == Qt.MouseButton.NoButton
    return widget, vm


def _grab(widget):
    return widget.quick.grab().toImage()


def _scale(widget) -> float:
    """Logical→device factor of the island grab (dpr 2 on Retina, 1 offscreen)."""
    return _grab(widget).width() / max(widget.quick.width(), 1)


def _delegate(widget, vm, idx: int):
    for it in walk_items(widget.quick.rootObject()):
        if it.objectName().endswith("Row") and it.property("kind") is not None \
                and it.property("index") == idx:
            return it
    raise AssertionError(f"row {idx} did not materialize")


def _reveal(widget, vm, idx: int):
    widget._root.scrollToIndex.emit(idx)
    QTest.qWait(20)
    QApplication.processEvents()
    return _delegate(widget, vm, idx)


def _scene(widget, it, fx: float, fy: float = 0.5) -> QPointF:
    return it.mapToScene(QPointF(it.width() * fx, it.height() * fy))


def _pixel(widget, it, fx: float, fy: float = 0.5) -> QColor:
    """The grabbed pixel under a fractional point of an item."""
    image = _grab(widget)
    scene = _scene(widget, it, fx, fy)
    scale = image.width() / max(widget.quick.width(), 1)
    return image.pixelColor(
        min(max(int(scene.x() * scale), 0), image.width() - 1),
        min(max(int(scene.y() * scale), 0), image.height() - 1),
    )


def _row_right_pixel(widget, vm, idx: int) -> QColor:
    """A no-text pixel of the row: the far right, clear of the elided text."""
    return _pixel(widget, _delegate(widget, vm, idx), fx=0.97)


def _type_dot_pixel(widget, vm, idx: int) -> QColor:
    """The pixel at the center of the type dot of the card at ``idx``."""
    delegate = _delegate(widget, vm, idx)
    dot = next(c for c in delegate.childItems()
               if c.objectName() == "eventTypeDot")
    return _pixel(widget, dot, fx=0.5, fy=0.5)


def _delegate_contains(widget, idx: int, color: QColor) -> bool:
    """True when any pixel inside row ``idx``'s bounds equals ``color``."""
    # The delegate may already be recycled away from the viewport; callers
    # reveal first (this raises honestly when they did not).
    image = _grab(widget)
    scale = image.width() / max(widget.quick.width(), 1)
    for it in walk_items(widget.quick.rootObject()):
        if it.property("index") == idx and it.objectName().endswith("Row") \
                and it.property("kind") is not None:
            top_left = it.mapToScene(QPointF(0, 0))
            bottom_right = it.mapToScene(QPointF(it.width(), it.height()))
            x0 = max(int(top_left.x() * scale), 0)
            y0 = max(int(top_left.y() * scale), 0)
            x1 = min(int(bottom_right.x() * scale), image.width() - 1)
            y1 = min(int(bottom_right.y() * scale), image.height() - 1)
            return any(
                image.pixelColor(x, y) == color
                for y in range(y0, y1 + 1)
                for x in range(x0, x1 + 1)
            )
    raise AssertionError(f"row {idx} is not under the viewport")


def _move_over(widget, it, fx: float = 0.5, fy: float = 0.5) -> None:
    """Rest the cursor over an item (the HoverHandler wash input)."""
    scene = _scene(widget, it, fx, fy)
    QTest.mouseMove(widget.quick, QPoint(int(scene.x()), int(scene.y())))
    QTest.qWait(10)
    QApplication.processEvents()


def _tokens_with_accent(tmp_path, theme: str, new_accent: str):
    """A copied token file with ``color.accent`` retargeted for one theme."""
    tokens = json.loads(tokens_file_path().read_text(encoding="utf-8"))
    tokens["color.accent"][theme] = new_accent
    path = tmp_path / f"tokens-{theme}.json"
    path.write_text(json.dumps(tokens), encoding="utf-8")
    return path


def _hover_wash(surface: QColor, accent: QColor) -> QColor:
    """The composite the delegate paints: accent at the migrated wash alpha.
    Exact channel rounding depends on Qt's raster path (opacity node vs the
    retired widget's fillRect differ by a channel unit), so this answers the
    analytic composite and ``_is_wash`` compares with a ±2 channel tolerance;
    the token-invariance direction (restyle the accent → the wash follows) is
    pinned exactly by ``test_accent_token_edit_recolors…``'s cross-checks."""
    a = ROW_HOVER_ALPHA
    return QColor(
        round(accent.red() * a + surface.red() * (1 - a)),
        round(accent.green() * a + surface.green() * (1 - a)),
        round(accent.blue() * a + surface.blue() * (1 - a)),
    )


def _is_wash(actual: QColor, surface: QColor, accent: QColor) -> bool:
    """``actual`` is the hover wash of ``accent`` over ``surface`` within the
    raster rounding (±2 per channel) — and not the unhovered surface itself
    (the wash always moves every channel of the token pair far more)."""
    if max(abs(actual.red() - surface.red()),
           abs(actual.green() - surface.green()),
           abs(actual.blue() - surface.blue())) <= 2:
        return False  # still the plain surface: hover not painted
    wanted = _hover_wash(surface, accent)
    return (abs(actual.red() - wanted.red()) <= 2
            and abs(actual.green() - wanted.green()) <= 2
            and abs(actual.blue() - wanted.blue()) <= 2)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_surface_selection_and_hover_are_accent_derivatives(qtbot, tmp_path, theme):
    """Header/card surface == surface token, selected card == accent, hovered
    card == the accent derivative wash (spec «Токен-инвариант шкалы»)."""
    runtime = make_runtime(tmp_path, theme)
    surface = token_color("color.bg.surface", theme)
    accent = token_color("color.accent", theme)
    widget, vm = _island(qtbot, runtime, [_evt(1, date(1200, 1, 1), date(1200, 1, 20), "З")])
    card = vm.index_for_event(1)  # row 0 is the day header
    assert card == 1
    _reveal(widget, vm, card)

    # unselected: neither the header nor the card paints a wash — surface
    assert _row_right_pixel(widget, vm, 0) == surface, theme
    assert _row_right_pixel(widget, vm, card) == surface, theme

    widget.set_selected(1)
    QTest.qWait(10)
    QApplication.processEvents()
    assert _row_right_pixel(widget, vm, card) == accent, theme  # accent itself

    widget.set_selected(None)
    QTest.qWait(10)
    QApplication.processEvents()
    _move_over(widget, _delegate(widget, vm, card), fx=0.97)
    deadline = 50
    while deadline:  # hover repaint may lag one frame offscreen
        if _is_wash(_row_right_pixel(widget, vm, card), surface, accent):
            break
        QTest.qWait(10)
        QApplication.processEvents()
        deadline -= 1
    assert _is_wash(_row_right_pixel(widget, vm, card), surface, accent), theme


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_type_dot_is_the_chart_token_muted_when_untyped(qtbot, tmp_path, theme):
    """Spec «Цвет типа равен токену» / «Метка типа на карточке»: the dot of a
    type-k card == color.chart.k of the live theme; no type → fg.muted dot."""
    runtime = make_runtime(tmp_path, theme)
    widget, vm = _island(qtbot, runtime, [
        _evt(1, date(1200, 1, 1), date(1200, 1, 1), "Слух", color_index=3),
        _evt(2, date(1200, 1, 2), date(1200, 1, 2), "Без типа"),
    ])
    typed = vm.index_for_event(1)
    untyped = vm.index_for_event(2)
    _reveal(widget, vm, max(typed, untyped))  # materialize both days
    assert _type_dot_pixel(widget, vm, typed) == token_color("color.chart.3", theme), theme
    assert _type_dot_pixel(widget, vm, untyped) == token_color("color.fg.muted", theme), theme


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_empty_placeholder_gap_and_counter_captions_use_the_muted_token(qtbot, tmp_path, theme):
    """«нет события» / collapsed-gap / «нет событий» rows paint fg.muted text."""
    runtime = make_runtime(tmp_path, theme)
    widget, vm = _island(qtbot, runtime, [
        _evt(1, date(1200, 1, 1), date(1200, 1, 1)),
        _evt(2, date(1200, 1, 3), date(1200, 1, 3)),
        _evt(3, date(1200, 3, 1), date(1200, 3, 1)),  # gap Jan 4 … Feb 29
    ])
    muted = token_color("color.fg.muted", theme)
    rows = list(vm.rows)
    empty_idx = next(i for i, r in enumerate(rows) if type(r).__name__ == "EmptyDayRow")
    gap_idx = next(i for i, r in enumerate(rows) if type(r).__name__ == "GapCollapsedRow")
    _reveal(widget, vm, empty_idx)
    assert _delegate_contains(widget, empty_idx, muted), theme
    _reveal(widget, vm, gap_idx)
    assert _delegate_contains(widget, gap_idx, muted), theme

    vm.level = ScaleUnit.MONTH
    QTest.qWait(20)
    QApplication.processEvents()
    rows = list(vm.rows)
    empty_period = next(
        i for i, r in enumerate(rows)
        if type(r).__name__ == "PeriodCardRow" and r.count == 0
    )
    _reveal(widget, vm, empty_period)
    assert _delegate_contains(widget, empty_period, muted), theme


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_sticky_band_is_surface_accent_and_primary_tokens(qtbot, tmp_path, theme):
    """Sticky date: surface band, accent hairline, fg.primary date text."""
    runtime = make_runtime(tmp_path, theme)
    widget, vm = _island(qtbot, runtime, [_evt(1, date(1200, 1, 1), date(1200, 1, 20), "З")])
    band = next(i for i in walk_items(widget.quick.rootObject())
                if i.objectName() == "stickyCurrent")
    assert band.property("visible") is True
    text = next(i for i in walk_items(widget.quick.rootObject())
                if i.objectName() == "stickyCurrentText")
    assert text.property("text")  # the top row's full game date (D3: Python says)
    image = _grab(widget)
    scale = image.width() / max(widget.quick.width(), 1)

    band_top = band.mapToScene(QPointF(0, 0)).y()
    assert image.pixelColor(int(4 * scale), int((band_top + 2) * scale)) == token_color(
        "color.bg.surface", theme
    ), theme
    assert _contains_pixel(_band_only(image, widget, band, scale),
                           token_color("color.fg.primary", theme)), theme
    hairline = token_color("color.accent", theme)
    bottom_scene = band.mapToScene(QPointF(0, band.height() - 0.5))
    bottom = int(bottom_scene.y() * scale)
    left = int(band.mapToScene(QPointF(0, 0)).x() * scale)
    right = int(band.mapToScene(QPointF(band.width(), 0)).x() * scale)
    assert any(image.pixelColor(x, bottom) == hairline
               for x in range(left, max(right, left + 1) + 1)), theme


def _band_only(image, widget, band, scale):
    """The sticky band's crop of the island grab."""
    top_left = band.mapToScene(QPointF(0, 0))
    bottom_right = band.mapToScene(QPointF(band.width(), band.height()))
    crop = image.copy(
        int(top_left.x() * scale), int(top_left.y() * scale),
        max(int((bottom_right.x() - top_left.x()) * scale), 1),
        max(int((bottom_right.y() - top_left.y()) * scale), 1),
    )
    return crop


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_accent_token_edit_recolors_the_scale_without_screen_changes(qtbot, tmp_path, theme):
    """A retargeted ``color.accent`` moves the selected fill and the hover wash."""
    new_accent = "#0f8c3c" if theme == "dark" else "#c00f2e"
    runtime = make_runtime(
        tmp_path, theme, tokens_path=_tokens_with_accent(tmp_path, theme, new_accent)
    )
    widget, vm = _island(qtbot, runtime, [_evt(1, date(1200, 1, 1), date(1200, 1, 20), "Бой")])
    surface = token_color("color.bg.surface", theme)
    card = vm.index_for_event(1)
    _reveal(widget, vm, card)

    widget.set_selected(1)
    QTest.qWait(10)
    QApplication.processEvents()
    assert _row_right_pixel(widget, vm, card) == QColor(new_accent), theme

    widget.set_selected(None)
    QTest.qWait(10)
    QApplication.processEvents()
    _move_over(widget, _delegate(widget, vm, card), fx=0.97)
    new = QColor(new_accent)
    old = token_color("color.accent", theme)  # shipped accent, superseded
    deadline = 50
    while deadline and not _is_wash(_row_right_pixel(widget, vm, card),
                                    surface, new):
        QTest.qWait(10)
        QApplication.processEvents()
        deadline -= 1
    washed = _row_right_pixel(widget, vm, card)
    assert _is_wash(washed, surface, new), theme
    # The shipped accent's wash would be a different, far pair of composites:
    # the tape follows the EDITED token, not the stock one (token invariance).
    assert not _is_wash(washed, surface, old), theme


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_empty_hint_paints_the_muted_token(qtbot, tmp_path, theme):
    """No events → the explanatory hint text renders in the fg.muted token."""
    runtime = make_runtime(tmp_path, theme)
    widget, vm = _island(qtbot, runtime, [])
    hint = find_items(widget.quick, "emptyHint")
    assert hint and hint[0].property("visible") is True
    assert _contains_pixel(_grab(widget), token_color("color.fg.muted", theme)), theme


def test_live_retheme_moves_tokens_and_keeps_selection_and_scroll(qtbot, tmp_path):
    """Spec «Живая ре-тема» + «Выбранное событие в обеих темах»: a theme flip
    repaints every derived color; selection and the reading position survive."""
    runtime = make_runtime(tmp_path, "dark")
    widget, vm = _island(qtbot, runtime, [
        _evt(i, date(1200, 1, 1) + timedelta(days=i),
             date(1200, 1, 1) + timedelta(days=i))
        for i in range(40)  # a scrollable week-plus tape
    ])
    card = vm.index_for_event(20)
    _reveal(widget, vm, card)
    widget.set_selected(20)
    QTest.qWait(10)
    QApplication.processEvents()
    before_theme = runtime.theme
    event_list = next(i for i in walk_items(widget.quick.rootObject())
                      if i.objectName() == "eventList")
    scroll_before = event_list.property("contentY")
    accent_before = token_color("color.accent", "dark")
    assert _row_right_pixel(widget, vm, card) == accent_before

    runtime.toggle()
    QTest.qWait(30)
    QApplication.processEvents()
    assert runtime.theme != before_theme

    # selection: the row still carries the wash of the OTHER theme's accent
    selected = [i for i in walk_items(widget.quick.rootObject())
                if i.property("kind") == "event" and i.property("index") == card]
    assert selected and selected[0].property("selectedRow") is True
    # scroll: the ListView did not move
    event_list = next(i for i in walk_items(widget.quick.rootObject())
                      if i.objectName() == "eventList")
    assert event_list.property("contentY") == scroll_before
    # pixels: the accent fill now answers the light-theme token
    assert _row_right_pixel(widget, vm, card) == token_color("color.accent", "light")
