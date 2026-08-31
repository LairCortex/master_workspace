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
from PySide6.QtCore import QEvent, QModelIndex, QPoint, QPointF, Qt
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
from app.presentation.views.timeline_widget import (
    BRACKET_LANE_STEP,
    BRACKET_SERIF_W,
    BRACKET_X0,
    EMPTY_HINT_TEXT,
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
    TimelineListView,
    TimelineWidget,
    bracket_lanes,
    rows_palette,
)
from app.presentation.views.timeline_rows import RowKind


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

    def test_click_on_decorative_rail_is_inert(self, qtbot):
        """Spec «Рейка декоративная»: presses left of the text zone select nothing."""
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
