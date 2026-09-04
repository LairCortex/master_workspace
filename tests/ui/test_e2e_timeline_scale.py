"""E2E for the day-ladder zoom on the QML island (Q2.5a task 6.3 port).

The pre-Q1 scale e2e drove the Ctrl-wheel zoom, the rail jump, the rail
range-drag and the header switchers — all deleted with the rail. The whole-app
contour lives on the island now: the Alt/Opt + wheel gesture on the REAL
boot-wired panel steps the ladder both ways (spec «Alt-колесо вместо Ctrl»,
«Лестница ступеней просмотра»), Ctrl is dead, one plain notch scrolls exactly
one row (spec «Шаг прокрутки»), and a click on a period card drills one rung
down with the window set to the period while the selection stays put (spec
«Проваливание выставляет окно»). Events are created through the real «+»
dialog; the wheel is a synthetic ``QWheelEvent`` on the island at the anchor
row's scene position.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt

from app.presentation.utils.date_utils import format_game_date
from app.presentation.views.timeline_date_popup import WINDOW_CHIP_ALL
from app.presentation.views.timeline_rows import (
    DayHeaderRow, PeriodCardRow, PeriodHeaderRow, ScaleUnit,
)
from tests.ui import helpers, timeline_probe

_ALT = Qt.KeyboardModifier.AltModifier
_CTRL = Qt.KeyboardModifier.ControlModifier
_EVENTS = [
    dict(start_date=QDate(1200, 3, 2), end_date=QDate(1200, 3, 5)),
    dict(start_date=QDate(1245, 6, 1), end_date=QDate(1245, 6, 2)),
]


def _period_card(window, needle: date) -> int:
    return next(
        i for i, r in enumerate(timeline_probe.rows(window))
        if isinstance(r, PeriodCardRow) and r.date == needle
    )


async def _boot_two_years_apart(app, wait_for):
    _application, window = app
    for spec in _EVENTS:
        await helpers.create_event_via_ui(window, wait_for, "Scale", **spec)
    tape = timeline_probe.tape(window)
    await wait_for(lambda: len(tape.events) == 2)
    return window, tape


async def test_alt_wheel_steps_the_booted_ladder_both_ways(app, wait_for):
    """Task 8.2 / spec «Alt-колесо вместо Ctrl»: on the boot-wired island the
    Alt/Opt wheel moves сутки → месяц → год (clamped at год), the tape really
    re-models to counter cards, Ctrl leaves every layer untouched, a plain
    notch steps exactly one row, and the way back descends rung by rung to
    days — every descent installing the anchor period as the window (chip
    caption included, task 9 defects b/a)."""
    window, tape = await _boot_two_years_apart(app, wait_for)
    panel = window.timeline_widget
    assert panel._vm.level is ScaleUnit.DAY

    list_center = timeline_probe.scene_point(window, timeline_probe.event_list(window))
    timeline_probe.wheel(window, list_center, -120, _ALT)
    await helpers.wait_until_settled()
    assert panel._vm.level is ScaleUnit.MONTH
    timeline_probe.wheel(window, list_center, -120, _ALT)
    await helpers.wait_until_settled()
    assert panel._vm.level is ScaleUnit.YEAR
    assert all(
        isinstance(r, PeriodHeaderRow | PeriodCardRow) for r in tape.rows
    )

    timeline_probe.wheel(window, list_center, -120, _ALT)  # clamped at «год»
    await helpers.wait_until_settled()
    assert panel._vm.level is ScaleUnit.YEAR

    scroll_before = timeline_probe.content_y(window)
    timeline_probe.wheel(window, list_center, -120, _CTRL)  # dead gesture
    await helpers.wait_until_settled()
    assert panel._vm.level is ScaleUnit.YEAR
    assert timeline_probe.content_y(window) == scroll_before

    # Spec «Шаг прокрутки»: one plain notch == exactly one row on the island.
    timeline_probe.set_content_y(window, 0)
    timeline_probe.wheel(window, list_center, -120)
    assert abs(timeline_probe.content_y(window)
               - timeline_probe.root(window).property("rowHeight")) < 0.01

    # The way back is steered by the cursor so the anchors are exact. Task 9
    # defect (b), spec «Приближение от карточки события»: the inward wheel is
    # a descent — the anchor period becomes the window («ступень — сутки,
    # окно — август»); defect (a)'s chip caption follows on both descents.
    timeline_probe.set_content_y(window, 0)
    timeline_probe.pump(4)
    anchor = _period_card(window, date(1200, 1, 1))
    timeline_probe.reveal(window, anchor)
    timeline_probe.wheel(window, timeline_probe.row_center(window, anchor), 120, _ALT)
    await helpers.wait_until_settled()
    assert panel._vm.level is ScaleUnit.MONTH
    assert panel._vm.window == (date(1200, 1, 1), date(1200, 12, 31))
    assert timeline_probe.chip_caption(window) != WINDOW_CHIP_ALL
    anchor = _period_card(window, date(1200, 3, 1))
    timeline_probe.reveal(window, anchor)
    timeline_probe.wheel(window, timeline_probe.row_center(window, anchor), 120, _ALT)
    await helpers.wait_until_settled()
    assert panel._vm.level is ScaleUnit.DAY
    assert panel._vm.window == (date(1200, 3, 1), date(1200, 3, 31))
    bounds = (format_game_date(date(1200, 3, 1)), format_game_date(date(1200, 3, 31)))
    assert timeline_probe.chip_caption(window) == f"{bounds[0]} — {bounds[1]} ▾"
    for r in tape.rows:
        d = getattr(r, "date", None)
        if d is not None:
            assert date(1200, 3, 1) <= d <= date(1200, 3, 31)
    await wait_for(lambda: any(isinstance(r, DayHeaderRow) for r in tape.rows))


async def test_period_card_click_drills_with_the_period_window(app, wait_for):
    """Task 8.2 / spec «Проваливание выставляет окно»: from «месяц» a click on
    the March card drops to сутки with window = 1–31 марта — the chip caption
    and the day tape follow, and no event gets selected."""
    window, tape = await _boot_two_years_apart(app, wait_for)
    panel = window.timeline_widget
    panel._vm.level = ScaleUnit.MONTH
    panel._sync_from_vm()
    panel.update_events(panel._vm.events)
    await helpers.wait_until_settled()
    timeline_probe.pump(4)

    march = _period_card(window, date(1200, 3, 1))
    timeline_probe.reveal(window, march)
    timeline_probe.click(window, timeline_probe.row_center(window, march))
    await helpers.wait_until_settled()

    await wait_for(lambda: panel._vm.level is ScaleUnit.DAY)
    assert panel._vm.window == (date(1200, 3, 1), date(1200, 3, 31))
    # Task 9 defect (a): the chip mirrors the drilled window — «Все дни» here
    # means the caption missed a window the VM already owns.
    bounds = (format_game_date(date(1200, 3, 1)), format_game_date(date(1200, 3, 31)))
    assert timeline_probe.chip_caption(window) == f"{bounds[0]} — {bounds[1]} ▾"
    # The tape re-models to exactly the windowed March days, top row first.
    assert isinstance(tape.rows[0], DayHeaderRow)
    assert tape.rows[0].date == date(1200, 3, 1)  # top of the tape = 1 марта
    assert all(r.date <= date(1200, 3, 31) for r in tape.rows)
    assert timeline_probe.selected_id(window) is None  # a drill selects nothing


async def test_migrated_header_tooltips_are_the_old_texts(app, wait_for):
    """Spec qml-shell «Нативный шим всплывающих подсказок для островов»: the
    перенесённых header tooltips are declared verbatim on the island through
    the library's ``Nri.tooltip`` scope (the chip's «Выбор даты» is pinned in
    test_e2e_hide_empty_toggle; the rows' dynamic summary — in
    tests/presentation/test_timeline_row_model.py)."""
    _application, window = app
    await wait_for(lambda: timeline_probe.tooltip_of(window, "jumpNext") is not None)
    assert timeline_probe.tooltip_of(window, "addButton") == (
        "Добавить событие (правый клик — другие сущности)")
    assert timeline_probe.tooltip_of(window, "hideEmptyToggle") == (
        "Скрыть пустые дни, схлопнутые провалы и пустые периоды")
    assert timeline_probe.tooltip_of(window, "jumpNext") == (
        "К следующему событию (Alt+Down)")
    assert timeline_probe.tooltip_of(window, "jumpPrev") == (
        "К предыдущему событию (Alt+Up)")
