"""Pixel acceptance for the QML FLAT-LIST island (simplify-event-timeline-flat-
list, task 5.2): every color of the flat row is a live token.

The panel is a ``QQuickWidget`` island (change port-event-timeline-qml-island-
q2-5a) whose ladder era (day cards, sticky band, gap placeholders, period
counters, drag ghost) was deleted with the ladder itself (REMOVED requirements
«Лента дней и карточки событий», «Липкий заголовок периода», «Окно, пустые
позиции и подсказки», «Перетаскивание события с выбором действия»). What is
painted and probed now is the flat row inside the bordered content field every
other column uses: the row surface (the field's ``color.bg.canvas`` over the
panel's ``color.bg.surface``), the selection wash (``color.accent`` itself) and
the hover wash (the accent under the row-wash alpha), the description line
(``color.fg.muted``, ``color.accent.fg`` when washed), the type mark — exactly
``color.chart.k`` of the live theme (spec «Цвет типа равен токену») with
untyped events landing on ``color.fg.muted`` (spec «Метка типа на строке»),
the single emptiness hint in ``color.fg.muted`` (spec «Событий ещё нет») and
the live re-theme that keeps selection and scroll (spec «Живая ре-тема»,
«Выбранное событие в обеих темах»). Rewriting ``color.accent`` in a copied
token file moves the selection and the hover wash with no screen code touched
(spec «Токен-инвариант шкалы»; the «вне скина» grep invariant lives in
``test_no_chrome_hex``).
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.presentation.theme.compiler import load_tokens, tokens_file_path
from app.presentation.viewmodels.timeline_viewmodel import TimelineViewModel
from app.presentation.views.timeline_island import TimelineWidget

from tests.presentation.qml_helpers import find_items, walk_items
from tests.ui.test_theme_grab import _contains_pixel, make_runtime, token_color

ROW_HOVER_ALPHA = 0.25  # the delegate's wash alpha (TimelineRowDelegate.qml)


def _evt(id_, start, end=None, name=None, color_index=None, description=None):
    event = SimpleNamespace(id=id_, start_date=start, end_date=end, name=name or f"E{id_}")
    event.event_type = None if color_index is None else SimpleNamespace(color_index=color_index)
    event.description = description
    return event


class _Service:
    def __init__(self, events):
        self._events = list(events)

    async def get_all_events(self):
        return list(self._events)


def _island(qtbot, runtime, events, size=(440, 260)):
    """A skinned flat-list island carrying ``events`` (seeded VM, no
    scheduler — the ``test_timeline_island`` pattern under a real QML root)."""
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
    # and the row under the cursor never goes ``hovered``.
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


def _delegate(widget, idx: int):
    """The materialized flat row for list index ``idx`` (the delegate's
    ``eventRow`` objectName contract, addressed by its delivered ``index``)."""
    for it in walk_items(widget.quick.rootObject()):
        if it.objectName() == "eventRow" and it.property("index") == idx:
            return it
    raise AssertionError(f"row {idx} did not materialize")


def _reveal(widget, idx: int):
    widget._root.scrollToIndex.emit(idx)
    QTest.qWait(20)
    QApplication.processEvents()
    return _delegate(widget, idx)


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


def _row_right_pixel(widget, idx: int) -> QColor:
    """A no-text pixel of the row: the far right, clear of the elided text."""
    return _pixel(widget, _delegate(widget, idx), fx=0.97)


def _detail_item(widget, idx: int):
    """The description line of the row at ``idx`` (may be invisible: a row with
    nothing to say paints no second line)."""
    delegate = _delegate(widget, idx)
    return next(i for i in delegate.childItems() if i.objectName() == "rowDetail")


def _field_color(theme: str) -> QColor:
    """The background the rows ride on: the canvas token of the bordered
    content field the list sits in (spec «Оформление списка из токенов»)."""
    return token_color("color.bg.canvas", theme)


def _wash_item(widget, idx: int):
    """The selection/hover wash rectangle of the row at ``idx``."""
    delegate = _delegate(widget, idx)
    return next(i for i in delegate.childItems() if i.objectName() == "rowWash")


def _radius_px(theme: str) -> float:
    """``radius.sm`` of the shipped token file, in px (``"6px"`` -> 6.0)."""
    return float(str(load_tokens(tokens_file_path())["radius.sm"][theme]).removesuffix("px"))


def _type_mark_pixel(widget, idx: int) -> QColor:
    """The pixel at the center of the type mark of the row at ``idx``."""
    delegate = _delegate(widget, idx)
    mark = next(c for c in delegate.childItems() if c.objectName() == "eventTypeMark")
    return _pixel(widget, mark, fx=0.5, fy=0.5)


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
    """The composite the delegate paints: accent at the row-wash alpha.
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


def _wait_wash(widget, idx: int, surface: QColor, accent: QColor) -> QColor:
    """Poll the row pixel until the hover wash paints (offscreen repaint may
    lag a frame); returns the last observed pixel for the caller's assert."""
    deadline = 50
    while deadline:
        pixel = _row_right_pixel(widget, idx)
        if _is_wash(pixel, surface, accent):
            return pixel
        QTest.qWait(10)
        QApplication.processEvents()
        deadline -= 1
    return _row_right_pixel(widget, idx)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_row_surface_selection_and_hover_are_accent_derivatives(qtbot, tmp_path, theme):
    """Row surface == surface token, selected row == accent, hovered row ==
    the accent derivative wash (spec «Токен-инвариант шкалы», одно событие —
    одна строка: ровно одна строка на событие, без карточек и периодов)."""
    runtime = make_runtime(tmp_path, theme)
    surface = _field_color(theme)  # the rows ride the content field, not the panel
    accent = token_color("color.accent", theme)
    widget, vm = _island(qtbot, runtime, [_evt(1, date(1200, 1, 1), date(1200, 1, 20), "З")])
    row = vm.index_for_event(1)
    assert row == 0  # flat list: the event's single row is row 0, no day heads
    assert len(vm.rows) == 1
    _reveal(widget, row)

    # unselected: the row paints no wash — the content field behind it
    assert _row_right_pixel(widget, row) == surface, theme

    widget.set_selected(1)
    QTest.qWait(10)
    QApplication.processEvents()
    assert _row_right_pixel(widget, row) == accent, theme  # accent itself

    # The field's rounded corners stay unbuilt by the wash: the LIST clips, the
    # card does not (a Rectangle clip is rectangular and would square the
    # accent off against the radius). The corner inside the card's bounds but
    # outside its rounded outline is never the accent.
    card = find_items(widget.quick, "timelineListCard")[0]
    corner = _pixel(widget, card, fx=0.012, fy=0.03)
    assert corner == _field_color(theme), (theme, corner.name())

    widget.set_selected(None)
    QTest.qWait(10)
    QApplication.processEvents()
    _move_over(widget, _delegate(widget, row), fx=0.97)
    washed = _wait_wash(widget, row, surface, accent)
    assert _is_wash(washed, surface, accent), theme


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_type_mark_is_the_chart_token_muted_when_untyped(qtbot, tmp_path, theme):
    """Spec «Цвет типа равен токену» / «Метка типа на строке»: the mark of the
    type-k row == color.chart.k of the live theme; no type → muted mark."""
    runtime = make_runtime(tmp_path, theme)
    widget, vm = _island(qtbot, runtime, [
        _evt(1, date(1200, 1, 1), date(1200, 1, 1), "Слух", color_index=3),
        _evt(2, date(1200, 1, 2), date(1200, 1, 2), "Без типа"),
    ])
    typed = vm.index_for_event(1)
    untyped = vm.index_for_event(2)
    _reveal(widget, max(typed, untyped))  # materialize both rows
    assert _type_mark_pixel(widget, typed) == token_color("color.chart.3", theme), theme
    assert _type_mark_pixel(widget, untyped) == token_color("color.fg.muted", theme), theme


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_accent_token_edit_recolors_the_list_without_screen_changes(qtbot, tmp_path, theme):
    """A retargeted ``color.accent`` moves the selected fill and the hover wash
    (spec «Токен-инвариант шкалы» — the list follows the tokens, not code)."""
    new_accent = "#0f8c3c" if theme == "dark" else "#c00f2e"
    runtime = make_runtime(
        tmp_path, theme, tokens_path=_tokens_with_accent(tmp_path, theme, new_accent)
    )
    widget, vm = _island(qtbot, runtime, [_evt(1, date(1200, 1, 1), date(1200, 1, 20), "Бой")])
    surface = _field_color(theme)
    row = vm.index_for_event(1)
    _reveal(widget, row)

    widget.set_selected(1)
    QTest.qWait(10)
    QApplication.processEvents()
    assert _row_right_pixel(widget, row) == QColor(new_accent), theme

    widget.set_selected(None)
    QTest.qWait(10)
    QApplication.processEvents()
    _move_over(widget, _delegate(widget, row), fx=0.97)
    new = QColor(new_accent)
    old = token_color("color.accent", theme)  # shipped accent, superseded
    washed = _wait_wash(widget, row, surface, new)
    assert _is_wash(washed, surface, new), theme
    # The shipped accent's wash would be a different, far pair of composites:
    # the list follows the EDITED token, not the stock one (token invariance).
    assert not _is_wash(washed, surface, old), theme


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_empty_hint_paints_the_muted_token(qtbot, tmp_path, theme):
    """No events → the single explanatory hint renders in the fg.muted token
    (spec «Событий ещё нет»: one hint, no placeholders per empty day)."""
    runtime = make_runtime(tmp_path, theme)
    widget, vm = _island(qtbot, runtime, [])
    hint = find_items(widget.quick, "emptyHint")
    assert hint and hint[0].property("visible") is True
    assert _contains_pixel(_grab(widget), token_color("color.fg.muted", theme)), theme


def test_live_retheme_moves_tokens_and_keeps_selection_and_scroll(qtbot, tmp_path):
    """Spec «Живая ре-тема» + «Выбранное событие в обеих темах»: a theme flip
    repaints every derived color; selection and the reading position survive."""
    runtime = make_runtime(tmp_path, "dark")
    events = [
        _evt(i, date(1200, 1, 1) + timedelta(days=i),
             date(1200, 1, 1) + timedelta(days=i))
        for i in range(20)
    ] + [
        _evt(20, date(1200, 1, 21), date(1200, 1, 21), "Типизированное",
             color_index=5),
    ] + [
        _evt(i, date(1200, 1, 1) + timedelta(days=i),
             date(1200, 1, 1) + timedelta(days=i))
        for i in range(21, 40)
    ]
    widget, vm = _island(qtbot, runtime, events)
    row = vm.index_for_event(20)
    _reveal(widget, row)
    widget.set_selected(20)
    QTest.qWait(10)
    QApplication.processEvents()
    before_theme = runtime.theme
    event_list = next(i for i in walk_items(widget.quick.rootObject())
                      if i.objectName() == "eventList")
    scroll_before = event_list.property("contentY")
    accent_before = token_color("color.accent", "dark")
    assert _row_right_pixel(widget, row) == accent_before

    runtime.toggle()
    QTest.qWait(30)
    QApplication.processEvents()
    assert runtime.theme != before_theme

    # selection: the SAME recycled delegate still carries the selection wash
    selected = [i for i in walk_items(widget.quick.rootObject())
                if i.objectName() == "eventRow" and i.property("index") == row]
    assert selected and selected[0].property("selectedRow") is True
    # scroll: the ListView did not move
    event_list = next(i for i in walk_items(widget.quick.rootObject())
                      if i.objectName() == "eventList")
    assert event_list.property("contentY") == scroll_before
    # pixels: the accent fill now answers the light-theme token
    assert _row_right_pixel(widget, row) == token_color("color.accent", "light")
    # …and so does the type mark of the same (visible, not recycled-away) row:
    # the chart tokens ride the same live palette bridge (spec «Живая ре-тема»
    # перекрашивает и метки типов; the mark keeps its color over the wash).
    assert _type_mark_pixel(widget, row) == token_color("color.chart.5", "light")


def test_a_neighbour_island_dying_does_not_strand_the_list_off_skin(qtbot, tmp_path):
    """Islands share the one process engine, so a facade must keep its token
    bridge out of the ENGINE root context: pushed under the global
    ``islandPalette`` name, the bridge is nulled for everyone when its own
    dialog dies and every other island falls back to the off-skin whites —
    the scale «becoming light theme» after ESC on the char-sheet list."""
    runtime = make_runtime(tmp_path, "dark")
    panel_surface = token_color("color.bg.surface", "dark")
    surface = _field_color("dark")  # the rows ride the bordered content field
    widget, vm = _island(qtbot, runtime, [_evt(1, date(1200, 1, 1), date(1200, 1, 20), "З")])
    assert _row_right_pixel(widget, vm.index_for_event(1)) == surface

    # A second island on the same engine, closed and destroyed the way a
    # dialog is (release the scene, then the deferred delete takes the facade
    # and the palette it owns with it).
    neighbour, _ = _island(qtbot, runtime, [])
    neighbour.quick.setSource(QUrl())
    neighbour.deleteLater()
    QApplication.processEvents()
    QApplication.processEvents()
    QTest.qWait(10)

    # Both token halves of the panel are still skinned after the neighbour died
    # (its palette leaving the shared engine must not strand this island off
    # skin): the panel surface, the content field the rows ride on.
    assert widget.quick.rootObject().property("surfaceColor") == panel_surface
    assert widget.quick.rootObject().property("canvasColor") == surface
    assert _row_right_pixel(widget, vm.index_for_event(1)) == surface


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_description_line_and_the_list_field_are_tokens(qtbot, tmp_path, theme):
    """Spec «Плоский список событий» + «Оформление списка из токенов»: the row's
    description line paints in the skin's one muted token ``color.fg.muted``
    (``color.accent.fg`` under
    the selection wash) over the list's CONTENT FIELD — the bordered, rounded
    canvas panel every other column puts its body in, which is what ties the
    rows to this column. The height follows the kind: the caption alone is the
    compact row, a description buys the detailed one."""
    runtime = make_runtime(tmp_path, theme)
    widget, vm = _island(qtbot, runtime, [
        _evt(1, date(1200, 1, 1), date(1200, 1, 20), "Совет",
             description=SimpleNamespace(
                 characteristics="мир, но ненадолго", backstory="")),
        _evt(2, date(1200, 2, 1), date(1200, 2, 2), "Без описания"),
    ])
    detailed = vm.index_for_event(1)
    compact = vm.index_for_event(2)
    _reveal(widget, compact)  # materialize both rows

    root = widget._root
    detailed_row = _delegate(widget, detailed)
    detail = _detail_item(widget, detailed)
    assert detail.property("text") == "мир, но ненадолго"
    assert detail.property("visible") is True
    assert detail.property("maximumLineCount") == 2  # a glimpse, not the whole text
    assert detailed_row.property("height") == root.property("detailedRowHeight")
    assert _delegate(widget, compact).property("height") == root.property("rowHeight")
    assert _detail_item(widget, compact).property("visible") is False

    assert detail.property("color") == token_color("color.fg.muted", theme), theme
    assert detail.property("color") != token_color(
        "color.fg.primary", theme), theme  # visibly the second-rank text

    # The list field: canvas background, hairline border, rounded corners — the
    # card role's own tokens, no invented color.
    card = find_items(widget.quick, "timelineListCard")[0]
    assert card.property("color") == _field_color(theme), theme
    assert card.property("borderColor") == token_color("color.border", theme), theme
    assert card.property("radius") > 0
    # The corner geometry pin: neither the card nor the list area clips
    # (a Rectangle clip is RECTANGULAR and would square the selected row's wash
    # off against the field's radius); the LIST clips, inset by the card's own
    # rounding, so a full-width wash never reaches a rounded corner or the
    # hairline border. The unbuilt corner itself is asserted by
    # ``test_row_surface_selection_and_hover_are_accent_derivatives``.
    assert card.property("clip") is False
    assert find_items(widget.quick, "timelineListArea")[0].property("clip") is False
    listView = find_items(widget.quick, "eventList")[0]
    assert listView.property("clip") is True
    # anchors.margins of the list == the card's radius (readable off the
    # geometry: the list is offset inside the 1-px inner area by exactly that)
    assert listView.property("x") == card.property("radius")
    assert listView.property("y") == card.property("radius")
    # The rows really live INSIDE that field (the pixel the grab answers is the
    # field's canvas, see the surface/selection tests above).
    assert _row_right_pixel(widget, detailed) in (
        _field_color(theme), token_color("color.accent", theme))

    widget.set_selected(1)
    QTest.qWait(10)
    QApplication.processEvents()
    assert detail.property("color") == token_color("color.accent.fg", theme), theme


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_row_wash_is_rounded_like_the_other_list_items(qtbot, tmp_path, theme):
    """Spec «Оформление списка из токенов»: the row's wash carries the card
    rounding (`radius.sm`) — every other list item in the skin wears it (the
    snapshot/detail rows ride the rounded `ThemeRatingCard`), only the
    timeline row used to paint a square accent block. The middle of the row
    still answers the accent token itself; the corner of the row's band,
    outside the rounded wash, keeps the field's canvas."""
    runtime = make_runtime(tmp_path, theme)
    surface = _field_color(theme)
    accent = token_color("color.accent", theme)
    widget, vm = _island(qtbot, runtime, [_evt(1, date(1200, 1, 1), date(1200, 1, 20), "З")])
    row = vm.index_for_event(1)
    _reveal(widget, row)
    widget.set_selected(1)
    QTest.qWait(10)
    QApplication.processEvents()

    wash = _wash_item(widget, row)
    assert wash.property("visible") is True, theme
    # The same rounding the content field's corners use — one token, both
    # halves pinned off the live objects (no literal drift possible).
    card = find_items(widget.quick, "timelineListCard")[0]
    assert wash.property("radius") == card.property("radius"), theme
    assert wash.property("radius") == _radius_px(theme), theme

    # Raster half: mid-edge is the accent verbatim, the corner pixel of the
    # row's band is not washed (the rounded corner lets the canvas through).
    delegate = _delegate(widget, row)
    assert _pixel(widget, delegate, fx=0.5) == accent, theme
    corner = _pixel(widget, delegate, fx=0.002, fy=0.06)
    assert corner == surface, (theme, corner.name())
