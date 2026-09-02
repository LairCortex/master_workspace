"""Header toggle «Скрыть даты без событий» (task 7.3, spec «Скрытие дат без событий»).

The checkable control sits next to «Выбор даты», defaults to OFF, is session-only
(nothing persists it), and its toggled path writes ``vm.hide_empty`` (the single
mutation point, design D7) — the mirror re-models the tape: empty days,
collapsed gaps and empty period cards disappear on every rung and return
verbatim when the toggle goes back off; sample, selection and the date window
are untouched throughout.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox

from app.presentation.utils.date_utils import (
    get_custom_months, set_custom_months,
)
from app.presentation.viewmodels.timeline_viewmodel import (
    TimelineViewModel,
)
from app.presentation.views.timeline_rows import (
    EmptyDayRow, EventRow, GapCollapsedRow, PeriodCardRow, ScaleUnit,
)
from app.presentation.views.timeline_widget import (
    HIDE_EMPTY_TOGGLE_TEXT,
    TimelineWidget,
)


@pytest.fixture(autouse=True)
def _default_months():
    saved = get_custom_months()
    set_custom_months(None)
    yield
    set_custom_months(saved)


def _evt(eid: int, start: date, end: date | None = None):
    return SimpleNamespace(
        id=eid, name=f"event-{eid}", start_date=start, end_date=end
    )


# March 1 + June 1: a ~2-month emptiness stands as placeholders + a collapsed
# gap on the day rung; April/May stay empty months on the MONTH rung; 1201 is
# an empty year on the YEAR rung.
_EVENTS = [
    _evt(1, date(1200, 3, 1), date(1200, 3, 1)),
    _evt(2, date(1205, 6, 1), date(1205, 6, 1)),
    # closes 13 eventless days after June 1 → expanded EmptyDay rows (13 ≤ 14),
    # while the corridor between the years stands as one collapsed gap.
    _evt(3, date(1205, 6, 15), date(1205, 6, 15)),
]


class _Service:
    async def get_all_events(self):
        return list(_EVENTS)


def _wired_panel(qtbot):
    """Panel on a REAL ViewModel driven exactly like the app (the toggle only
    moves ``vm.hide_empty`` and mirrors — no event reload is needed)."""
    vm = TimelineViewModel(_Service())
    vm._all_events = list(_EVENTS)
    vm.events = list(_EVENTS)
    vm._rebuild_rows()
    panel = TimelineWidget(vm)
    qtbot.addWidget(panel)
    panel.resize(300, 260)
    panel.show()
    panel.update_events(vm.events)
    return panel, vm


def _empty_positions(view):
    return [
        r for r in view.rows
        if isinstance(r, EmptyDayRow | GapCollapsedRow)
        or (isinstance(r, PeriodCardRow) and r.count == 0)
    ]


class TestHeaderControl:
    def test_toggle_next_to_the_date_button_default_off(self, qtbot):
        """Spec: a checkable control next to «Выбор даты», off by default."""
        panel, _vm = _wired_panel(qtbot)
        toggle = panel.hide_empty_toggle
        assert isinstance(toggle, QCheckBox)
        assert toggle.text() == HIDE_EMPTY_TOGGLE_TEXT
        assert not toggle.isChecked()  # «по умолчанию выключена»
        # the header sibling: «Выбор даты» button and the toggle side by side
        assert panel.window_chip.toolTip() == "Выбор даты"

    def test_session_only_a_fresh_panel_starts_unchecked_again(self, qtbot):
        """Spec «Вид не переживает перезапуск»: the state lives in the session
        only — a NEW ViewModel (fresh open) opens «тумблер выключен» with no
        persisted trace to read back."""
        panel, vm = _wired_panel(qtbot)
        panel.hide_empty_toggle.setChecked(True)
        assert vm.hide_empty is True
        reopened = TimelineWidget(TimelineViewModel(_Service()))
        qtbot.addWidget(reopened)
        assert not reopened.hide_empty_toggle.isChecked()

    def test_toggle_writes_the_viewmodel_knob(self, qtbot):
        """The panel mirrors; the VM setter is the single mutation point."""
        panel, vm = _wired_panel(qtbot)
        panel.hide_empty_toggle.toggle()
        assert vm.hide_empty is True
        panel.hide_empty_toggle.toggle()
        assert vm.hide_empty is False


class TestToggleCutsEmptinessOnEveryRung:
    def test_day_rung_placeholders_and_gaps_cut_then_return(self, qtbot):
        """Spec «Пустые дни исчезают»: with the toggle on the day rung keeps
        only day headers and event cards; off restores every empty position."""
        panel, vm = _wired_panel(qtbot)
        view = panel.rows_view
        before = _empty_positions(view)
        assert any(isinstance(r, EmptyDayRow) for r in before)
        assert any(isinstance(r, GapCollapsedRow) for r in before)

        panel.hide_empty_toggle.setChecked(True)
        assert _empty_positions(view) == []
        assert any(isinstance(r, EventRow) for r in view.rows)
        assert view.rows[0].date == date(1200, 3, 1)  # the tape still starts
        assert view.rows[-1].date == date(1205, 6, 15)  # …and ends with cards

        panel.hide_empty_toggle.setChecked(False)
        assert _empty_positions(view) == before

    def test_month_rung_empty_period_cards_cut_then_return(self, qtbot):
        """Spec «Пустые периоды исчезают» on MONTH: the eventless months of
        the 1200-03…1205-06 span are cut by the toggle and return with it."""
        panel, vm = _wired_panel(qtbot)
        vm.level = ScaleUnit.MONTH
        panel._sync_from_vm()
        view = panel.rows_view
        empty_before = _empty_positions(view)
        # the whole corridor between the two event months stands empty…
        assert date(1200, 4, 1) in [r.date for r in empty_before]
        assert date(1205, 5, 1) in [r.date for r in empty_before]
        assert len(empty_before) == 62  # 64 months − March 1200 − June 1205

        panel.hide_empty_toggle.setChecked(True)
        assert _empty_positions(view) == []
        assert [r.date for r in view.rows if isinstance(r, PeriodCardRow)] == [
            date(1200, 3, 1), date(1205, 6, 1),
        ]  # the non-empty counters stay put

        panel.hide_empty_toggle.setChecked(False)
        assert [r.date for r in _empty_positions(view)] == [
            r.date for r in empty_before
        ]

    def test_year_rung_empty_period_cards_cut_then_return(self, qtbot):
        """Same cut on YEAR: the emptiness between the event years vanishes
        with the toggle and comes back when it goes off."""
        panel, vm = _wired_panel(qtbot)
        vm.level = ScaleUnit.YEAR
        panel._sync_from_vm()
        view = panel.rows_view
        empty_before = _empty_positions(view)
        assert [r.date.year for r in empty_before] == [1201, 1202, 1203, 1204]

        panel.hide_empty_toggle.setChecked(True)
        assert _empty_positions(view) == []
        assert [r.date.year for r in view.rows if isinstance(r, PeriodCardRow)] == [
            1200, 1205,
        ]

        panel.hide_empty_toggle.setChecked(False)
        assert _empty_positions(view) == empty_before

    def test_toggle_keeps_window_sample_and_selection(self, qtbot):
        """The knob only cuts positions: the window, the sample and the
        selection survive untouched (VM ``hide_empty`` setter contract)."""
        panel, vm = _wired_panel(qtbot)
        vm.window = (date(1200, 1, 1), date(1205, 12, 31))
        vm.select_event_by_id(1)
        panel.update_events(vm.events)
        panel.set_selected(vm.selected_event.id)  # the wiring's selection echo
        view = panel.rows_view
        assert any(isinstance(r, GapCollapsedRow) for r in view.rows)
        panel.hide_empty_toggle.setChecked(True)
        assert vm.window == (date(1200, 1, 1), date(1205, 12, 31))
        assert vm.selected_event is not None and vm.selected_event.id == 1
        assert view.selected_id == 1  # the wash followed the re-model
        assert not any(isinstance(r, GapCollapsedRow) for r in view.rows)
