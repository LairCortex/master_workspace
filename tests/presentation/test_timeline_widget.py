"""Widget tests for the vertical day-scale timeline (W3b group 2: list + delegate).

Covers tasks 2.1–2.5 offscreen: id-contract signals and the inert empty day,
rail geometry (tick per day, once-per-month rotated label, span brackets on
lanes), token colors with a live re-theme that keeps selection and scroll,
the sticky-date overlay, and the public panel API (rebuilds only on a real
version change, idempotent external selection, scroll/jump navigation).
"""
from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QDate, QEvent, QModelIndex, QPoint, QPointF, Qt
from PySide6.QtGui import (
    QColor, QMouseEvent, QPainter, QWheelEvent,
)
from PySide6.QtWidgets import QApplication

from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation.theme import ThemeRuntime
from app.presentation.theme.compiler import token_rgb, tokens_file_path
from app.presentation.utils.date_utils import (
    format_game_date, get_custom_months, month_name, set_custom_months,
)
from app.presentation.viewmodels.timeline_viewmodel import EntityKind
from app.presentation.theme.compiler import CHART_TOKEN_KEYS
from app.presentation.views.timeline_widget import (
    BRACKET_LANE_STEP,
    BRACKET_SERIF_W,
    BRACKET_X0,
    DOT_SIZE,
    DRAG_START_THRESHOLD_PX,
    DRAG_WASH_ALPHA,
    EMPTY_HINT_TEXT,
    FILTER_CHIP_ALL,
    MONTH_SHORT_FORM,
    RAIL_FIXED_ZONE,
    RAIL_MIN_WIDTH,
    RAIL_TICK_LEN,
    ROLE_BRACKETS,
    ROLE_ROW,
    ROLE_SHOW_MONTH,
    ROLE_SHOW_TICK,
    ROW_HEIGHT,
    STICKY_HEIGHT,
    TEXT_LEFT_PAD,
    TimelineListView,
    TimelineWidget,
    bracket_lanes,
    filter_chip_text,
    rows_palette,
)
from app.presentation.views.timeline_rows import (
    SERIF_HIT_PX, RowKind, ScaleUnit, SerifTarget,
)


@pytest.fixture(autouse=True)
def _default_months():
    """Month names are process-global (date_utils); tests assert the default map."""
    saved = get_custom_months()
    set_custom_months(None)
    yield
    set_custom_months(saved)


def _evt(eid: int, start: date, end: date | None = None, name: str | None = None):
    return SimpleNamespace(id=eid, name=name or f"event-{eid}", start_date=start, end_date=end)


def _view(qtbot, events=(), theme=None, rows_visible=6):
    view = TimelineListView(theme=theme)
    view.resize(300, ROW_HEIGHT * rows_visible + STICKY_HEIGHT + 8)
    qtbot.addWidget(view)
    view.show()
    if events:
        view.update_events(events)
    return view


def _row_center(view, idx: int) -> QPoint:
    return view.visualItemRect(view.item(idx)).center()


def _click(view, idx: int, x: int | None = None) -> None:
    center = _row_center(view, idx)
    from PySide6.QtTest import QTest
    QTest.mouseClick(
        view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        QPoint(center.x() if x is None else x, center.y()),
    )


def _double_click(widget, point: QPoint) -> None:
    """Full press → release → dbl-click sequence (Qt emits ``doubleClicked``
    only for a dbl-click over a pressed index)."""
    for etype, buttons in (
        (QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
        (QEvent.Type.MouseButtonDblClick, Qt.MouseButton.LeftButton),
    ):
        QApplication.sendEvent(widget, QMouseEvent(
            etype, QPointF(point), widget.mapToGlobal(point),
            Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier,
        ))


def _press_only(widget, point: QPoint) -> None:
    """Bare left-button press at a viewport point (no release)."""
    QApplication.sendEvent(widget, QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(point), widget.mapToGlobal(point),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    ))


def _release_only(widget, point: QPoint) -> None:
    """Bare left-button release at a viewport point (pairs with _press_only)."""
    QApplication.sendEvent(widget, QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(point), widget.mapToGlobal(point),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    ))


def _move(widget, point: QPoint) -> None:
    """A plain (buttonless) hover move at a viewport point."""
    QApplication.sendEvent(widget, QMouseEvent(
        QEvent.Type.MouseMove, QPointF(point), widget.mapToGlobal(point),
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    ))


def _drag_move(widget, point: QPoint) -> None:
    """A move with the left button held down — the drag phase (W3c D2)."""
    QApplication.sendEvent(widget, QMouseEvent(
        QEvent.Type.MouseMove, QPointF(point), widget.mapToGlobal(point),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    ))


def _rail_point(view, idx: int) -> QPoint:
    """Middle of the rail zone against row ``idx`` (viewport coordinates)."""
    return QPoint(view.rail_width() // 2, _row_center(view, idx).y())


def _make_runtime(tmp_path, tokens_path=None) -> ThemeRuntime:
    return ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"),
        tokens_path=tokens_path or tokens_file_path(),
    )


@pytest.fixture
def line_spy(monkeypatch):
    """Capture QPointF ``QPainter.drawLine`` calls as (x0, y0, x1, y1)."""
    calls: list[tuple[float, float, float, float]] = []
    real = QPainter.drawLine

    def spy(self, *args):
        if len(args) == 2 and isinstance(args[0], QPointF) and isinstance(args[1], QPointF):
            calls.append((args[0].x(), args[0].y(), args[1].x(), args[1].y()))
        return real(self, *args)

    monkeypatch.setattr(QPainter, "drawLine", spy)
    return calls


@pytest.fixture
def text_spy(monkeypatch):
    """Capture every string drawn with ``QPainter.drawText`` + rotate angles."""
    texts: list[str] = []
    angles: list[float] = []
    real_text = QPainter.drawText
    real_rotate = QPainter.rotate

    def spy_text(self, *args, **kwargs):
        texts.extend(a for a in args if isinstance(a, str))
        return real_text(self, *args, **kwargs)

    def spy_rotate(self, angle):
        angles.append(float(angle))
        return real_rotate(self, angle)

    monkeypatch.setattr(QPainter, "drawText", spy_text)
    monkeypatch.setattr(QPainter, "rotate", spy_rotate)
    return texts, angles


# ── 2.1 — list model, fixed heights, id-contract signals ───────────────────

class TestListAndSignals:
    def test_canvas_is_fully_removed(self):
        """Task 2.1: the horizontal Gantt canvas is gone from the module."""
        import app.presentation.views.timeline_widget as mod

        assert not hasattr(mod, "TimelineCanvas")
        assert not hasattr(mod, "canvas_palette")

    def test_item_data_row_model_with_equal_fixed_heights(self, qtbot):
        """Task 2.1: itemData mirrors ``timeline_rows``; every row is ROW_HEIGHT."""
        events = [
            _evt(1, date(1200, 1, 1), name="A"),
            _evt(2, date(1200, 1, 1), name="B"),   # second event on the same day
            _evt(3, date(1200, 1, 3), name="C"),   # day 2 stays an empty placeholder
        ]
        view = _view(qtbot, events)
        assert view.count() == len(view.rows) == 4  # 1·A 1·B empty(2) 3·C
        for idx, row in enumerate(view.rows):
            assert view.item(idx).data(ROLE_ROW) == row
            rect = view.visualItemRect(view.item(idx))  # mixed text + empty stubs
            assert rect.height() == ROW_HEIGHT
        empty = view.item(2)
        assert not bool(empty.flags() & Qt.ItemFlag.ItemIsSelectable)
        assert not bool(empty.flags() & Qt.ItemFlag.ItemIsEnabled)

    def test_delegate_paints_line_and_open_end(self, qtbot, text_spy):
        """Task 2.1/spec: ``start — end · name``; open end renders ``start — ``.

        Wide on purpose — this test pins the *full* line text; elision (which
        moves the remainder into the tooltip) is covered separately below.
        """
        texts, _ = text_spy
        events = [
            _evt(1, date(1200, 1, 3), date(1200, 1, 3), name="Бой"),
            _evt(2, date(1200, 1, 6), None, name="Изгнание"),
        ]
        view = _view(qtbot, events)
        view.resize(560, view.height())
        view.grab()
        assert "03 Январь 1200 — 03 Январь 1200 · Бой" in texts
        assert "06 Январь 1200 — · Изгнание" in texts
        # Spec «Подсказка доступна и на подписанной полосе»: the tooltip is on
        # every event row, not only on elided ones.
        assert "Бой" in view.item(0).toolTip()
        assert "03 Январь 1200 — 03 Январь 1200" in view.item(0).toolTip()

    def test_line_is_elided_but_tooltip_keeps_name_and_range(self, qtbot, text_spy):
        """Spec «Tooltip при нехватке места»: elision never loses data."""
        texts, _ = text_spy
        long_name = "Очень долгое название события, которое не влезает в панель"
        events = [_evt(1, date(1200, 1, 2), date(1200, 1, 4), name=long_name)]
        view = _view(qtbot, events)
        view.resize(240, view.height())
        view.grab()
        assert any(t.endswith("…") and long_name not in t for t in texts)
        tip = view.item(0).toolTip()
        assert long_name in tip
        assert "02 Январь 1200 — 04 Январь 1200" in tip

    def test_click_event_row_emits_selected_id(self, qtbot):
        """Task 2.1 «клик по EVENT-row»: the signal carries the event id."""
        view = _view(qtbot, [_evt(7, date(1200, 1, 1)), _evt(8, date(1200, 1, 3))])
        received: list[int] = []
        view.event_selected.connect(received.append)
        _click(view, 0)
        assert received == [7]
        assert view.selected_id == 7
        assert view.selectedIndexes()[0].row() == 0

    def test_double_click_event_row_emits_id(self, qtbot):
        """Task 2.1 «dblclick эмитит id»."""
        view = _view(qtbot, [_evt(9, date(1200, 1, 1), date(1200, 1, 2))])
        received: list[int] = []
        view.event_double_clicked.connect(received.append)
        _double_click(view.viewport(), _row_center(view, 0))
        assert received == [9]

    def test_click_empty_day_emits_nothing_and_keeps_selection(self, qtbot):
        """Task 2.1/spec «Пустая позиция не выбирается»."""
        view = _view(qtbot, [_evt(1, date(1200, 1, 1)), _evt(2, date(1200, 1, 3))])
        received: list[int] = []
        view.event_selected.connect(received.append)
        _click(view, 0)
        assert received == [1]
        _click(view, 1)  # the empty day between the two events
        assert received == [1]  # nothing new reached the outside
        assert view.selected_id == 1
        assert view.selectedIndexes()[0].row() == 0  # the detail layer never moved

    def test_click_on_rail_never_selects_an_event(self, qtbot):
        """Spec «Нажатие в рейке не выбирает событие» (W3c replaced «декоративная»):
        the press against an event's line belongs to the rail — selection and
        id-signals untouched (the jump itself is covered in TestRailInteractivity)."""
        view = _view(qtbot, [_evt(5, date(1200, 1, 1))])
        received: list[int] = []
        view.event_selected.connect(received.append)
        _click(view, 0, x=2)
        assert received == []
        assert view.selected_id is None
        assert view.selectedIndexes() == []


# ── 2.2 — rail geometry: ticks, month labels, brackets ─────────────────────

class TestRailGeometry:
    def test_day_tick_sits_at_first_rows_top(self, qtbot, line_spy):
        """Task 2.2 «тикет ↔ позиция строки»: tick ↔ the day's first row."""
        events = [
            _evt(1, date(1200, 1, 1)), _evt(2, date(1200, 1, 1)),  # day 1: two rows
            _evt(4, date(1200, 1, 3)),                              # day 2: empty
        ]
        view = _view(qtbot, events)
        assert bool(view.item(0).data(ROLE_SHOW_TICK))
        assert not bool(view.item(1).data(ROLE_SHOW_TICK))  # same day, not re-ticked
        rail_w = view.rail_width()
        rail_w = view.rail_width()
        expected_tops = {
            idx: view.visualItemRect(view.item(idx)).top() for idx in (0, 2, 3)
        }
        assert bool(view.item(2).data(ROLE_SHOW_TICK)) and bool(view.item(3).data(ROLE_SHOW_TICK))
        view.grab()
        tick_y = {
            int(y0) for x0, y0, x1, y1 in line_spy
            if y0 == y1 and x0 >= rail_w - RAIL_TICK_LEN - 1 and x1 <= rail_w + 1
        }
        assert tick_y == {top for top in expected_tops.values()}

    def test_multiday_bracket_covers_every_spanned_day(self, qtbot, line_spy):
        """Task 2.2 «скобка многодневки покрывает её сутки» + serif ends."""
        view = _view(qtbot, [_evt(1, date(1200, 1, 1), date(1200, 1, 4), name="Поход")])
        segs = [view.item(i).data(ROLE_BRACKETS) for i in range(4)]
        # One segment per day of the span, all on the same lane (D6).
        assert [[s.lane for s in seg] for seg in segs] == [[0], [0], [0], [0]]
        assert segs[0][0].serif_top and not segs[0][0].serif_bottom
        assert segs[1][0] == segs[2][0] and not segs[1][0].serif_top
        assert segs[3][0].serif_bottom and not segs[3][0].serif_top
        view.grab()
        x = float(BRACKET_X0) + 0.5
        spans = sorted((y0, y1) for x0, y0, x1, y1 in line_spy
                       if x0 == x1 == x and y1 > y0)  # the vertical bracket strokes
        first = view.visualItemRect(view.item(0))
        last = view.visualItemRect(view.item(3))
        assert len(spans) == 4  # one stroke per day of the span
        assert spans[0][0] == pytest.approx(first.top() + 0.5, abs=0.01)
        assert spans[-1][1] == pytest.approx(last.bottom() - 0.5, abs=0.01)
        serifs = [
            y0 for x0, y0, x1, y1 in line_spy
            if x0 == x and abs(y1 - y0) < 0.01 and x1 - x0 == BRACKET_SERIF_W
        ]
        assert len(serifs) == 2  # start and end serif of the span

    def test_overlapping_brackets_take_neighbouring_lanes(self, qtbot):
        """Task 2.2 «пересекающиеся скобки — соседние дорожки рейки» (D6)."""
        view = _view(qtbot, [
            _evt(1, date(1200, 1, 1), date(1200, 1, 5)),
            _evt(2, date(1200, 1, 2), date(1200, 1, 6)),  # overlaps event 1
        ])
        assert (view.bracket_lane(1), view.bracket_lane(2)) == (0, 1)
        assert all(
            BRACKET_X0 + lane * BRACKET_LANE_STEP < view.rail_width() for lane in (0, 1)
        )
        # a span that starts after the previous one ended reuses the first lane
        view.update_events([
            _evt(1, date(1200, 1, 1), date(1200, 1, 3)),
            _evt(2, date(1200, 2, 1), date(1200, 2, 4)),
        ])
        assert (view.bracket_lane(1), view.bracket_lane(2)) == (0, 0)

    def test_one_day_event_owns_no_bracket_lane(self, qtbot):
        """Spec «Привязка событий к рейке»: a single day is marked by its tick."""
        view = _view(qtbot, [_evt(3, date(1200, 1, 9), date(1200, 1, 9))])
        assert view.bracket_lane(3) is None
        assert view.item(0).data(ROLE_BRACKETS) == ()
        assert bool(view.item(0).data(ROLE_SHOW_TICK))

    def test_month_label_once_per_month_rotated_climbing(self, qtbot, text_spy):
        """Spec «Подпись месяца один раз» + «поворот снизу вверх»; «Начало диапазона
        не является границей месяца»."""
        texts, angles = text_spy
        events = [_evt(1, date(1200, 6, 20), date(1200, 7, 3))]  # July 1 lands mid-list
        view = _view(qtbot, events, rows_visible=14)
        month_flags = [bool(view.item(i).data(ROLE_SHOW_MONTH)) for i in range(view.count())]
        assert month_flags.count(True) == 1
        first_july = month_flags.index(True)
        assert view.rows[first_july].date == date(1200, 7, 1)
        assert view.rows[0].date.day == 20  # range starts mid-month: no label there
        view.viewport().grab()
        labels = [t for t in texts if t and " · " not in t]
        assert labels == [format_game_date(date(1200, 7, 1))]  # full form: headroom above
        assert -90.0 in angles  # rotated bottom-to-top (climbs from its tick)

    def test_month_label_short_form_without_headroom(self, qtbot, text_spy):
        """Task 2.2 «короткая форма при нехватке места»: month first row at the top."""
        texts, _ = text_spy
        view = _view(qtbot, [_evt(1, date(1200, 7, 1), date(1200, 7, 3))], rows_visible=4)
        assert bool(view.item(0).data(ROLE_SHOW_MONTH))
        assert view.visualItemRect(view.item(0)).top() == 0  # no room to climb
        view.viewport().grab()
        labels = [t for t in texts if t and " · " not in t]
        assert labels == [f"{month_name(7)[:MONTH_SHORT_FORM]} 1200"]
        assert format_game_date(date(1200, 7, 1)) not in labels

    def test_rail_width_is_label_zone_floored_by_minimum_constant(self, qtbot):
        """Task 2.2 «ширина рейки = max(ширина подписей, константа-минимум)».

        A label rotated bottom-to-top occupies its font height horizontally; the
        rail reserves that zone plus the bracket/tick zone, floored by the
        constant (D6).
        """
        view = _view(qtbot, [_evt(1, date(1200, 1, 1))])
        expected = max(RAIL_MIN_WIDTH, RAIL_FIXED_ZONE + view.fontMetrics().height())
        assert view.rail_width() == expected


# ── 2.3 — token colors, live re-theme, off-skin ────────────────────────────

@pytest.fixture
def pen_colors(monkeypatch):
    """Capture every color the painter is set to during the test."""
    colors: list = []
    real_set_pen = QPainter.setPen

    def spy(self, *args):
        if args:
            pen = args[0]
            if isinstance(pen, QColor):
                colors.append(pen)
            elif hasattr(pen, "color"):
                colors.append(pen.color())
        return real_set_pen(self, *args)

    monkeypatch.setattr(QPainter, "setPen", spy)
    return colors


class TestTheme:
    def test_selected_pixel_is_accent_in_both_themes_and_choice_survives(
        self, qtbot, tmp_path
    ):
        """Task 2.3 «смена темы с выбранным событием» (spec «Живая ре-тема»)."""
        runtime = _make_runtime(tmp_path)
        events = [
            _evt(1, date(1200, 1, 1), date(1200, 1, 4)),
            _evt(2, date(1200, 1, 9), date(1200, 1, 10)),
        ]
        view = _view(qtbot, events, theme=runtime, rows_visible=3)
        view.set_selected(2)  # the last row: outside the visible area → scrolls there
        idx = view.index_for_event(2)
        scroll_before = view.verticalScrollBar().value()
        rect = view.visualItemRect(view.item(idx))
        x, y = view.rail_width() + 2, rect.top() + 2  # fill left of the text start

        dark_rgb = token_rgb(runtime.tokens, "dark", "color.accent")
        img = view.viewport().grab().toImage()
        assert img.pixelColor(x, y) == QColor(*dark_rgb)

        assert runtime.toggle() and runtime.theme == "light"
        light_rgb = token_rgb(runtime.tokens, "light", "color.accent")
        img = view.viewport().grab().toImage()
        rect = view.visualItemRect(view.item(idx))  # scroll preserved ⇒ same rect
        assert img.pixelColor(x, rect.top() + 2) == QColor(*light_rgb)
        # ...and the choice and the reading position are untouched by the switch
        assert view.selected_id == 2
        assert view.selectedIndexes()[0].row() == idx
        assert view.verticalScrollBar().value() == scroll_before
        assert QColor(*dark_rgb) != QColor(*light_rgb)  # the guard above has teeth

    def test_palette_is_token_derivatives_including_hover_alpha(self, qtbot, tmp_path):
        """Task 2.3 «цвета из токенов, альфы от accent_rgba» (D10)."""
        runtime = _make_runtime(tmp_path)
        view = _view(qtbot, [_evt(1, date(1200, 1, 1))], theme=runtime)
        palette = view.paint_palette()
        tokens, theme = runtime.tokens, runtime.theme
        rgb = lambda key: token_rgb(tokens, theme, key)  # noqa: E731
        assert (palette.rail.red(), palette.rail.green(), palette.rail.blue()) == rgb("color.border")
        assert (palette.bracket.red(), palette.bracket.green(), palette.bracket.blue()) == rgb("color.border")
        assert (palette.row_text.red(), palette.row_text.green(), palette.row_text.blue()) == rgb("color.fg.primary")
        assert (palette.month_text.red(), palette.month_text.green(),
                palette.month_text.blue()) == rgb("color.fg.muted")
        accent = rgb("color.accent")
        assert (palette.selected_fill.red(), palette.selected_fill.green(), palette.selected_fill.blue()) == accent
        assert palette.selected_fill.alphaF() == pytest.approx(1.0)
        assert (palette.hover_fill.red(), palette.hover_fill.green(), palette.hover_fill.blue()) == accent
        assert palette.hover_fill.alphaF() == pytest.approx(0.25, abs=0.02)

    def test_off_skin_without_runtime_uses_named_qt_globals(self):
        """Task 2.3/spec «Вне скина»: named Qt globals only, no invented hex."""
        palette = rows_palette(None)
        assert palette.row_text == QColor(Qt.GlobalColor.black)
        assert palette.selected_text == QColor(Qt.GlobalColor.white)
        assert palette.selected_fill == QColor(Qt.GlobalColor.gray)
        assert palette.hover_fill.alphaF() < 1.0

    def test_off_skin_palette_covers_the_w4_chart_and_unit_fields(self):
        """Task 7.2: the fields the W4 delegate added fall back to the same
        named Qt globals — all eight chart slots and both muted texts."""
        palette = rows_palette(None)
        gray = QColor(Qt.GlobalColor.gray)
        assert palette.unit_muted == gray
        assert palette.type_dot_muted == gray
        assert set(palette.type_dots) == set(CHART_TOKEN_KEYS)
        assert all(color == gray for color in palette.type_dots.values())

    def test_off_skin_delegate_paints_events_units_and_sections_on_qt_globals(
        self, qtbot, pen_colors
    ):
        """Task 7.2/spec «Вне скина» на пути делегата W4: без рантайма рисуются
        строка события с точкой типа (пиксель — Qt gray), позиции единиц/секций
        — тексты пенятся Qt-глобалами, падений нет."""
        events = [
            SimpleNamespace(
                id=1, name="Поход", start_date=date(1200, 1, 5), end_date=None,
                event_type=SimpleNamespace(name="Слух", color_index=3),
                characters=[SimpleNamespace(name="Анна")],
                locations=[], organizations=[], items=[],
            ),
            SimpleNamespace(
                id=2, name="Сход", start_date=date(1200, 1, 9), end_date=None,
                event_type=None, characters=[], locations=[],
                organizations=[], items=[],
            ),
        ]
        view = TimelineListView(theme=None)  # no runtime at all → off-skin
        view.resize(300, ROW_HEIGHT * 6 + STICKY_HEIGHT + 8)
        qtbot.addWidget(view)
        view.show()
        view.update_events(events)  # DAY rung: both type dots paint
        image = view.viewport().grab().toImage()
        scale = image.width() / max(view.viewport().width(), 1)
        gray = QColor(Qt.GlobalColor.gray)
        x_dot = int((view.rail_width() + TEXT_LEFT_PAD + DOT_SIZE // 2) * scale)
        for event_id in (1, 2):  # typed and untyped both degrade to gray
            rect = view.visualItemRect(view.item(view.index_for_event(event_id)))
            assert image.pixelColor(
                x_dot, int(rect.center().y() * scale)
            ) == gray, event_id

        # MONTH rung (no grouping): the filled unit and the muted empty stub
        # run through the same delegate paths, pens from Qt globals (D7).
        view.update_events(events, date(1200, 1, 1), date(1200, 2, 28))
        view.set_view(ScaleUnit.MONTH)
        view.viewport().grab().toImage()
        # SECTION headers follow (grouping on, still off-skin)
        view.set_view(group_by=EntityKind.CHARACTER)
        view.viewport().grab().toImage()
        kinds = {row.kind for row in view.rows}
        assert {RowKind.UNIT, RowKind.SECTION} <= kinds
        # black = filled unit / section / line text, gray = muted stub & rail
        assert QColor(Qt.GlobalColor.black) in pen_colors
        assert QColor(Qt.GlobalColor.gray) in pen_colors

    def test_unparsable_accent_token_falls_back_neutrally(self, qtbot, tmp_path):
        """Spec «Вне скина» (token unparsable): neutral Qt gray, never an invented color."""
        tokens = json.loads(tokens_file_path().read_text(encoding="utf-8"))
        tokens["color.accent"]["dark"] = "not-a-color"
        broken = tmp_path / "tokens.json"
        broken.write_text(json.dumps(tokens), encoding="utf-8")
        palette = rows_palette(_make_runtime(tmp_path, tokens_path=broken))
        assert palette.selected_fill.red() == palette.selected_fill.green()

    def test_widget_source_carries_no_palette_calls(self):
        """Task 2.3 «ни hex, ни palette()» — the hex half is the existing
        ``test_no_chrome_hex`` invariant; this closes the palette() half for us."""
        import app.presentation.views.timeline_widget as mod

        source = open(mod.__file__, encoding="utf-8").read()
        assert ".palette(" not in source
        assert "\n palette()" not in source


# ── 2.4 — sticky date overlay ──────────────────────────────────────────────

class TestStickyDate:
    def test_viewport_is_offset_by_the_sticky_band(self, qtbot):
        """D7: rows never hide behind the overlay — the viewport starts below it."""
        view = _view(qtbot, [_evt(1, date(1200, 1, 1))])
        assert view.viewport().y() >= STICKY_HEIGHT
        assert view.sticky_label.height() == STICKY_HEIGHT
        assert view.sticky_label.property("uiRole") == "title"

    def test_sticky_shows_top_row_and_changes_on_day_boundary(self, qtbot):
        """Task 2.4: date of the row under the top edge; only day changes move it."""
        events = [
            _evt(1, date(1200, 1, 1), name="A"),
            _evt(2, date(1200, 1, 1), name="B"),   # day 1: two rows
            _evt(3, date(1200, 1, 2), name="C"),   # day 2: two rows
            _evt(4, date(1200, 1, 2), name="D"),
        ]
        view = _view(qtbot, events, rows_visible=1)
        bar = view.verticalScrollBar()
        assert bar.maximum() >= 2  # room for the two steps below
        assert view.sticky_label.isVisible()
        assert view.sticky_label.text() == format_game_date(date(1200, 1, 1))
        bar.setValue(1)  # same day, second row — sticky must not move
        assert view.top_visible_index() == 1
        assert view.sticky_label.text() == format_game_date(date(1200, 1, 1))
        bar.setValue(2)  # crossed the day boundary
        assert view.top_visible_index() == 2
        assert view.sticky_label.text() == format_game_date(date(1200, 1, 2))

    def test_sticky_hidden_while_hint_stays_when_empty(self, qtbot):
        """Task 2.4 «скрыт при пустом списке (hint остаётся)»."""
        view = _view(qtbot, [_evt(1, date(1200, 1, 1))])
        view.update_events([_evt(9, date(1200, 2, 1))])  # still visible → sticky shown
        assert view.sticky_label.isVisible()
        view.update_events([])
        assert not view.sticky_label.isVisible()
        assert view.hint_label.isVisible()
        assert view.hint_label.text() == EMPTY_HINT_TEXT

    def test_sticky_updates_on_model_change_without_scroll(self, qtbot):
        """Task 2.4 «обновление по смене модели» — reload, no scrollbar movement."""
        view = _view(qtbot, [_evt(1, date(1200, 1, 1))])
        assert view.sticky_label.text() == format_game_date(date(1200, 1, 1))
        view.update_events([_evt(2, date(1200, 3, 5))])
        assert view.verticalScrollBar().value() == 0
        assert view.sticky_label.text() == format_game_date(date(1200, 3, 5))

    def test_overlays_never_eat_mouse_events(self, qtbot):
        """Spec «Липкая дата» (W3c clause «не перехватывать мышиные события»):
        the sticky band and the empty-state hint that replaces it stay
        transparent to the mouse — input can only belong to the list below."""
        view = _view(qtbot, [_evt(1, date(1200, 1, 1))])
        assert view.sticky_label.testAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        view.update_events([])
        assert view.hint_label.testAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)


# ── 2.5 — public panel API ─────────────────────────────────────────────────

class TestPanelApi:
    _SPREAD = None

    def test_external_selection_highlights_and_reveals(self, qtbot):
        """Task 2.5/spec «Выбор из поиска»: highlight + autoscroll to the row."""
        events = [
            _evt(1, date(1200, 1, 1), date(1200, 1, 2)),
            _evt(2, date(1200, 2, 15)),
        ]
        view = _view(qtbot, events, rows_visible=4)
        assert view.visualItemRect(view.item(view.index_for_event(2))).top() >= view.viewport().height()
        view.set_selected(2)
        idx = view.index_for_event(2)
        assert view.selectedIndexes()[0].row() == idx
        rect = view.visualItemRect(view.item(idx))
        assert 0 <= rect.top() and rect.bottom() <= view.viewport().height()

    def test_set_selected_is_idempotent_and_never_rebuilds(self, qtbot, mocker):
        """Task 2.5 «повторный set_selected не пересобирает»."""
        view = _view(qtbot, [_evt(1, date(1200, 1, 1), date(1200, 1, 3))])
        rebuild = mocker.spy(view, "_rebuild")
        rows_before = view.rows
        view.set_selected(1)
        view.set_selected(1)
        view.set_selected(None)
        view.set_selected(None)
        assert rebuild.call_count == 0
        assert view.rows is rows_before
        assert view.selected_id is None

    def test_update_events_rebuilds_only_when_the_set_version_moves(self, qtbot):
        """Task 2.5: rebuild iff (id, start, end, name) changed — never otherwise."""
        view = _view(qtbot)
        events = [_evt(1, date(1200, 1, 1))]
        view.update_events(events)
        v1 = view.rows
        view.update_events(list(events))  # new list, identical set
        assert view.rows is v1  # no rebuild
        view.update_events([_evt(1, date(1200, 1, 1), name="переименовано")])
        assert view.rows is not v1
        v2 = view.rows
        view.update_events([_evt(1, date(1200, 1, 1), name="переименовано"),
                            _evt(2, date(1200, 1, 9))])
        assert view.rows is not v2  # a new event moved the version again

    def test_rebuild_restores_scroll_from_selected_id(self, qtbot):
        """Task 2.5 «позиция скролла по выбранному id» on a real rebuild."""
        events = [
            _evt(1, date(1200, 1, 1), date(1200, 1, 2)),
            _evt(2, date(1200, 2, 20)),
        ]
        view = _view(qtbot, events, rows_visible=4)
        view.set_selected(2)
        idx = view.index_for_event(2)
        pos = view.visualItemRect(view.item(idx))
        view.update_events(events + [_evt(3, date(1200, 3, 1))])  # version moved → rebuild
        assert view.selected_id == 2
        rect = view.visualItemRect(view.item(idx))
        assert 0 <= rect.top() and rect.bottom() <= view.viewport().height()
        assert abs(rect.top() - pos.top()) <= ROW_HEIGHT  # reading position kept

    def test_rebuild_without_selection_rewinds_to_the_top(self, qtbot):
        """Risks note: a different set (another filter) opens from its first day."""
        events = [_evt(1, date(1200, 1, 1), date(1200, 1, 2)), _evt(2, date(1200, 2, 1))]
        view = _view(qtbot, events, rows_visible=4)
        view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
        assert view.verticalScrollBar().value() > 0
        view.update_events([_evt(9, date(1200, 9, 1))])  # different set, nothing selected
        assert view.verticalScrollBar().value() == 0

    def test_pruned_selection_drops_on_rebuild(self, qtbot):
        """Spec «Фильтр исключил выбранное»: the panel forgets a missing id."""
        view = _view(qtbot, [_evt(1, date(1200, 1, 1)), _evt(2, date(1200, 1, 5))])
        view.set_selected(2)
        view.update_events([_evt(1, date(1200, 1, 1))])  # event 2 excluded by the filter
        assert view.selected_id is None
        assert view.selectedIndexes() == []

    def test_scroll_to_event_brings_the_row_into_view(self, qtbot):
        view = _view(qtbot, [_evt(1, date(1200, 1, 1)), _evt(2, date(1200, 3, 1))], rows_visible=3)
        view.update_events([
            _evt(1, date(1200, 1, 1), date(1200, 2, 28)), _evt(2, date(1200, 3, 1)),
        ])
        idx = view.index_for_event(2)
        assert idx > 3  # far below the fold before scrolling
        assert view.visualItemRect(view.item(idx)).top() >= view.viewport().height()
        view.scroll_to_event(2)
        rect = view.visualItemRect(view.item(idx))
        assert 0 <= rect.top() and rect.bottom() <= view.viewport().height()

    def test_jump_next_skips_empty_days_prev_stays_inert_at_head(self, qtbot):
        """Task 2.5 (and D8): jump lands on EVENT rows, edges are inert."""
        events = [_evt(1, date(1200, 1, 1)), _evt(2, date(1200, 1, 10))]
        view = _view(qtbot, events, rows_visible=3)
        received: list[int] = []
        view.event_selected.connect(received.append)
        assert view.count() == 10  # empty corridor in between
        view.jump_next_event()
        assert view.currentRow() == 9
        rect = view.visualItemRect(view.item(9))
        assert 0 <= rect.top() and rect.bottom() <= view.viewport().height()
        # navigation alone neither selects nor emits (the detail layer stays put)
        assert received == [] and view.selected_id is None
        view.jump_prev_event()
        assert view.currentRow() == 0
        view.verticalScrollBar().setValue(0)
        view.jump_prev_event()  # at the head: nothing to skip to, no motion
        assert view.currentRow() == 0
        assert view.verticalScrollBar().value() == 0

# ── filter window: the live chip range decides the enumerated days ──────────

class TestFilterWindowOnTheScale:
    def test_explicit_range_enumerates_filter_days_empty_included(self, qtbot):
        """Spec «Пустые и фильтрационные состояния»: the filter's window is
        the scale's window — empty days inside it stay visible positions."""
        view = _view(qtbot)
        view.update_events(
            [_evt(1, date(1200, 1, 5), date(1200, 1, 6), name="A")],
            date(1200, 1, 1), date(1200, 1, 10),
        )
        assert [r.date for r in view.rows] == [date(1200, 1, d) for d in range(1, 11)]
        kinds = [r.kind for r in view.rows]
        assert kinds.count(RowKind.EVENT) == 1
        assert kinds.count(RowKind.EMPTY_DAY) == 9
        assert not view.hint_label.isVisible()  # empty day rows to show, no hint
        assert view.sticky_label.text() == format_game_date(date(1200, 1, 1))

    def test_empty_filter_range_shows_only_its_empty_days(self, qtbot):
        """Spec scenario «Пустой диапазон фильтра»: days without events are
        shown as empty positions of the filter's own range, not collapsed."""
        view = _view(qtbot)
        view.update_events([], date(1200, 2, 1), date(1200, 2, 3))
        assert [r.kind for r in view.rows] == [RowKind.EMPTY_DAY] * 3
        assert [r.date for r in view.rows] == [date(1200, 2, d) for d in (1, 2, 3)]

    def test_range_only_change_rebuilds_identical_samples(self, qtbot):
        """The version key carries the window: same events, another filter
        range = a different scale (must not hit the no-rebuild fast path)."""
        view = _view(qtbot)
        events = [_evt(1, date(1200, 1, 5))]
        view.update_events(events)
        rows_open = view.rows  # derived min–max: exactly the event's day
        assert len(rows_open) == 1
        view.update_events(list(events), date(1200, 1, 1), date(1200, 1, 8))
        assert view.rows is not rows_open
        assert len(view.rows) == 8
        view.update_events(list(events), date(1200, 1, 1), date(1200, 1, 8))
        assert view.rows is not rows_open  # identical window: no second rebuild

    def test_open_end_bracket_reaches_the_filter_range_end(self, qtbot):
        """Spec «Идущие события»: the open end binds to the last day of the
        *visible* range — with a filter that is the filter's end bound."""
        view = _view(qtbot)
        view.update_events([_evt(1, date(1200, 1, 2), None)], date(1200, 1, 1), date(1200, 1, 5))
        assert view.bracket_lane(1) == 0  # open span reaches the range end: a bracket
        segs = [view.item(i).data(ROLE_BRACKETS) for i in range(5)]
        assert [len(s) for s in segs[:5]] == [0, 1, 1, 1, 1]  # days 2..5 bracketed
        # the serif closes at the range's last day, not at any "current" date
        assert segs[1][0].serif_top and not segs[1][0].serif_bottom
        assert segs[4][0].serif_bottom

    def test_bracket_lanes_without_a_range_own_no_lane(self):
        """No enumerable range → no bracket can claim an end: nothing assigned."""
        assert bracket_lanes([_evt(1, date(1200, 1, 1), date(1200, 1, 5))], None) == {}

    def test_wheel_notch_moves_exactly_one_row(self, qtbot):
        """Spec scenario «Шаг прокрутки колеса»: one notch, one position."""
        events = [_evt(1, date(1200, 1, 1)), _evt(2, date(1200, 1, 30))]
        view = _view(qtbot, events, rows_visible=5)
        bar = view.verticalScrollBar()
        bar.setValue(0)
        center = QPointF(view.viewport().rect().center())

        def _wheel(angle: int) -> None:
            QApplication.sendEvent(view.viewport(), QWheelEvent(
                center, view.viewport().mapToGlobal(center.toPoint()),
                QPoint(0, 0), QPoint(0, angle),
                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase, False,
            ))

        _wheel(-120)
        assert bar.value() == 1  # one notch down == one row, no skipping
        _wheel(-120)
        assert bar.value() == 2
        _wheel(120)
        assert bar.value() == 1  # and back up, one row per notch as well

        def _h_wheel(angle_x: int) -> None:
            QApplication.sendEvent(view.viewport(), QWheelEvent(
                center, view.viewport().mapToGlobal(center.toPoint()),
                QPoint(angle_x, 0), QPoint(angle_x, 0),
                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase, False,
            ))

        _h_wheel(120)  # no vertical notch (e.g. a horizontal glide): no jump
        assert bar.value() == 1

    def test_leave_view_clears_the_hover_row(self, qtbot):
        """The accent hover wash follows the pointer off the list too."""
        view = _view(qtbot, [_evt(1, date(1200, 1, 1), date(1200, 1, 3))])
        center = _row_center(view, 0)
        QApplication.sendEvent(view.viewport(), QMouseEvent(
            QEvent.Type.MouseMove, QPointF(center), view.viewport().mapToGlobal(center),
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ))
        assert view.hover_index() == 0
        QApplication.sendEvent(view, QEvent(QEvent.Type.Leave))
        assert view.hover_index() == -1

    def test_scroll_to_unknown_id_is_an_inert_no_op(self, qtbot):
        """Public API contract: a miss neither moves nor raises."""
        view = _view(qtbot, [_evt(1, date(1200, 1, 1)), _evt(2, date(1200, 3, 1))], rows_visible=3)
        view.verticalScrollBar().setValue(2)
        before = view.verticalScrollBar().value()
        view.scroll_to_event(999)  # not in the sample
        assert view.verticalScrollBar().value() == before

    def test_panel_api_delegates_to_the_scale(self, qtbot):
        """Task 2.5: the public panel surface drives the list (id-contract kept)."""
        from unittest.mock import MagicMock

        vm = MagicMock()
        vm.events = []
        panel = TimelineWidget(vm)
        qtbot.addWidget(panel)
        events = [_evt(1, date(1200, 1, 1)), _evt(2, date(1200, 1, 8))]
        panel.update_events(events)
        panel.set_selected(1)
        assert panel.rows_view.selected_id == 1
        panel.set_selected(2)
        panel.scroll_to_event(2)
        panel.jump_prev_event()
        assert panel.rows_view.currentRow() == 0
        panel.jump_next_event()
        # event 2 starts 8 Jan → row 7 (one position per calendar day, D3/D4)
        assert panel.rows_view.currentRow() == 7


# ── W3c 3.1–3.4 — rail interactivity: click-jump, follow-дата, mute dblclick ─

class TestRailInteractivity:
    def test_rail_press_arms_without_selecting_or_emitting(self, qtbot):
        """Task 3.1: a press in the rail is armed and consumed — the base list
        never sees it, so nothing selects and no id-signal leaves the view."""
        view = _view(qtbot, [_evt(1, date(1200, 1, 1)), _evt(2, date(1200, 1, 4))])
        selected: list[int] = []
        doubled: list[int] = []
        view.event_selected.connect(selected.append)
        view.event_double_clicked.connect(doubled.append)
        # Qt defers the current-row assignment after a rebuild; read the base
        # value instead of hardcoding it — what matters is press/release phases.
        base_current = view.currentRow()
        _press_only(view.viewport(), _rail_point(view, 0))
        assert selected == [] and doubled == []
        assert view.selected_id is None
        assert view.currentRow() == base_current  # the press alone moves nothing
        _release_only(view.viewport(), _rail_point(view, 0))
        assert selected == [] and doubled == []
        assert view.selectedIndexes() == []  # selection never moved
        # The release jumped: day 1's row already sat at the top, so only the
        # current row (the jump anchor) moved onto it (D4).
        assert view.currentRow() == 0

    def test_release_past_threshold_does_not_jump(self, qtbot):
        """D2 click-phase boundary: a release past the drag-move threshold is
        the range-drag's territory (tasks 4.x) — it must not jump in the meantime."""
        view = _view(qtbot, [_evt(1, date(1200, 1, 1)), _evt(2, date(1200, 1, 3))])
        base_current = view.currentRow()
        point = _rail_point(view, 0)
        _press_only(view.viewport(), point)
        _release_only(view.viewport(), point + QPoint(0, DRAG_START_THRESHOLD_PX + 1))
        assert view.currentRow() == base_current  # no jump: no anchor moved
        assert view.verticalScrollBar().value() == 0
        assert view.selected_id is None
        assert view.selectedIndexes() == []

    def test_click_jump_scrolls_empty_day_to_top_keeping_selection(self, qtbot):
        """Spec «Клик по дню = прыжок скролла» + «Прыжок на пустой день»: the
        empty day clicked in the rail becomes the top row under the sticky
        date, while the selection stands and no id-signal is emitted."""
        events = [_evt(1, date(1200, 1, 1)), _evt(9, date(1200, 1, 8))]
        view = _view(qtbot, events, rows_visible=3)
        received: list[int] = []
        view.event_selected.connect(received.append)
        view.set_selected(1)  # day 1's event is the pre-existing selection
        _click(view, 2, x=view.rail_width() // 2)  # rail of day 3 — an empty day
        assert view.verticalScrollBar().value() == 2
        assert view.top_visible_index() == 2
        assert view.rows[2].kind == RowKind.EMPTY_DAY  # the jumped target was empty
        assert view.sticky_label.text() == format_game_date(date(1200, 1, 3))
        assert view.currentRow() == 2  # reading position moved with the day
        assert view.selected_id == 1  # selection and details never moved
        assert view.selectedIndexes()[0].row() == 0
        assert received == []

    def test_click_jump_anchors_first_row_of_multi_event_day(self, qtbot):
        """Spec «Якорь дня с несколькими событиями»: against day 2's *second*
        row the day's *first* row is what lands on top."""
        events = [
            _evt(1, date(1200, 1, 1)),
            _evt(2, date(1200, 1, 2), name="A"),
            _evt(3, date(1200, 1, 2), name="B"),
            _evt(4, date(1200, 1, 3)),
        ]
        view = _view(qtbot, events, rows_visible=3)
        received: list[int] = []
        view.event_selected.connect(received.append)
        _click(view, 2, x=view.rail_width() // 2)  # the day's second row
        assert view.verticalScrollBar().value() == 1  # day 2's first row on top
        assert view.top_visible_index() == 1
        assert view.currentRow() == 1  # reading anchor followed the day's head
        assert view.rows[view.top_visible_index()].date == date(1200, 1, 2)
        assert view.sticky_label.text() == format_game_date(date(1200, 1, 2))
        assert received == [] and view.selected_id is None

    def test_follow_sticky_shows_day_under_cursor_in_rail(self, qtbot):
        """Spec «Follow-дата под курсором» (task 3.3): hovering the rail
        rewrites the sticky text to the day under the cursor — while the
        hover-wash row keeps moving exactly as before."""
        events = [_evt(i, date(1200, 1, d)) for i, d in enumerate(range(1, 11), start=1)]
        view = _view(qtbot, events, rows_visible=3)
        view.verticalScrollBar().setValue(2)  # top row is day 3 — the sync text
        assert view.sticky_label.text() == format_game_date(date(1200, 1, 3))
        _move(view.viewport(), QPoint(view.rail_width() // 2, 60))
        # viewport y 60 → viewport row 2 → model row 4 → day 5 (a day the top
        # edge does not show) — the follow text, over the sync text (D5)
        assert view.hover_index() == 4  # the wash row moved as before
        assert view.sticky_label.text() == format_game_date(date(1200, 1, 5))

    def test_follow_resumes_top_row_after_leaving_the_rail(self, qtbot):
        """Spec «Возврат после выхода из рейки»: moving into the text zone, and
        leaving the list, hand the sticky back to the top row's date (no drag
        exists before tasks 4.x, so the leave always releases the follow)."""
        events = [_evt(i, date(1200, 1, d)) for i, d in enumerate(range(1, 11), start=1)]
        view = _view(qtbot, events, rows_visible=3)
        view.verticalScrollBar().setValue(2)
        rail_x = view.rail_width() // 2
        _move(view.viewport(), QPoint(rail_x, 60))
        assert view.sticky_label.text() == format_game_date(date(1200, 1, 5))
        _move(view.viewport(), QPoint(view.rail_width() + 12, 60))  # into the text
        assert view.sticky_label.text() == format_game_date(date(1200, 1, 3))
        assert view.hover_index() == 4  # the wash row is unaffected by the follow
        _move(view.viewport(), QPoint(rail_x, 60))  # back onto the rail
        assert view.sticky_label.text() == format_game_date(date(1200, 1, 5))
        QApplication.sendEvent(view, QEvent(QEvent.Type.Leave))
        assert view.hover_index() == -1
        assert view.sticky_label.text() == format_game_date(date(1200, 1, 3))

    def test_double_click_in_rail_stays_mute_on_event_row(self, qtbot):
        """Spec «Двойной клик в рейке глушится» + D8 (task 3.4): against an
        EVENT row's rail — no selection, no editing."""
        view = _view(qtbot, [_evt(8, date(1200, 1, 1), date(1200, 1, 3))])
        selected: list[int] = []
        doubled: list[int] = []
        view.event_selected.connect(selected.append)
        view.event_double_clicked.connect(doubled.append)
        _double_click(view.viewport(), _rail_point(view, 0))
        assert selected == [] and doubled == []
        assert view.selected_id is None
        assert view.selectedIndexes() == []


# ── W3c 4.1–4.3 — range drag: threshold machine, wash band, single apply ────

def _drag_applied(view) -> list[tuple]:
    """Record every ``day_range_applied`` emit of ``view``."""
    emitted: list[tuple] = []
    view.day_range_applied.connect(lambda start, end: emitted.append((start, end)))
    return emitted


def _spread_view(qtbot, rows_visible=3, scroll=3, theme=None):
    """A 12-day one-event-per-day scale row idx == day − 1, scrolled by default."""
    view = _view(
        qtbot,
        [_evt(i, date(1200, 1, d)) for i, d in enumerate(range(1, 13), start=1)],
        theme=theme,
        rows_visible=rows_visible,
    )
    view.verticalScrollBar().setValue(scroll)
    return view


class TestRangeDragStateMachine:
    """Task 4.1 (D2/D3/D5/D6): the threshold machine, its y-only visible clamp
    and the follow day it keeps; the apply semantics of the release are the
    next class's, the full acceptance runs are group 5's."""

    def test_move_before_threshold_arms_nothing_and_release_jumps(self, qtbot):
        """Task 4.1 «move до порога не создаёт диапазона»: sub-threshold moves
        never open a band, and the release still resolves as the click-jump."""
        view = _spread_view(qtbot)  # scroll 3: top visible row 3 = day 4
        emitted = _drag_applied(view)
        point = _rail_point(view, 5)  # day 6's rail
        _press_only(view.viewport(), point)
        _drag_move(view.viewport(), point + QPoint(0, DRAG_START_THRESHOLD_PX - 1))
        assert view.drag_range() is None  # 3 < threshold — no band
        _drag_move(view.viewport(), point - QPoint(0, DRAG_START_THRESHOLD_PX - 1))
        assert view.drag_range() is None  # neither above the press point
        _release_only(view.viewport(), point + QPoint(0, DRAG_START_THRESHOLD_PX - 1))
        assert emitted == []
        assert view.verticalScrollBar().value() == 5  # …it was the click-jump
        assert view.currentRow() == 5

    def test_move_past_threshold_opens_and_normalises_drag_range(self, qtbot):
        """D2/D6: the armed press past the threshold enters the drag mode; the
        band is normalize(anchor, day under cursor) — a bottom-up pair
        normalizes without inversion (spec «Drag снизу вверх нормализуется»)."""
        view = _spread_view(qtbot, rows_visible=5, scroll=2)
        emitted = _drag_applied(view)
        point = _rail_point(view, 5)  # day 6's rail
        _press_only(view.viewport(), point)
        # One pixel below the threshold still no band…
        _drag_move(view.viewport(), point + QPoint(0, DRAG_START_THRESHOLD_PX - 1))
        assert view.drag_range() is None
        # …exactly ON it opens, latched: a later move back under the threshold
        # keeps the drag alive.
        _drag_move(view.viewport(), point + QPoint(0, DRAG_START_THRESHOLD_PX))
        _drag_move(view.viewport(), point)
        assert view.drag_range() == (date(1200, 1, 6), date(1200, 1, 6))
        _drag_move(view.viewport(), QPoint(point.x(), _row_center(view, 6).y()))
        assert view.drag_range() == (date(1200, 1, 6), date(1200, 1, 7))
        # Only y is significant once dragging: the cursor left into the text
        # zone, x beyond the rail changes nothing, y picks day 4 → inverted
        # pair normalizes to (min, max).
        _drag_move(
            view.viewport(),
            QPoint(view.width() - 5, _row_center(view, 3).y()),
        )
        assert view.drag_range() == (date(1200, 1, 4), date(1200, 1, 6))
        # Moves emit nothing — the apply belongs to the release alone.
        assert emitted == []

    def test_release_outside_viewport_applies_last_visible_day(self, qtbot):
        """Spec «Границы drag'а ограничены видимым»: a cursor past the bottom
        edge (and a release outside the widget) applies the last VISIBLE day,
        the sticky follows the clamped day, and nothing autoscrolls."""
        view = _spread_view(qtbot)  # viewport rows: days 4, 5, 6 full + day 7 sliver
        emitted = _drag_applied(view)
        point = _rail_point(view, 5)  # anchor day 6
        _press_only(view.viewport(), point)
        below = view.viewport().height() + 30  # beyond the viewport's bottom edge
        _drag_move(view.viewport(), QPoint(point.x(), below))
        assert view.drag_range() == (date(1200, 1, 6), date(1200, 1, 7))
        assert view.sticky_label.text() == format_game_date(date(1200, 1, 7))
        scroll_before = view.verticalScrollBar().value()
        # The release itself beyond the widget edges — same clamped boundary.
        _release_only(view.viewport(), QPoint(point.x(), below + 40))
        assert emitted == [(date(1200, 1, 6), date(1200, 1, 7))]
        assert view.verticalScrollBar().value() == scroll_before  # no autoscroll
        assert view.selectedIndexes() == [] and view.selected_id is None

    def test_single_day_drag_resolves_to_the_click_jump(self, qtbot):
        """Task 4.3 «однодневный drag = клик», view half: a past-threshold
        drag that stayed on its day applies no filter — D4's jump instead."""
        view = _spread_view(qtbot, scroll=0)
        emitted = _drag_applied(view)
        point = _rail_point(view, 1)  # day 2's row spans viewport y 24..47
        _press_only(view.viewport(), point)
        _drag_move(view.viewport(), point + QPoint(0, DRAG_START_THRESHOLD_PX))
        assert view.drag_range() == (date(1200, 1, 2), date(1200, 1, 2))
        _release_only(view.viewport(), point + QPoint(0, DRAG_START_THRESHOLD_PX))
        assert emitted == []  # not a filter gesture
        assert view.drag_range() is None  # drag state gone with the gesture
        assert view.verticalScrollBar().value() == 1  # the click-jump ran
        assert view.currentRow() == 1

    def test_follow_sticky_wins_leaving_the_rail_and_view(self, qtbot):
        """Spec «Follow во время drag'а» (core of the D5 leave-guard): the
        sticky keeps the clamp-followed day across the rail's edge, the text
        zone and the whole-view Leave; after the release the hover rule is
        back in charge."""
        view = _spread_view(qtbot)
        emitted = _drag_applied(view)
        _press_only(view.viewport(), _rail_point(view, 5))  # anchor day 6
        text_point = QPoint(view.rail_width() + 40, 75)  # text zone over day 7's sliver
        _drag_move(view.viewport(), text_point)
        assert view.sticky_label.text() == format_game_date(date(1200, 1, 7))
        QApplication.sendEvent(view, QEvent(QEvent.Type.Leave))
        assert view.sticky_label.text() == format_game_date(date(1200, 1, 7))
        _release_only(view.viewport(), text_point)
        assert emitted == [(date(1200, 1, 6), date(1200, 1, 7))]
        # Drag over — the sticky returns to the top visible row's day (D5).
        assert view.sticky_label.text() == format_game_date(date(1200, 1, 4))


class TestRangeDragWashBand:
    """Task 4.2 (D6): the delegate paints the accent-derived wash band over
    every covered day — partially visible rows clip their slice — and the band
    is gone again with the drag."""

    def test_band_paints_covered_rows_including_partial(self, qtbot, tmp_path):
        runtime = _make_runtime(tmp_path)  # on-skin: wash is an accent derivative
        view = _spread_view(qtbot, theme=runtime)
        # visible: day 4 (y 0..23), day 5 (24..47), day 6 (48..71), day 7 (72..79)
        x = view.rail_width() + 3  # between the rail edge and the line text
        plain_before = view.viewport().grab().toImage().pixelColor(x, 36)
        _press_only(view.viewport(), _rail_point(view, 4))  # day 5…
        _drag_move(view.viewport(), QPoint(view.rail_width() // 2, 75))  # …→ day 7

        image = view.viewport().grab().toImage()
        pal = view.paint_palette()
        alpha = pal.drag_fill.alphaF()
        assert 0.0 < alpha < 1.0  # the wash is a translucent accent derivative
        base = pal.drag_fill
        blended = QColor(
            int(alpha * base.red() + (1 - alpha) * plain_before.red()),
            int(alpha * base.green() + (1 - alpha) * plain_before.green()),
            int(alpha * base.blue() + (1 - alpha) * plain_before.blue()),
        )
        for y in (36, 60):  # fully visible covered days 5 and 6
            got = image.pixelColor(x, y)
            for chan in ("red", "green", "blue"):
                assert abs(getattr(got, chan)() - getattr(blended, chan)()) <= 2
            assert (got.red(), got.green(), got.blue()) != (
                plain_before.red(), plain_before.green(), plain_before.blue(),
            )
        stripped = image.pixelColor(x, 75)  # partially visible covered day 7
        assert (stripped.red(), stripped.green(), stripped.blue()) != (
            plain_before.red(), plain_before.green(), plain_before.blue(),
        )
        # Days the drag does not cover wear nothing.
        assert image.pixelColor(x, 12) == plain_before  # day 4, out of the range

        _release_only(view.viewport(), QPoint(view.rail_width() // 2, 75))
        after = view.viewport().grab().toImage()
        assert after.pixelColor(x, 36) == plain_before  # band washed off with the drag

    def test_retheme_during_drag_repaints_band_without_touching_gesture(self,
                                                                        qtbot,
                                                                        tmp_path):
        """Task 5.3 «Live-retheme во время активного drag'а»: a live token flip
        mid-drag recolors the wash band pixels (new accent derivative), while
        the gesture range, the scroll position and a pre-existing selection
        all stand untouched."""
        runtime = _make_runtime(tmp_path)
        view = _spread_view(qtbot, theme=runtime)
        _click(view, 5)  # a pre-existing selection (day 6), text zone, row visible
        selection_row = view.selectedIndexes()[0].row()
        _press_only(view.viewport(), _rail_point(view, 4))
        _drag_move(view.viewport(), QPoint(view.rail_width() // 2, 60))
        old_wash = view.paint_palette().drag_fill.name()
        scroll_before = view.verticalScrollBar().value()
        x = view.rail_width() + 3  # inside the band, beside the line text
        wash_before = view.viewport().grab().toImage().pixelColor(x, 36)
        assert runtime.toggle()  # dark ↔ light through the runtime listener

        assert view.drag_range() == (date(1200, 1, 5), date(1200, 1, 6))
        assert view.paint_palette().drag_fill.name() != old_wash
        wash_after = view.viewport().grab().toImage().pixelColor(x, 36)
        assert wash_after != wash_before  # the band is visibly repainted, not just renamed
        assert view.verticalScrollBar().value() == scroll_before  # scroll intact
        assert view.selected_id == 6  # the selection was never reset
        assert view.selectedIndexes()[0].row() == selection_row

    def test_drag_wash_alpha_is_a_plain_constant_both_modes(self):
        """4.2: off-skin the band is the Qt-global with the same constant alpha,
        on-skin an accent derivative — no hex, no OS palette anywhere."""
        off = rows_palette(None)
        # QColor stores alpha as one 8-bit byte — compare a byte off, not a bit.
        assert off.drag_fill.alphaF() == pytest.approx(DRAG_WASH_ALPHA, abs=0.5 / 255)
        import app.presentation.views.timeline_widget as mod

        source = open(mod.__file__, encoding="utf-8").read()
        assert ".palette(" not in source  # the hex/.palette() gate stays honest


class TestRangeDragAppliesFilter:
    """Task 4.3 (D6/D7): the panel consumes ``day_range_applied`` through the
    very same ``_on_filter_range`` path — exactly one ``filter_changed`` per
    release, the chip mirrors it, an active filter is replaced wholesale, and
    the model rebuilds exactly once (no intermediate rebuilds while dragging)."""

    _ALL = [_evt(i, date(1200, 1, d)) for i, d in enumerate(range(1, 13), start=1)]

    def _wired_panel(self, qtbot, mocker):
        """The app-side mirror: filter_changed → ViewModel-like date-window
        filter → ``update_events`` into the same panel (see app wiring)."""
        from unittest.mock import MagicMock

        panel = TimelineWidget(MagicMock())
        qtbot.addWidget(panel)
        panel.resize(320, 420)  # tall enough for the gesture rows to sit on screen
        panel.show()
        received: list[tuple] = []

        def on_filter(start, end):
            received.append((start, end))
            keep = [
                e for e in self._ALL
                if start is None or (start <= e.start_date <= end)
            ]
            panel.update_events(keep)

        panel.filter_changed.connect(on_filter)
        panel.update_events(self._ALL)  # before the spy: the initial build is not the drag's
        rebuild = mocker.spy(panel.rows_view, "_rebuild")
        return panel, received, rebuild

    def test_release_applies_filter_once_chip_mirrors_model_rebuilds_once(self,
                                                                          qtbot,
                                                                          mocker):
        panel, received, rebuild = self._wired_panel(qtbot, mocker)
        view = panel.rows_view
        rows_before = view.rows
        _press_only(view.viewport(), _rail_point(view, 2))  # day 3
        target = QPoint(view.rail_width() // 2, _row_center(view, 3).y())  # day 4
        _drag_move(view.viewport(), target)
        # No intermediate applies and no model churn while the button is held.
        assert received == []
        assert view.rows is rows_before
        assert rebuild.call_count == 0

        _release_only(view.viewport(), target)
        assert received == [(date(1200, 1, 3), date(1200, 1, 4))]
        assert panel.filter_chip.text() == filter_chip_text(
            date(1200, 1, 3), date(1200, 1, 4)
        )
        assert panel._filter_range == (date(1200, 1, 3), date(1200, 1, 4))
        assert rebuild.call_count == 1  # the model version moved exactly once
        assert [row.date for row in view.rows] == [date(1200, 1, 3), date(1200, 1, 4)]

    def test_drag_over_active_filter_replaces_the_bounds_wholly(self, qtbot, mocker):
        """Spec «Перезапись активного фильтра»: the new range stands on its own,
        the old bounds neither extend nor survive."""
        panel, received, _ = self._wired_panel(qtbot, mocker)
        panel.filter_popup.range_applied.emit(date(1200, 1, 2), date(1200, 1, 9))
        assert received == [(date(1200, 1, 2), date(1200, 1, 9))]
        view = panel.rows_view  # window days 2..9, row idx == day − 2
        assert view.rows[0].date == date(1200, 1, 2) and view.rows[-1].date == date(1200, 1, 9)

        _press_only(view.viewport(), _rail_point(view, 2))  # day 4
        target = QPoint(view.rail_width() // 2, _row_center(view, 3).y())  # day 5
        _drag_move(view.viewport(), target)
        _release_only(view.viewport(), target)
        assert received[-1] == (date(1200, 1, 4), date(1200, 1, 5))
        assert panel._filter_range == (date(1200, 1, 4), date(1200, 1, 5))
        assert panel.filter_chip.text() == filter_chip_text(
            date(1200, 1, 4), date(1200, 1, 5)
        )
        assert [row.date for row in view.rows] == [date(1200, 1, 4), date(1200, 1, 5)]

    def test_chip_mirrors_drag_range_and_popover_opens_with_it(self, qtbot, mocker):
        """Spec «Чип зеркалит drag-диапазон»: after a rail-drag filter the chip
        shows the very drag's bounds in the game format and the popover reopens
        seeded with them — the same mirror a popover-set range gets."""
        panel, received, _ = self._wired_panel(qtbot, mocker)
        view = panel.rows_view
        _press_only(view.viewport(), _rail_point(view, 2))  # day 3
        target = QPoint(view.rail_width() // 2, _row_center(view, 4).y())  # day 5
        _drag_move(view.viewport(), target)
        _release_only(view.viewport(), target)
        assert received == [(date(1200, 1, 3), date(1200, 1, 5))]
        assert panel.filter_chip.text() == filter_chip_text(
            date(1200, 1, 3), date(1200, 1, 5)
        )  # the game-formatted mirror, «Все даты» fallback gone

        panel.filter_chip.click()  # the popover's own open path, unmodified
        assert panel.filter_popup.isVisible()
        assert panel.filter_popup.start_calendar.selectedDate() == QDate(1200, 1, 3)
        assert panel.filter_popup.end_calendar.selectedDate() == QDate(1200, 1, 5)

    def test_reset_restores_both_entrances_alike(self, qtbot, mocker):
        """Spec «Сброс касается обоих способов»: a drag-set filter clears
        through the popover's reset like the chip's own."""
        panel, received, _ = self._wired_panel(qtbot, mocker)
        view = panel.rows_view
        _press_only(view.viewport(), _rail_point(view, 1))  # day 2
        target = QPoint(view.rail_width() // 2, _row_center(view, 3).y())  # day 4
        _drag_move(view.viewport(), target)
        _release_only(view.viewport(), target)
        assert received[-1] == (date(1200, 1, 2), date(1200, 1, 4))

        panel.filter_popup.reset_button.click()
        assert received[-1] == (None, None)
        assert panel.filter_chip.text() == FILTER_CHIP_ALL
        assert [row.date for row in view.rows][0] == date(1200, 1, 1)
        assert [row.date for row in view.rows][-1] == date(1200, 1, 12)

    def test_single_day_drag_never_reaches_the_filter(self, qtbot, mocker):
        """Task 4.3: «однодневный drag = клик» on the panel — no emit, no chip
        touch, no rebuild; only the view scrolls."""
        panel, received, rebuild = self._wired_panel(qtbot, mocker)
        view = panel.rows_view
        chip_before = panel.filter_chip.text()
        _press_only(view.viewport(), _rail_point(view, 2))  # day 3, scroll 0
        under = QPoint(view.rail_width() // 2, _row_center(view, 2).y() + DRAG_START_THRESHOLD_PX)
        _drag_move(view.viewport(), under)
        _release_only(view.viewport(), under)
        assert received == []  # click, never a filter
        assert panel.filter_chip.text() == chip_before
        assert panel._filter_range == (None, None)
        assert view.verticalScrollBar().value() == 0  # the tall panel shows every row
        assert view.currentRow() == 2  # …so the jump shows up in the anchor only
        assert view.drag_range() is None
        assert rebuild.call_count == 0  # the click path never touches the model


# ── W3c group 5 — spec-scenario acceptance & input-channel invariants ───────

class TestScenarioAcceptanceW3c:
    """Tasks 5.1/5.2: the spec-delta scenarios whose dedicated tests the earlier
    groups left implicit (rail drag-continuation, bracket miss, visible-clamp
    from above), plus the «nothing else changed» half of 5.2 — the right button
    and modifier wheel keep their pre-W3c behavior, and there is no zoom."""

    def test_rail_drag_continuation_never_selects_or_opens_the_event(self, qtbot):
        """Spec «Нажатие в рейке не выбирает событие», drag continuation: a
        gesture that grew from a rail press through the threshold into a range
        drag still belongs to the rail — the pre-existing selection stays and
        not one id-signal leaves the view."""
        view = _view(
            qtbot,
            [_evt(1, date(1200, 1, 1)), _evt(2, date(1200, 1, 3))],
            rows_visible=3,
        )
        selected: list[int] = []
        doubled: list[int] = []
        applied: list[tuple] = []
        view.event_selected.connect(selected.append)
        view.event_double_clicked.connect(doubled.append)
        view.day_range_applied.connect(lambda s, e: applied.append((s, e)))
        view.set_selected(2)  # a pre-existing selection on day 3's row
        _press_only(view.viewport(), _rail_point(view, 0))  # rail, day 1
        _drag_move(view.viewport(), _row_center(view, 2))  # past the threshold
        assert view.drag_range() == (date(1200, 1, 1), date(1200, 1, 3))
        _release_only(view.viewport(), _row_center(view, 2))
        assert selected == [] and doubled == []  # the rail never touches the contract
        assert applied == [(date(1200, 1, 1), date(1200, 1, 3))]  # only its own channel
        assert view.selected_id == 2
        assert view.selectedIndexes()[0].row() == 2  # the details layer never moved

    def test_press_next_to_bracket_lands_on_the_day_not_the_event(self, qtbot):
        """Spec «Промах мимо привязки» (requirement «Привязка событий к рейке»):
        the bracket owns no hit-target — a press on the rail flush against a
        multi-day event's bracket is handled as its day (the click-jump ran),
        the event is neither selected nor opened."""
        view = _view(
            qtbot,
            [_evt(1, date(1200, 1, 1), date(1200, 1, 5), name="Поход")],
            rows_visible=3,
        )
        assert view.bracket_lane(1) == 0  # lane-0 stroke at BRACKET_X0 + 0.5
        selected: list[int] = []
        doubled: list[int] = []
        view.event_selected.connect(selected.append)
        view.event_double_clicked.connect(doubled.append)
        beside_bracket = QPoint(BRACKET_X0 + 4, _row_center(view, 2).y())
        _press_only(view.viewport(), beside_bracket)  # inside the bracket's serif
        _release_only(view.viewport(), beside_bracket)
        assert selected == [] and doubled == []
        assert view.selected_id is None and view.selectedIndexes() == []
        assert view.verticalScrollBar().value() == 2  # the day's jump ran instead
        assert view.top_visible_index() == 2
        assert view.currentRow() == 2

    def test_drag_past_top_edge_applies_first_visible_day(self, qtbot):
        """Spec «Границы drag'а ограничены видимым», the top edge (the existing
        bottom-edge twin lives in TestRangeDragStateMachine): a cursor dragged
        above the viewport clamps to the first visible day, a release there
        applies that boundary and nothing autoscrolls."""
        view = _spread_view(qtbot)  # scroll 3: top visible row 3 = day 4
        emitted = _drag_applied(view)
        point = _rail_point(view, 5)  # anchor day 6
        _press_only(view.viewport(), point)
        above = -30  # above the viewport's top edge
        _drag_move(view.viewport(), QPoint(point.x(), above))
        assert view.drag_range() == (date(1200, 1, 4), date(1200, 1, 6))
        assert view.sticky_label.text() == format_game_date(date(1200, 1, 4))
        scroll_before = view.verticalScrollBar().value()
        _release_only(view.viewport(), QPoint(point.x(), above - 20))
        assert emitted == [(date(1200, 1, 4), date(1200, 1, 6))]
        assert view.verticalScrollBar().value() == scroll_before  # no autoscroll
        assert view.selectedIndexes() == [] and view.selected_id is None

    def test_right_click_in_rail_never_arms_the_scale_gesture(self, qtbot):
        """Task 5.2 / spec «Правый клик … ведёт себя как до изменения»: the rail
        state machine arms on the left button only — a right press falls through
        to the plain list exactly as in W3b (no jump, no band, no rail apply)."""
        view = _spread_view(qtbot, scroll=0)
        emitted = _drag_applied(view)
        point = _rail_point(view, 2)  # day 3, fully visible: a jump would scroll to 2
        for etype in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            pressed = etype == QEvent.Type.MouseButtonPress
            QApplication.sendEvent(view.viewport(), QMouseEvent(
                etype, QPointF(point), view.viewport().mapToGlobal(point),
                Qt.MouseButton.RightButton,
                Qt.MouseButton.RightButton if pressed else Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            ))
        assert view.drag_range() is None  # never armed
        assert view.verticalScrollBar().value() == 0  # never jumped
        assert emitted == []  # the rail applied nothing

    def test_wheel_with_modifier_keeps_single_row_step_and_no_zoom(self, qtbot):
        """W4 rewrote this scenario half-by-half: «иные модификаторы шаг
        прокрутки менять НЕ SHALL» — Alt and Shift wheels still move exactly
        one row; «Ctrl/Cmd + колесо SHALL менять ступень … и SHALL не трогать
        прокрутку» — the Ctrl wheel steps the ladder instead of scrolling, and
        every row keeps its ROW_HEIGHT (continuous zoom still does not exist)."""
        events = [_evt(1, date(1200, 1, 1)), _evt(2, date(1200, 1, 30))]
        view = _view(qtbot, events, rows_visible=5)
        bar = view.verticalScrollBar()
        bar.setValue(0)
        center = QPointF(view.viewport().rect().center())

        def _wheel(angle: int, mods) -> None:
            QApplication.sendEvent(view.viewport(), QWheelEvent(
                center, view.viewport().mapToGlobal(center.toPoint()),
                QPoint(0, 0), QPoint(0, angle),
                Qt.MouseButton.NoButton, mods,
                Qt.ScrollPhase.NoScrollPhase, False,
            ))

        for mods in (Qt.KeyboardModifier.AltModifier,
                     Qt.KeyboardModifier.ShiftModifier):
            before = bar.value()
            _wheel(-120, mods)
            assert bar.value() == before + 1  # one row per notch, modifier or not
        # Ctrl zooms: the scrollbar never moves, the rung does.
        bar.setValue(0)
        _wheel(-120, Qt.KeyboardModifier.ControlModifier)  # wheel down = coarser
        assert bar.value() == 0
        assert view.scale_unit is ScaleUnit.MONTH
        _wheel(120, Qt.KeyboardModifier.ControlModifier)  # wheel up = finer
        assert bar.value() == 0
        assert view.scale_unit is ScaleUnit.DAY
        assert all(
            view.visualItemRect(view.item(i)).height() == ROW_HEIGHT
            for i in range(view.count())
        )  # no zoom: fixed heights survive every wheel chord


# ── defensive guards (project gate: changed files hold 100% line coverage) ──

class TestDefensiveGuards:
    def test_delegate_early_returns_without_row_item_data(self, qtbot):
        """An index carrying no ROLE_ROW paints nothing and never raises."""
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QStyleOptionViewItem

        view = _view(qtbot, [_evt(1, date(1200, 1, 1))])
        delegate = view.itemDelegate()
        painter = QPainter(QPixmap(16, 16))
        try:
            delegate.paint(painter, QStyleOptionViewItem(), QModelIndex())
        finally:
            painter.end()  # the guard path draws nothing — no crash, no pixels

    def test_event_id_at_invalid_index_is_none(self):
        """The id-contract extractor treats invalid indices as no event."""
        assert TimelineListView._event_id_at(QModelIndex()) is None

    def test_visible_cursor_day_without_rows_maps_to_no_day(self, qtbot):
        """The drag's y→day map answers ``None`` when there is no model to
        map onto — a gesture can never arm on an empty scale, so the guard
        only surfaces if the model empties under a held press."""
        view = _view(qtbot, [])
        assert view._visible_cursor_day(10) is None

    def test_refresh_sticky_keeps_text_without_row_data(self, qtbot):
        """The sticky funnel ignores a top-row item stripped of its row data."""
        view = _view(qtbot, [_evt(1, date(1200, 1, 1))])
        before = view.sticky_label.text()
        view.item(0).setData(ROLE_ROW, None)
        view._refresh_sticky_text()  # no raise, no text change, still shown
        assert view.sticky_label.text() == before
        assert view.sticky_label.isVisible()

    def test_jump_to_missing_row_is_an_inert_no_op(self, qtbot):
        """The rail jump guard: an index without an item neither moves nor raises."""
        view = _view(qtbot, [_evt(1, date(1200, 1, 1))])
        view._jump_to_day_row(view.count())  # one past the model
        assert view.verticalScrollBar().value() == 0
        assert view.currentRow() == view.currentRow()  # nothing moved anywhere


# ── W5 group 2 — the move gesture in TimelineListView ────────────────────────

def _moved(view) -> list[tuple]:
    """Record every ``event_dates_moved`` emit of ``view``."""
    emitted: list[tuple] = []
    view.event_dates_moved.connect(lambda eid, start, end: emitted.append((eid, start, end)))
    return emitted


def _selected(view) -> list:
    """Record every ``event_selected`` emit of ``view``."""
    ids: list = []
    view.event_selected.connect(ids.append)
    return ids


def _press_drag(view, start_point: QPoint, end_point: QPoint) -> None:
    """Press → latched drag-move → release: the whole move gesture."""
    vp = view.viewport()
    _press_only(vp, start_point)
    _drag_move(vp, end_point)
    _release_only(vp, end_point)


class TestEventMoveGesture:
    """W5 tasks 2.1–2.4 (D1/D2/D5/D6): a past-threshold press-drag on the text
    line of a *closed* EVENT row on the DAY rung becomes the move gesture —
    armed on press, previewed (never committed) on every move, committed once
    on release, cancelled by Esc or by an external row-model rebuild. An open
    event owns no gesture at all."""

    @staticmethod
    def _sample():
        """Jan 1…12 block: e2 closed 4…6 (row 3), e3 open on Jan 9 (row 8),
        one-day e1/e4 — row index == day − 1 throughout (≤1 event per day)."""
        return [
            _evt(1, date(1200, 1, 1)),
            _evt(2, date(1200, 1, 4), date(1200, 1, 6)),
            _evt(3, date(1200, 1, 9), None),
            _evt(4, date(1200, 1, 12)),
        ]

    def _view(self, qtbot, rows_visible=6, scroll=0):
        events = self._sample()
        view = _view(qtbot, events, rows_visible=rows_visible)
        view.verticalScrollBar().setValue(scroll)
        return view

    @staticmethod
    def _text_point(view, idx: int) -> QPoint:
        """A point in the text zone against row ``idx`` (never the rail)."""
        center = _row_center(view, idx)
        return QPoint(view.rail_width() + 40, center.y())

    # ── 2.1 — arming, threshold, the click stays a click, open rows inert ───

    def test_sub_threshold_press_release_still_selects_once(self, qtbot):
        """Task 2.1 «клик без порога выбирает как раньше»: press, jitter moves
        under DRAG_START_THRESHOLD_PX, release — the plain ``event_selected``
        click fires exactly once, no move signal, no preview state."""
        view = self._view(qtbot)
        moved, selected = _moved(view), _selected(view)
        point = self._text_point(view, 3)  # closed e2 line (Jan 4…6)
        _press_only(view.viewport(), point)
        assert view.edit_preview() is None  # arming alone never previews
        _drag_move(view.viewport(), point + QPoint(0, DRAG_START_THRESHOLD_PX - 1))
        assert view.edit_preview() is None
        _drag_move(view.viewport(), point - QPoint(0, DRAG_START_THRESHOLD_PX - 1))
        _release_only(view.viewport(), point)
        assert moved == []
        assert selected == [2]
        assert view.selected_id == 2
        assert view.edit_preview() is None

    def test_open_event_press_drag_emits_nothing(self, qtbot):
        """Spec «Тело бессрочного события не поднимается»: a press-drag on a
        continuation empty day of an open event arms no gesture."""
        view = self._view(qtbot, scroll=6)  # rows 6…11 visible, e3 at row 8
        moved, selected = _moved(view), _selected(view)
        point = self._text_point(view, 9)  # empty Jan 10 — body of open e3
        below = QPoint(point.x(), _row_center(view, 11).y())  # Jan 12
        _press_only(view.viewport(), point)
        _drag_move(view.viewport(), below)
        assert view.edit_preview() is None
        _release_only(view.viewport(), below)
        assert moved == []
        assert selected == []
        assert view.selected_id is None

    # ── 2.2 — the preview follows every move, data and model untouched ─────

    def test_moves_retarget_preview_through_scroll_without_touching_data(self, qtbot):
        """Task 2.2: each move recomputes ``_edit_preview`` through
        ``target_day`` (scroll included) and ``translate_span`` — two moves
        land the preview on the target days, duration intact; the events and
        the row model objects are never touched, nothing is emitted."""
        view = self._view(qtbot, scroll=2)
        moved = _moved(view)
        rows_before, events_before = view.rows, view.events
        point = self._text_point(view, 3)  # press the Jan 4 line
        _press_only(view.viewport(), point)
        # Move 1: down to row 6 (Jan 7) → the whole span shifts +3 days.
        first = QPoint(point.x(), _row_center(view, 6).y())
        _drag_move(view.viewport(), first)
        assert view.edit_preview() == (2, date(1200, 1, 7), date(1200, 1, 9))
        # Move 2: back up to row 5 (Jan 6) → +2 days, preview follows.
        second = QPoint(point.x(), _row_center(view, 5).y())
        _drag_move(view.viewport(), second)
        assert view.edit_preview() == (2, date(1200, 1, 6), date(1200, 1, 8))
        assert view.rows is rows_before
        assert view.events is events_before
        assert view.rows[3].start == date(1200, 1, 4)  # row model holds old dates
        assert moved == []
        _release_only(view.viewport(), second)  # hand the mouse back

    def test_sticky_follows_the_preview_target(self, qtbot):
        """D2/D6 support: while the move is latched the sticky shows the true
        target day, and the day-crossing arithmetic rides months (−3 days from
        Jan 4 crosses into the previous year's… same here: stays in game map)."""
        view = self._view(qtbot, scroll=0)
        point = self._text_point(view, 3)  # Jan 4
        _press_only(view.viewport(), point)
        _drag_move(view.viewport(), QPoint(point.x(), _row_center(view, 1).y()))  # Jan 2
        assert view.sticky_label.text() == format_game_date(date(1200, 1, 2))
        _release_only(view.viewport(), QPoint(point.x(), _row_center(view, 1).y()))

    # ── 2.3 — release commits exactly once, release beyond the tail commits ─

    def test_release_commits_exactly_once_with_duration_intact(self, qtbot):
        """Task 2.3: the release drops the gesture state *before* resolving
        (W3c-D6) and emits exactly one ``event_dates_moved`` with the closed
        shifted pair — ``end = start + duration``."""
        view = self._view(qtbot)
        moved = _moved(view)
        point = self._text_point(view, 3)  # e2: Jan 4…6, duration 2 days
        target = QPoint(point.x(), _row_center(view, 4).y())  # Jan 5
        _press_drag(view, point, target)
        assert moved == [(2, date(1200, 1, 5), date(1200, 1, 7))]
        assert view.edit_preview() is None  # the state is gone with the commit

    def test_release_below_the_viewport_commits_the_extrapolated_day(self, qtbot):
        """Spec «Цель за хвостом списка экстраполируется» + «Release вне списка
        — обычный commit»: released two pitches below the last model row the
        target is the last model day + 2 — a commit, not a cancel."""
        events = [_evt(i, date(1200, 1, d), date(1200, 1, d))
                  for i, d in enumerate(range(1, 13), start=1)]
        view = _view(qtbot, events, rows_visible=3)
        view.verticalScrollBar().setValue(9)  # days 10, 11, 12 visible
        moved = _moved(view)
        point = self._text_point(view, 9)  # day 10's closed one-day row
        # Content row index = (y + scroll·pitch) // pitch: y=104 with scroll 9
        # is row 13 — two pitches past the model tail (rows 0…11, day 12).
        _press_drag(view, point, QPoint(point.x(), 104))
        assert moved == [(10, date(1200, 1, 14), date(1200, 1, 14))]
        assert view.edit_preview() is None

    # ── 2.4 — Esc cancels; an external rebuild kills the gesture ──────────

    def test_escape_cancels_the_active_move_without_emitting(self, qtbot):
        """Spec «Отмена по Esc»: Esc while the move is latched drops the press
        and the preview; the later release commits nothing and clicks nothing."""
        from PySide6.QtGui import QKeyEvent

        view = self._view(qtbot)
        moved, selected = _moved(view), _selected(view)
        point = self._text_point(view, 3)
        target = QPoint(point.x(), _row_center(view, 4).y())
        vp = view.viewport()
        _press_only(vp, point)
        _drag_move(vp, target)
        assert view.edit_preview() is not None
        for etype in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QApplication.sendEvent(view, QKeyEvent(
                etype, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier,
            ))
        assert view.edit_preview() is None
        _release_only(vp, target)
        assert moved == []
        assert selected == []

    def test_escape_before_threshold_is_a_plain_no_op(self, qtbot):
        """D5 «до порога Esc и так ничего не значит»: with no latched move an
        Esc falls through to the list's own key handling and the press still
        resolves as the ordinary selection click."""
        from PySide6.QtGui import QKeyEvent

        view = self._view(qtbot)
        moved, selected = _moved(view), _selected(view)
        point = self._text_point(view, 3)
        _press_only(view.viewport(), point)
        for etype in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QApplication.sendEvent(view, QKeyEvent(
                etype, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier,
            ))
        assert view.edit_preview() is None
        _release_only(view.viewport(), point)
        assert moved == []
        assert selected == [2]

    def test_external_rebuild_during_the_drag_kills_the_gesture(self, qtbot):
        """Spec «Внешняя пересборка убивает жест»: a row-model rebuild during
        the move (``_rebuild`` resets the gesture like the rail states) leaves
        a dead gesture — the release writes nothing."""
        view = self._view(qtbot)
        moved, selected = _moved(view), _selected(view)
        point = self._text_point(view, 3)
        target = QPoint(point.x(), _row_center(view, 4).y())
        vp = view.viewport()
        _press_only(vp, point)
        _drag_move(vp, target)
        assert view.edit_preview() is not None
        # An outside reload rebuilds the model (e4 moves) — the gesture dies.
        moved_sample = self._sample()
        moved_sample[3] = _evt(4, date(1200, 1, 11))
        view.update_events(moved_sample)
        assert view.edit_preview() is None
        _release_only(vp, target)
        assert moved == []
        assert selected == []


# ── W5 group 3 — the end-stretch gesture on the bottom serif ─────────────────

class TestEventEndStretchGesture:
    """W5 tasks 3.1–3.2 (D1/D8): a press inside the bottom serif's hit zone of
    a *closed multi-day* bracket arms the end-stretch **before** the rail
    branch — past-threshold moves preview ``end`` at the day under the cursor
    clamped to ``end ≥ start``, and the release commits exactly one
    ``event_dates_moved`` keeping the old start. Open ends, one-day spans and
    x-misses beside the serif all stay the rail's (jump / range-drag)."""

    @staticmethod
    def _sample():
        """The W5 group-2 quartet: closed multi-day e2 (Jan 4…6, lane → serif
        on row 5), open e3 draws its (decorative) serif at the window tail,
        one-day e1/e4 own no lane and no handle at all."""
        return [
            _evt(1, date(1200, 1, 1)),
            _evt(2, date(1200, 1, 4), date(1200, 1, 6)),
            _evt(3, date(1200, 1, 9), None),
            _evt(4, date(1200, 1, 12)),
        ]

    def _view(self, qtbot, rows_visible=6, scroll=0):
        view = _view(qtbot, self._sample(), rows_visible=rows_visible)
        view.verticalScrollBar().setValue(scroll)
        return view

    @staticmethod
    def _serif_point(view, event_id: int, offset_x: int = 0) -> QPoint:
        """Point at the painted bottom serif of ``event_id`` (its end day's row,
        its bracket lane's center x plus ``offset_x``) — all public geometry."""
        end = view.rows[view.index_for_event(event_id)].end
        row = max(i for i, r in enumerate(view.rows) if r.date == end)
        x = BRACKET_X0 + view.bracket_lane(event_id) * BRACKET_LANE_STEP + offset_x
        return QPoint(x, _row_center(view, row).y())

    @staticmethod
    def _day_y(view, idx: int) -> int:
        """Viewport y of row ``idx``'s center at the current scroll — valid
        also for rows outside the viewport (the target extrapolates there)."""
        return idx * ROW_HEIGHT + ROW_HEIGHT // 2 \
            - ROW_HEIGHT * view.verticalScrollBar().value()

    # ── 3.1 — arming above the rail branch, target end with the clamp ───────

    def test_serif_pull_two_days_previews_the_new_end(self, qtbot):
        """Task 3.1 «тяга на +2 суток даёт preview с новым end»: the pull
        retargets only the end — old start held, data and row model untouched,
        nothing emitted while the button is down."""
        view = self._view(qtbot)
        moved = _moved(view)
        rows_before, events_before = view.rows, view.events
        point = self._serif_point(view, 2)  # Jan 6's serif, lane of e2
        _press_only(view.viewport(), point)
        assert view.edit_preview() is None  # arming alone never previews
        below = QPoint(point.x(), self._day_y(view, 7))  # Jan 8
        _drag_move(view.viewport(), below)
        assert view.edit_preview() == (2, date(1200, 1, 4), date(1200, 1, 8))
        assert moved == []
        assert view.rows is rows_before and view.events is events_before
        assert view.rows[3].end == date(1200, 1, 6)  # model keeps the old end
        _release_only(view.viewport(), below)

    def test_pull_above_the_start_clamps_end_to_start(self, qtbot):
        """Spec «Конец не переезжает начало»: a pull past the start day previews
        ``end == start`` — the gesture never turns into moving the start."""
        view = self._view(qtbot)
        moved = _moved(view)
        point = self._serif_point(view, 2)
        _press_only(view.viewport(), point)
        above = QPoint(point.x(), self._day_y(view, 1))  # Jan 2 < Jan 4
        _drag_move(view.viewport(), above)
        assert view.edit_preview() == (2, date(1200, 1, 4), date(1200, 1, 4))
        _release_only(view.viewport(), above)
        assert moved == [(2, date(1200, 1, 4), date(1200, 1, 4))]  # committed clamped

    def test_serif_press_without_move_jumps_nothing(self, qtbot):
        """Spec «Интерактив рейки» (hit-зона вычтена): a press inside the serif's
        zone belongs to the stretch — a sub-threshold press+release neither
        jumps the day nor drags the filter nor commits anything."""
        view = self._view(qtbot)
        moved, selected = _moved(view), _selected(view)
        point = self._serif_point(view, 2)
        _press_only(view.viewport(), point)
        _drag_move(view.viewport(), point + QPoint(0, DRAG_START_THRESHOLD_PX - 1))
        assert view.edit_preview() is None
        _release_only(view.viewport(), point)
        assert moved == [] and selected == []
        assert view.currentRow() == -1  # a rail click-jump would anchor row 5
        assert view.verticalScrollBar().value() == 0

    def test_open_event_serif_press_goes_to_the_rail_jump(self, qtbot):
        """Spec «Засечка открытой скобки не ручка»: pressing exactly where the
        open e3 draws its tail serif arms no stretch — the rail owns the press
        and the release jumps that day as always."""
        view = self._view(qtbot, scroll=6)  # row 11 (Jan 12) visible at the tail
        moved, selected = _moved(view), _selected(view)
        point = QPoint(
            BRACKET_X0 + view.bracket_lane(3) * BRACKET_LANE_STEP,
            _row_center(view, 11).y(),
        )
        _press_only(view.viewport(), point)
        _release_only(view.viewport(), point)
        assert view.edit_preview() is None
        assert moved == [] and selected == []
        assert view.currentRow() == 11  # the rail jump ran instead

    def test_miss_beside_the_serif_stays_the_rail_drag(self, qtbot):
        """Spec «Промах мимо засечки остаётся рейкой»: one pixel outside the
        hit radius (``SERIF_HIT_PX`` inclusive inside) the ordinary rail
        range-drag runs — one ``day_range_applied``, no stretch preview."""
        view = self._view(qtbot)
        moved = _moved(view)
        applied: list = []
        view.day_range_applied.connect(lambda start, end: applied.append((start, end)))
        point = self._serif_point(view, 2, offset_x=SERIF_HIT_PX + 1)
        _press_only(view.viewport(), point)
        up = QPoint(point.x(), _row_center(view, 3).y())  # Jan 4
        _drag_move(view.viewport(), up)
        assert view.edit_preview() is None
        _release_only(view.viewport(), up)
        assert moved == []
        assert applied == [(date(1200, 1, 4), date(1200, 1, 6))]

    # ── 3.2 — release commits exactly once; one-day spans stay mute ────────

    def test_release_commits_exactly_once_with_the_old_start(self, qtbot):
        """Task 3.2: the release emits one ``event_dates_moved`` carrying the
        OLD start and the new end, and drops the preview state with the commit."""
        view = self._view(qtbot)
        moved = _moved(view)
        point = self._serif_point(view, 2)
        target = QPoint(point.x(), self._day_y(view, 7))  # Jan 8
        _press_drag(view, point, target)
        assert moved == [(2, date(1200, 1, 4), date(1200, 1, 8))]
        assert view.edit_preview() is None

    def test_one_day_event_arms_no_stretch(self, qtbot):
        """Spec «Однодневное нельзя растянуть»/e2e-немота: a one-day closed event
        owns no handle — its rail press+drag applies the rail range instead and
        the date-commit channel stays silent."""
        view = self._view(qtbot)
        moved = _moved(view)
        applied: list = []
        view.day_range_applied.connect(lambda start, end: applied.append((start, end)))
        point = _rail_point(view, 0)  # one-day e1 (Jan 1) — no lane, no serif
        below = QPoint(point.x(), _row_center(view, 2).y())  # Jan 3
        _press_only(view.viewport(), point)
        _drag_move(view.viewport(), below)
        assert view.edit_preview() is None
        _release_only(view.viewport(), below)
        assert moved == []
        assert applied == [(date(1200, 1, 1), date(1200, 1, 3))]  # rail handled it

    def test_forged_serif_target_without_an_event_row_stays_rail(self, qtbot):
        """Defensive guard: a serif map entry whose event owns no row (a forged
        future desync) must fall through to the rail instead of arming."""
        view = self._view(qtbot)
        point = self._serif_point(view, 2)
        view._serif_target_by_row = {5: (SerifTarget(event_id=99, row_index=5, lane=0),)}
        _press_only(view.viewport(), point)
        _release_only(view.viewport(), point)
        assert view.edit_preview() is None
        assert view.currentRow() == 5  # the rail jump handled the press instead


class TestEventMoveGrabOffset:
    """W5 2.5: delta is target − grab-row day, not target − event.start."""

    def test_mid_body_grab_shifts_relative_to_the_grab_row(self, qtbot):
        """Spec «Перенос многодневки сохраняет длительность (grab-offset)»:
        3–10 March grabbed on the 5th, released against the 12th → 10–17."""
        events = [_evt(1, date(1200, 3, 3), date(1200, 3, 10))]
        view = _view(qtbot, (), rows_visible=18)
        view.update_events(events, date(1200, 3, 3), date(1200, 3, 20))
        moved = _moved(view)
        grab = QPoint(view.rail_width() + 40, _row_center(view, 2).y())  # Mar 5
        release = QPoint(grab.x(), _row_center(view, 9).y())  # Mar 12
        _press_drag(view, grab, release)
        assert moved == [(1, date(1200, 3, 10), date(1200, 3, 17))]

    def test_threshold_preview_matches_the_original_span(self, qtbot):
        """Spec «Захват за середину не телепортирует событие»."""
        events = [_evt(1, date(1200, 3, 3), date(1200, 3, 10))]
        view = _view(qtbot, (), rows_visible=12)
        view.update_events(events, date(1200, 3, 3), date(1200, 3, 14))
        grab = QPoint(view.rail_width() + 40, _row_center(view, 2).y())  # Mar 5
        _press_only(view.viewport(), grab)
        _drag_move(view.viewport(), grab + QPoint(0, DRAG_START_THRESHOLD_PX))
        assert view.edit_preview() == (1, date(1200, 3, 3), date(1200, 3, 10))
        _release_only(view.viewport(), grab + QPoint(0, DRAG_START_THRESHOLD_PX))


class TestOpenEventStartDrag:
    """W5 2b: start-row drag of an open event; body stays mute."""

    def _view(self, qtbot):
        events = [
            _evt(1, date(1200, 1, 1)),
            _evt(2, date(1200, 1, 4), None),
            _evt(3, date(1200, 1, 12)),
        ]
        return _view(qtbot, events, rows_visible=8)

    @staticmethod
    def _text_point(view, idx: int) -> QPoint:
        return QPoint(view.rail_width() + 40, _row_center(view, idx).y())

    def test_start_row_previews_new_start_with_open_end(self, qtbot):
        view = self._view(qtbot)
        moved = _moved(view)
        rows_before = view.rows
        point = self._text_point(view, 3)  # e2 start Jan 4
        below = QPoint(point.x(), _row_center(view, 6).y())  # Jan 7
        _press_only(view.viewport(), point)
        _drag_move(view.viewport(), below)
        assert view.edit_preview() == (2, date(1200, 1, 7), None)
        assert view.rows is rows_before
        _release_only(view.viewport(), below)
        assert moved == [(2, date(1200, 1, 7), None)]
        assert view.edit_preview() is None

    def test_escape_cancels_start_drag(self, qtbot):
        from PySide6.QtGui import QKeyEvent

        view = self._view(qtbot)
        moved = _moved(view)
        point = self._text_point(view, 3)
        below = QPoint(point.x(), _row_center(view, 6).y())
        _press_only(view.viewport(), point)
        _drag_move(view.viewport(), below)
        QApplication.sendEvent(view, QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier,
        ))
        assert view.edit_preview() is None
        _release_only(view.viewport(), below)
        assert moved == []


class TestEditPreviewPaint:
    """W5 4.1–4.2: ghost wash is the accent derivative; retheme keeps the gesture."""

    def test_ghost_pixel_is_accent_wash_in_both_themes(self, qtbot, tmp_path):
        runtime = _make_runtime(tmp_path)
        events = [_evt(1, date(1200, 1, 1)), _evt(2, date(1200, 1, 4), date(1200, 1, 6))]
        view = _view(qtbot, events, theme=runtime, rows_visible=8)
        grab = QPoint(view.rail_width() + 40, _row_center(view, 3).y())
        target = QPoint(grab.x(), _row_center(view, 6).y())  # empty Jan 7
        _press_only(view.viewport(), grab)
        _drag_move(view.viewport(), target)
        x = view.rail_width() + 3
        y = _row_center(view, 6).y()
        pal = view.paint_palette()
        img = view.viewport().grab().toImage()
        got = img.pixelColor(x, y)
        assert got.alpha() > 0
        assert abs(got.red() - pal.drag_fill.red()) < 80  # blended over the row
        runtime.set_theme("light")
        view._retheme()
        pal_light = view.paint_palette()
        img2 = view.viewport().grab().toImage()
        got2 = img2.pixelColor(x, y)
        assert view.edit_preview() is not None
        assert pal_light.drag_fill != pal.drag_fill or got2 != got
        _release_only(view.viewport(), target)

    def test_serif_center_x_matches_painted_lane(self, qtbot):
        view = _view(qtbot, [
            _evt(1, date(1200, 1, 1)),
            _evt(2, date(1200, 1, 4), date(1200, 1, 6)),
        ])
        lane = view.bracket_lane(2)
        assert lane is not None
        x = BRACKET_X0 + lane * BRACKET_LANE_STEP
        row = max(i for i, r in enumerate(view.rows) if r.date == date(1200, 1, 6))
        point = QPoint(x, _row_center(view, row).y())
        _press_only(view.viewport(), point)
        _drag_move(view.viewport(), QPoint(x, _row_center(view, row + 1).y()))
        assert view.edit_preview() is not None
        _release_only(view.viewport(), QPoint(x, _row_center(view, row + 1).y()))


class TestEditDragSideEffects:
    """W5 5.1–5.2: wheel retargets; Ctrl-wheel and header switchers are mute."""

    def test_wheel_during_drag_retargets_release(self, qtbot):
        events = [_evt(i, date(1200, 1, d)) for i, d in enumerate(range(1, 16), start=1)]
        view = _view(qtbot, events, rows_visible=4)
        moved = _moved(view)
        point = QPoint(view.rail_width() + 40, _row_center(view, 0).y())
        _press_only(view.viewport(), point)
        _drag_move(view.viewport(), point + QPoint(0, DRAG_START_THRESHOLD_PX))
        center = QPointF(point)
        QApplication.sendEvent(view.viewport(), QWheelEvent(
            center, view.viewport().mapToGlobal(point),
            QPoint(0, 0), QPoint(0, -120),
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        ))
        QApplication.sendEvent(view.viewport(), QWheelEvent(
            center, view.viewport().mapToGlobal(point),
            QPoint(0, 0), QPoint(0, -120),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ControlModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        ))
        assert view.scale_unit is ScaleUnit.DAY
        _release_only(view.viewport(), point)
        assert len(moved) == 1
        assert moved[0][0] == 1
        assert moved[0][1] != date(1200, 1, 1)

    def test_header_scale_click_ignored_during_drag(self, qtbot):
        from unittest.mock import MagicMock

        vm = MagicMock()
        vm.unit = ScaleUnit.DAY
        vm.group_by = None
        panel = TimelineWidget(vm)
        qtbot.addWidget(panel)
        panel.resize(320, 280)
        panel.show()
        panel.update_events([
            _evt(1, date(1200, 1, 1)),
            _evt(2, date(1200, 1, 4), date(1200, 1, 6)),
            _evt(3, date(1200, 1, 12)),
        ])
        view = panel.rows_view
        point = QPoint(view.rail_width() + 40, _row_center(view, 3).y())
        _press_only(view.viewport(), point)
        _drag_move(view.viewport(), QPoint(point.x(), _row_center(view, 4).y()))
        assert view.edit_preview() is not None
        panel.scale_buttons[ScaleUnit.MONTH].click()
        assert vm.unit == ScaleUnit.DAY
        _release_only(view.viewport(), QPoint(point.x(), _row_center(view, 4).y()))

    def test_double_click_during_drag_is_mute(self, qtbot):
        view = _view(qtbot, [_evt(1, date(1200, 1, 1)), _evt(2, date(1200, 1, 4), date(1200, 1, 6))])
        dbl = []
        view.event_double_clicked.connect(dbl.append)
        point = QPoint(view.rail_width() + 40, _row_center(view, 3).y())
        _press_only(view.viewport(), point)
        _drag_move(view.viewport(), QPoint(point.x(), _row_center(view, 4).y()))
        _double_click(view.viewport(), QPoint(point.x(), _row_center(view, 4).y()))
        assert dbl == []
        _release_only(view.viewport(), QPoint(point.x(), _row_center(view, 4).y()))


class TestPanelDatesMoved:
    """W5 6.1: the panel is the single dates-moved signal."""

    def test_panel_forwards_id_and_both_dates(self, qtbot):
        from unittest.mock import MagicMock

        panel = TimelineWidget(MagicMock())
        qtbot.addWidget(panel)
        panel.update_events([
            _evt(1, date(1200, 1, 1)),
            _evt(2, date(1200, 1, 4), date(1200, 1, 6)),
            _evt(3, date(1200, 1, 9), None),
        ])
        seen: list = []
        panel.event_dates_moved.connect(lambda *a: seen.append(a))
        view = panel.rows_view
        point = QPoint(view.rail_width() + 40, _row_center(view, 3).y())
        _press_drag(view, point, QPoint(point.x(), _row_center(view, 4).y()))
        assert seen == [(2, date(1200, 1, 5), date(1200, 1, 7))]
        view.event_dates_moved.emit(3, date(1200, 1, 11), None)
        assert seen[-1] == (3, date(1200, 1, 11), None)
