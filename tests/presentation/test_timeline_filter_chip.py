"""Widget tests for the chip date filter and jump navigation (W3b group 3).

Covers tasks 3.1–3.3 offscreen: the header lost its ``CustomDateEdit`` pair
with apply/clear and gained one chip plus the jump-button row while the «+»
menu stays alive; the popover picks a range with two taps (live-apply, no
separate «Применить»), re-arms on a backwards second tap, resets to «Все даты»,
and collapses to a single calendar when the room under the chip is too low;
``Alt+Up``/``Alt+Down`` scoped to the panel walk EVENT rows across empty days
and stay inert at the sample edges.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QDate, QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QPushButton

from app.presentation.utils.date_utils import (
    get_custom_months, set_custom_months,
)
from app.presentation.views.timeline_widget import (
    EMPTY_HINT_TEXT,
    FILTER_CHIP_ALL,
    ROW_HEIGHT,
    STICKY_HEIGHT,
    TimelineWidget,
    filter_chip_text,
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
        """Task 3.1: chips/buttons exist; the date fields + apply/clear are dead."""
        panel = _panel(qtbot)
        assert panel.filter_chip.text() == FILTER_CHIP_ALL
        assert panel.jump_prev_button.text() == "⤒"
        assert panel.jump_next_button.text() == "⤓"
        for gone in ("filter_start", "filter_end", "filter_button",
                     "clear_filter_button"):
            assert not hasattr(panel, gone)

        def _outside_popup(widget) -> bool:
            while widget is not None:
                if widget is panel.filter_popup:
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
        assert panel.filter_chip.toolTip() == "Фильтр по датам"
        assert panel.add_button.contextMenuPolicy() == _Qt.ContextMenuPolicy.CustomContextMenu

    def test_jump_buttons_are_right_of_empty_row_and_fixed_size(self, qtbot):
        """Task 3.1: the second row was built for the jump pair specifically."""
        panel = _panel(qtbot)
        assert (panel.jump_prev_button.width(), panel.jump_next_button.height()) == (30, 30)
        assert panel.jump_prev_button.toolTip().endswith("(Alt+Up)")
        assert panel.jump_next_button.toolTip().endswith("(Alt+Down)")


class TestChipTextIsGameFormatted:
    def test_chip_shows_game_formated_borders(self, qtbot):
        """Task 3.1/spec «Чип-фильтр диапазона»: dates in the game format."""
        panel = _panel(qtbot)
        panel._on_filter_range(date(1200, 1, 5), date(1200, 3, 9))
        assert panel.filter_chip.text() == "05 Январь 1200 — 09 Март 1200 ▾"

    def test_chip_falls_back_to_all_dates_when_either_bound_missing(self, qtbot):
        panel = _panel(qtbot)
        panel._on_filter_range(date(1200, 1, 5), None)
        assert panel.filter_chip.text() == FILTER_CHIP_ALL
        assert filter_chip_text(None, None) == FILTER_CHIP_ALL


# ── 3.2 — popover: two taps live-apply, backwards tap, reset, fallback ─────

class TestFilterPopover:
    def test_first_tap_only_arms_start_second_applies_and_closes(self, qtbot):
        """Task 3.2: no «Применить» anywhere — the finish tap applies (D9)."""
        panel = _panel(qtbot)
        received: list[tuple] = []
        panel.filter_changed.connect(lambda s, e: received.append((s, e)))

        panel.filter_popup.show()  # the chip click path, minus the WM geometry
        panel.filter_popup.start_calendar.clicked.emit(QDate(1200, 1, 5))
        assert received == []  # start alone is not a filter yet

        panel.filter_popup.start_calendar.clicked.emit(QDate(1200, 1, 9))
        assert received == [(date(1200, 1, 5), date(1200, 1, 9))]
        assert not panel.filter_popup.isVisible()
        assert panel.filter_chip.text() == "05 Январь 1200 — 09 Январь 1200 ▾"

    def test_finish_may_be_picked_on_the_second_calendar(self, qtbot):
        panel = _panel(qtbot)
        received: list[tuple] = []
        panel.filter_changed.connect(lambda s, e: received.append((s, e)))
        panel.filter_popup.start_calendar.clicked.emit(QDate(1200, 2, 1))
        panel.filter_popup.end_calendar.clicked.emit(QDate(1200, 2, 20))
        assert received == [(date(1200, 2, 1), date(1200, 2, 20))]

    def test_earlier_second_tap_rearms_instead_of_backwards_range(self, qtbot):
        """Spec «Живое применение»: only forward ranges reach the ViewModel."""
        panel = _panel(qtbot)
        received: list[tuple] = []
        panel.filter_changed.connect(lambda s, e: received.append((s, e)))
        panel.filter_popup.start_calendar.clicked.emit(QDate(1200, 1, 9))
        panel.filter_popup.start_calendar.clicked.emit(QDate(1200, 1, 3))  # earlier
        assert received == []  # re-armed, nothing applied
        assert panel.filter_popup._pending_start == date(1200, 1, 3)
        panel.filter_popup.start_calendar.clicked.emit(QDate(1200, 1, 12))
        assert received == [(date(1200, 1, 3), date(1200, 1, 12))]

    def test_reset_emits_clear_and_restores_chip(self, qtbot):
        """Task 3.2 «Сбросить» → filter_changed(None, None) + «Все даты»."""
        panel = _panel(qtbot)
        panel.filter_popup.start_calendar.clicked.emit(QDate(1200, 1, 5))
        panel.filter_popup.start_calendar.clicked.emit(QDate(1200, 1, 9))

        received: list[tuple] = []
        panel.filter_changed.connect(lambda s, e: received.append((s, e)))
        panel.filter_popup.show()  # reopen; the pick above closed it
        panel.filter_popup.reset_button.click()

        assert received == [(None, None)]
        assert not panel.filter_popup.isVisible()
        assert panel.filter_chip.text() == FILTER_CHIP_ALL

    def test_chip_click_opens_the_popover_seeded_with_filter(self, qtbot):
        """Task 3.2 «Активация чипа»: pressing the chip drops the popover,
        re-seeding the currently applied borders."""
        panel = _panel(qtbot)
        panel._on_filter_range(date(1200, 4, 3), None)
        panel.filter_chip.click()
        assert panel.filter_popup.isVisible()
        assert panel.filter_popup.start_calendar.selectedDate() == QDate(1200, 4, 3)
        panel.filter_popup.close()

    def test_reopening_rearms_a_finished_pick(self, qtbot):
        """A closed pick must not leak its start into the next popover."""
        panel = _panel(qtbot)
        panel.filter_popup.start_calendar.clicked.emit(QDate(1200, 1, 5))
        panel.filter_popup.start_calendar.clicked.emit(QDate(1200, 1, 9))
        panel.filter_popup.open_at(panel.filter_chip, (None, None))
        assert panel.filter_popup._pending_start is None

    def test_open_at_seeds_calendars_with_the_live_filter(self, qtbot):
        """Reopening keeps the applied borders visible on the calendars."""
        panel = _panel(qtbot)
        panel._on_filter_range(date(1200, 4, 3), None)
        panel.filter_popup.open_at(panel.filter_chip, panel._filter_range)
        assert panel.filter_popup.start_calendar.selectedDate() == QDate(1200, 4, 3)

    def test_low_screen_fallback_shows_a_single_calendar(self, qtbot):
        """Task 3.2 fallback: no room for both calendars → taps assign both."""
        panel = _panel(qtbot)
        popup = panel.filter_popup
        popup._fit_low_screen(10_000)
        assert not popup.end_calendar.isHidden()
        popup._fit_low_screen(0)
        assert popup.end_calendar.isHidden()
        # the single-calendar popover is still a complete range picker
        received: list[tuple] = []
        panel.filter_changed.connect(lambda s, e: received.append((s, e)))
        popup.start_calendar.clicked.emit(QDate(1200, 1, 1))
        popup.start_calendar.clicked.emit(QDate(1200, 1, 4))
        assert received == [(date(1200, 1, 1), date(1200, 1, 4))]


# ── the applied window rides along into the scale (W3b audit fix) ───────────

class TestFilterRangeShapesTheScale:
    """Spec «Пустые и фильтрационные состояния»: with a live filter the scale
    enumerates the filter's own days — the panel forwards its chip window with
    every reload, exactly as the wiring feeds it the filtered events."""

    _ALL = [
        _evt(1, date(1200, 1, 5), date(1200, 1, 6)),
        _evt(2, date(1200, 3, 10)),
    ]

    def _wire_fake_vm(self, panel) -> None:
        """Mirror the app-side wiring: filter_changed → filtered reload."""
        def on_filter(start, end):
            visible = [
                e for e in self._ALL
                if start is None
                or (e.start_date >= start
                    and (e.end_date is None or e.end_date <= end))
            ]
            panel.update_events(visible)
        panel.filter_changed.connect(on_filter)

    def test_applied_window_survives_into_the_rows(self, qtbot):
        panel = _panel(qtbot)
        self._wire_fake_vm(panel)
        panel.filter_popup.range_applied.emit(date(1200, 1, 1), date(1200, 1, 10))
        view = panel.rows_view
        # The whole filter window is enumerated even though event 1 sits on
        # day 5: days 1–4 and 7–10 remain empty positions, not collapsed.
        assert [r.date for r in view.rows] == [date(1200, 1, d) for d in range(1, 11)]
        assert not view.hint_label.isVisible()

    def test_filter_window_without_events_shows_its_empty_days(self, qtbot):
        """Scenario «Пустой диапазон фильтра» on the panel, not only the VM."""
        panel = _panel(qtbot)
        self._wire_fake_vm(panel)
        panel.filter_popup.range_applied.emit(date(1200, 6, 1), date(1200, 6, 3))
        view = panel.rows_view
        assert [(r.kind.value, r.date.day) for r in view.rows] == [
            ("empty_day", 1), ("empty_day", 2), ("empty_day", 3),
        ]
        assert not view.hint_label.isVisible()

    def test_reset_returns_the_scale_to_the_sample_min_max(self, qtbot):
        panel = _panel(qtbot)
        self._wire_fake_vm(panel)
        panel.filter_popup.range_applied.emit(date(1200, 1, 1), date(1200, 1, 10))
        panel.filter_popup.range_applied.emit(None, None)
        view = panel.rows_view
        # «Все даты» → the sample's own min(start)…max(end|start) window again.
        assert view.rows[0].date == date(1200, 1, 5)
        assert view.rows[-1].date == date(1200, 3, 10)
        assert panel.filter_chip.text() == FILTER_CHIP_ALL


# ── 3.3 — panel-level jump navigation: buttons + Alt shortcuts ─────────────

class TestPanelJump:
    """E2E-flavoured widget tests: the sample spans weeks of empty days."""

    _EVENTS = [
        _evt(1, date(1200, 1, 1), name="Старт"),
        _evt(2, date(1200, 3, 1), name="Середина"),   # ~59 empty days in between
        _evt(3, date(1200, 6, 1), name="Финиш"),      # ~92 more empty days
    ]

    def _panel_with_spread(self, qtbot):
        panel = _panel(qtbot, self._EVENTS)
        indices = [panel.rows_view.index_for_event(eid) for eid in (1, 2, 3)]
        assert indices[-1] > 100  # the corridor is genuinely long
        return panel, indices

    def test_button_jumps_over_empty_days_reach_event_rows(self, qtbot):
        """Task 3.3 «e2e»: each button press lands visibly on the next event."""
        panel, (i1, i2, i3) = self._panel_with_spread(qtbot)
        view = panel.rows_view
        panel.jump_next_button.click()
        assert view.currentRow() == i2 and _visible(view, i2)
        panel.jump_next_button.click()
        assert view.currentRow() == i3 and _visible(view, i3)
        panel.jump_prev_button.click()
        assert view.currentRow() == i2 and _visible(view, i2)
        panel.jump_prev_button.click()
        assert view.currentRow() == i1 and _visible(view, i1)

    def test_repeated_press_at_the_edges_only_reaches_the_ends(self, qtbot):
        """Task 3.3: past the last/first event the scroll stops at the edge."""
        panel, (_, _, i3) = self._panel_with_spread(qtbot)
        view = panel.rows_view
        for _ in range(5):
            panel.jump_next_button.click()
        assert view.currentRow() == i3
        tail_scroll = view.verticalScrollBar().value()
        panel.jump_next_button.click()  # already at the tail event: inert
        assert view.currentRow() == i3
        assert view.verticalScrollBar().value() == tail_scroll

        for _ in range(5):
            panel.jump_prev_button.click()
        head_scroll = view.verticalScrollBar().value()
        assert view.currentRow() == 0
        panel.jump_prev_button.click()  # already at the head event: inert
        assert view.currentRow() == 0
        assert view.verticalScrollBar().value() == head_scroll

    def test_alt_shortcuts_jump_with_panel_focus(self, qtbot):
        """Task 3.3: Alt+Down/Alt+Up are the keyboard twins of the buttons."""
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
        view.setFocus(Qt.FocusReason.OtherFocusReason)
        QApplication.processEvents()
        _press(view, Qt.Key.Key_Up)  # at the head already
        assert view.currentRow() == i1
        assert view.verticalScrollBar().value() == 0
        panel.update_events([])  # empty sample: the commands must not explode
        assert view.hint_label.text() == EMPTY_HINT_TEXT
        panel.jump_prev_button.click()
        panel.jump_next_button.click()

    def test_jump_never_selects_never_emits(self, qtbot):
        """Navigation is not selection: the id-contract layers stay put (D8)."""
        panel, (_, i2, _) = self._panel_with_spread(qtbot)
        received: list[int] = []
        panel.event_selected.connect(received.append)
        panel.jump_next_button.click()
        assert panel.rows_view.currentRow() == i2
        assert received == [] and panel.rows_view.selected_id is None


def test_panel_geometry_constants_still_hold_with_the_new_header(qtbot):
    """Regression guard for 2.x invariants next to the rebuilt header."""
    panel = _panel(qtbot, [_evt(1, date(1200, 1, 1), date(1200, 1, 3))])
    assert panel.rows_view.viewport().y() >= STICKY_HEIGHT
    assert panel.rows_view.visualItemRect(panel.rows_view.item(0)).height() == ROW_HEIGHT
