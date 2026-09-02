"""Widget tests for the «Выбор даты» window button (task 7.1) and jumps.

Covers tasks 3.1–3.3 offscreen: the header lost its ``CustomDateEdit`` pair
with apply/clear and gained one chip plus the jump-button row while the «+»
menu stays alive; the popover picks a range with two taps (live-apply, no
separate «Применить»), re-arms on a backwards second tap, resets to «Все дни»,
and collapses to a single calendar when the room under the chip is too low;
``Alt+Up``/``Alt+Down`` scoped to the panel walk EVENT rows across empty days
and stay inert at the sample edges.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QDate, QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QPushButton

from app.presentation.utils.date_utils import (
    format_game_date, get_custom_months, set_custom_months,
)
from app.presentation.viewmodels.timeline_viewmodel import TimelineViewModel
from app.presentation.views.timeline_rows import (
    DayHeaderRow, EmptyDayRow, EventRow, GapCollapsedRow, PeriodCardRow,
    ScaleUnit,
)
from app.presentation.views.timeline_widget import (
    EMPTY_HINT_TEXT,
    WINDOW_CHIP_ALL,
    ROW_HEIGHT,
    STICKY_HEIGHT,
    TimelineWidget,
    window_chip_text,
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


def _vm():
    class _VM:
        events: list = []
    return _VM()


def _panel(qtbot, events=(), height_px=160):
    panel = TimelineWidget(_vm())
    qtbot.addWidget(panel)
    panel.resize(280, height_px)
    panel.show()
    if events:
        panel.update_events(events)
    return panel


def _visible(view, idx: int) -> bool:
    rect = view.visualItemRect(view.item(idx))
    return 0 <= rect.top() and rect.bottom() <= view.viewport().height()


def _press(view, key: int, alt: bool = True) -> None:
    """Real key event through the app dispatcher, as the shortcuts need it."""
    mod = Qt.KeyboardModifier.AltModifier if alt else Qt.KeyboardModifier.NoModifier
    for etype in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        QApplication.sendEvent(view, QKeyEvent(etype, key, mod))


# ── 3.1 — header surface: chip + jump row, old controls gone, «+» alive ────

class TestHeaderSurface:
    def test_chip_and_jump_buttons_present_old_controls_gone(self, qtbot):
        """Task 3.1: «Выбор даты» button exists; the W3b-era date fields are dead."""
        panel = _panel(qtbot)
        assert panel.window_chip.text() == WINDOW_CHIP_ALL
        assert panel.jump_prev_button.text() == "⤒"
        assert panel.jump_next_button.text() == "⤓"
        for gone in ("legacy_date_start", "legacy_date_end", "legacy_apply",
                     "legacy_clear"):
            assert not hasattr(panel, gone)

        def _outside_popup(widget) -> bool:
            while widget is not None:
                if widget is panel.window_popup:
                    return False
                widget = widget.parent()
            return True

        # nothing from the removed controls is left on the panel itself —
        # the popover's calendar nav owns its own ◀/▶ glyphs, outside it none
        # of the old captions exists anymore.
        texts = {
            b.text() for b in panel.findChildren(QPushButton) if _outside_popup(b)
        }
        assert "▶" not in texts and "✕" not in texts

    def test_add_button_menu_still_alive_and_chip_is_a_button(self, qtbot):
        """Task 3.1 ««+»-меню живо»: the right-click menu wiring survived."""
        from PySide6.QtCore import Qt as _Qt
        panel = _panel(qtbot)
        assert panel.window_chip.toolTip() == "Выбор даты"
        assert panel.add_button.contextMenuPolicy() == _Qt.ContextMenuPolicy.CustomContextMenu

    def test_jump_buttons_are_right_of_empty_row_and_fixed_size(self, qtbot):
        """Task 3.1: the second row was built for the jump pair specifically."""
        panel = _panel(qtbot)
        assert (panel.jump_prev_button.width(), panel.jump_next_button.height()) == (30, 30)
        assert panel.jump_prev_button.toolTip().endswith("(Alt+Up)")
        assert panel.jump_next_button.toolTip().endswith("(Alt+Down)")


class TestChipTextIsGameFormatted:
    def test_chip_shows_game_formated_borders(self, qtbot):
        """Task 7.1/spec «Выбор даты»: bounds in the game format."""
        panel = _panel(qtbot)
        panel._on_window_range(date(1200, 1, 5), date(1200, 3, 9))
        assert panel.window_chip.text() == "05 Январь 1200 — 09 Март 1200 ▾"

    def test_chip_falls_back_to_all_dates_when_either_bound_missing(self, qtbot):
        panel = _panel(qtbot)
        panel._on_window_range(date(1200, 1, 5), None)
        assert panel.window_chip.text() == WINDOW_CHIP_ALL
        assert window_chip_text(None, None) == WINDOW_CHIP_ALL


# ── 3.2 — popover: two taps live-apply, backwards tap, reset, fallback ─────

class TestWindowPopover:
    def test_first_tap_only_arms_start_second_applies_and_closes(self, qtbot):
        """Task 7.1: no «Применить» anywhere — the finish tap applies live (D9)."""
        panel = _panel(qtbot)
        received: list[tuple] = []
        panel.window_changed.connect(lambda s, e: received.append((s, e)))

        panel.window_popup.show()  # the button click path, minus the WM geometry
        panel.window_popup.start_calendar.clicked.emit(QDate(1200, 1, 5))
        assert received == []  # start alone is not a window yet

        panel.window_popup.start_calendar.clicked.emit(QDate(1200, 1, 9))
        assert received == [(date(1200, 1, 5), date(1200, 1, 9))]
        assert not panel.window_popup.isVisible()
        assert panel.window_chip.text() == "05 Январь 1200 — 09 Январь 1200 ▾"

    def test_finish_may_be_picked_on_the_second_calendar(self, qtbot):
        panel = _panel(qtbot)
        received: list[tuple] = []
        panel.window_changed.connect(lambda s, e: received.append((s, e)))
        panel.window_popup.start_calendar.clicked.emit(QDate(1200, 2, 1))
        panel.window_popup.end_calendar.clicked.emit(QDate(1200, 2, 20))
        assert received == [(date(1200, 2, 1), date(1200, 2, 20))]

    def test_earlier_second_tap_rearms_instead_of_backwards_range(self, qtbot):
        """Spec «Живое применение»: only forward ranges reach the ViewModel."""
        panel = _panel(qtbot)
        received: list[tuple] = []
        panel.window_changed.connect(lambda s, e: received.append((s, e)))
        panel.window_popup.start_calendar.clicked.emit(QDate(1200, 1, 9))
        panel.window_popup.start_calendar.clicked.emit(QDate(1200, 1, 3))  # earlier
        assert received == []  # re-armed, nothing applied
        assert panel.window_popup._pending_start == date(1200, 1, 3)
        panel.window_popup.start_calendar.clicked.emit(QDate(1200, 1, 12))
        assert received == [(date(1200, 1, 3), date(1200, 1, 12))]

    def test_reset_emits_clear_and_restores_chip(self, qtbot):
        """Task 7.1 «Сбросить» — the window's only reset → (None, None) + «Все дни»."""
        panel = _panel(qtbot)
        panel.window_popup.start_calendar.clicked.emit(QDate(1200, 1, 5))
        panel.window_popup.start_calendar.clicked.emit(QDate(1200, 1, 9))

        received: list[tuple] = []
        panel.window_changed.connect(lambda s, e: received.append((s, e)))
        panel.window_popup.show()  # reopen; the pick above closed it
        panel.window_popup.reset_button.click()

        assert received == [(None, None)]
        assert not panel.window_popup.isVisible()
        assert panel.window_chip.text() == WINDOW_CHIP_ALL

    def test_button_click_opens_the_popover_seeded_with_the_window(self, qtbot):
        """Task 7.1: pressing «Выбор даты» drops the popover,
        re-seeding the currently applied window."""
        panel = _panel(qtbot)
        panel._on_window_range(date(1200, 4, 3), None)
        panel.window_chip.click()
        assert panel.window_popup.isVisible()
        assert panel.window_popup.start_calendar.selectedDate() == QDate(1200, 4, 3)
        panel.window_popup.close()

    def test_reopening_rearms_a_finished_pick(self, qtbot):
        """A closed pick must not leak its start into the next popover."""
        panel = _panel(qtbot)
        panel.window_popup.start_calendar.clicked.emit(QDate(1200, 1, 5))
        panel.window_popup.start_calendar.clicked.emit(QDate(1200, 1, 9))
        panel.window_popup.open_at(panel.window_chip, (None, None))
        assert panel.window_popup._pending_start is None

    def test_open_at_seeds_calendars_with_the_live_window(self, qtbot):
        """Reopening keeps the applied borders visible on the calendars."""
        panel = _panel(qtbot)
        panel._on_window_range(date(1200, 4, 3), None)
        panel.window_popup.open_at(panel.window_chip, panel._window_range)
        assert panel.window_popup.start_calendar.selectedDate() == QDate(1200, 4, 3)

    def test_low_screen_fallback_shows_a_single_calendar(self, qtbot):
        """Fallback: no room for both calendars → taps assign both."""
        panel = _panel(qtbot)
        popup = panel.window_popup
        popup._fit_low_screen(10_000)
        assert not popup.end_calendar.isHidden()
        popup._fit_low_screen(0)
        assert popup.end_calendar.isHidden()
        # the single-calendar popover is still a complete range picker
        received: list[tuple] = []
        panel.window_changed.connect(lambda s, e: received.append((s, e)))
        popup.start_calendar.clicked.emit(QDate(1200, 1, 1))
        popup.start_calendar.clicked.emit(QDate(1200, 1, 4))
        assert received == [(date(1200, 1, 1), date(1200, 1, 4))]


# ── the applied window rides along into the tape (day-ladder revision) ──────

class TestWindowShapesTheScale:
    """Spec «Окно, пустые позиции и подсказки»: the chip window rides into the
    ViewModel as ``window`` and the panel re-mirrors it on every reload — the
    tape enumerates exactly the window's days (day ladder, design D7)."""

    _ALL = [
        _evt(1, date(1200, 1, 5), date(1200, 1, 6)),
        _evt(2, date(1200, 3, 10)),
    ]

    def _wired_panel(self, qtbot):
        """A panel on a REAL ViewModel, wired exactly like the app does:
        window_changed → ``vm.window`` → reload of the VM's slice."""
        class _Service:
            async def get_all_events(self):
                return list(TestWindowShapesTheScale._ALL)

        vm = TimelineViewModel(_Service())
        vm._all_events = list(self._ALL)
        vm.events = list(self._ALL)
        vm._rebuild_rows()
        panel = TimelineWidget(vm)
        qtbot.addWidget(panel)
        panel.resize(280, 200)
        panel.show()
        # the wiring's ``on_window_changed`` twin — no lambda-in-lambda here
        def _apply_window(s, e):
            vm.window = (s, e)
            panel.update_events(vm.events)

        panel.window_changed.connect(_apply_window)
        panel.update_events(vm.events)
        return panel

    def test_applied_window_survives_into_the_rows(self, qtbot):
        panel = self._wired_panel(qtbot)
        panel.window_popup.range_applied.emit(date(1200, 1, 1), date(1200, 1, 10))
        view = panel.rows_view
        # The whole window is enumerated even though event 1 sits on day 5:
        # every day of Jan 1–10 keeps its sticky header, empty days keep
        # their «нет события» placeholder, nothing collapses.
        assert [r.date for r in view.rows if isinstance(r, DayHeaderRow)] == [
            date(1200, 1, d) for d in range(1, 11)
        ]
        assert {r.date for r in view.rows if isinstance(r, EventRow)} == {
            date(1200, 1, 5), date(1200, 1, 6),
        }
        assert not view.hint_label.isVisible()

    def test_window_without_events_shows_its_empty_days(self, qtbot):
        """Scenario «Пустое окно показано пустотой» on the panel, not only VM.
        February crosses neither event (the open one starts in March, so the
        window must sit before it)."""
        panel = self._wired_panel(qtbot)
        panel.window_popup.range_applied.emit(date(1200, 2, 1), date(1200, 2, 3))
        view = panel.rows_view
        assert [(type(r).__name__, r.date.day) for r in view.rows] == [
            ("DayHeaderRow", 1), ("EmptyDayRow", 1),
            ("DayHeaderRow", 2), ("EmptyDayRow", 2),
            ("DayHeaderRow", 3), ("EmptyDayRow", 3),
        ]
        assert not view.hint_label.isVisible()

    def test_reset_returns_the_scale_to_the_content_span(self, qtbot):
        panel = self._wired_panel(qtbot)
        panel.window_popup.range_applied.emit(date(1200, 1, 1), date(1200, 1, 10))
        panel.window_popup.range_applied.emit(None, None)
        view = panel.rows_view
        # «Все дни» → the content span: first event start … tape bottom
        # (the open Mar-10 event pulls the bottom a year past its start,
        # spec «Дно при бессрочных событиях»).
        assert view.rows[0].date == date(1200, 1, 5)
        assert view.rows[-1].date == date(1201, 3, 10)
        assert any(isinstance(r, GapCollapsedRow) for r in view.rows)
        assert panel.window_chip.text() == WINDOW_CHIP_ALL


class TestCaptionFollowsWindow:
    """Task 9 (defect a): the chip caption mirrors the ViewModel's window on
    EVERY path — a drill click writes ``vm.window`` past the popover and once
    left the chip reading «Все дни» under an active drilled window."""

    def test_period_drill_click_recaptions_the_chip(self, qtbot):
        """A real drill on a month card (task 4.2 path) recaptions the chip
        to the drilled period — the «Проваливание выставляет окно» contract
        covers the caption too, not only the tape."""
        panel = TestWindowShapesTheScale()._wired_panel(qtbot)
        view = panel.rows_view
        view.set_knobs(level=ScaleUnit.MONTH)
        idx = next(
            i for i, r in enumerate(view.rows)
            if isinstance(r, PeriodCardRow) and r.date == date(1200, 1, 1)
        )
        assert panel.window_chip.text() == WINDOW_CHIP_ALL
        view._on_clicked(view.model().index(idx, 0))
        assert panel.window_chip.text() == "01 Январь 1200 — 31 Январь 1200 ▾"
        assert panel._window_range == (date(1200, 1, 1), date(1200, 1, 31))
        assert panel.rows_view.window == (date(1200, 1, 1), date(1200, 1, 31))

    def test_external_window_reset_recaptions_on_next_sync(self, qtbot):
        """Spec «Внешний выбор с крупной ступени спускает лестницу»: the descent
        resets ``vm.window`` past the chip; the reload/sync that follows pulls
        the caption back to «Все дни» together with the tape."""
        panel = TestWindowShapesTheScale()._wired_panel(qtbot)
        panel.window_popup.range_applied.emit(date(1200, 1, 1), date(1200, 1, 10))
        assert panel.window_chip.text() != WINDOW_CHIP_ALL
        vm = panel._vm
        vm.window = None  # what select_event_by_id does to an excluded event
        panel.set_selected(None)  # the wiring's post-descent sync twin        assert panel.window_chip.text() == WINDOW_CHIP_ALL
        assert panel._window_range == (None, None)
        assert panel.rows_view.window == (None, None)


# ── task 7.1 — «Выбор даты»: single-day window, live apply, gap pre-fill ────

class TestDateChoiceTask71:
    """Spec «Выбор даты»: «дата = дата» is a ONE-day window, borders apply the
    instant the second tap lands (no «Применить», «Сбросить» is the only
    reset), and a click on the collapsed gap reopens the popover pre-filled
    with the gap's bounds (spec «Схлопнутый провал кликабелен для окна»)."""

    def test_button_is_the_date_choice_entry_default_all_days(self, qtbot):
        panel = _panel(qtbot)
        assert panel.window_chip.toolTip() == "Выбор даты"
        assert panel.window_chip.text() == WINDOW_CHIP_ALL == "Все дни ▾"

    def test_single_day_window_is_exactly_one_day(self, qtbot):
        """Spec «Окно из одного дня»: both bounds on the same 14 August →
        the tape shows only that day, the button shows its game date."""
        class _Service:
            async def get_all_events(self):
                return [_evt(1, date(1200, 8, 14)), _evt(2, date(1200, 9, 1))]

        vm = TimelineViewModel(_Service())
        panel = TimelineWidget(vm)
        qtbot.addWidget(panel)
        panel.resize(280, 200)
        panel.show()
        applied = []
        def _apply(s, e):
            applied.append((s, e))
        panel.window_changed.connect(_apply)

        # Two taps on the SAME calendar day: first arms, second applies
        # (equal bounds are the one-day window, not a re-arm).
        panel.window_popup.start_calendar.clicked.emit(QDate(1200, 8, 14))
        panel.window_popup.start_calendar.clicked.emit(QDate(1200, 8, 14))
        assert applied == [(date(1200, 8, 14), date(1200, 8, 14))]
        day = date(1200, 8, 14)
        panel.rows_view.set_knobs(window=(day, day))
        assert [(type(r).__name__, r.date) for r in panel.rows_view.rows] == [
            ("DayHeaderRow", day), ("EmptyDayRow", day),
        ]
        fmt = format_game_date(day)
        assert panel.window_chip.text() == f"{fmt} — {fmt} ▾"

    def test_live_apply_reaches_the_panel_without_extra_button(self, qtbot):
        """Spec «Живое применение и сброс»: the finishing tap applies — the
        chip caption and window_changed land with it, the popover closes."""
        panel = _panel(qtbot)
        received: list[tuple] = []
        panel.window_changed.connect(lambda s, e: received.append((s, e)))
        panel.window_popup.start_calendar.clicked.emit(QDate(1200, 5, 2))
        assert received == []  # start alone arms, nothing applied yet
        panel.window_popup.end_calendar.clicked.emit(QDate(1200, 5, 20))
        assert received == [(date(1200, 5, 2), date(1200, 5, 20))]
        assert not panel.window_popup.isVisible()
        assert panel.window_chip.text() != WINDOW_CHIP_ALL
        # the same popover resets to «Все дни» — its only reset
        panel.window_popup.show()
        panel.window_popup.reset_button.click()
        assert received[-1] == (None, None)
        assert panel.window_chip.text() == WINDOW_CHIP_ALL

    def test_gap_row_click_opens_popover_prefilled_with_gap(self, qtbot):
        """Spec «Схлопнутый провал кликабелен для окна»: clicking the collapsed
        gap reopens «Выбор даты» under the button with the gap's bounds
        pre-filled; nothing is applied, nothing is selected."""
        events = [
            _evt(1, date(1200, 1, 1), date(1200, 1, 1)),
            _evt(2, date(1200, 3, 10), date(1200, 3, 10)),
        ]
        panel = _panel(qtbot, events)
        view = panel.rows_view
        gap_idx = next(
            i for i, r in enumerate(view.rows) if isinstance(r, GapCollapsedRow)
        )
        gap = view.rows[gap_idx]
        # enabled for the click, never selectable; no id-signal path exists
        assert view.item(gap_idx).flags() == Qt.ItemFlag.ItemIsEnabled
        ids: list = []
        panel.event_selected.connect(ids.append)
        received: list[tuple] = []
        panel.window_changed.connect(lambda s, e: received.append((s, e)))

        view._on_clicked(view.model().index(gap_idx, 0))

        assert panel.window_popup.isVisible()
        assert panel.window_popup.start_calendar.selectedDate() == QDate(
            gap.date.year, gap.date.month, gap.date.day)
        assert panel.window_popup.end_calendar.selectedDate() == QDate(
            gap.end.year, gap.end.month, gap.end.day)
        assert received == []  # a pre-fill is not an application
        assert ids == [] and view.selected_id is None
        panel.window_popup.close()

    def test_gap_click_via_real_mouse_release(self, qtbot):
        """The pre-fill also survives a REAL press/release — the item's
        enablement (task 7.1) is what makes Qt deliver the click."""
        events = [
            _evt(1, date(1200, 1, 1), date(1200, 1, 1)),
            _evt(2, date(1200, 3, 10), date(1200, 3, 10)),
        ]
        panel = _panel(qtbot, events)
        view = panel.rows_view
        gap_idx = next(
            i for i, r in enumerate(view.rows) if isinstance(r, GapCollapsedRow)
        )
        vp = view.viewport()
        point = view.visualItemRect(view.item(gap_idx)).center()
        for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            QApplication.sendEvent(vp, QMouseEvent(
                kind, QPointF(point), vp.mapToGlobal(point),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton
                if kind is QEvent.Type.MouseButtonPress
                else Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            ))
        gap = view.rows[gap_idx]
        assert panel.window_popup.isVisible()
        assert panel.window_popup.start_calendar.selectedDate() == QDate(
            gap.date.year, gap.date.month, gap.date.day)
        panel.window_popup.close()


# ── 3.3 — panel-level jump navigation: buttons + Alt shortcuts ─────────────

class TestPanelJump:
    """E2E-flavoured widget tests: the panel jumps between event cards over a
    long open-event tape (cards stand on every covered day; the jump walks
    cards, and the first press from a fresh tape heads for the first card)."""

    _EVENTS = [
        _evt(1, date(1200, 1, 1), date(1200, 1, 1), name="Старт"),
        _evt(2, date(1200, 3, 1), date(1200, 3, 1), name="Середина"),
        _evt(3, date(1200, 6, 1), date(1200, 6, 1), name="Финиш"),
    ]

    def _panel_with_spread(self, qtbot):
        panel = _panel(qtbot, self._EVENTS)
        view = panel.rows_view
        indices = [view.index_for_event(eid) for eid in (1, 2, 3)]
        rows = view.rows
        # The corridors really are corridors: each ~2-month emptiness stands
        # as a collapsed gap the jumps have to walk over, not as neighbors.
        assert any(
            isinstance(r, GapCollapsedRow) for r in rows[indices[0]:indices[1]]
        )
        assert any(
            isinstance(r, GapCollapsedRow) for r in rows[indices[1]:indices[2]]
        )
        return panel, indices

    def test_button_jumps_over_empty_days_reach_event_rows(self, qtbot):
        """Task 3.3 «e2e»: each button press lands visibly on the next card;
        the first from the tape head reveals the first event's card."""
        panel, (i1, i2, i3) = self._panel_with_spread(qtbot)
        view = panel.rows_view
        panel.jump_next_button.click()
        assert view.currentRow() == i1 and _visible(view, i1)
        panel.jump_next_button.click()
        assert view.currentRow() == i2 and _visible(view, i2)
        panel.jump_next_button.click()
        assert view.currentRow() == i3 and _visible(view, i3)
        panel.jump_prev_button.click()
        assert view.currentRow() == i2 and _visible(view, i2)
        panel.jump_prev_button.click()
        assert view.currentRow() == i1 and _visible(view, i1)

    def test_repeated_press_at_the_edges_only_reaches_the_ends(self, qtbot):
        """Task 3.3: past the last/first card the scroll stops at the edge."""
        panel, (i1, _, i3) = self._panel_with_spread(qtbot)
        view = panel.rows_view
        for _ in range(5):
            panel.jump_next_button.click()
        assert view.currentRow() == i3
        tail_scroll = view.verticalScrollBar().value()
        panel.jump_next_button.click()  # already at the tail card: inert
        assert view.currentRow() == i3
        assert view.verticalScrollBar().value() == tail_scroll

        for _ in range(5):
            panel.jump_prev_button.click()
        head_scroll = view.verticalScrollBar().value()
        assert view.currentRow() == max(i1, 0)
        panel.jump_prev_button.click()  # already at the head card: inert
        assert view.currentRow() == max(i1, 0)
        assert view.verticalScrollBar().value() == head_scroll

    def test_alt_shortcuts_jump_with_panel_focus(self, qtbot):
        """Task 3.3: Alt+Down/Alt+Up are the keyboard twins of the buttons.
        (The list itself consumes the plain arrow first, so a shortcut press
        reads from the card the arrow landed on — same net as the old W3b
        harness: the first press from the head crosses the first corridor,
        the reverse press returns to the head card.)"""
        panel, (i1, i2, _) = self._panel_with_spread(qtbot)
        view = panel.rows_view
        view.setFocus(Qt.FocusReason.OtherFocusReason)
        QApplication.processEvents()
        _press(view, Qt.Key.Key_Down)
        assert view.currentRow() == i2
        _press(view, Qt.Key.Key_Up)
        assert view.currentRow() == i1

    def test_shortcuts_inert_at_head_and_stay_empty_state_safe(self, qtbot):
        """Spec «Навигация к событиям»: бездействие на краях + пустая панель."""
        panel, (i1, _, _) = self._panel_with_spread(qtbot)
        view = panel.rows_view
        panel.jump_next_button.click()  # land on the head card first
        assert view.currentRow() == i1
        view.setFocus(Qt.FocusReason.OtherFocusReason)
        QApplication.processEvents()
        _press(view, Qt.Key.Key_Up)  # at the head already: inert
        assert view.currentRow() == i1
        assert view.verticalScrollBar().value() == 0
        panel.jump_prev_button.click()  # the button twin stays inert too
        assert view.currentRow() == i1
        panel.update_events([])  # empty sample: the commands must not explode
        assert view.hint_label.text() == EMPTY_HINT_TEXT
        panel.jump_prev_button.click()
        panel.jump_next_button.click()

    def test_jump_never_selects_never_emits(self, qtbot):
        """Navigation is not selection: the id-contract layers stay put (D8)."""
        panel, (_, i2, _) = self._panel_with_spread(qtbot)
        received: list[int] = []
        panel.event_selected.connect(received.append)
        panel.jump_next_button.click()  # onto the head card
        panel.jump_next_button.click()  # and one corridor further
        assert panel.rows_view.currentRow() == i2
        assert received == [] and panel.rows_view.selected_id is None


def test_panel_geometry_constants_still_hold_with_the_new_header(qtbot):
    """Regression guard for 2.x invariants next to the rebuilt header."""
    panel = _panel(qtbot, [_evt(1, date(1200, 1, 1), date(1200, 1, 3))])
    assert panel.rows_view.viewport().y() >= STICKY_HEIGHT
    assert panel.rows_view.visualItemRect(panel.rows_view.item(0)).height() == ROW_HEIGHT
