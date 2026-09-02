"""Widget tests for the vertical day-ladder tape (redesign-timeline-day-ladder).

The W4/W5 rail suite retired with the rail (design D9: no ticks, no span
ties, no stretch handles, no rail hit zones); the ladder revision re-establishes
the contract offscreen: the id-contract signals over duplicate cards, the
inert non-event positions, per-kind delegate painting with rail-free paint
primitives (task 3.1), the two-overlay sticky with the ~120 ms push-out and
mouse transparency (task 3.2), the one-row wheel step with the Alt/Opt
rung zoom and dead Ctrl/Cmd branch (task 4.1), the period-rung drill click
(task 4.2), the rebuild memo and the live re-theme that keeps selection
and scroll.

Pixel-level token colors live in ``tests/ui/test_e2e_timeline_theme.py``.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QModelIndex, QPoint, QPointF, Qt
from PySide6.QtGui import (
    QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QWheelEvent,
)
from PySide6.QtWidgets import QApplication, QMenu

from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation.theme import ThemeRuntime
from app.presentation.theme.compiler import tokens_file_path, token_rgb
from app.presentation.utils.date_utils import (
    format_game_date, get_custom_months, set_custom_months,
)
from app.presentation.views.timeline_widget import (
    DRAG_START_THRESHOLD_PX,
    EMPTY_DAY_TEXT,
    EMPTY_HINT_TEXT,
    NO_EVENTS_TEXT,
    OPEN_MARK,
    ROLE_ROW,
    ROW_HEIGHT,
    STICKY_HEIGHT,
    STICKY_PUSH_MS,
    TEXT_LEFT_PAD,
    DOT_SIZE,
    TimelineListView,
    _counter_line,
    _events_phrase,
    _gap_line,
    window_chip_text,
    rows_palette,
)
from app.presentation.views.timeline_rows import (
    DayHeaderRow,
    EmptyDayRow,
    EventRow,
    GapCollapsedRow,
    PeriodCardRow,
    PeriodHeaderRow,
    ScaleUnit,
    header_caption,
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


def _typed(eid: int, start: date, end: date | None, color_index: int | None, name: str = ""):
    event = _evt(eid, start, end, name)
    event.event_type = None if color_index is None else SimpleNamespace(color_index=color_index)
    return event


def _view(qtbot, events=(), theme=None, rows_visible=4, window=None, level=ScaleUnit.DAY):
    view = TimelineListView(theme=theme)
    view.resize(300, ROW_HEIGHT * rows_visible + STICKY_HEIGHT + 8)
    qtbot.addWidget(view)
    view.show()
    if window is not None or level is not ScaleUnit.DAY:
        view.set_knobs(window=window, level=level)
    if events:
        view.update_events(events)
    return view


def _row_center(view, idx: int) -> QPoint:
    return view.visualItemRect(view.item(idx)).center()


def _make_runtime(tmp_path, tokens_path=None) -> ThemeRuntime:
    return ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"),
        tokens_path=tokens_path or tokens_file_path(),
    )


def _wheel(view, dy: int, modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    """A wheel notch over the viewport — Qt routes it through the scroll area
    into the view's :meth:`wheelEvent` (the W3b harness pattern)."""
    vp = view.viewport()
    pos = QPointF(vp.rect().center())
    QApplication.sendEvent(vp, QWheelEvent(
        pos, vp.mapToGlobal(pos.toPoint()), QPoint(0, 0), QPoint(0, dy),
        Qt.MouseButton.NoButton, modifiers,
        Qt.ScrollPhase.NoScrollPhase, False,
    ))


@pytest.fixture
def text_spy(monkeypatch):
    """Capture every string drawn with ``QPainter.drawText`` + rotate angles.

    The rotated-angle twin is the rail-month-label witness: with the rail gone
    the delegate never rotates (task 3.1), so the angle history stays empty.
    """
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


@pytest.fixture
def line_spy(monkeypatch):
    """Capture ``QPainter.drawLine`` calls — the rail's tie/tick witness.

    The ladder delegate paints with rects and text only: a single line call
    would mean rail/tick/tie painting snuck back in.
    """
    calls: list[tuple[float, float, float, float]] = []
    real = QPainter.drawLine

    def spy(self, *args):
        if len(args) == 2 and isinstance(args[0], QPointF) and isinstance(args[1], QPointF):
            calls.append((args[0].x(), args[0].y(), args[1].x(), args[1].y()))
        return real(self, *args)

    monkeypatch.setattr(QPainter, "drawLine", spy)
    return calls


# ── 3.1 — the delegate paints the five ladder row kinds ─────────────────────

class TestDelegateRowKinds:
    def test_empty_shows_hint_and_no_sticky(self, qtbot):
        """Spec «Событий нет вовсе»: hint only, sticky pair hidden (D3)."""
        view = _view(qtbot)
        assert view.hint_label.isVisible()
        assert view.hint_label.text() == EMPTY_HINT_TEXT
        assert view.sticky_label.isHidden()
        assert view.sticky_next.isHidden()

    def test_event_card_paints_name_muted_open_mark(self, qtbot, text_spy):
        """Task 3.1: closed cards draw the name only; open cards append the
        «бессрочно» mark (spec «Бессрочные события»)."""
        view = _view(qtbot, [
            _evt(1, date(1200, 1, 1), date(1200, 1, 1), name="Бой"),
            _evt(2, date(1200, 1, 2), name="Чума"),
        ], rows_visible=6)
        view.grab()
        texts, _ = text_spy
        assert "Бой" in texts and "Чума" in texts
        # The open mark is a separate muted run — never glued into the name,
        # and the closed card's run never wears it.
        assert any(OPEN_MARK in t for t in texts)
        assert not any(OPEN_MARK in t and "Бой" in t for t in texts)

    def test_empty_day_placeholder_and_gap_caption(self, qtbot, text_spy):
        """Task 3.1: «+  нет события» placeholders and muted gap captions with
        game-formatted bounds (spec «Провал схлопнут»)."""
        jan9, apr30 = date(1200, 1, 9), date(1200, 4, 30)
        view = _view(
            qtbot,
            [
                _evt(1, date(1200, 1, 1), date(1200, 1, 1)),
                _evt(2, date(1200, 1, 8), date(1200, 1, 8)),  # empties Jan 2–7
                _evt(3, date(1200, 5, 1), date(1200, 5, 1)),   # past a collapsed gap
            ],
            rows_visible=24,
        )
        view.resize(560, view.height())  # the full gap caption must not elide
        view.grab()
        texts, _ = text_spy
        assert EMPTY_DAY_TEXT in texts
        gaps = [r for r in view.rows if isinstance(r, GapCollapsedRow)]
        assert len(gaps) == 1
        expected = _gap_line(gaps[0])
        assert format_game_date(jan9) in expected and format_game_date(apr30) in expected
        assert expected in texts  # the whole caption lands un-elided

    def test_period_counter_ru_phrase_and_empty_stub(self, qtbot, text_spy):
        """Task 3.1: «N событий» counters with RU pluralisation and the muted
        «нет событий» stub (spec «Строка месяца со счётчиком»)."""
        view = _view(
            qtbot,
            [
                _evt(1, date(1200, 3, 2), date(1200, 3, 5)),
                _evt(2, date(1200, 3, 10), date(1200, 3, 10)),
                _evt(3, date(1200, 3, 30), date(1200, 4, 3)),
                _evt(4, date(1200, 2, 20), date(1200, 3, 1)),
                _evt(5, date(1200, 6, 1), date(1200, 6, 1)),  # keeps April empty
            ],
            rows_visible=8,
            level=ScaleUnit.MONTH,
        )
        view.grab()
        texts, _ = text_spy
        assert "4 события" in texts  # March
        assert NO_EVENTS_TEXT in texts  # April's stub
        assert "1 событие" in texts  # June (June is past March's April in-row…)
        assert _counter_line(PeriodCardRow(date(1200, 12, 1), ScaleUnit.MONTH, 5)) == "5 событий"
        assert _events_phrase(11) == "событий" and _events_phrase(21) == "событие"

    def test_day_period_headers_draw_game_captions(self, qtbot, text_spy):
        """Task 3.1: section heads carry the same core captions the sticky pair
        repeats («Липкий заголовок периода»)."""
        view = _view(
            qtbot,
            [_evt(1, date(1200, 3, 4), date(1200, 3, 4))],
            rows_visible=4,
            level=ScaleUnit.MONTH,
        )
        view.grab()
        texts, _ = text_spy
        header = next(r for r in view.rows if isinstance(r, PeriodHeaderRow))
        assert header_caption(header) == "Март 1200"
        assert "Март 1200" in texts

    def test_type_dot_uses_token_key_and_mutes_untyped(self, qtbot, tmp_path):
        """Core hands the delegate the exact ``color.chart.k`` token key and the
        palette resolves it from the live theme (widget pixel proof lives in the
        theme e2e); an untyped row carries ``None`` → muted dot."""
        view = _view(qtbot, [
            _typed(1, date(1200, 1, 1), date(1200, 1, 1), 3, name="Слух"),
            _typed(2, date(1200, 1, 2), date(1200, 1, 2), None, name="Без типа"),
        ], rows_visible=6)
        card = next(r for r in view.rows if isinstance(r, EventRow) and r.event_id == 1)
        other = next(r for r in view.rows if isinstance(r, EventRow) and r.event_id == 2)
        assert card.token_key == "color.chart.3" and other.token_key is None
        runtime = _make_runtime(tmp_path)
        palette = rows_palette(runtime)
        expected = token_rgb(runtime.tokens, runtime.theme, "color.chart.3")
        dot = palette.type_dots["color.chart.3"]
        assert (dot.red(), dot.green(), dot.blue()) == expected
        muted = token_rgb(runtime.tokens, runtime.theme, "color.fg.muted")
        plain = palette.type_dot_muted
        assert (plain.red(), plain.green(), plain.blue()) == muted

    def test_tooltip_holds_name_and_range_on_every_card(self, qtbot):
        """Task 3.1 tooltip «name + start — end» on every card incl. open."""
        closed, open_ev = _evt(1, date(1200, 1, 1), date(1200, 1, 3), "Поход"), _evt(2, date(1200, 1, 2), name="Чума")
        view = _view(qtbot, [closed, open_ev], rows_visible=6)
        for idx, row in enumerate(view.rows):
            tip = view.item(idx).toolTip()
            if isinstance(row, EventRow):
                assert row.name in tip
                assert format_game_date(row.start) in tip
                if row.end is not None:
                    assert format_game_date(row.end) in tip
                else:
                    # The open card spells only its start, an explicit «—» end.
                    assert tip.endswith(f"{format_game_date(row.start)} —")
            else:
                assert tip == ""  # only cards carry tooltips

    def test_rail_is_gone_from_the_delegate(self, qtbot, line_spy, text_spy):
        """Task 3.1 removals: no ``_paint_rail``, no ``ROLE_SHOW_*`` roles, no
        drawLine/rotate — ties, ticks and stretch handles stay deleted."""
        import app.presentation.views.timeline_widget as mod

        assert not hasattr(mod._RowDelegate, "_paint_rail")
        assert not hasattr(mod, "_paint_rail")
        assert not any(name.startswith("ROLE_SHOW") for name in dir(mod))
        view = _view(qtbot, [_evt(1, date(1200, 1, 1), date(1200, 3, 1))], rows_visible=8)
        view.grab()
        assert line_spy == []          # no ties, no ticks
        assert text_spy[1] == []       # no rotated rail month labels

    def test_delegate_paint_smoke_over_mixed_tape(self, qtbot):
        """Every row kind paints without error (cards, empties, gap, headers,
        period cards) — off-skin fallback included (spec «Вне скина»)."""
        events = [
            _typed(1, date(1200, 1, 1), date(1200, 1, 2), 1, name="А"),
            _evt(2, date(1200, 1, 8), date(1200, 1, 8), name="Б"),     # empty run
            _evt(3, date(1200, 4, 1), date(1200, 4, 1), name="В"),     # past a gap
        ]
        view = _view(qtbot, events, rows_visible=10)
        image = QImage(600, view.height(), QImage.Format.Format_RGB32)
        view.render(image)  # DAY level: cards, empty days, headers
        view.set_knobs(level=ScaleUnit.MONTH)
        view.render(image)  # MONTH level: period headers and counter cards


# ── 3.2 — the sticky pair: two QLabels, push-out, mouse-transparent ─────────

class TestStickyPushOut:
    _SPREAD = [
        _evt(1, date(1200, 1, 1), date(1200, 1, 4), name="А"),
        _evt(2, date(1200, 1, 6), date(1200, 1, 6), name="Б"),
        _evt(3, date(1200, 1, 8), date(1200, 1, 8), name="В"),
    ]

    def _tall_view(self, qtbot):
        # rows: hdr1,c1,c2,c3,hdr5,c5? — Jan1..Jan8 with cards on 1–4,6,8;
        # viewport hosts ~3 rows so the bar scrolls.
        return _view(qtbot, self._SPREAD, rows_visible=3)

    def test_pair_are_mouse_transparent_band_children(self, qtbot):
        """Task 3.2 / spec: sticky labels sit over the viewport and never
        intercept the mouse; the viewport keeps exactly their band as margin."""
        view = self._tall_view(qtbot)
        for label in (view.sticky_label, view.sticky_next):
            assert label.parent() is view
            assert label.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        assert view.viewport().y() == STICKY_HEIGHT
        assert not view.sticky_next.isVisible()  # hidden while at rest

    def test_sticky_follows_top_section_without_push_inside_a_day(self, qtbot):
        """Within one section a scroll is inert; the text comes from the core
        (``sticky_state`` / ``header_caption``)."""
        view = self._tall_view(qtbot)
        top_day = view.sticky_label.text()
        assert top_day == format_game_date(date(1200, 1, 1))
        view.verticalScrollBar().setValue(1)  # deeper into Jan 1's cards
        assert view.sticky_label.text() == top_day
        assert not view.sticky_next.isVisible()

    def test_section_change_pushes_the_pair_then_commits(self, qtbot):
        """Task 3.2 / spec «Push-out при плотном дне»: the incoming header
        slides the old one out (~STICKY_PUSH_MS), never a text swap; after the
        animation the current label rests in the band and the next hides."""
        view = self._tall_view(qtbot)
        old_text = view.sticky_label.text()
        view.verticalScrollBar().setValue(5)  # top edge crosses into a later day
        assert view.sticky_next.isVisible()    # the push started, not a swap
        qtbot.wait(STICKY_PUSH_MS + 120)
        assert view.sticky_label.text() != old_text
        assert view.sticky_label.pos().y() == 0
        assert view.sticky_next.isHidden()

    def test_push_shows_second_label_before_commit(self, qtbot):
        """The push is animated by a second QLabel, not an instant repaint:
        right after the crossing (before the event loop pumps) the *current*
        label still shows the old caption while the next one has it."""
        view = self._tall_view(qtbot)
        old_text = view.sticky_label.text()
        view.verticalScrollBar().setValue(6)
        assert view.sticky_next.isVisible()
        assert view.sticky_next.text() != old_text
        assert view.sticky_label.text() == old_text  # not swapped yet
        qtbot.wait(STICKY_PUSH_MS + 120)
        assert view.sticky_label.text() != old_text
        assert view.sticky_next.isHidden()

    def test_rapid_reversal_settles_on_the_core_truth(self, qtbot):
        """Spec D3 risk note: aggressive scrolling snaps then re-pushes; the
        resting text always equals the core's section caption."""
        from app.presentation.views.timeline_rows import sticky_state

        view = self._tall_view(qtbot)
        for value in (5, 0, 6, 2, 7):
            view.verticalScrollBar().setValue(value)
            QApplication.processEvents()
        qtbot.wait(STICKY_PUSH_MS + 120)
        state = sticky_state(view.rows, view.top_visible_index())
        expected = state.current_text if state.current_index is not None else ""
        assert view.sticky_label.text() == expected
        assert view.sticky_next.isHidden()

    def test_sticky_uses_game_month_names(self, qtbot):
        """Spec «Игровые месяцы»: renaming months repaints the sticky caption
        without a rebuild — the identical-sample path re-reads the caption map
        (the change arrives as a regular push, then rests in the band)."""
        view = self._tall_view(qtbot)
        set_custom_months({1: "Январь-Луны"})
        view.update_events(self._SPREAD)  # same sample — memo path re-syncs
        qtbot.wait(STICKY_PUSH_MS + 120)
        assert view.sticky_label.text().startswith("01 Январь-Луны")
        assert view.sticky_next.isHidden()

    def test_sticky_hidden_while_empty_hint_survives(self, qtbot):
        """Spec «Sticky скрыт при пустоте» — hint stays, pair hidden."""
        view = self._tall_view(qtbot)
        view.update_events([])
        assert view.hint_label.isVisible()
        assert view.sticky_label.isHidden()
        assert view.sticky_next.isHidden()


# ── id contract over duplicate cards; inert positions ───────────────────────

class TestListSignals:
    def test_every_duplicate_click_selects_the_record(self, qtbot):
        """Spec «Клик по полосе»: any duplicate card of one record leads to the
        same event id; the wash tracks the view's id, not Qt bookkeeping."""
        view = _view(qtbot, [_evt(1, date(1200, 1, 1), date(1200, 1, 3))], rows_visible=8)
        indexes = view.indexes_for_event(1)
        assert len(indexes) == 3
        received: list[int] = []
        view.event_selected.connect(received.append)
        view._on_clicked(view.model().index(indexes[2], 0))
        assert received == [1] and view.selected_id == 1
        view._on_clicked(view.model().index(indexes[0], 0))
        assert received == [1, 1]  # a plain click on any duplicate re-emits

    def test_double_click_emits_id(self, qtbot):
        view = _view(qtbot, [_evt(7, date(1200, 1, 1), date(1200, 1, 1))], rows_visible=4)
        received: list[int] = []
        view.event_double_clicked.connect(received.append)
        view._on_double_clicked(view.model().index(view.index_for_event(7), 0))
        assert received == [7]

    def test_non_event_positions_are_inert(self, qtbot):
        """Spec «Пустая позиция не выбирается» / «Заголовок дня не кликабелен»:
        headers, gaps and period headers carry no flags and yield no ids. The
        empty day (task 6.1) is the one exception: it is ENABLED so its click
        opens the inline editor — yet it never selects (no id), the panel's
        selection and the id signals stay untouched."""
        view = _view(qtbot, [
            _evt(1, date(1200, 1, 1), date(1200, 1, 1)),
            _evt(2, date(1200, 1, 3), date(1200, 1, 3)),
        ], rows_visible=8)
        received: list[int] = []
        view.event_selected.connect(received.append)
        for idx, row in enumerate(view.rows):
            if isinstance(row, EventRow):
                continue
            if isinstance(row, EmptyDayRow):
                # A create entry point: enabled, never selectable.
                flags = view.item(idx).flags()
                assert flags == Qt.ItemFlag.ItemIsEnabled
                assert not (flags & Qt.ItemFlag.ItemIsSelectable)
            else:
                assert view.item(idx).flags() == Qt.ItemFlag.NoItemFlags
            view._on_clicked(view.model().index(idx, 0))
        assert received == []
        # The empty-day click landed the inline editor without selecting.
        assert view.inline_editor.isVisible()
        assert view.selected_id is None

    def test_period_header_click_stays_inert(self, qtbot):
        """Task 4.2 scope line: only the *card* drills — the period header
        selects nothing, drills nothing, emits nothing."""
        view = _view(qtbot, [_evt(1, date(1200, 3, 2), date(1200, 3, 4))],
                     rows_visible=4, level=ScaleUnit.MONTH)
        received: list = []
        view.event_selected.connect(received.append)
        view.period_drilled.connect(lambda *a: received.append(a))
        for idx, row in enumerate(view.rows):
            if not isinstance(row, PeriodHeaderRow):
                continue
            assert view.item(idx).flags() == Qt.ItemFlag.NoItemFlags
            view._on_clicked(view.model().index(idx, 0))
        assert received == [] and view.level is ScaleUnit.MONTH

    def test_selection_wash_and_scroll_over_duplicates(self, qtbot):
        view = _view(qtbot, [_evt(1, date(1200, 1, 1), date(1200, 1, 5))], rows_visible=4)
        view.set_selected(1)
        assert view.selected_id == 1
        first = view.index_for_event(1)
        rect = view.visualItemRect(view.item(first))
        assert 0 <= rect.top() <= view.viewport().height()
        view.set_selected(None)
        assert view.selected_id is None

    def test_unpictured_selection_pending_on_period_rung(self, qtbot):
        """An id the ladder does not picture keeps a pending invisible wash and
        scrolls nothing (the VM owns descends; the list stays dumb)."""
        view = _view(qtbot, [_evt(1, date(1200, 3, 2), date(1200, 3, 4))],
                     rows_visible=4, level=ScaleUnit.MONTH)
        view.set_selected(1)  # month rung: no cards — stays pending
        assert view.selected_id == 1
        assert view.verticalScrollBar().value() == 0


# ── task 4.2 — the period-card click drills, never selects ──────────────────

class TestPeriodDrill:
    def _click_card(self, view, card: PeriodCardRow) -> None:
        idx = next(
            i for i, r in enumerate(view.rows)
            if isinstance(r, PeriodCardRow) and r.date == card
        )
        view._on_clicked(view.model().index(idx, 0))

    def test_month_card_click_drills_to_days_with_month_window(self, qtbot):
        """Spec «Клик по месяцу приближает»: ступень — сутки, окно — март,
        the tape enumerates exactly the month's days from the 1st."""
        view = _view(qtbot, [_evt(1, date(1200, 3, 2), date(1200, 3, 4))],
                     rows_visible=4, level=ScaleUnit.MONTH)
        drilled: list = []
        view.period_drilled.connect(lambda lvl, win: drilled.append((lvl, win)))
        self._click_card(view, date(1200, 3, 1))
        assert view.level is ScaleUnit.DAY
        assert view.window == (date(1200, 3, 1), date(1200, 3, 31))
        assert drilled == [(ScaleUnit.DAY, (date(1200, 3, 1), date(1200, 3, 31)))]
        # The month's days enumerated from the 1st — with the core's own gap
        # contract inside (the eventless 5–31 stretch stands collapsed).
        days = [r.date for r in view.rows if isinstance(r, DayHeaderRow)]
        assert days == [date(1200, 3, d) for d in (1, 2, 3, 4)]
        assert any(isinstance(r, GapCollapsedRow) for r in view.rows)
        assert view.verticalScrollBar().value() == 0  # top is 1 марта

    def test_year_card_click_drills_to_months_with_year_window(self, qtbot):
        """Spec «Провал из года в месяцы»: ступень — месяц, окно — весь год,
        every month of 1245 comes with its counter card."""
        view = _view(
            qtbot,
            [_evt(1, date(1245, 6, 1), date(1245, 6, 2))],
            rows_visible=4, level=ScaleUnit.YEAR,
        )
        self._click_card(view, date(1245, 1, 1))
        assert view.level is ScaleUnit.MONTH
        assert view.window == (date(1245, 1, 1), date(1245, 12, 31))
        months = [r.date for r in view.rows if isinstance(r, PeriodCardRow)]
        assert months == [date(1245, m, 1) for m in range(1, 13)]

    def test_drill_emits_no_id_signals_and_keeps_the_selection(self, qtbot):
        """Task 4.2 absence clause: a drill is navigation, not a click on an
        event — no event_selected, no double-click, the still-pictured card of
        the previously selected record keeps its wash (spec «…выбрано остаётся
        прежнее (никакого нового выбора)»)."""
        view = _view(qtbot, [_evt(1, date(1200, 3, 2), date(1200, 3, 4))],
                     rows_visible=4, level=ScaleUnit.MONTH)
        ids: list = []
        view.event_selected.connect(ids.append)
        view.event_double_clicked.connect(ids.append)
        view.set_selected(1)  # pending invisible on the month rung
        self._click_card(view, date(1200, 3, 1))
        assert ids == [] and view.selected_id == 1
        assert view.index_for_event(1) is not None  # now pictured on the days

    def test_drill_of_empty_month_and_real_release_click(self, qtbot):
        """Spec «Клик по пустому месяцу проваливает»: the muted «нет событий»
        card drills too — driving a REAL press/release proves the position is
        clickable in Qt terms (enabled, yet not selectable)."""
        view = _view(
            qtbot,
            [
                _evt(1, date(1200, 3, 2), date(1200, 3, 4)),
                _evt(2, date(1200, 6, 1), date(1200, 6, 1)),  # keeps April empty
            ],
            rows_visible=4, level=ScaleUnit.MONTH,
        )
        card_idx = next(
            i for i, r in enumerate(view.rows)
            if isinstance(r, PeriodCardRow) and r.date == date(1200, 4, 1)
        )
        assert view.item(card_idx).flags() == Qt.ItemFlag.ItemIsEnabled
        vp = view.viewport()
        point = _row_center(view, card_idx)
        for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            QApplication.sendEvent(vp, QMouseEvent(
                kind, QPointF(point), vp.mapToGlobal(point),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton
                if kind is QEvent.Type.MouseButtonPress
                else Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            ))
        assert view.level is ScaleUnit.DAY
        assert view.window == (date(1200, 4, 1), date(1200, 4, 30))
        assert view.selected_id is None


# ── task 6.1 — inline creation from an empty day (design D4) ────────────────

class TestInlineCreate:
    """A click on an «нет события» placeholder turns that one row into the
    reusable inline field: Enter commits a ``(day, name)`` create intent, an
    empty field / Esc / a focus loss with nothing typed returns the row to its
    placeholder with no signal."""

    @staticmethod
    def _empty_view(qtbot):
        """Two one-day events Mar 1 / Mar 3 → Mar 2 is the empty day."""
        return _view(qtbot, [
            _evt(1, date(1200, 3, 1), date(1200, 3, 1)),
            _evt(2, date(1200, 3, 3), date(1200, 3, 3)),
        ], rows_visible=8)

    @staticmethod
    def _empty_idx(view, day) -> int:
        return next(
            i for i, r in enumerate(view.rows)
            if isinstance(r, EmptyDayRow) and r.date == day
        )

    def _click_empty(self, view, day) -> None:
        """A real press/release on the empty-day row (drives ``clicked``)."""
        vp = view.viewport()
        point = _row_center(view, self._empty_idx(view, day))
        for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            QApplication.sendEvent(vp, QMouseEvent(
                kind, QPointF(point), vp.mapToGlobal(point),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton
                if kind is QEvent.Type.MouseButtonPress
                else Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            ))

    def test_click_empty_day_opens_editor_on_the_row(self, qtbot):
        view = self._empty_view(qtbot)
        self._click_empty(view, date(1200, 3, 2))
        assert view.inline_editor.isVisible()
        assert view.editing_day == date(1200, 3, 2)
        # The editor is parked over the clicked row, not somewhere else.
        item = view.item(self._empty_idx(view, date(1200, 3, 2)))
        assert view.inline_editor.geometry().top() == view.visualItemRect(item).top()

    def test_one_editor_is_reused_across_days(self, qtbot):
        """Design D4: a single reused QLineEdit — clicking a second empty day
        moves the same widget, it is never duplicated."""
        view = _view(qtbot, [
            _evt(1, date(1200, 3, 1), date(1200, 3, 1)),
            _evt(2, date(1200, 3, 4), date(1200, 3, 4)),
        ], rows_visible=8)
        from PySide6.QtWidgets import QLineEdit
        editors = view.findChildren(QLineEdit)
        assert len(editors) == 1
        self._click_empty(view, date(1200, 3, 2))
        # Mar 2 is empty; now point at the Mar 3 empty day too (gap in 1..4).
        self._click_empty(view, date(1200, 3, 3))
        assert view.findChildren(QLineEdit) == editors  # still the one widget
        assert view.editing_day == date(1200, 3, 3)

    def test_enter_emits_create_with_day_and_name(self, qtbot):
        view = self._empty_view(qtbot)
        created: list = []
        view.event_create_requested.connect(lambda d, n: created.append((d, n)))
        self._click_empty(view, date(1200, 3, 2))
        view.inline_editor.setText("Засека")
        qtbot.keyClick(view.inline_editor, Qt.Key_Return)
        assert created == [(date(1200, 3, 2), "Засека")]
        # Enter commits and dismisses: no stale field left on the row.
        assert not view.inline_editor.isVisible()
        assert view.editing_day is None

    def test_enter_empty_creates_nothing(self, qtbot):
        """Spec «Пустое поле не создаёт»: an empty (or spaces-only) field never
        emits and simply returns the row to its placeholder."""
        view = self._empty_view(qtbot)
        created: list = []
        view.event_create_requested.connect(lambda *a: created.append(a))
        self._click_empty(view, date(1200, 3, 2))
        qtbot.keyClick(view.inline_editor, Qt.Key_Return)
        assert created == [] and not view.inline_editor.isVisible()
        # …and a whitespace-only draft is treated as empty too.
        self._click_empty(view, date(1200, 3, 2))
        view.inline_editor.setText("   ")
        qtbot.keyClick(view.inline_editor, Qt.Key_Return)
        assert created == [] and not view.inline_editor.isVisible()

    def test_escape_hides_without_emitting(self, qtbot):
        """Spec «Escape … SHALL возвращать строку в состояние плейсхолдера» —
        a draft is discarded, no create intent leaves the view."""
        view = self._empty_view(qtbot)
        created: list = []
        view.event_create_requested.connect(lambda *a: created.append(a))
        self._click_empty(view, date(1200, 3, 2))
        view.inline_editor.setText("Забавно")
        qtbot.keyClick(view.inline_editor, Qt.Key_Escape)
        assert created == [] and not view.inline_editor.isVisible()
        assert view.editing_day is None

    def test_focus_loss_without_text_hides(self, qtbot):
        """Spec «потеря фокуса без текста»: dropping focus on an empty field
        returns the placeholder; a draft-in-progress is kept for Enter/Esc."""
        view = self._empty_view(qtbot)
        self._click_empty(view, date(1200, 3, 2))
        QApplication.sendEvent(
            view.inline_editor, QEvent(QEvent.Type.FocusOut)
        )
        assert not view.inline_editor.isVisible() and view.editing_day is None

    def test_rebuild_dismisses_the_editor(self, qtbot):
        """A reload after creation (the empty day is replaced by the new card)
        clears the field so no overlay lingers over stale coordinates."""
        view = self._empty_view(qtbot)
        self._click_empty(view, date(1200, 3, 2))
        assert view.inline_editor.isVisible()
        view.update_events([
            _evt(1, date(1200, 3, 1), date(1200, 3, 1)),
            _evt(2, date(1200, 3, 3), date(1200, 3, 3)),
            _evt(3, date(1200, 3, 2), date(1200, 3, 2), name="Засека"),
        ])
        assert not view.inline_editor.isVisible() and view.editing_day is None


# ── wheel: one notch == one position; Alt/Opt + wheel steps the ladder ──────

def _wheel_at(view, dy: int, pos: QPointF, modifiers) -> None:
    """A wheel notch over an exact viewport position (cursor-anchor tests)."""
    vp = view.viewport()
    QApplication.sendEvent(vp, QWheelEvent(
        pos, vp.mapToGlobal(pos.toPoint()), QPoint(0, 0), QPoint(0, dy),
        Qt.MouseButton.NoButton, modifiers,
        Qt.ScrollPhase.NoScrollPhase, False,
    ))


class TestWheel:
    #: Single-day events in March, April and June 1200 — the daily tape holds
    #: cards, two collapsed gaps; the month tape spans March…June (May is the
    #: empty «нет событий» card); the year tape holds only 1200.
    _SPREAD = [
        _evt(1, date(1200, 3, 1), date(1200, 3, 1)),
        _evt(2, date(1200, 4, 15), date(1200, 4, 15)),
        _evt(3, date(1200, 6, 1), date(1200, 6, 1)),
    ]

    def _scrollable(self, qtbot):
        events = [_evt(i, date(1200, 1, d), date(1200, 1, d))
                  for i, d in enumerate(range(1, 12), 1)]
        return _view(qtbot, events, rows_visible=3)

    def _spread(self, qtbot, level=ScaleUnit.DAY):
        return _view(qtbot, self._SPREAD, rows_visible=4, level=level)

    def _top_row(self, view):
        return view.rows[max(view.top_visible_index(), 0)]

    def test_plain_notch_scrolls_exactly_one_row(self, qtbot):
        view = self._scrollable(qtbot)
        first = view.verticalScrollBar().value()
        _wheel(view, -120)
        assert view.verticalScrollBar().value() == first + 1
        _wheel(view, 120)
        assert view.verticalScrollBar().value() == first

    def test_alt_wheel_walks_the_ladder_and_emits(self, qtbot):
        """Task 4.1 (spec «Лестница ступеней просмотра»): Alt/Opt + wheel is
        the only wheel rung move — outward сутки → месяц → год with the wheel
        away from the user, inward back; every real step is emitted for the
        panel to mirror into the ViewModel, clamped notches stay silent."""
        view = self._spread(qtbot)
        stepped: list[ScaleUnit] = []
        view.scale_changed.connect(stepped.append)
        _wheel(view, -120, Qt.KeyboardModifier.AltModifier)   # сутки → месяц
        assert view.level is ScaleUnit.MONTH
        _wheel(view, -120, Qt.KeyboardModifier.AltModifier)   # месяц → год
        assert view.level is ScaleUnit.YEAR
        _wheel(view, -120, Qt.KeyboardModifier.AltModifier)   # «год» clamps
        assert stepped == [ScaleUnit.MONTH, ScaleUnit.YEAR]
        _wheel(view, 120, Qt.KeyboardModifier.AltModifier)    # год → месяц
        _wheel(view, 120, Qt.KeyboardModifier.AltModifier)    # месяц → сутки
        _wheel(view, 120, Qt.KeyboardModifier.AltModifier)    # «сутки» clamps
        assert view.level is ScaleUnit.DAY
        assert stepped == [ScaleUnit.MONTH, ScaleUnit.YEAR,
                           ScaleUnit.MONTH, ScaleUnit.DAY]

    def test_alt_wheel_zoom_out_anchors_on_the_row_under_the_cursor(self, qtbot):
        """Spec «Лестница ступеней просмотра» / «Якорь при отдалении» via the
        mouse: the row under the cursor anchors — the April 15 card is under
        the wheel, so after zooming out the April section (not the first-
        visible March) sits on top."""
        view = self._spread(qtbot)
        day = view.verticalScrollBar().value()
        cursor = QPointF(_row_center(view, 3))  # EventRow of 15 апреля
        _wheel_at(view, -120, cursor, Qt.KeyboardModifier.AltModifier)
        assert view.level is ScaleUnit.MONTH
        top = self._top_row(view)
        assert isinstance(top, PeriodHeaderRow)
        assert top.date == date(1200, 4, 1)
        # the wheel event itself scrolled nothing beyond the re-model
        assert day == 0

    def test_alt_wheel_zoom_in_anchors_on_the_row_under_the_cursor(self, qtbot):
        """Inward from the month rung: the period card under the cursor
        anchors its period on top — the April card brings the tape back onto
        April, not onto the head of the content span."""
        view = self._spread(qtbot, level=ScaleUnit.MONTH)
        # month rows: hdrMar, cardMar, hdrApr, cardApr, hdrMay, cardMay, …
        cursor = QPointF(_row_center(view, 3))  # April's counter card
        _wheel_at(view, 120, cursor, Qt.KeyboardModifier.AltModifier)
        assert view.level is ScaleUnit.DAY
        assert self._top_row(view).date.month == 4

    def test_alt_wheel_zoom_in_installs_the_anchor_period_as_window(self, qtbot):
        """Task 9 (defect b), spec «Приближение от карточки события»: an inward
        Alt/Opt notch is a descent — «ступень — сутки, окно — август». The
        April card under the cursor drills the tape onto April's window and the
        pair leaves on the drill channel so the VM (and chip) follow."""
        view = self._spread(qtbot, level=ScaleUnit.MONTH)
        # month rows: hdrMar, cardMar, hdrApr, cardApr, hdrMay, cardMay, …
        cursor = QPointF(_row_center(view, 3))  # April's counter card
        drilled: list = []
        view.period_drilled.connect(lambda lvl, win: drilled.append((lvl, win)))
        _wheel_at(view, 120, cursor, Qt.KeyboardModifier.AltModifier)
        assert view.level is ScaleUnit.DAY
        assert view.window == (date(1200, 4, 1), date(1200, 4, 30))
        assert drilled == [(ScaleUnit.DAY, (date(1200, 4, 1), date(1200, 4, 30)))]

    def test_alt_wheel_zoom_out_keeps_the_active_window(self, qtbot):
        """Spec «Якорь при отдалении» pins only the top unit — zooming out
        over an active window moves the rung, the window stays (the wheel
        installs windows on descents only)."""
        view = _view(qtbot, self._SPREAD, rows_visible=4,
                     window=(date(1200, 4, 1), date(1200, 4, 30)))
        _wheel(view, -120, Qt.KeyboardModifier.AltModifier)  # сутки → месяц
        assert view.level is ScaleUnit.MONTH
        assert view.window == (date(1200, 4, 1), date(1200, 4, 30))

    def test_alt_wheel_zoom_in_off_the_rows_falls_back_to_the_top_span(self, qtbot):
        """Cursor past the row block — the «верхняя позиция» anchor also owns
        the installed window (fallback shared with the anchor fallback)."""
        view = self._spread(qtbot, level=ScaleUnit.MONTH)
        _wheel_at(view, 120, QPointF(5, 100_000),  # far below the last row
                  Qt.KeyboardModifier.AltModifier)
        assert view.level is ScaleUnit.DAY
        # the top visible month is March → window = the whole of March
        assert view.window == (date(1200, 3, 1), date(1200, 3, 31))

    def test_ctrl_cmd_wheel_is_the_dead_gesture(self, qtbot):
        """Spec «Alt-колесо вместо Ctrl»: Ctrl/Cmd + wheel changes nothing —
        no rung move, no scroll, no emit (the deleted interaction is eaten)."""
        view = self._spread(qtbot)
        stepped: list[ScaleUnit] = []
        view.scale_changed.connect(stepped.append)
        before = view.verticalScrollBar().value()
        for mod in (Qt.KeyboardModifier.ControlModifier,
                    Qt.KeyboardModifier.MetaModifier):
            _wheel(view, -120, mod)
            _wheel(view, 120, mod)
        assert stepped == [] and view.level is ScaleUnit.DAY
        assert view.verticalScrollBar().value() == before

    def test_alt_wheel_never_touches_the_scroll_step(self, qtbot):
        """Spec «Alt-колесо вместо Ctrl»: «не трогая шаги прокрутки» — an
        Alt notch at the clamped end neither rows-scrolls nor moves the rung."""
        view = self._spread(qtbot)
        stepped: list = []
        view.scale_changed.connect(stepped.append)
        before = view.verticalScrollBar().value()
        _wheel(view, 120, Qt.KeyboardModifier.AltModifier)  # DAY + finer = clamp
        assert view.level is ScaleUnit.DAY and stepped == []
        assert view.verticalScrollBar().value() == before

    def test_other_modifiers_keep_the_row_step(self, qtbot):
        """Spec: «иные модификаторы шаг прокрутки менять НЕ SHALL»."""
        view = self._scrollable(qtbot)
        stepped: list = []
        view.scale_changed.connect(stepped.append)
        before = view.verticalScrollBar().value()
        _wheel(view, -120, Qt.KeyboardModifier.ShiftModifier)
        assert view.verticalScrollBar().value() == before + 1
        assert stepped == []


# ── rebuild memo, knobs mirror, re-theme ────────────────────────────────────

class TestMemoAndRetheme:
    def test_identical_sample_and_knobs_never_rebuild(self, qtbot):
        view = _view(qtbot, [_evt(1, date(1200, 1, 1), date(1200, 1, 3))], rows_visible=3)
        view.verticalScrollBar().setValue(2)
        rows_before = view.rows
        view.update_events([
            _evt(1, date(1200, 1, 1), date(1200, 1, 3)),
        ])  # equal by value → memo hit: rows and scroll untouched
        assert view.rows == rows_before
        assert view.verticalScrollBar().value() == 2

    def test_knob_change_remodels_without_stale_positions(self, qtbot):
        events = [_evt(1, date(1200, 1, 1), date(1200, 1, 1)),
                  _evt(2, date(1200, 2, 1), date(1200, 2, 1))]
        view = _view(qtbot, events, rows_visible=4)
        day_rows = len(view.rows)
        view.set_knobs(level=ScaleUnit.MONTH)
        assert {type(r) for r in view.rows} == {PeriodHeaderRow, PeriodCardRow}
        view.set_knobs(hide_empty=True, level=ScaleUnit.DAY)
        assert all(isinstance(r, (DayHeaderRow, EventRow)) for r in view.rows)
        assert len(view.rows) < day_rows
        assert view.level is ScaleUnit.DAY and view.hide_empty is True

    def test_window_knob_limits_the_tape(self, qtbot):
        view = _view(qtbot, [_evt(1, date(1200, 1, 10), date(1200, 1, 12))], rows_visible=6)
        view.set_knobs(window=(date(1200, 1, 11), date(1200, 1, 13)))
        assert view.window == (date(1200, 1, 11), date(1200, 1, 13))
        assert all(date(1200, 1, 11) <= r.date <= date(1200, 1, 13) for r in view.rows)

    def test_retheme_repaints_keeps_selection_scroll(self, qtbot, tmp_path):
        runtime = _make_runtime(tmp_path)
        runtime.set_theme("dark")
        events = [_evt(i, date(1200, 1, d), date(1200, 1, d)) for i, d in enumerate(range(1, 12), 1)]
        view = _view(qtbot, events, theme=runtime, rows_visible=3)
        view.set_selected(5)
        view.verticalScrollBar().setValue(4)
        runtime.set_theme("light")
        view._retheme()  # the pattern the W4 suite used (listener + explicit repaint)
        assert view.selected_id == 5
        assert view.verticalScrollBar().value() == 4
        accent = token_rgb(runtime.tokens, runtime.theme, "color.accent")
        assert view.paint_palette().selected_fill.red() == accent[0]

    def test_version_key_covers_color_and_bottom(self, qtbot):
        """Recoloring a type or growing the open-run bottom remotes rebuilds
        even with identical ids/dates/names (design D7 memo notes)."""
        view = _view(qtbot, [_typed(1, date(1200, 1, 5), date(1200, 1, 5), 2, "x")], rows_visible=4)
        recolor = _typed(1, date(1200, 1, 5), date(1200, 1, 5), 4, "x")
        view.update_events([recolor])
        card = next(r for r in view.rows if isinstance(r, EventRow))
        assert card.token_key == "color.chart.4"


# ── hover + header geometry misc ────────────────────────────────────────────

class TestMisc:
    def test_hover_tracks_event_rows_only_via_mouse_move(self, qtbot):
        view = _view(qtbot, [_evt(1, date(1200, 1, 1), date(1200, 1, 1)),
                             _evt(2, date(1200, 1, 3), date(1200, 1, 3))], rows_visible=6)
        idx = view.index_for_event(2)
        point = _row_center(view, idx)
        vp = view.viewport()
        vp_point = QPoint(point.x(), point.y())
        QApplication.sendEvent(vp, QMouseEvent(
            QEvent.Type.MouseMove, QPointF(vp_point), vp.mapToGlobal(vp_point),
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ))
        assert view.hover_index() == idx

    def test_chip_text_helpers_unchanged_by_the_redesign(self, qtbot):
        assert window_chip_text(None, None) == "Все дни ▾"
        assert window_chip_text(date(1200, 1, 5), date(1200, 1, 9)) == (
            f"{format_game_date(date(1200, 1, 5))} — "
            f"{format_game_date(date(1200, 1, 9))} ▾"
        )

    def test_gap_caption_helper(self):
        line = _gap_line(GapCollapsedRow(date(1200, 1, 2), date(1200, 3, 1)))
        assert line == (
            f"нет событий: {format_game_date(date(1200, 1, 2))} — "
            f"{format_game_date(date(1200, 3, 1))}"
        )


# ── tasks 5.1/5.2/5.4 — the date-drop gesture, the release menu, inert rungs ──

def _mouse(
    view, kind, point, *, button=Qt.MouseButton.LeftButton, buttons,
) -> None:
    """A raw mouse event on the viewport at ``point`` (gesture driving)."""
    vp = view.viewport()
    QApplication.sendEvent(vp, QMouseEvent(
        kind, QPointF(point), vp.mapToGlobal(point),
        button, buttons, Qt.KeyboardModifier.NoModifier,
    ))


def _press(view, point: QPoint) -> None:
    _mouse(view, QEvent.Type.MouseButtonPress, point,
           buttons=Qt.MouseButton.LeftButton)


def _drag_to(view, point: QPoint) -> None:
    _mouse(
        view, QEvent.Type.MouseMove, point,
        button=Qt.MouseButton.NoButton, buttons=Qt.MouseButton.LeftButton,
    )


def _release(view, point: QPoint) -> None:
    _mouse(view, QEvent.Type.MouseButtonRelease, point,
           buttons=Qt.MouseButton.NoButton)


def _press_and_arm(view, idx: int) -> QPoint:
    """Press the card at ``idx`` and pull past the gesture threshold."""
    p0 = _row_center(view, idx)
    _press(view, p0)
    _drag_to(view, QPoint(p0.x(), p0.y() + DRAG_START_THRESHOLD_PX))
    return p0


def _esc(view) -> None:
    QApplication.sendEvent(view, QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier,
    ))


@pytest.fixture
def drop_menu(monkeypatch):
    """Stub the release-menu ``exec`` in the widget module (the ui/conftest
    MenuControl pattern at unit scale): every menu built is captured and the
    chooser set by the test returns the clicked item — ``None`` = closed
    without a choice."""
    import app.presentation.views.timeline_widget as mod

    created: list[QMenu] = []

    class _StubMenu(QMenu):
        chooser = None

        def __init__(self, parent=None):
            super().__init__(parent)
            created.append(self)

        def exec(self, *args):  # Qt API name
            return _StubMenu.chooser(self) if _StubMenu.chooser is not None else None

    monkeypatch.setattr(mod, "QMenu", _StubMenu)
    yield created, _StubMenu


def _chooser(text: str):
    def choose(menu: QMenu):
        for action in menu.actions():
            if action.text() == text:
                return action
        return None

    return choose


@pytest.fixture
def fill_spy(monkeypatch):
    """Capture every ``QPainter.fillRect`` color drawn during the test."""
    colors: list[QColor] = []
    real = QPainter.fillRect

    def spy(self, *args, **kwargs):
        for arg in args:
            if isinstance(arg, QColor):
                colors.append(arg)
                break
        return real(self, *args, **kwargs)

    monkeypatch.setattr(QPainter, "fillRect", spy)
    return colors


@pytest.fixture
def opacity_spy(monkeypatch):
    """Capture every ``QPainter.setOpacity`` value drawn during the test."""
    values: list[float] = []
    real = QPainter.setOpacity

    def spy(self, value):
        values.append(float(value))
        return real(self, value)

    monkeypatch.setattr(QPainter, "setOpacity", spy)
    return values


class TestDateDropGesture:
    """Task 5.1 (with the task 5.4 inert clause): the press → 4 px threshold →
    preview chain, the ghost's accent wash, the sticky on the target day and
    every cancel branch — including off-tape with NO edge extrapolation."""

    def test_below_threshold_press_release_is_plain_click(self, qtbot):
        """Spec: до превышения порога нажатие остаётся штатным кликом."""
        view = _view(qtbot, [_evt(1, date(1200, 1, 1), date(1200, 1, 3))],
                     rows_visible=8)
        ids: list[int] = []
        view.event_selected.connect(ids.append)
        p0 = _row_center(view, view.indexes_for_event(1)[0])
        _press(view, p0)
        nudge = QPoint(p0.x(), p0.y() + DRAG_START_THRESHOLD_PX - 1)
        _drag_to(view, nudge)
        assert view.drag_preview is None
        _release(view, nudge)
        assert ids == [1] and view.selected_id == 1

    def test_press_past_threshold_arms_preview_ghost_and_sticky(self, qtbot):
        """Task 5.1: the armed gesture carries the source card, the row under
        the cursor materializes the target day, and the sticky band rides the
        target date (spec «sticky-заголовок SHALL показывать целевую дату»)."""
        view = _view(qtbot, [_evt(1, date(1200, 1, 1), date(1200, 1, 3))],
                     rows_visible=8)
        source = view.indexes_for_event(1)[0]
        _press_and_arm(view, source)
        preview = view.drag_preview
        assert preview is not None and preview.event_id == 1
        assert preview.source_index == source
        assert preview.target_day == date(1200, 1, 1)  # still on the source row
        target = view.indexes_for_event(1)[-1]
        _drag_to(view, _row_center(view, target))
        preview = view.drag_preview
        assert preview.target_day == date(1200, 1, 3)
        assert preview.target_index == target
        qtbot.wait(STICKY_PUSH_MS + 150)  # the push-out settles in the band
        assert view.sticky_label.text() == format_game_date(date(1200, 1, 3))

    def test_ghost_wash_and_dimmed_card_are_accent_derivatives(
        self, qtbot, tmp_path, fill_spy
    ):
        """Task 5.1 / spec «Оформление шкалы из токенов»: the ghost is a
        ``color.accent`` derivative at alpha 0.35 — no new token, no hex."""
        runtime = _make_runtime(tmp_path)
        view = _view(qtbot, [_evt(1, date(1200, 1, 1), date(1200, 1, 3))],
                     theme=runtime, rows_visible=8)
        _press_and_arm(view, view.indexes_for_event(1)[0])
        _drag_to(view, _row_center(view, view.indexes_for_event(1)[-1]))
        view.grab()
        ghost = rows_palette(runtime).ghost
        accent = token_rgb(runtime.tokens, runtime.theme, "color.accent")
        assert (ghost.red(), ghost.green(), ghost.blue()) == accent
        assert any(
            c.red() == ghost.red() and c.green() == ghost.green()
            and c.blue() == ghost.blue() and c.alpha() == ghost.alpha()
            for c in fill_spy
        )

    def test_source_card_paints_dimmed_while_dragging(
        self, qtbot, tmp_path, opacity_spy
    ):
        """Spec: «Исходная карточка SHALL оставаться на месте в приглушённом
        виде» — the delegate renders the pressed card at the ghost alpha."""
        from app.presentation.views.timeline_widget import GHOST_ALPHA

        view = _view(qtbot, [_evt(1, date(1200, 1, 1), date(1200, 1, 3))],
                     rows_visible=8)
        _press_and_arm(view, view.indexes_for_event(1)[0])
        _drag_to(view, _row_center(view, view.indexes_for_event(1)[-1]))
        view.grab()
        assert any(abs(v - GHOST_ALPHA) < 1e-9 for v in opacity_spy)

    def test_retheme_mid_gesture_recolors_ghost_and_keeps_the_drag(
        self, qtbot, tmp_path, fill_spy
    ):
        """Spec «Живая ре-тема» (the active-drag half): switching themes while
        the gesture flies repaints the ghost from the NEW tokens — no widget
        recreation — and the gesture survives, so the release menu still fires."""
        runtime = _make_runtime(tmp_path)
        runtime.set_theme("dark")
        view = _view(qtbot, [_evt(1, date(1200, 1, 1), date(1200, 1, 3))],
                     theme=runtime, rows_visible=8)
        _press_and_arm(view, view.indexes_for_event(1)[0])
        _drag_to(view, _row_center(view, view.indexes_for_event(1)[-1]))
        runtime.set_theme("light")
        view._retheme()  # the listener path: repaint only, no re-modelling
        preview = view.drag_preview
        assert preview is not None and preview.target_day == date(1200, 1, 3)
        ghost = rows_palette(runtime).ghost  # the LIGHT theme's ghost now
        assert view.paint_palette().ghost.getRgb() == ghost.getRgb()
        fill_spy.clear()
        view.grab()
        assert any(
            c.getRgb() == ghost.getRgb() for c in fill_spy
        )  # the wash on screen is the new theme's accent derivative

    def test_release_over_collapsed_gap_cancels_without_menu(
        self, qtbot, drop_menu
    ):
        """Spec «Промах на схлопнутый провал отменяет»."""
        view = _view(qtbot, [
            _evt(1, date(1200, 1, 1), date(1200, 1, 1)),
            _evt(2, date(1200, 1, 20), date(1200, 1, 20)),  # Jan 2–19 collapsed
        ], rows_visible=8)
        assert any(isinstance(r, GapCollapsedRow) for r in view.rows)
        moved: list = []
        view.event_dates_moved.connect(lambda *a: moved.append(a))
        created, _stub = drop_menu
        _press_and_arm(view, view.index_for_event(1))
        gap_idx = next(
            i for i, r in enumerate(view.rows)
            if isinstance(r, GapCollapsedRow)
        )
        _drag_to(view, _row_center(view, gap_idx))
        assert view.drag_preview.target_day is None  # the ghost went out
        _release(view, _row_center(view, gap_idx))
        assert created == [] and moved == [] and view.drag_preview is None

    def test_release_beyond_the_last_row_cancels_no_extrapolation(
        self, qtbot, drop_menu
    ):
        """Task 5.1 removal proof: the deleted rail gesture extrapolated a
        target past the block's edges — here a release below the last row has
        NO target at all and lands on the cancel branch."""
        view = _view(qtbot, [_evt(1, date(1200, 1, 5), date(1200, 1, 5))],
                     rows_visible=8)
        moved: list = []
        view.event_dates_moved.connect(lambda *a: moved.append(a))
        created, _stub = drop_menu
        _press_and_arm(view, view.index_for_event(1))
        below = _row_center(view, len(view.rows) - 1)
        below.setY(below.y() + 3 * ROW_HEIGHT)  # past the tape, inside the viewport
        _drag_to(view, below)
        assert view.drag_preview.target_day is None
        _release(view, below)
        assert created == [] and moved == [] and view.drag_preview is None

    def test_esc_before_release_cancels(self, qtbot, drop_menu):
        """Spec «Отмена по Esc»: no menu, no signal after Esc."""
        view = _view(qtbot, [_evt(1, date(1200, 1, 1), date(1200, 1, 3))],
                     rows_visible=8)
        moved: list = []
        view.event_dates_moved.connect(lambda *a: moved.append(a))
        created, _stub = drop_menu
        _press_and_arm(view, view.indexes_for_event(1)[0])
        target = view.indexes_for_event(1)[-1]
        _drag_to(view, _row_center(view, target))
        assert view.drag_preview is not None
        _esc(view)
        assert view.drag_preview is None
        _release(view, _row_center(view, target))
        assert created == [] and moved == []

    def test_external_rebuild_cancels_the_gesture(self, qtbot, drop_menu):
        """Task 5.1: a rebuild under a live gesture leaves nothing to drop."""
        view = _view(qtbot, [_evt(1, date(1200, 1, 1), date(1200, 1, 3))],
                     rows_visible=8)
        moved: list = []
        view.event_dates_moved.connect(lambda *a: moved.append(a))
        created, _stub = drop_menu
        _press_and_arm(view, view.indexes_for_event(1)[0])
        view.update_events([  # external move of the same record — new tape
            _evt(1, date(1200, 2, 1), date(1200, 2, 2)),
        ])
        assert view.drag_preview is None
        _release(view, _row_center(view, min(3, len(view.rows) - 1)))
        assert created == [] and moved == []

    def test_release_on_the_source_day_shows_no_menu(self, qtbot, drop_menu):
        """Spec «Дроп на свой день без меню»: silent, and NOT a selection."""
        view = _view(qtbot, [_evt(1, date(1200, 1, 1), date(1200, 1, 3))],
                     rows_visible=8)
        ids: list[int] = []
        view.event_selected.connect(ids.append)
        moved: list = []
        view.event_dates_moved.connect(lambda *a: moved.append(a))
        created, _stub = drop_menu
        src = view.indexes_for_event(1)[0]
        p0 = _row_center(view, src)
        _press(view, p0)
        _drag_to(view, QPoint(p0.x(), p0.y() + DRAG_START_THRESHOLD_PX))
        _release(view, QPoint(p0.x(), p0.y() + DRAG_START_THRESHOLD_PX))
        assert created == [] and moved == [] and ids == []
        assert view.selected_id is None  # a drag release never selects

    def test_press_drag_on_a_header_row_is_not_a_gesture(self, qtbot, drop_menu):
        """Only cards arm; a header press-drag reaches neither gesture nor
        selection (spec «Заголовок дня не кликабелен»)."""
        view = _view(qtbot, [_evt(1, date(1200, 1, 1), date(1200, 1, 3))],
                     rows_visible=8)
        moved: list = []
        view.event_dates_moved.connect(lambda *a: moved.append(a))
        created, _stub = drop_menu
        header_idx = 0
        _press_and_arm(view, header_idx)
        assert view.drag_preview is None
        _release(view, _row_center(view, 4))
        assert created == [] and moved == [] and view.selected_id is None

    def test_period_rungs_keep_gestures_inert(self, qtbot, drop_menu):
        """Task 5.4 / spec «Жестов нет на крупных уровнях»: on «месяц» a
        press-drag is a no-op — no gesture, no drill, no emit, no scroll."""
        view = _view(qtbot, [
            _evt(1, date(1200, 3, 2), date(1200, 3, 4)),
            _evt(2, date(1200, 6, 1), date(1200, 6, 1)),  # keeps the tape alive
        ], rows_visible=4, level=ScaleUnit.MONTH)
        moved: list = []
        view.event_dates_moved.connect(lambda *a: moved.append(a))
        drilled: list = []
        view.period_drilled.connect(lambda *a: drilled.append(a))
        ids: list = []
        view.event_selected.connect(ids.append)
        created, _stub = drop_menu
        scroll_before = view.verticalScrollBar().value()
        card_idx = next(
            i for i, r in enumerate(view.rows) if isinstance(r, PeriodCardRow)
        )
        _press_and_arm(view, card_idx)
        assert view.drag_preview is None  # nothing armed on the period rung
        _release(view, _row_center(view, len(view.rows) - 1))
        assert created == [] and moved == [] and drilled == [] and ids == []
        assert view.level is ScaleUnit.MONTH
        assert view.verticalScrollBar().value() == scroll_before


class TestDropReleaseMenu:
    """Task 5.2: the release menu at the cursor carries exactly the core's
    ``drop_actions`` verdict; a chosen action is one ``event_dates_moved``."""

    #: event 1 closes Mar 5, event 2 stands on Mar 8 — the tape materializes
    #: every day in between (no day hides inside a collapse).
    EVENTS = [
        _evt(1, date(1200, 3, 3), date(1200, 3, 5)),
        _evt(2, date(1200, 3, 8), date(1200, 3, 8)),
    ]

    def _menu_texts(self, view, event_id: int, target: date, drop_menu) -> list[str]:
        created, stub = drop_menu
        stub.chooser = None
        source = next(e for e in view.events if e.id == event_id)
        view._open_drop_menu(source, target, QPoint(0, 0))
        return [a.text() for a in created[-1].actions()]

    def test_menu_items_follow_the_core_rules(self, qtbot, drop_menu):
        """Presence per task 1.4 (the requirement body is authoritative):
        after the end = move + extend-down, inside the span = move only,
        before the start = move + start-earlier; an open event dropped later
        only ever gets «Перенести» (extend is closed-events-only)."""
        view = _view(qtbot, list(self.EVENTS), rows_visible=4)
        assert self._menu_texts(view, 1, date(1200, 3, 15), drop_menu) == [
            "Перенести", "Расширить вниз до этого дня",
        ]
        assert self._menu_texts(view, 1, date(1200, 3, 4), drop_menu) == [
            "Перенести",
        ]
        assert self._menu_texts(view, 1, date(1200, 3, 1), drop_menu) == [
            "Перенести", "Начать раньше в этом дне",
        ]
        open_view = _view(qtbot, [_evt(9, date(1200, 6, 5), None)], rows_visible=4)
        assert self._menu_texts(open_view, 9, date(1200, 6, 20), drop_menu) == [
            "Перенести",
        ]
        assert self._menu_texts(open_view, 9, date(1200, 6, 2), drop_menu) == [
            "Перенести", "Начать раньше в этом дне",
        ]

    def _emit_drag(self, qtbot, drop_menu, pick, text: str):
        """Full gesture over ``EVENTS``: press ``pick(view)[0]``'s card, cross
        the threshold, release over ``pick(view)[1]``; the menu chooser picks
        ``text``. Returns the tape, the id-signal and menu captures."""
        view = _view(qtbot, list(self.EVENTS), rows_visible=12)
        moved: list = []
        view.event_dates_moved.connect(lambda *a: moved.append(a))
        ids: list = []
        view.event_selected.connect(ids.append)
        created, stub = drop_menu
        stub.chooser = _chooser(text)
        src_idx, tgt_idx = pick(view)
        _press_and_arm(view, src_idx)
        point = _row_center(view, tgt_idx)
        _drag_to(view, point)
        _release(view, point)
        return view, moved, ids, created

    @staticmethod
    def _mar3_to_mar8(view):
        return view.indexes_for_event(1)[0], view.indexes_for_event(2)[0]

    def test_release_elsewhere_opens_menu_and_move_keeps_the_length(
        self, qtbot, drop_menu
    ):
        """Spec «Перенос многодневки сохраняет длину»: 3–5 Mar → 8–10 Mar by
        one signal; the drag itself was never a selection."""
        _v, moved, ids, created = self._emit_drag(
            qtbot, drop_menu, self._mar3_to_mar8, "Перенести")
        assert len(created) == 1  # one menu, at the release point
        assert moved == [(1, date(1200, 3, 8), date(1200, 3, 10))]
        assert ids == [] and _v.drag_preview is None

    def test_extend_down_choice_shifts_only_the_end(self, qtbot, drop_menu):
        """Spec «Расширение вниз»: end := the target day, the start holds."""
        _v, moved, _ids, created = self._emit_drag(
            qtbot, drop_menu, self._mar3_to_mar8,
            "Расширить вниз до этого дня")
        assert moved == [(1, date(1200, 3, 3), date(1200, 3, 8))]
        assert len(created) == 1

    def test_start_earlier_choice_shifts_only_the_start(self, qtbot, drop_menu):
        """Spec «Начать раньше»: start := the target day, the end holds."""
        _v, moved, _ids, created = self._emit_drag(
            qtbot, drop_menu,
            lambda v: (v.indexes_for_event(2)[0], v.indexes_for_event(1)[0]),
            "Начать раньше в этом дне")
        assert moved == [(2, date(1200, 3, 3), date(1200, 3, 8))]
        assert [a.text() for a in created[-1].actions()] == [
            "Перенести", "Начать раньше в этом дне",
        ]

    def test_menu_closed_without_choice_writes_nothing(self, qtbot, drop_menu):
        """Spec «Закрытие меню без действия … не SHALL менять ничего»."""
        _v, moved, ids, created = self._emit_drag(
            qtbot, drop_menu, self._mar3_to_mar8, "◀ nonexistent ▶")
        assert moved == [] and ids == []
        assert len(created) == 1  # the menu opened, the choice stayed None
        assert _v.drag_preview is None
