"""E2E for the day-ladder zoom (task 8.2 rewrite of the retired scale e2e).

The pre-redesign scale e2e drove the Ctrl-wheel zoom, the rail jump, the
rail range-drag and the header switchers — all deleted with the rail (design
D9). Its replacement coverage offscreen lives in ``test_timeline_widget.py``
and ``test_timeline_scale_widget.py``; this file keeps the whole-app contour:
the Alt/Opt + wheel gesture on the REAL boot-wired list steps the ladder both
ways (spec «Alt-колесо вместо Ctrl», «Лестница ступеней просмотра»), Ctrl is
dead, and a click on a period card drills one rung down with the window set
to the period while the selection stays put (spec «Проваливание выставляет
окно»). Events are created through the real «+» dialog; the wheel is a
synthetic ``QWheelEvent`` on the real list viewport.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from app.presentation.utils.date_utils import format_game_date
from app.presentation.views.timeline_rows import (
    DayHeaderRow, PeriodCardRow, PeriodHeaderRow, ScaleUnit,
)
from app.presentation.views.timeline_widget import WINDOW_CHIP_ALL
from tests.ui import helpers


def _wheel(view, dy: int, modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    _wheel_at(view, dy, QPointF(view.viewport().rect().center()), modifiers)


def _wheel_at(view, dy: int, pos: QPointF,
              modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    """A wheel notch over an exact viewport position (anchor determinism)."""
    vp = view.viewport()
    QApplication.sendEvent(vp, QWheelEvent(
        pos, vp.mapToGlobal(pos.toPoint()), QPoint(0, 0), QPoint(0, dy),
        Qt.MouseButton.NoButton, modifiers,
        Qt.ScrollPhase.NoScrollPhase, False,
    ))
    QApplication.processEvents()


def _row_center(view, idx: int) -> QPointF:
    return QPointF(view.visualItemRect(view.item(idx)).center())


def _period_card(view, day: date) -> int:
    return next(
        i for i, r in enumerate(view.rows)
        if isinstance(r, PeriodCardRow) and r.date == day
    )


_ALT = Qt.KeyboardModifier.AltModifier
_EVENTS = [
    dict(start_date=QDate(1200, 3, 2), end_date=QDate(1200, 3, 5)),
    dict(start_date=QDate(1245, 6, 1), end_date=QDate(1245, 6, 2)),
]


async def _boot_two_years_apart(app, wait_for):
    _application, window = app
    for spec in _EVENTS:
        await helpers.create_event_via_ui(window, wait_for, "Scale", **spec)
    view = window.timeline_widget.rows_view
    await wait_for(lambda: len(view.events) == 2)
    return window, view


async def test_alt_wheel_steps_the_booted_ladder_both_ways(app, wait_for):
    """Task 8.2 / spec «Alt-колесо вместо Ctrl»: on the boot-wired panel the
    Alt/Opt wheel moves сутки → месяц → год (clamped at год), the tape really
    re-models to counter cards, Ctrl leaves every layer untouched, and the way
    back descends rung by rung to days — every descent installing the anchor
    period as the window (chip caption included, task 9 defects b/a)."""
    window, view = await _boot_two_years_apart(app, wait_for)
    panel = window.timeline_widget
    assert panel._vm.level is ScaleUnit.DAY

    _wheel(view, -120, _ALT)
    await helpers.wait_until_settled()
    assert panel._vm.level is ScaleUnit.MONTH
    _wheel(view, -120, _ALT)
    await helpers.wait_until_settled()
    assert panel._vm.level is ScaleUnit.YEAR
    assert all(
        isinstance(r, PeriodHeaderRow | PeriodCardRow) for r in view.rows
    )

    _wheel(view, -120, _ALT)  # clamped at «год» — silent
    await helpers.wait_until_settled()
    assert panel._vm.level is ScaleUnit.YEAR

    bar_before = view.verticalScrollBar().value()
    _wheel(view, -120, Qt.KeyboardModifier.ControlModifier)  # dead gesture
    await helpers.wait_until_settled()
    assert panel._vm.level is ScaleUnit.YEAR
    assert view.verticalScrollBar().value() == bar_before

    # The way back is steered by the cursor so the anchors are exact. Task 9
    # defect (b), spec «Приближение от карточки события»: the inward wheel is
    # a descent — the anchor period becomes the window («ступень — сутки,
    # окно — август»); defect (a)'s chip caption follows on both descents.
    view.verticalScrollBar().setValue(0)
    _wheel_at(view, 120, _row_center(view, _period_card(view, date(1200, 1, 1))), _ALT)
    await helpers.wait_until_settled()
    assert panel._vm.level is ScaleUnit.MONTH
    assert panel._vm.window == (date(1200, 1, 1), date(1200, 12, 31))
    assert panel.window_chip.text() != WINDOW_CHIP_ALL
    _wheel_at(view, 120, _row_center(view, _period_card(view, date(1200, 3, 1))), _ALT)
    await helpers.wait_until_settled()
    assert panel._vm.level is ScaleUnit.DAY
    assert panel._vm.window == (date(1200, 3, 1), date(1200, 3, 31))
    bounds = (format_game_date(date(1200, 3, 1)), format_game_date(date(1200, 3, 31)))
    assert panel.window_chip.text() == f"{bounds[0]} — {bounds[1]} ▾"
    assert all(
        date(1200, 3, 1) <= r.date <= date(1200, 3, 31) for r in view.rows
    )
    await wait_for(lambda: any(isinstance(r, DayHeaderRow) for r in view.rows))


async def test_period_card_click_drills_with_the_period_window(app, wait_for):
    """Task 8.2 / spec «Проваливание выставляет окно»: from «месяц» a click on
    the March card drops to сутки with window = 1–31 марта — the button caption
    and the day tape follow, and no event gets selected."""
    window, view = await _boot_two_years_apart(app, wait_for)
    panel = window.timeline_widget
    panel._vm.level = ScaleUnit.MONTH
    panel._sync_from_vm()
    panel.update_events(panel._vm.events)
    await helpers.wait_until_settled()

    march = next(
        i for i, r in enumerate(view.rows)
        if isinstance(r, PeriodCardRow) and r.date == date(1200, 3, 1)
    )
    rect = view.visualItemRect(view.item(march))
    assert rect.isValid()
    panel.rows_view._on_clicked(view.model().index(march, 0))
    await helpers.wait_until_settled()

    await wait_for(lambda: panel._vm.level is ScaleUnit.DAY)
    assert panel._vm.window == (date(1200, 3, 1), date(1200, 3, 31))
    # Task 9 defect (a): the chip mirrors the drilled window — «Все дни» here
    # means the caption missed a window the VM already owns.
    bounds = (format_game_date(date(1200, 3, 1)), format_game_date(date(1200, 3, 31)))
    assert panel.window_chip.text() == f"{bounds[0]} — {bounds[1]} ▾"
    # The tape re-models to exactly the windowed March days, top row first.
    assert isinstance(view.rows[0], DayHeaderRow)
    assert view.rows[0].date == date(1200, 3, 1)  # top of the tape = 1 марта
    assert all(r.date <= date(1200, 3, 31) for r in view.rows)
    assert view.selected_id is None  # a drill selects nothing
