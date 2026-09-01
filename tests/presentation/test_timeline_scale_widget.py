"""Widget tests for the W4 scale ladder rungs (group 5): delegate renderings,
the MONTH/YEAR rail, the unit-captioned sticky label, Ctrl/Cmd + wheel, the
zooming unit click, per-unit rail jumps, and the normalized unit-drag emit.

Offscreen pixel/grab acceptance exactly where the task text asks for it
(dot = chart token, ladder rail labels), everything else through the public
view/panel API and the same synthetic-mouse helpers W3b/W3c established. The
full-application wiring of the header switchers is E2E's (tests/ui).
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation.theme import ThemeRuntime
from app.presentation.theme.compiler import (
    CHART_TOKEN_KEYS, token_rgb, tokens_file_path,
)
from app.presentation.utils.date_utils import (
    get_custom_months, set_custom_months,
)
from app.presentation.viewmodels.timeline_viewmodel import EntityKind, TimelineViewModel
from app.presentation.views.timeline_rows import RowKind
from app.presentation.views.timeline_widget import (
    DOT_SIZE,
    DRAG_START_THRESHOLD_PX,
    ROLE_BRACKETS,
    ROLE_SHOW_TICK,
    ROLE_SHOW_YEAR,
    ROW_HEIGHT,
    STICKY_HEIGHT,
    TEXT_LEFT_PAD,
    TimelineListView,
    TimelineWidget,
    ScaleUnit,
)

from tests.ui.test_theme_grab import make_runtime


@pytest.fixture(autouse=True)
def _default_months():
    """Month names are process-global (date_utils); tests assert the default map."""
    saved = get_custom_months()
    set_custom_months(None)
    yield
    set_custom_months(saved)


def _evt(eid: int, start: date, end: date | None = None, name: str | None = None,
         color_index: int | None = None, **links):
    event = SimpleNamespace(
        id=eid, name=name or f"event-{eid}", start_date=start, end_date=end,
        event_type=None if color_index is None
        else SimpleNamespace(name="type", color_index=color_index),
    )
    for attr, names in links.items():
        setattr(event, attr, [SimpleNamespace(name=n) for n in names])
    return event


def _view(qtbot, events=(), theme=None, rows_visible=6, unit=None, group_by=None):
    view = TimelineListView(theme=theme)
    view.resize(320, ROW_HEIGHT * rows_visible + STICKY_HEIGHT + 8)
    qtbot.addWidget(view)
    view.show()
    if unit is not None or group_by is not None:
        view.set_view(unit if unit is not None else ScaleUnit.DAY,
                      group_by if group_by is not None else None)
    if events:
        view.update_events(events)
    elif unit is not None or group_by is not None:
        view.update_events([])
    return view


def _row_center(view, idx: int) -> QPoint:
    return view.visualItemRect(view.item(idx)).center()


def _rail_point(view, idx: int) -> QPoint:
    return QPoint(view.rail_width() // 2, _row_center(view, idx).y())


def _press_only(widget, point: QPoint) -> None:
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    QApplication.sendEvent(widget, QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(point), widget.mapToGlobal(point),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    ))


def _release_only(widget, point: QPoint) -> None:
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    QApplication.sendEvent(widget, QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(point), widget.mapToGlobal(point),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    ))


def _drag_move(widget, point: QPoint) -> None:
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    QApplication.sendEvent(widget, QMouseEvent(
        QEvent.Type.MouseMove, QPointF(point), widget.mapToGlobal(point),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    ))


def _click(view, idx: int, x: int | None = None) -> None:
    center = _row_center(view, idx)
    QTest.mouseClick(
        view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        QPoint(center.x() if x is None else x, center.y()),
    )


def _make_runtime(tmp_path) -> ThemeRuntime:
    return ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"),
        tokens_path=tokens_file_path(),
    )


def _wheel(view, angle: int, mods=Qt.KeyboardModifier.NoModifier) -> None:
    center = QPointF(view.viewport().rect().center())
    from PySide6.QtCore import QPoint as _QP
    from PySide6.QtGui import QWheelEvent
    QApplication.sendEvent(view.viewport(), QWheelEvent(
        center, view.viewport().mapToGlobal(center.toPoint()),
        _QP(0, 0), _QP(0, angle),
        Qt.MouseButton.NoButton, mods,
        Qt.ScrollPhase.NoScrollPhase, False,
    ))


@pytest.fixture
def text_spy(monkeypatch):
    """Capture every string drawn with ``QPainter.drawText`` + pen colors."""
    texts: list[str] = []
    pens: list = []
    state = {"pen": None}
    real_text = QPainter.drawText
    real_pen = QPainter.setPen

    def spy_text(self, *args, **kwargs):
        texts.extend(a for a in args if isinstance(a, str))
        pens.append(state["pen"])
        return real_text(self, *args, **kwargs)

    def spy_pen(self, *args):
        if args and isinstance(args[0], Qt.PenStyle) is False:
            pen = args[0]
            if isinstance(pen, QColor):
                state["pen"] = pen
            elif hasattr(pen, "color"):
                state["pen"] = pen.color()
        return real_pen(self, *args)

    monkeypatch.setattr(QPainter, "drawText", spy_text)
    monkeypatch.setattr(QPainter, "setPen", spy_pen)
    return texts, pens


@pytest.fixture
def bold_spy(monkeypatch):
    """Record whether any painted text run used a bold font."""
    state = {"bold": False}
    real_font = QPainter.setFont

    def spy(self, font):
        if font.bold():
            state["bold"] = True
        return real_font(self, font)

    monkeypatch.setattr(QPainter, "setFont", spy)
    return state


# ── 5.1 — delegate: UNIT / SECTION / type dot / equal heights ──────────────

class TestDelegateW4Kinds:
    def test_unit_positions_paint_caption_count_and_muted_stub(self, qtbot, text_spy):
        """Task 5.1/spec «Строка месяца со счётчиком», «Пустой месяц»."""
        texts, _ = text_spy
        events = [
            _evt(1, date(1245, 3, 5), date(1245, 3, 20)),
            _evt(2, date(1245, 3, 10)),
            _evt(3, date(1245, 3, 10), date(1245, 3, 30)),
            _evt(4, date(1245, 3, 25), date(1245, 3, 31)),
        ]
        events[1] = _evt(2, date(1245, 3, 10), date(1245, 3, 12))
        view = _view(qtbot, events, unit=ScaleUnit.MONTH, rows_visible=4)
        view.update_events(events, date(1245, 3, 1), date(1245, 4, 30))
        assert [r.kind for r in view.rows] == [RowKind.UNIT, RowKind.UNIT]
        view.grab()
        assert "Март 1245 · 4 события" in texts
        assert "Апрель 1245 · нет событий" in texts

    def test_empty_stub_muted_and_filled_primary(self, qtbot, text_spy, tmp_path):
        """Task 5.1: «Март · 1 событие» in fg.primary, the stub in fg.muted."""
        texts, pens = text_spy
        runtime = _make_runtime(tmp_path)
        events = [_evt(1, date(1245, 3, 5), date(1245, 3, 5))]
        view = _view(qtbot, events, theme=runtime, unit=ScaleUnit.MONTH,
                     rows_visible=4)
        view.update_events(events, date(1245, 3, 1), date(1245, 4, 30))
        view.grab()
        tokens, theme = runtime.tokens, runtime.theme
        drawn = {
            t: p.color() if hasattr(p, "color") else p
            for t, p in zip(texts, pens)
            if p is not None and "1245" in t
        }
        assert (drawn["Март 1245 · 1 событие"].red(),
                drawn["Март 1245 · 1 событие"].green(),
                drawn["Март 1245 · 1 событие"].blue()) == \
            token_rgb(tokens, theme, "color.fg.primary")
        assert (drawn["Апрель 1245 · нет событий"].red(),
                drawn["Апрель 1245 · нет событий"].green(),
                drawn["Апрель 1245 · нет событий"].blue()) == \
            token_rgb(tokens, theme, "color.fg.muted")

    def test_type_dot_pixel_is_the_chart_token_including_over_selection(
        self, qtbot, tmp_path
    ):
        """Task 5.1/spec «Метка типа», «Цвет типа равен токену»: the square at
        rail + pad is ``color.chart.3``, and stays the token pixel over the
        accent selection wash (no outline on top of the highlight)."""
        runtime = _make_runtime(tmp_path)
        view = _view(qtbot, [_evt(1, date(1245, 1, 5), color_index=3)],
                     theme=runtime, rows_visible=3)
        tokens, theme = runtime.tokens, runtime.theme
        dot_rgb = token_rgb(tokens, theme, "color.chart.3")
        dot_x = view.rail_width() + TEXT_LEFT_PAD + DOT_SIZE // 2
        dot_y = _row_center(view, 0).y()
        assert view.viewport().grab().toImage().pixelColor(dot_x, dot_y) == QColor(*dot_rgb)
        view.set_selected(1)
        img = view.viewport().grab().toImage()
        # the row is washed by the accent fill…
        assert img.pixelColor(view.rail_width() + 2, dot_y) == QColor(
            *token_rgb(tokens, theme, "color.accent")
        )
        # …and the dot still paints its token, no selection outline over it
        assert img.pixelColor(dot_x, dot_y) == QColor(*dot_rgb)

    def test_unit_captions_follow_custom_game_months(self, qtbot, text_spy):
        """Spec «Игровые месяцы» на крупных ступенях: подписи MONTH-позиций
        (и липкой) берут игровые названия месяцев, а не дефолтные."""
        texts, _ = text_spy
        set_custom_months({3: "Метель"})
        events = [_evt(1, date(1245, 3, 5), date(1245, 3, 10))]
        view = _view(qtbot, events, unit=ScaleUnit.MONTH, rows_visible=3)
        assert view.sticky_label.text() == "Метель 1245"
        view.grab()
        assert "Метель 1245 · 1 событие" in texts

    def test_untyped_event_dot_is_muted(self, qtbot, tmp_path):
        """Spec «Событие без типа»: the dot falls back to ``color.fg.muted``."""
        runtime = _make_runtime(tmp_path)
        view = _view(qtbot, [_evt(1, date(1245, 1, 5))], theme=runtime,
                     rows_visible=3)
        rgb = token_rgb(runtime.tokens, runtime.theme, "color.fg.muted")
        dot_x = view.rail_width() + TEXT_LEFT_PAD + DOT_SIZE // 2
        assert view.viewport().grab().toImage().pixelColor(
            dot_x, _row_center(view, 0).y()
        ) == QColor(*rgb)

    def test_section_headers_paint_group_titles(self, qtbot, text_spy, bold_spy):
        """Task 5.1/«Порядок секций»: SECTION rows carry the entity names in
        title weights, «Без привязки» last."""
        texts, _ = text_spy
        events = [
            _evt(1, date(1245, 3, 5), date(1245, 3, 7), characters=["Борис"]),
            _evt(2, date(1245, 3, 6), date(1245, 3, 18), characters=["Анна"]),
            _evt(3, date(1245, 4, 2), date(1245, 4, 2)),
        ]
        view = _view(qtbot, events, unit=ScaleUnit.MONTH,
                     group_by=EntityKind.CHARACTER, rows_visible=8)
        kinds = [(r.kind, r.group_key) for r in view.rows]
        assert kinds == [
            (RowKind.SECTION, "Анна"), (RowKind.UNIT, "Анна"),
            (RowKind.SECTION, "Борис"), (RowKind.UNIT, "Борис"),
            (RowKind.SECTION, "Без привязки"), (RowKind.UNIT, "Без привязки"),
        ]
        view.grab()
        assert "Анна" in texts and "Борис" in texts and "Без привязки" in texts
        assert bold_spy["bold"]  # the section head is painted title-bold

    def test_all_four_row_kinds_are_equal_height(self, qtbot):
        """Spec «Равновысокие строки»: EVENT, EMPTY_DAY, UNIT and SECTION."""
        events = [_evt(1, date(1245, 1, 5), characters=["Анна"]),
                  _evt(2, date(1245, 3, 6))]
        day = _view(qtbot, events, rows_visible=4)
        assert {r.kind for r in day.rows} >= {RowKind.EVENT, RowKind.EMPTY_DAY}
        month = _view(qtbot, events, unit=ScaleUnit.MONTH,
                      group_by=EntityKind.CHARACTER, rows_visible=4)
        assert {RowKind.SECTION, RowKind.UNIT} <= {r.kind for r in month.rows}
        for view in (day, month):
            for idx in range(view.count()):
                assert view.visualItemRect(view.item(idx)).height() == ROW_HEIGHT


# helpers used by the muted/filled color pairing test ───────────────────────


# ── 5.2 — MONTH/YEAR rail: ticks, year labels, unit brackets ───────────────

class TestLadderRail:
    def test_month_rung_ticks_every_unit_and_labels_year_once(self, qtbot, text_spy):
        """Task 5.2: one tick per unit position, «раз в год подпись года»."""
        texts, _ = text_spy
        events = [_evt(1, date(1245, 1, 10), date(1245, 3, 20)),
                  _evt(2, date(1245, 3, 25))]
        view = _view(qtbot, events, unit=ScaleUnit.MONTH, rows_visible=5)
        assert [r.date for r in view.rows] == [
            date(1245, 1, 1), date(1245, 2, 1), date(1245, 3, 1)
        ]
        assert [bool(view.item(i).data(ROLE_SHOW_TICK)) for i in range(3)] == \
            [True, True, True]
        assert [bool(view.item(i).data(ROLE_SHOW_YEAR)) for i in range(3)] == \
            [True, False, False]
        view.grab()
        assert "1245" in texts  # the rotated year label painted once

    def test_year_rung_labels_every_position(self, qtbot, text_spy):
        """Task 5.2: the YEAR rung is all year-label positions."""
        texts, _ = text_spy
        events = [_evt(1, date(1243, 5, 1), date(1245, 2, 2))]
        view = _view(qtbot, events, unit=ScaleUnit.YEAR, rows_visible=5)
        assert [r.date for r in view.rows] == [
            date(1243, 1, 1), date(1244, 1, 1), date(1245, 1, 1)
        ]
        assert all(view.item(i).data(ROLE_SHOW_YEAR) for i in range(3))
        view.grab()
        assert {"1243", "1244", "1245"} <= set(texts)

    def test_bracket_spans_every_touched_unit(self, qtbot, line_spy):
        """Spec «Скобка через месяцы»: Feb…Apr continuous, serifs at the ends."""
        view = _view(qtbot, [_evt(1, date(1245, 2, 20), date(1245, 4, 10))],
                     unit=ScaleUnit.MONTH, rows_visible=4)
        segs = [view.item(i).data(ROLE_BRACKETS) for i in range(3)]
        assert [[(s.lane, s.serif_top, s.serif_bottom) for s in seg] for seg in segs] == [
            [(0, True, False)], [(0, False, False)], [(0, False, True)],
        ]
        view.grab()
        assert view.bracket_lane(1) == 0

    @pytest.fixture
    def line_spy(self, monkeypatch):
        calls = []
        real = QPainter.drawLine

        def spy(self, *args):
            if len(args) == 2 and isinstance(args[0], QPointF):
                calls.append((args[0].x(), args[0].y(), args[1].x(), args[1].y()))
            return real(self, *args)

        monkeypatch.setattr(QPainter, "drawLine", spy)
        return calls

    def test_sectioned_rung_ticks_only_touched_units(self, qtbot):
        """Spec «Пустой месяц не показан в секции» — и тик берётся только там."""
        events = [_evt(1, date(1245, 1, 5), date(1245, 1, 20), characters=["Анна"]),
                  _evt(2, date(1245, 4, 5), date(1245, 4, 20), characters=["Анна"])]
        view = _view(qtbot, events, unit=ScaleUnit.MONTH,
                     group_by=EntityKind.CHARACTER, rows_visible=8)
        unit_ticks = [
            (r.date, bool(view.item(i).data(ROLE_SHOW_TICK)))
            for i, r in enumerate(view.rows) if r.kind is RowKind.UNIT
        ]
        assert unit_ticks == [
            (date(1245, 1, 1), True), (date(1245, 4, 1), True),
        ]


# ── 5.3 — sticky caption by rung, follow per unit ──────────────────────────

class TestStickyLadder:
    def _months_view(self, qtbot, rows_visible=2):
        events = [_evt(i, date(1245, m, 5), date(1245, m, 5))
                for i, m in enumerate(range(1, 7), 1)]
        return _view(qtbot, events, unit=ScaleUnit.MONTH,
                     rows_visible=rows_visible)

    def test_sticky_syncs_on_unit_boundary(self, qtbot):
        """Task 5.3/spec «Липкая подпись месяца»."""
        view = self._months_view(qtbot, rows_visible=3)
        bar = view.verticalScrollBar()
        assert view.sticky_label.text() == "Январь 1245"
        bar.setValue(1)  # still row 1 — a month crossed only at row 2
        assert view.sticky_label.text() == "Февраль 1245"
        bar.setValue(3)
        assert view.sticky_label.text() == "Апрель 1245"

    def test_sticky_follows_unit_under_cursor_and_drag(self, qtbot):
        """Spec «Follow-дата под курсором» + «Follow во время drag'а» на MONTH."""
        view = self._months_view(qtbot)  # rows_visible=2 → 3 months visible
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent
        QApplication.sendEvent(view.viewport(), QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(_rail_point(view, 1)), view.viewport().mapToGlobal(_rail_point(view, 1)),
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ))
        assert view.sticky_label.text() == "Февраль 1245"
        _press_only(view.viewport(), _rail_point(view, 1))  # anchor Feb
        _drag_move(view.viewport(), QPoint(view.width() - 5, _row_center(view, 2).y()))
        assert view.drag_range() == (date(1245, 2, 1), date(1245, 3, 1))
        assert view.sticky_label.text() == "Март 1245"  # follow past the rail

    def test_sticky_year_caption_on_year_rung(self, qtbot):
        events = [_evt(1, date(1243, 5, 1), date(1245, 2, 2))]
        view = _view(qtbot, events, unit=ScaleUnit.YEAR, rows_visible=2)
        assert view.sticky_label.text() == "1243"
        view.verticalScrollBar().setValue(1)
        assert view.sticky_label.text() == "1244"


# ── 5.4 — Ctrl/Cmd + wheel steps the ladder with the anchor ────────────────

class TestWheelLadder:
    def _day_view(self, qtbot, rows_visible=4):
        events = [_evt(1, date(1245, 1, 1), date(1245, 12, 20))]
        view = _view(qtbot, events, rows_visible=rows_visible)
        return view

    def test_ctrl_wheel_down_zooms_out_with_first_visible_anchor(self, qtbot):
        """Spec «Якорь при отдалении»: при верхней строке 14 марта отдаление
        ставит на ступень «месяц» сверху вниз март того же года."""
        view = self._day_view(qtbot)
        # 1245 не високосный: 31 янв + 28 фев → строка 72 = 14 марта.
        view.verticalScrollBar().setValue(72)
        assert view.sticky_label.text().startswith("14 ")
        _wheel(view, -120, Qt.KeyboardModifier.ControlModifier)  # coarse
        assert view.scale_unit is ScaleUnit.MONTH
        assert view.verticalScrollBar().value() == 2  # янв и фев Above — март сверху
        assert view.sticky_label.text() == "Март 1245"
        assert view.top_visible_index() == 2

    def test_ctrl_wheel_up_zooms_in_with_sticky_anchor(self, qtbot):
        """Spec «Колесо с Ctrl меняет ступень»: приближение — единица из-под липкой."""
        events = [_evt(1, date(1245, 1, 1), date(1245, 12, 20))]
        view = _view(qtbot, events, unit=ScaleUnit.MONTH, rows_visible=3)
        view.verticalScrollBar().setValue(3)  # top unit = апрель
        assert view.sticky_label.text() == "Апрель 1245"
        _wheel(view, 120, Qt.KeyboardModifier.ControlModifier)  # finer
        assert view.scale_unit is ScaleUnit.DAY
        # 31 янв + 28 фев + 31 мар → 1 апреля = строка 90.
        assert view.verticalScrollBar().value() == 90
        assert view.sticky_label.text().startswith("01 ")
        steps: list = []
        view.scale_changed.connect(steps.append)
        _wheel(view, -120, Qt.KeyboardModifier.ControlModifier)
        assert steps == [ScaleUnit.MONTH]  # and the step is announced outward

    def test_ctrl_wheel_inert_at_the_ladder_floor(self, qtbot):
        """«сутки — отдаление запрещено как уже нижняя» (the finer edge at DAY)."""
        view = self._day_view(qtbot)
        steps: list = []
        view.scale_changed.connect(steps.append)
        scroll_before = view.verticalScrollBar().value()
        _wheel(view, 120, Qt.KeyboardModifier.ControlModifier)  # finer than DAY
        assert view.scale_unit is ScaleUnit.DAY
        assert view.verticalScrollBar().value() == scroll_before  # nothing moved
        assert steps == []

    def test_bare_wheel_step_unchanged_on_unit_rungs(self, qtbot):
        """«Скролл-шаг без Ctrl не меняется» — one unit position per notch."""
        events = [_evt(1, date(1245, 1, 1), date(1245, 12, 20))]
        view = _view(qtbot, events, unit=ScaleUnit.MONTH, rows_visible=3)
        view.verticalScrollBar().setValue(0)
        _wheel(view, -120)
        assert view.verticalScrollBar().value() == 1
        assert view.scale_unit is ScaleUnit.MONTH


# ── 5.5 — zooming unit click, per-unit rail jump ───────────────────────────

class TestUnitClicks:
    def _months(self, qtbot, rows_visible=3):
        events = [_evt(i, date(1245, m, 5), date(1245, m, 5))
                for i, m in enumerate(range(1, 7), 1)]
        return _view(qtbot, events, unit=ScaleUnit.MONTH, rows_visible=rows_visible)

    def test_click_on_unit_position_zooms_anchored_without_signals(self, qtbot):
        """Spec «Клик по месяцу приближает»: сутки, верхним рядом — начало
        месяца; ни выбора, ни id-сигналов, ни дня-прыжка."""
        view = self._months(qtbot, rows_visible=4)
        selected, doubled, scaled = [], [], []
        view.event_selected.connect(selected.append)
        view.event_double_clicked.connect(doubled.append)
        view.scale_changed.connect(scaled.append)
        x = view.rail_width() + 40  # text zone, clear of the rail
        _click(view, 2, x=x)  # март
        assert view.scale_unit is ScaleUnit.DAY
        # 1 марта — верхний ряд (окно стартует 5 января, строка 1 марта — 55-я)
        assert view.rows[view.top_visible_index()].date == date(1245, 3, 1)
        assert view.sticky_label.text().startswith("01 ")
        assert selected == [] and doubled == []
        assert view.selected_id is None and view.selectedIndexes() == []
        assert scaled == [ScaleUnit.DAY]  # the VM mirror rides this signal

    def test_zoom_from_year_lands_on_month(self, qtbot):
        events = [_evt(1, date(1243, 5, 1), date(1245, 2, 2))]
        view = _view(qtbot, events, unit=ScaleUnit.YEAR, rows_visible=4)
        _click(view, 1, x=view.rail_width() + 40)  # 1244
        assert view.scale_unit is ScaleUnit.MONTH
        assert view.verticalScrollBar().value() > 0  # anchor 1244 not at the head

    def test_rail_click_jumps_to_an_empty_unit(self, qtbot):
        """Spec «Прыжок на пустой день»: на ступени «месяц» пустая позиция-заглушка —
        валидная цель прыжка (выбор и id-сигналы не тронуты)."""
        events = [_evt(i, date(1245, m, 5), date(1245, m, 5))
                  for i, m in enumerate((1, 3, 5), 1)]  # февраль and апрель empty
        view = _view(qtbot, events, unit=ScaleUnit.MONTH, rows_visible=3)
        assert view.rows[1].unit_count == 0  # февраль — заглушка
        selected: list = []
        view.event_selected.connect(selected.append)
        _click(view, 1, x=view.rail_width() // 2)  # пустой февраль на рейке
        assert view.verticalScrollBar().value() == 1
        assert view.top_visible_index() == 1
        assert view.sticky_label.text() == "Февраль 1245"
        assert selected == []

    def test_rail_click_jumps_by_unit_keeping_selection(self, qtbot):
        """W3c jump, MONTH rung: the clicked unit goes to the top under the
        sticky label; selection/ids untouched (spec «Клик по дню» per unit)."""
        view = self._months(qtbot, rows_visible=3)
        selected: list = []
        view.event_selected.connect(selected.append)
        view.set_selected(1)  # январь's event stays put
        _click(view, 2, x=view.rail_width() // 2)  # март на рейке
        assert view.verticalScrollBar().value() == 2  # март — верхний ряд
        assert view.top_visible_index() == 2
        assert view.sticky_label.text() == "Март 1245"
        assert view.currentRow() == 2
        assert selected == []
        # на месячной ступени у выбора нет строки — id остаётся pending
        assert view.selected_id == 1 and view.selectedIndexes() == []


# ── 5.6 — unit drag: highlight once, normalized full-date emit, click ──────

class TestUnitDrag:
    def _months(self, qtbot, rows_visible=3, scroll=0, theme=None):
        events = [_evt(i, date(1245, m, 5), date(1245, m, 5))
                for i, m in enumerate(range(1, 7), 1)]
        view = _view(qtbot, events, theme=theme, unit=ScaleUnit.MONTH,
                     rows_visible=rows_visible)
        view.verticalScrollBar().setValue(scroll)
        return view

    def test_month_drag_emits_full_borders_once(self, qtbot):
        """Spec «Drag по месяцам отдаёт целые границы» + ровно один emit."""
        view = self._months(qtbot, rows_visible=6)
        emitted: list = []
        view.day_range_applied.connect(lambda s, e: emitted.append((s, e)))
        _press_only(view.viewport(), _rail_point(view, 2))  # март
        target = _rail_point(view, 4)                        # май
        _drag_move(view.viewport(), target)
        assert view.drag_range() == (date(1245, 3, 1), date(1245, 5, 1))
        assert emitted == []  # live highlight only — the apply is the release's
        _release_only(view.viewport(), target)
        assert emitted == [(date(1245, 3, 1), date(1245, 5, 31))]

    def test_bottom_up_drag_normalizes(self, qtbot):
        """Spec «Drag снизу вверх нормализуется» на месячной ступени."""
        view = self._months(qtbot, rows_visible=6)
        emitted: list = []
        view.day_range_applied.connect(lambda s, e: emitted.append((s, e)))
        _press_only(view.viewport(), _rail_point(view, 4))  # май…
        target = _rail_point(view, 2)                        # …к марту
        _drag_move(view.viewport(), target)
        _release_only(view.viewport(), target)
        assert emitted == [(date(1245, 3, 1), date(1245, 5, 31))]

    def test_year_drag_emits_full_year_bounds(self, qtbot):
        events = [_evt(1, date(1243, 5, 1), date(1245, 2, 2))]
        view = _view(qtbot, events, unit=ScaleUnit.YEAR, rows_visible=4)
        emitted: list = []
        view.day_range_applied.connect(lambda s, e: emitted.append((s, e)))
        _press_only(view.viewport(), _rail_point(view, 1))  # 1244
        target = _rail_point(view, 2)                        # 1245
        _drag_move(view.viewport(), target)
        _release_only(view.viewport(), target)
        assert emitted == [(date(1244, 1, 1), date(1245, 12, 31))]

    def test_single_unit_drag_is_the_click_jump(self, qtbot):
        """Spec «Однодневный drag равен клику» на месячной ступени."""
        view = self._months(qtbot, rows_visible=4)
        emitted: list = []
        view.day_range_applied.connect(lambda s, e: emitted.append((s, e)))
        point = _rail_point(view, 2)  # март: row y 48..71 (sticky offset 26? center)
        _press_only(view.viewport(), point)
        over = QPoint(point.x(), point.y() + DRAG_START_THRESHOLD_PX)
        _drag_move(view.viewport(), over)
        _release_only(view.viewport(), over)
        assert emitted == []  # фильтр не применён
        assert view.verticalScrollBar().value() == 2  # …прыжок на март

    def test_drag_washes_every_covered_unit(self, qtbot, tmp_path):
        """Task 5.6 «подсветка покрываемых единиц» — wash pixels on the rungs."""
        runtime = _make_runtime(tmp_path)
        view = self._months(qtbot, rows_visible=4, theme=runtime)
        x = view.rail_width() + 3  # left of the text indent, empty paint zone
        plain = view.viewport().grab().toImage().pixelColor(x, 83)  # май center
        _press_only(view.viewport(), _rail_point(view, 2))  # март…
        _drag_move(view.viewport(), QPoint(x, _row_center(view, 4).y()))  # …→ май
        img = view.viewport().grab().toImage()
        assert img.pixelColor(x, _row_center(view, 3).y()) != plain  # апрель
        assert img.pixelColor(x, _row_center(view, 4).y()) != plain  # май
        assert img.pixelColor(x, _row_center(view, 0).y()) == plain  # январь чист


# ── 5.7 — header switchers (panel level; the app wiring is E2E's) ───────────

def _panel_with_vm(qtbot, events):
    vm = TimelineViewModel(MagicMockService())
    vm._all_events = list(events)
    vm._apply_filter()
    panel = TimelineWidget(vm)
    qtbot.addWidget(panel)
    panel.resize(340, 420)
    panel.show()

    def on_filter(start, end):
        vm.filter_by_dates(start, end)
        panel.update_events(vm.events)

    panel.filter_changed.connect(on_filter)
    panel.update_events(vm.events)
    return panel, vm


class MagicMockService:
    """The ViewModel loads nothing in these tests; the service is never used."""

    async def get_all_events(self):  # pragma: no cover - never awaited
        raise AssertionError("not used in switcher tests")


class TestHeaderSwitchers:
    def test_switchers_fit_the_header_without_displacing_controls(self, qtbot):
        """Task 5.7: «+», чип, прыжки на месте; ступень и группа видны."""
        panel, vm = _panel_with_vm(qtbot, [_evt(1, date(1245, 2, 3))])
        for widget in (panel.add_button, panel.filter_chip,
                       panel.jump_prev_button, panel.jump_next_button):
            assert widget is not None and widget.parent() is not None
        assert panel.scale_buttons[ScaleUnit.DAY].isChecked()
        assert not panel.scale_buttons[ScaleUnit.MONTH].isChecked()
        assert "выкл" in panel.group_button.text()

    def test_ladder_switcher_remodels_rows_and_shows_state(self, qtbot):
        events = [_evt(1, date(1245, 1, 5), date(1245, 1, 20)),
                  _evt(2, date(1245, 4, 6))]
        panel, vm = _panel_with_vm(qtbot, events)
        panel.scale_buttons[ScaleUnit.MONTH].click()
        assert vm.unit is ScaleUnit.MONTH
        assert panel.scale_buttons[ScaleUnit.MONTH].isChecked()
        assert panel.rows_view.scale_unit is ScaleUnit.MONTH
        assert [r.kind for r in panel.rows_view.rows] == [RowKind.UNIT] * 4
        panel.group_actions[EntityKind.CHARACTER].trigger()
        assert vm.group_by is EntityKind.CHARACTER
        assert [r.kind for r in panel.rows_view.rows][0] is RowKind.SECTION

    def test_switching_units_round_trip_keeps_selection_and_filter(self, qtbot):
        """Spec «Переключение не трогает выбор» + «Фильтр переживает лестницу»."""
        events = [_evt(1, date(1245, 2, 3)), _evt(2, date(1245, 4, 6))]
        panel, vm = _panel_with_vm(qtbot, events)
        vm.select_event_by_id(2)  # external-selection path, as in wiring
        panel.set_selected(vm.selected_event.id)
        panel.filter_popup.range_applied.emit(date(1245, 1, 1), date(1245, 6, 30))
        chip = panel.filter_chip.text()
        assert chip != "Все даты ▾"
        for unit in (ScaleUnit.MONTH, ScaleUnit.YEAR, ScaleUnit.DAY):
            panel.scale_buttons[unit].click()
        assert vm.unit is ScaleUnit.DAY
        assert vm.selected_event is not None and vm.selected_event.id == 2
        assert panel.rows_view.selected_id == 2
        assert panel.rows_view.selectedIndexes()[0].row() == \
            panel.rows_view.index_for_event(2)
        assert panel.filter_chip.text() == chip  # границы не съехали
        assert all(e.id in {1, 2} for e in panel.rows_view.events)

    def test_jump_command_from_month_drops_to_day(self, qtbot):
        """Spec «Прыжок с месяцной ступени» (VM-less panel path included)."""
        events = [_evt(1, date(1245, 1, 5)), _evt(2, date(1245, 5, 6))]
        panel, vm = _panel_with_vm(qtbot, events)
        panel.scale_buttons[ScaleUnit.MONTH].click()
        panel.rows_view.verticalScrollBar().setValue(0)
        panel.jump_next_event()
        assert vm.unit is ScaleUnit.DAY
        assert panel.rows_view.scale_unit is ScaleUnit.DAY
        assert panel.rows_view.currentRow() == panel.rows_view.index_for_event(2)


# ── 7.1 — type pixel acceptance: every chart token, both themes, retheme ─────
#
# The §5 tests proved the mechanism on one index (chart.3); the acceptance
# group pins the whole mandated palette: dot k of a typed row must be exactly
# ``color.chart.k`` in BOTH themes, and opening the window with a selection
# and a scrolled list must repaint all eight colors on a live theme flip
# (spec «Цвет типа равен токену», «Живая ре-тема», «Оформление шкалы из
# токенов»).

class TestTypePixelAcceptance:
    def _eight_events(self):
        return [
            _evt(1, date(1245, 1, 1), color_index=1),
            _evt(2, date(1245, 1, 2), color_index=2),
            _evt(3, date(1245, 1, 3), color_index=3),
            _evt(4, date(1245, 1, 4), color_index=4),
            _evt(5, date(1245, 1, 5), color_index=5),
            _evt(6, date(1245, 1, 6), color_index=6),
            _evt(7, date(1245, 1, 7), color_index=7),
            _evt(8, date(1245, 1, 8), color_index=8),
        ]

    def _dot_pixel(self, image, scale, view, idx: int) -> "QColor":
        rect = view.visualItemRect(view.item(idx))
        x = int((view.rail_width() + TEXT_LEFT_PAD + DOT_SIZE // 2) * scale)
        return image.pixelColor(x, int(rect.center().y() * scale))

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_type_row_dot_is_chart_token_for_all_eight_indices_both_themes(
        self, qtbot, tmp_path, theme
    ):
        """Task 7.1/spec «Цвет типа равен токену»: метка строки события с
        индексом k == ``color.chart.k`` — все восемь индексов, обе темы."""
        runtime = make_runtime(tmp_path, theme)
        assert runtime.theme == theme and runtime.is_valid
        view = _view(qtbot, self._eight_events(), theme=runtime, rows_visible=8)
        image = view.viewport().grab().toImage()
        scale = image.width() / max(view.viewport().width(), 1)
        seen = set()
        for idx, row in enumerate(view.rows):
            assert row.token_key == f"color.chart.{idx + 1}"
            expected = QColor(*token_rgb(runtime.tokens, theme, row.token_key))
            assert self._dot_pixel(image, scale, view, idx) == expected, \
                f"{row.token_key} in theme {theme}"
            seen.add(row.token_key)
        assert seen == set(CHART_TOKEN_KEYS)  # all eight probed, none skipped

    def test_live_retheme_moves_all_eight_dot_colors_keeping_selection_and_scroll(
        self, qtbot, tmp_path
    ):
        """Task 7.1/spec «Живая ре-тема»: a theme flip on the open panel
        repaints every chart dot to its token of the new theme while the
        selection and the reading position survive untouched."""
        runtime = make_runtime(tmp_path, "dark")
        colors = [1, 2, 3, 4, 5, 6, 7, 8, 1, 2]  # ten rows, all eight indices
        events = [_evt(i, date(1245, 1, i), color_index=c)
                  for i, c in enumerate(colors, 1)]
        view = _view(qtbot, events, theme=runtime, rows_visible=4)
        bar = view.verticalScrollBar()
        tokens = runtime.tokens

        def check_visible_dots(theme: str) -> set:
            """Every visible EVENT row's dot is its chart token of ``theme``."""
            image = view.viewport().grab().toImage()
            scale = image.width() / max(view.viewport().width(), 1)
            seen: set = set()
            for idx, row in enumerate(view.rows):
                if row.token_key is None:
                    continue
                rect = view.visualItemRect(view.item(idx))
                cy = int(rect.center().y() * scale)
                if not rect.intersects(view.viewport().rect()) \
                        or not 0 <= cy < image.height():
                    continue  # off-viewport (pixel probe must stay in bounds)
                expected = QColor(*token_rgb(tokens, theme, row.token_key))
                assert self._dot_pixel(image, scale, view, idx) == expected, \
                    f"{row.token_key} in theme {theme}"
                seen.add(row.token_key)
            return seen

        def sweep(theme: str) -> set:
            """Check the tokens at both scroll ends plus one mid position."""
            seen: set = set()
            for pos in (0, bar.maximum() // 2, bar.maximum()):
                bar.setValue(pos)
                seen |= check_visible_dots(theme)
            return seen

        # teeth: every chart pair actually differs across themes
        for key in CHART_TOKEN_KEYS:
            assert QColor(*token_rgb(tokens, "light", key)) != \
                QColor(*token_rgb(tokens, "dark", key))

        # dark theme, all eight tokens observed across the scrolling list
        assert sweep("dark") == set(CHART_TOKEN_KEYS)

        # select the tail event (centers its row — the list is scrolled),
        # then flip the live theme with the open window
        view.set_selected(10)
        scroll_before = bar.value()
        row_before = view.currentRow()
        sticky_before = view.sticky_label.text()
        assert scroll_before > 0
        assert runtime.toggle() and runtime.theme == "light"

        # selection, reading position and scroll survive the flip untouched
        assert view.selected_id == 10
        assert view.selectedIndexes()[0].row() == view.index_for_event(10)
        assert bar.value() == scroll_before
        assert view.currentRow() == row_before
        assert view.sticky_label.text() == sticky_before

        # …while every dot has moved to its token of the new theme (all eight)
        assert sweep("light") == set(CHART_TOKEN_KEYS)  # live re-theme, 8/8
