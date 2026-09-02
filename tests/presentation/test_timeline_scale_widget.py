"""Widget tests for the ladder rungs on the panel (VM-as-mutation-point).

redesign-timeline-day-ladder revision: the rungs are the three period levels
painted as period headers + counter cards; the rung moves through the Alt/Opt
wheel (task 4.1) and period-card drills (task 4.2), both re-modelled locally by
the list and mirrored into the ViewModel here. The W4/W5 header switchers are
gone: the ladder buttons died with the Alt-wheel zoom (4.1), the rail-era
scale tests with the rail (3.1) and the grouping menu with task 8.1.

Offscreen; every scenario drives a real ``TimelineViewModel`` so the
VM-as-single-mutation-point contract stays exercised.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from app.presentation.utils.date_utils import (
    get_custom_months, set_custom_months,
)
from app.presentation.viewmodels.timeline_viewmodel import TimelineViewModel
from app.presentation.views.timeline_rows import (
    DayHeaderRow, PeriodCardRow, PeriodHeaderRow, ScaleUnit,
)
from app.presentation.views.timeline_widget import (
    ROW_HEIGHT,
    STICKY_HEIGHT,
    TimelineWidget,
)


@pytest.fixture(autouse=True)
def _default_months():
    saved = get_custom_months()
    set_custom_months(None)
    yield
    set_custom_months(saved)


def _evt(eid: int, start: date, end: date | None = None):
    return SimpleNamespace(id=eid, name=f"event-{eid}", start_date=start, end_date=end)


class _Service:
    def __init__(self, events):
        self._events = events

    async def get_all_events(self):
        return list(self._events)


def _panel(qtbot, events, height_px=260):
    vm = TimelineViewModel(_Service(events))
    vm._all_events = list(events)
    vm.events = list(events)
    vm._rebuild_rows()
    panel = TimelineWidget(vm)
    qtbot.addWidget(panel)
    panel.resize(300, height_px)
    panel.show()
    panel.update_events(vm.events)
    return panel, vm


def _descend(panel, vm, level: ScaleUnit) -> None:
    """Move the rung the way the app does it: VM writes, panel mirrors."""
    vm.level = level
    panel._sync_from_vm()


def _wheel(view, dy: int, modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    vp = view.viewport()
    pos = QPointF(vp.rect().center())
    QApplication.sendEvent(vp, QWheelEvent(
        pos, vp.mapToGlobal(pos.toPoint()), QPoint(0, 0), QPoint(0, dy),
        Qt.MouseButton.NoButton, modifiers,
        Qt.ScrollPhase.NoScrollPhase, False,
    ))


_EVENTS = [
    _evt(1, date(1200, 3, 2), date(1200, 3, 5)),
    _evt(2, date(1200, 3, 10), date(1200, 3, 12)),
    _evt(3, date(1200, 3, 20), date(1200, 4, 10)),
]


# ── the retired header switchers stay retired (tasks 4.1 / 8.1) ─────────────

class TestHeaderSwitchersAreGone:
    def test_ladder_switcher_buttons_are_gone(self, qtbot):
        """Task 4.1: the header rung switcher is deleted together with the
        Ctrl-wheel branch — the rung moves only by Alt/Opt wheel and drills."""
        import app.presentation.views.timeline_widget as mod
        from PySide6.QtWidgets import QPushButton

        panel, _vm = _panel(qtbot, _EVENTS)
        assert not hasattr(mod, "LADDER_CAPTIONS")
        assert not hasattr(panel, "scale_buttons")
        assert not hasattr(panel.rows_view, "_step_scale")
        captions = {b.text() for b in panel.findChildren(QPushButton)}
        assert not {"сутки", "месяц", "год"} & captions

    def test_grouping_switcher_is_gone(self, qtbot):
        """Task 8.1: the entity-grouping switcher is deleted whole — no button,
        no captions table, no ``group_by`` anywhere on panel or ViewModel."""
        import app.presentation.views.timeline_widget as mod
        from app.presentation.viewmodels import timeline_viewmodel as vm_mod

        panel, vm = _panel(qtbot, _EVENTS)
        assert not hasattr(mod, "GROUPING_CAPTIONS")
        assert not hasattr(mod, "GROUPING_ORDER")
        assert not hasattr(vm_mod, "EntityKind")
        assert not hasattr(panel, "group_button")
        assert not hasattr(panel, "group_actions")
        assert not hasattr(vm, "group_by")


# ── task 4.1 — Alt/Opt wheel steps the VM through the panel ─────────────────

class TestAltWheelThroughPanel:
    def test_alt_wheel_steps_vm_rung_by_rung_both_ways(self, qtbot):
        """The list re-models (cursor-anchored) and emits; the panel mirrors
        into the VM — the single mutation point — without a second re-model."""
        panel, vm = _panel(qtbot, _EVENTS)
        assert vm.level is ScaleUnit.DAY
        _wheel(panel.rows_view, -120, Qt.KeyboardModifier.AltModifier)
        assert vm.level is ScaleUnit.MONTH
        _wheel(panel.rows_view, -120, Qt.KeyboardModifier.AltModifier)
        assert vm.level is ScaleUnit.YEAR
        _wheel(panel.rows_view, -120, Qt.KeyboardModifier.AltModifier)
        assert vm.level is ScaleUnit.YEAR  # clamped at «год», still silent
        _wheel(panel.rows_view, 120, Qt.KeyboardModifier.AltModifier)
        assert vm.level is ScaleUnit.MONTH
        assert {type(r) for r in panel.rows_view.rows} == {
            PeriodHeaderRow, PeriodCardRow,
        }

    def test_ctrl_wheel_changes_no_layer(self, qtbot):
        """Spec «Alt-колесо вместо Ctrl»: Ctrl moves neither the VM, nor the
        tape, nor the scroll position."""
        panel, vm = _panel(qtbot, _EVENTS)
        _wheel(panel.rows_view, -120, Qt.KeyboardModifier.ControlModifier)
        assert vm.level is ScaleUnit.DAY
        assert panel.rows_view.level is ScaleUnit.DAY
        assert panel.rows_view.verticalScrollBar().value() == 0


# ── task 4.2 — drill clicks move the VM window/rung pair ────────────────────

class TestDrillThroughPanel:
    def _card_index(self, view, day: date) -> int:
        return next(
            i for i, r in enumerate(view.rows)
            if isinstance(r, PeriodCardRow) and r.date == day
        )

    def test_month_drill_sets_days_and_period_window_in_vm(self, qtbot):
        """Spec «Проваливание выставляет окно»: clicking March writes
        ``window=март`` + ``level=сутки`` through the VM; no id ever moves."""
        panel, vm = _panel(qtbot, _EVENTS)
        _descend(panel, vm, ScaleUnit.MONTH)
        ids: list = []
        panel.event_selected.connect(ids.append)
        view = panel.rows_view
        view._on_clicked(view.model().index(self._card_index(view, date(1200, 3, 1)), 0))
        assert vm.level is ScaleUnit.DAY
        assert vm.window == (date(1200, 3, 1), date(1200, 3, 31))
        assert panel.rows_view.level is ScaleUnit.DAY
        assert isinstance(panel.rows_view.rows[0], DayHeaderRow)
        assert panel.rows_view.rows[0].date == date(1200, 3, 1)  # top = 1 марта
        assert ids == [] and panel.rows_view.selected_id is None

    def test_year_drill_sets_months_and_year_window_in_vm(self, qtbot):
        """Spec «Провал из года в месяцы»: the 1245 card writes the whole-year
        window and the month rung — with the counter cards for every month."""
        events = [
            _evt(1, date(1245, 6, 1), date(1245, 6, 2)),
            _evt(2, date(1245, 11, 5), date(1245, 11, 5)),
        ]
        panel, vm = _panel(qtbot, events)
        _descend(panel, vm, ScaleUnit.YEAR)
        view = panel.rows_view
        view._on_clicked(view.model().index(self._card_index(view, date(1245, 1, 1)), 0))
        assert vm.level is ScaleUnit.MONTH
        assert vm.window == (date(1245, 1, 1), date(1245, 12, 31))
        months = [r.date for r in view.rows if isinstance(r, PeriodCardRow)]
        assert months == [date(1245, m, 1) for m in range(1, 13)]


# ── the rung content: period rungs and their sticky captions ────────────────

class TestPeriodRungs:
    def test_month_rung_counters_and_captions(self, qtbot):
        panel, vm = _panel(qtbot, _EVENTS)
        _descend(panel, vm, ScaleUnit.MONTH)
        view = panel.rows_view
        counters = {r.date: r.count for r in view.rows if isinstance(r, PeriodCardRow)}
        assert counters == {date(1200, 3, 1): 3, date(1200, 4, 1): 1}
        view.verticalScrollBar().setValue(0)
        assert view.sticky_label.text() == "Март 1200"
        scroll_end = view.verticalScrollBar().maximum()
        view.verticalScrollBar().setValue(scroll_end)
        assert view.sticky_label.text() in {"Март 1200", "Апрель 1200"}

    def test_year_rung_lists_every_year_of_the_span(self, qtbot):
        events = [
            _evt(1, date(1240, 6, 1), date(1240, 6, 2)),
            _evt(2, date(1243, 1, 1), date(1243, 1, 1)),
        ]
        panel, vm = _panel(qtbot, events)
        vm.window = (date(1240, 1, 1), date(1243, 12, 31))
        panel.update_events(vm.events)
        _descend(panel, vm, ScaleUnit.YEAR)
        cards = [r for r in panel.rows_view.rows if isinstance(r, PeriodCardRow)]
        assert [r.date.year for r in cards] == [1240, 1241, 1242, 1243]
        assert [r.count for r in cards] == [1, 0, 0, 1]
        assert panel.rows_view.sticky_label.text() == "1240"

    def test_game_month_names_reach_period_captions(self, qtbot):
        panel, vm = _panel(qtbot, _EVENTS)
        _descend(panel, vm, ScaleUnit.MONTH)
        set_custom_months({3: "Таяние Снегов", 4: "Первая Вода"})
        _descend(panel, vm, ScaleUnit.DAY)
        _descend(panel, vm, ScaleUnit.MONTH)  # rebuild re-reads the caption map
        panel.rows_view.verticalScrollBar().setValue(0)
        assert panel.rows_view.sticky_label.text() == "Таяние Снегов 1200"

    def test_rail_area_press_drag_release_is_inert(self, qtbot):
        """Spec scenario «Рейки больше нет»: where the rail used to stand, a
        press-drag-release is handled by the row under the cursor — no separate
        rail zone exists, so no window change, no dates_moved and no selection."""
        panel, vm = _panel(qtbot, _EVENTS)
        view = panel.rows_view
        moved: list = []
        panel.event_dates_moved.connect(lambda *a: moved.append(a))
        panel.window_changed.connect(lambda *a: moved.append(a))
        vp = view.viewport()
        top = view.visualItemRect(view.item(0)).topLeft()
        for kind, dy in (
            (QEvent.Type.MouseButtonPress, 0),
            (QEvent.Type.MouseMove, 80),
            (QEvent.Type.MouseButtonRelease, 80),
        ):
            point = top + QPoint(4, 6 + dy)  # the old rail column
            QApplication.sendEvent(vp, QMouseEvent(
                kind, QPointF(point), vp.mapToGlobal(point),
                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            ))
        QApplication.processEvents()
        assert moved == []
        assert view.selected_id is None
        assert view.level is ScaleUnit.DAY  # no drill was triggered either
        assert view.verticalScrollBar().value() == 0  # the rail drag is dead


def test_panel_geometry_constants_still_hold_with_the_rebuilt_header(qtbot):
    panel, _vm = _panel(qtbot, _EVENTS)
    assert panel.rows_view.viewport().y() >= STICKY_HEIGHT
    first = panel.rows_view.item(0)
    assert panel.rows_view.visualItemRect(first).height() == ROW_HEIGHT
