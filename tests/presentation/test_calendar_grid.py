"""Focused tests for the game-calendar day grid (piece C3b, task group 1).

Covers the spec «game-calendar-grid» scenarios owned by the grid itself:
preset 12×7 Monday-first, custom 13×28 with a ten-day week, unclickable
holes in incomplete weeks, no «today»/foreign-month cells, intercalary chip
rows after the host month in rule-list order (two rules of one host), the
coordinate contract (day_selected, set_selection incl. the year-outside-
1…9999 un-prefill and the intercalary chip highlight), the pure era flag and
the interactive/show_era preview modes, plus the preset STANDARD_WEEK_NAMES
header versus a custom calendar's own week names (task 1.4).
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import pytest
from PySide6.QtWidgets import QGridLayout

from app.domain.game_calendar import (
    CalendarSpec,
    CustomCalendar,
    IntercalaryDay,
    IntercalarySpec,
    MonthDay,
    MonthSpec,
    StandardCalendar,
    current_calendar,
    set_current_calendar,
)
from app.presentation.utils.date_utils import STANDARD_WEEK_NAMES
from app.presentation.views.calendar_grid import (
    GameCalendarCell,
    GameCalendarDayName,
    GameCalendarGrid,
    GameCalendarIntercalaryChip,
)


@pytest.fixture(autouse=True)
def standard_active_calendar():
    """Every test starts on the «Стандартный» preset and restores the process
    calendar afterwards (the active calendar is a process global)."""
    saved = current_calendar()
    set_current_calendar(StandardCalendar())
    yield
    set_current_calendar(saved)


@contextmanager
def active(calendar):
    """Temporarily make ``calendar`` the ACTIVE game calendar."""
    saved = current_calendar()
    set_current_calendar(calendar)
    try:
        yield calendar
    finally:
        set_current_calendar(saved)


# 13 months × 28 days, a ten-day week — the spec's custom-calendar scenario.
CUSTOM_13 = CalendarSpec(
    months=tuple(MonthSpec(f"Месяц-{n}", 28) for n in range(1, 14)),
    week_names=tuple(f"Нед-{n}" for n in range(10)),
)

# Two months of a six-day week; the first host owns TWO intercalary rules.
SMALL = CalendarSpec(
    months=(MonthSpec("Таяль", 5), MonthSpec("Колодень", 4)),
    week_names=("А", "Б", "В", "Г", "Д", "Е"),
    intercalary=(
        IntercalarySpec("День Маски", 1),
        IntercalarySpec("День Теней", 1),
        IntercalarySpec("День Щели", 2),
    ),
)


def layout_position(grid: GameCalendarGrid, widget) -> tuple[int, int, int, int]:
    """(row, column, rowspan, colspan) of ``widget`` inside the grid layout."""
    layout = grid.findChild(QGridLayout)
    assert layout is not None
    for index in range(layout.count()):
        if layout.itemAt(index).widget() is widget:
            return layout.getItemPosition(index)
    raise AssertionError("widget is not laid out in the grid")


def placed_days(grid: GameCalendarGrid) -> dict[str, GameCalendarCell]:
    """Day cells of the shown page keyed by their day caption (holes skipped)."""
    return {c.text(): c for c in grid.findChildren(GameCalendarCell) if c.text()}


def show_page(grid: GameCalendarGrid, year: int, month: int) -> None:
    grid.set_selection(MonthDay(year, month, 1))


# ── task 1.1 — preset and custom pages ───────────────────────────────────────


def test_preset_shows_twelve_months_and_monday_first_columns(qtbot):
    grid = GameCalendarGrid()
    qtbot.addWidget(grid)
    # Panel: twelve active-calendar months and a 1…9999 year spin.
    assert grid._month_combo.count() == 12
    assert grid._month_combo.itemText(0) == "Январь"
    assert grid._month_combo.itemText(11) == "Декабрь"
    assert (grid._year_spin.minimum(), grid._year_spin.maximum()) == (1, 9999)
    # Header: the seven preset week names, Понедельник first (Monday-first).
    assert [label.text() for label in grid.findChildren(GameCalendarDayName)] == (
        list(STANDARD_WEEK_NAMES)
    )
    # September 2024 starts on Sunday — the LAST column, so the month's
    # first Monday (the 2nd) opens column 0 (the fixed Monday-first order).
    show_page(grid, 2024, 9)
    days = placed_days(grid)
    assert layout_position(grid, days["1"]) == (1, 6, 1, 1)
    assert layout_position(grid, days["2"]) == (2, 0, 1, 1)
    assert layout_position(grid, days["30"]) == (6, 0, 1, 1)


def test_custom_thirteen_month_ten_day_week_paints_its_own_grid(qtbot):
    with active(CustomCalendar(CUSTOM_13)):
        grid = GameCalendarGrid()
        qtbot.addWidget(grid)
        assert grid._month_combo.count() == 13
        assert grid._month_combo.itemText(0) == "Месяц-1"
        # Month 2 starts at weekday 28 % 10 == 8 of the decade.
        show_page(grid, 1, 2)
        assert sorted(placed_days(grid)) == sorted(str(d) for d in range(1, 29))
        assert layout_position(grid, placed_days(grid)["1"]) == (1, 8, 1, 1)
        assert layout_position(grid, placed_days(grid)["3"]) == (2, 0, 1, 1)
        assert layout_position(grid, placed_days(grid)["21"]) == (3, 8, 1, 1)
        # 4 decade rows: 40 slots for 28 days, the rest are holes.
        assert len(grid.findChildren(GameCalendarCell)) == 40
        # The thirteenth month exists and starts at 12·28 % 10 == 6.
        grid._month_combo.setCurrentIndex(12)
        assert placed_days(grid)["1"] is not None
        assert layout_position(grid, placed_days(grid)["1"])[1] == 6


def test_incomplete_week_holes_are_empty_and_unclickable(qtbot):
    with active(CustomCalendar(SMALL)):
        grid = GameCalendarGrid()  # opens on year 1, month 1
        qtbot.addWidget(grid)
        # 5 days of "Таяль" in a six-day week → exactly one trailing hole.
        cells = grid.findChildren(GameCalendarCell)
        assert len(cells) == 6
        holes = [c for c in cells if not c.text()]
        assert len(holes) == 1
        assert not holes[0].isEnabled()
        assert all(c.isEnabled() for c in cells if c.text())

        received: list = []
        grid.day_selected.connect(received.append)
        holes[0].click()
        assert received == []  # an empty hole never emits a coordinate
        placed_days(grid)["3"].click()
        assert received == [MonthDay(1, 1, 3)]

        # Month "Колодень" starts at weekday 5: two week rows, 8 holes.
        grid._month_combo.setCurrentIndex(1)
        assert layout_position(grid, placed_days(grid)["1"]) == (1, 5, 1, 1)
        assert len([c for c in grid.findChildren(GameCalendarCell) if not c.text()]) == 8


def test_no_today_marker_and_no_foreign_month_cells(qtbot):
    grid = GameCalendarGrid()
    qtbot.addWidget(grid)
    today = date.today()
    length = current_calendar().month_length(today.year, today.month)
    other_day = (today.day % length) + 1  # a day of the same month ≠ today
    grid.set_selection(MonthDay(today.year, today.month, other_day))
    days = placed_days(grid)
    # Exactly the days of THIS month — no neighbouring-month numbers, and the
    # page is not decorated with a system-«today» cell (nothing is selected
    # beyond the one day the pre-fill asked for).
    assert set(days) == {str(d) for d in range(1, length + 1)}
    assert sum(days[number].selected for number in days) == 1
    assert days[str(other_day)].selected
    assert not days[str(today.day)].selected


# ── task 1.2 — intercalary chip rows ─────────────────────────────────────────


def test_intercalary_chips_follow_host_month_in_rule_order(qtbot):
    with active(CustomCalendar(SMALL)):
        grid = GameCalendarGrid()
        qtbot.addWidget(grid)
        chips = grid.findChildren(GameCalendarIntercalaryChip)
        # Both rules of host month 1, in spec list order, after the week grid.
        assert [chip.text() for chip in chips] == ["День Маски", "День Теней"]
        row, column, _rowspan, colspan = layout_position(grid, chips[0].parentWidget())
        assert (column, colspan) == (0, 6)  # full width, no weekday columns
        assert row == 2  # right under the month's single week row

        received: list = []
        grid.day_selected.connect(received.append)
        chips[0].click()
        chips[1].click()
        # Two rules of ONE host month choose two distinct coordinates.
        assert received == [IntercalaryDay(1, 0), IntercalaryDay(1, 1)]

        grid._month_combo.setCurrentIndex(1)  # the second host month
        chips2 = grid.findChildren(GameCalendarIntercalaryChip)
        assert [chip.text() for chip in chips2] == ["День Щели"]
        chips2[0].click()
        assert received[-1] == IntercalaryDay(1, 2)


def test_calendar_without_intercalary_rules_has_no_chips(qtbot):
    grid = GameCalendarGrid()
    qtbot.addWidget(grid)
    for month in range(1, 13):
        grid._month_combo.setCurrentIndex(month - 1)
    assert grid.findChildren(GameCalendarIntercalaryChip) == []


# ── task 1.3 — coordinate contract ───────────────────────────────────────────


def test_click_emits_coordinate_and_marks_cell(qtbot):
    grid = GameCalendarGrid()
    qtbot.addWidget(grid)
    received: list = []
    grid.day_selected.connect(received.append)
    show_page(grid, 2024, 9)
    placed_days(grid)["3"].click()
    assert received == [MonthDay(2024, 9, 3)]
    assert grid.selection() == MonthDay(2024, 9, 3)
    days = placed_days(grid)
    assert days["3"].selected
    assert not any(days[n].selected for n in days if n != "3")


def test_set_selection_navigates_marks_and_carries_the_era(qtbot):
    pages: list = []
    grid = GameCalendarGrid()
    qtbot.addWidget(grid)
    grid.page_changed.connect(lambda year, month: pages.append((year, month)))

    grid.set_selection(MonthDay(1200, 5, 5), True)
    assert grid.selection() == MonthDay(1200, 5, 5)
    assert grid.is_bc() is True
    assert (grid._year_spin.value(), grid._month_combo.currentIndex()) == (1200, 4)
    assert placed_days(grid)["5"].selected
    assert pages[-1] == (1200, 5)

    # Same-page prefill keeps the page (no navigation noise) and moves the
    # highlight to the new cell.
    grid.set_selection(MonthDay(1200, 5, 20))
    assert pages.count((1200, 5)) == 1
    assert placed_days(grid)["20"].selected
    assert not placed_days(grid)["5"].selected

    grid._year_spin.setValue(1201)  # spinner stays a plain page control
    assert pages[-1] == (1201, 5)


def test_unprefilled_states_never_crash_nor_move_the_page(qtbot):
    grid = GameCalendarGrid()
    qtbot.addWidget(grid)
    grid.set_selection(MonthDay(1201, 5, 6))
    pages = []
    grid.page_changed.connect(lambda year, month: pages.append((year, month)))

    # A year outside the 1…9999 scale leaves the grid un-prefilled.
    grid.set_selection(MonthDay(10000, 1, 1))
    assert grid.selection() is None
    # An intercalary coordinate cannot exist in the standard preset.
    grid.set_selection(IntercalaryDay(1201, 0))
    assert grid.selection() is None
    # Explicit clearing keeps working and marks nothing.
    grid.set_selection(MonthDay(1201, 5, 6))
    grid.set_selection(None)
    assert grid.selection() is None
    assert not any(cell.selected for cell in grid.findChildren(GameCalendarCell))
    assert (grid._year_spin.value(), grid._month_combo.currentIndex()) == (1201, 4)
    assert pages == []


def test_intercalary_prefill_highlights_the_chip_on_the_host_page(qtbot):
    with active(CustomCalendar(SMALL)):
        grid = GameCalendarGrid()
        qtbot.addWidget(grid)
        pages: list = []
        grid.page_changed.connect(lambda year, month: pages.append((year, month)))

        grid.set_selection(IntercalaryDay(5, 2))
        assert grid.selection() == IntercalaryDay(5, 2)
        assert pages == [(5, 2)]  # navigated to host month 2 of year 5
        assert (grid._year_spin.value(), grid._month_combo.currentIndex()) == (5, 1)
        chips = grid.findChildren(GameCalendarIntercalaryChip)
        assert [chip.text() for chip in chips] == ["День Щели"]
        assert chips[0].selected
        assert not any(cell.selected for cell in grid.findChildren(GameCalendarCell))


def test_era_flag_is_pure(qtbot):
    pages: list = []
    grid = GameCalendarGrid()
    qtbot.addWidget(grid)
    grid.set_selection(MonthDay(2024, 9, 3))
    grid.page_changed.connect(lambda year, month: pages.append((year, month)))

    grid._bc_check.click()  # «до н.э.» — the date and the page must not move
    assert grid.is_bc() is True
    assert grid.selection() == MonthDay(2024, 9, 3)
    assert (grid._year_spin.value(), grid._month_combo.currentIndex()) == (2024, 8)
    assert placed_days(grid)["3"].selected
    grid._bc_check.click()
    assert grid.is_bc() is False
    assert grid.selection() == MonthDay(2024, 9, 3)
    assert pages == []  # switching the era is never a navigation

    grid.set_era(True)
    assert grid.is_bc() is True


def test_preview_modes_cells_inert_era_hidden_navigation_alive(qtbot):
    pages: list = []
    grid = GameCalendarGrid(interactive=False, show_era=False)
    qtbot.addWidget(grid)
    grid.page_changed.connect(lambda year, month: pages.append((year, month)))

    assert not grid._bc_check.isVisible()
    received: list = []
    grid.day_selected.connect(received.append)
    days = placed_days(grid)
    assert all(not cell.isEnabled() for cell in grid.findChildren(GameCalendarCell))
    days["1"].click()
    assert received == []
    assert grid.selection() is None

    # Navigation by months and years keeps working in the preview (spec
    # calendar-wizard «Живой предпросмотр сеткой»).
    grid._next_btn.click()
    assert pages == [(1, 2)]


def test_navigation_pages_wrap_and_stop_at_the_scale_bounds(qtbot):
    pages: list = []
    grid = GameCalendarGrid()
    qtbot.addWidget(grid)
    grid.page_changed.connect(lambda year, month: pages.append((year, month)))

    grid._prev_btn.click()  # (1, 1) is the bottom of the year scale
    assert pages == []
    assert (grid._year_spin.value(), grid._month_combo.currentIndex()) == (1, 0)

    grid._next_btn.click()  # plain forward step
    assert pages == [(1, 2)]

    grid.set_selection(MonthDay(5, 12, 1))
    grid._next_btn.click()  # December wraps into January of the next year
    assert pages[-1] == (6, 1)
    grid._prev_btn.click()  # and back wraps the other way
    assert pages[-1] == (5, 12)

    grid.set_selection(MonthDay(9999, 12, 31))
    grid._next_btn.click()  # (9999, December) is the top of the scale
    assert pages[-1] == (9999, 12)


# ── task 1.4 — preset week names vs. the custom calendar's own ───────────────


def test_preset_header_uses_standard_week_names_monday_first(qtbot):
    assert STANDARD_WEEK_NAMES == (
        "Понедельник",
        "Вторник",
        "Среда",
        "Четверг",
        "Пятница",
        "Суббота",
        "Воскресенье",
    )
    grid = GameCalendarGrid()
    qtbot.addWidget(grid)
    assert [label.text() for label in grid.findChildren(GameCalendarDayName)] == (
        list(STANDARD_WEEK_NAMES)
    )

    # A preset with renamed MONTHS is still the standard week — the header
    # only follows the preset constant, never the month-name override.
    with active(StandardCalendar(month_names={1: "Кисель"})):
        grid.refresh()
        assert grid._month_combo.itemText(0) == "Кисель"
        assert [label.text() for label in grid.findChildren(GameCalendarDayName)] == (
            list(STANDARD_WEEK_NAMES)
        )


def test_custom_header_uses_its_own_week_names(qtbot):
    with active(CustomCalendar(CUSTOM_13)):
        grid = GameCalendarGrid()
        qtbot.addWidget(grid)
        labels = [label.text() for label in grid.findChildren(GameCalendarDayName)]
        assert labels == list(CUSTOM_13.week_names)
        assert labels[0] == "Нед-0"  # the custom column 0 is its own week_names[0]


def test_refresh_rereads_the_active_calendar_and_clamps_the_page(qtbot):
    with active(CustomCalendar(CUSTOM_13)):
        grid = GameCalendarGrid()
        qtbot.addWidget(grid)
        grid._month_combo.setCurrentIndex(12)  # page: month 13 of year 1
        assert (grid._year_spin.value(), grid._month_combo.currentIndex()) == (1, 12)
    # Back on the preset a refresh renames the months and silently pulls the
    # impossible 13th month back to the last existing one.
    grid.refresh()
    assert grid._month_combo.count() == 12
    assert grid._month_combo.itemText(0) == "Январь"
    assert (grid._year_spin.value(), grid._month_combo.currentIndex()) == (1, 11)
    assert set(placed_days(grid)) == {str(d) for d in range(1, 32)}  # December
