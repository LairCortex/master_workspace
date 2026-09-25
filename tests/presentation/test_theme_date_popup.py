"""Focused tests for the coordinate-based date popup bridges (piece C3b, task 2.1).

The single-date popup and the «Выбор даты» range popover now host the game
calendar day grid (``GameCalendarGrid``) instead of the Gregorian
``QCalendarWidget``: pre-filling takes game coordinates through
``split_date_era``/``as_game_coord`` (a bare ``date`` is the same-numbers
``MonthDay``), clicks hand out ``(GameCoord, is_bc)`` pairs, the grid is
refreshed on every open, and the popup stays wholly inside the available
screen geometry (spec «Попапы даты поверх сетки сохраняют механику» — only the
carrier changed, the mechanics did not).
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import pytest
from PySide6.QtCore import QRect

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
from app.presentation.views.calendar_grid import (
    GameCalendarCell,
    GameCalendarGrid,
    GameCalendarIntercalaryChip,
)
from app.presentation.views.theme_date_popup import ThemeDatePopup
from app.presentation.views.timeline_date_popup import (
    _DateWindowPopup,
    window_chip_text,
)

# «День Маски» lives after month 1 — the popup must paint its chip, design D3.
ONE_MASK = CalendarSpec(
    months=(MonthSpec("Первомес", 30), MonthSpec("Второмес", 20)),
    week_names=("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"),
    intercalary=(IntercalarySpec("День Маски", 1),),
)


@contextmanager
def active(calendar):
    """Temporarily make ``calendar`` the ACTIVE game calendar."""
    saved = current_calendar()
    set_current_calendar(calendar)
    try:
        yield calendar
    finally:
        set_current_calendar(saved)


def _day_cell(popup: ThemeDatePopup, day: int) -> GameCalendarCell:
    return next(
        cell for cell in popup.calendar.findChildren(GameCalendarCell)
        if cell.text() == str(day)
    )


# ── single-date popup (task 2.1) ─────────────────────────────────────────────


def test_popup_owns_exactly_one_game_calendar_grid(qtbot):
    popup = ThemeDatePopup()
    qtbot.addWidget(popup)
    assert isinstance(popup.calendar, GameCalendarGrid)
    assert popup.findChildren(GameCalendarGrid) == [popup.calendar]


def test_open_refreshes_months_and_prefills_coordinate_and_era(qtbot):
    saved = current_calendar()
    popup = ThemeDatePopup()
    qtbot.addWidget(popup)
    try:
        months = {i: f"R4-{i}" for i in range(1, 13)}
        set_current_calendar(StandardCalendar(month_names=months))
        # The month combo re-reads the ACTIVE calendar on every open (spec
        # «Имена перечитываются при показе»); the pre-fill is a coordinate.
        popup.open_at(QRect(20, 30, 100, 20), (MonthDay(1, 2, 3), True))
        assert popup.calendar._month_combo.itemText(1) == "R4-2"
        assert popup.calendar.selection() == MonthDay(1, 2, 3)
        assert popup.calendar.is_bc() is True
        assert _day_cell(popup, 3).selected
    finally:
        popup.close()
        set_current_calendar(saved)


def test_open_without_pair_input_starts_in_our_era(qtbot):
    popup = ThemeDatePopup()
    qtbot.addWidget(popup)
    try:
        popup.calendar.set_era(True)  # stale era must not survive an open
        # A bare date is legal input: the popup pre-fills its MonthDay.
        popup.open_at(QRect(20, 30, 100, 20), date(1200, 5, 5))
        assert popup.calendar.selection() == MonthDay(1200, 5, 5)
        assert popup.calendar.is_bc() is False
        assert (
            popup.calendar._year_spin.value(),
            popup.calendar._month_combo.currentIndex(),
        ) == (1200, 4)
    finally:
        popup.close()


def test_open_with_unrepresentable_coordinate_stays_unprefilled(qtbot):
    """A year outside 1…9999 (or no date at all) leaves the popup un-prefilled
    without any crash or number substitution (spec «Сетка говорит
    координатами»)."""
    popup = ThemeDatePopup()
    qtbot.addWidget(popup)
    try:
        popup.open_at(QRect(20, 30, 100, 20), MonthDay(10000, 5, 5))
        assert popup.calendar.selection() is None
        popup.open_at(QRect(20, 30, 100, 20), None)
        assert popup.calendar.selection() is None
        assert popup.calendar.is_bc() is False
    finally:
        popup.close()


def test_intercalary_coordinate_prefills_its_chip_on_the_host_page(qtbot):
    """Spec «Вставной день виден предзаполненным»: the popup opens on the host
    month with the chip highlighted; nothing about the stored bound changes."""
    stored = (IntercalaryDay(44, 0), True)
    with active(CustomCalendar(ONE_MASK)):
        popup = ThemeDatePopup()
        qtbot.addWidget(popup)
        try:
            popup.open_at(QRect(20, 30, 100, 20), stored)
            assert popup.calendar.selection() == IntercalaryDay(44, 0)
            assert (
                popup.calendar._year_spin.value(),
                popup.calendar._month_combo.currentIndex(),
            ) == (44, 0)  # the host month's page
            chips = popup.calendar.findChildren(GameCalendarIntercalaryChip)
            assert [chip.text() for chip in chips] == ["День Маски"]
            assert chips[0].selected
            assert stored == (IntercalaryDay(44, 0), True)  # record untouched
        finally:
            popup.close()


def test_selection_emits_pair_and_closes_whatever_the_era_is(qtbot):
    popup = ThemeDatePopup()
    qtbot.addWidget(popup)
    received = []
    popup.date_selected.connect(received.append)

    popup.show()
    popup.calendar.day_selected.emit(MonthDay(1, 1, 1))
    assert received == [(MonthDay(1, 1, 1), False)]  # (GameCoord, is_bc)
    assert not popup.isVisible()

    popup.show()
    popup.calendar.day_selected.emit(MonthDay(9999, 12, 31))
    assert received[-1] == (MonthDay(9999, 12, 31), False)

    popup.show()
    popup.calendar.set_era(True)
    popup.calendar.day_selected.emit(MonthDay(44, 3, 5))
    assert received[-1] == (MonthDay(44, 3, 5), True)


def test_open_clamps_both_axes_to_available_geometry(qtbot, monkeypatch):
    popup = ThemeDatePopup()
    qtbot.addWidget(popup)
    geometry = QRect(100, 200, 640, 480)

    class Screen:
        def availableGeometry(self):
            return QRect(geometry)

    class App:
        @staticmethod
        def screenAt(_position):
            return Screen()

        @staticmethod
        def primaryScreen():
            return Screen()

    from app.presentation.views import theme_date_popup

    monkeypatch.setattr(theme_date_popup, "QApplication", App)
    popup.open_at(QRect(1000, 1000, 50, 20), date(1200, 4, 5))
    assert geometry.left() <= popup.x()
    assert popup.x() + popup.width() - 1 <= geometry.right()
    assert geometry.top() <= popup.y()
    assert popup.y() + popup.height() - 1 <= geometry.bottom()
    popup.close()


# ── «Выбор даты» range popover (task 2.2) ────────────────────────────────────


def test_timeline_range_popup_regression_contract_is_unchanged(qtbot):
    popup = _DateWindowPopup()
    qtbot.addWidget(popup)
    assert popup.findChildren(GameCalendarGrid) == [
        popup.start_calendar,
        popup.end_calendar,
    ]
    assert callable(popup._fit_low_screen)
    assert window_chip_text(None, None) == "Все дни ▾"
    assert window_chip_text(date(1200, 1, 2), date(1200, 1, 3)) == (
        "02 Январь 1200 — 03 Январь 1200 ▾"
    )


def test_range_popup_has_one_independent_era_check_box_per_calendar(qtbot):
    popup = _DateWindowPopup()
    qtbot.addWidget(popup)
    start_check = popup.start_calendar._bc_check
    end_check = popup.end_calendar._bc_check
    assert start_check is not end_check
    start_check.setChecked(True)
    assert popup.start_calendar.is_bc() is True
    assert popup.end_calendar.is_bc() is False


def test_range_popup_mixed_era_window_returns_two_pairs(qtbot):
    """окно 500 г. до н.э. … 100 г. н.э. applies as two carried coordinate pairs."""
    popup = _DateWindowPopup()
    qtbot.addWidget(popup)
    received: list = []
    popup.range_applied.connect(lambda start, end: received.append((start, end)))
    popup.open_at(QRect(0, 0, 10, 10))
    popup._fit_low_screen(10_000)  # both grids take the taps

    popup.start_calendar.set_era(True)
    popup.start_calendar.day_selected.emit(MonthDay(500, 1, 1))
    assert received == []  # start alone is not a window yet
    popup.end_calendar.day_selected.emit(MonthDay(100, 12, 31))

    assert received == [
        ((MonthDay(500, 1, 1), True), (MonthDay(100, 12, 31), False)),
    ]
    assert not popup.isVisible()


def test_range_popup_backwards_check_is_chronological_across_the_eras(qtbot):
    """A second tap chronologically BEFORE the armed start re-arms — with
    eras, «before» follows the single chronological key (design D2), not the
    raw year numbers: 500 г. до н.э. lies EARLIER than 100 г. до н.э. even
    though 500 > 100."""
    popup = _DateWindowPopup()
    qtbot.addWidget(popup)
    received: list = []
    popup.range_applied.connect(lambda start, end: received.append((start, end)))
    popup.open_at(QRect(0, 0, 10, 10))

    popup.start_calendar.set_era(True)
    popup.start_calendar.day_selected.emit(MonthDay(100, 1, 1))  # 100 г. до н.э.
    assert popup._pending_start == (MonthDay(100, 1, 1), True)
    popup.start_calendar.day_selected.emit(MonthDay(500, 1, 1))  # 500 г. до н.э. — раньше
    assert popup._pending_start == (MonthDay(500, 1, 1), True)  # re-armed
    assert received == []
    popup.end_calendar.set_era(True)
    popup.end_calendar.day_selected.emit(MonthDay(50, 1, 1))  # 50 г. до н.э. — позже
    assert received == [((MonthDay(500, 1, 1), True), (MonthDay(50, 1, 1), True))]


def test_range_popup_arm_tap_marks_both_grids_with_the_same_coordinate(qtbot):
    """The armed start mirrors onto the second grid's page (its old selectedDate
    mirror, now coordinate-carried) while each era flag stays independent."""
    popup = _DateWindowPopup()
    qtbot.addWidget(popup)
    popup.open_at(QRect(0, 0, 10, 10))
    popup.start_calendar.set_era(True)
    popup.start_calendar.day_selected.emit(MonthDay(1200, 6, 7))
    assert popup.start_calendar.selection() == MonthDay(1200, 6, 7)
    assert popup.end_calendar.selection() == MonthDay(1200, 6, 7)
    assert popup.start_calendar.is_bc() is True
    assert popup.end_calendar.is_bc() is False  # Q9: eras stay independent


def test_range_open_prefills_pairs_without_moving_numbers_back(qtbot):
    popup = _DateWindowPopup()
    qtbot.addWidget(popup)
    current = ((MonthDay(500, 1, 1), True), (MonthDay(100, 12, 31), False))
    popup.open_at(QRect(0, 0, 10, 10), current)
    assert popup.start_calendar.selection() == MonthDay(500, 1, 1)
    assert popup.start_calendar.is_bc() is True
    assert popup.end_calendar.selection() == MonthDay(100, 12, 31)
    assert popup.end_calendar.is_bc() is False
    assert current == ((MonthDay(500, 1, 1), True), (MonthDay(100, 12, 31), False))
    popup.close()


def test_range_open_prefills_intercalary_bound_as_a_chip_highlight(qtbot):
    """Spec event-timeline «Граница — вставной день» pre-fill half: the seeded
    intercalary bound shows its host page with the chip marked, era mirrored."""
    with active(CustomCalendar(ONE_MASK)):
        popup = _DateWindowPopup()
        qtbot.addWidget(popup)
        popup.open_at(QRect(0, 0, 10, 10), ((IntercalaryDay(44, 0), True), None))
        assert popup.start_calendar.selection() == IntercalaryDay(44, 0)
        chips = popup.start_calendar.findChildren(GameCalendarIntercalaryChip)
        assert chips and chips[0].selected
        assert popup.start_calendar.is_bc() is True
        # A bound absent from the window leaves its grid un-prefilled (no
        # stale selection survives an open) but the era flag is reset too.
        assert popup.end_calendar.selection() is None
        assert popup.end_calendar.is_bc() is False
        popup.close()


@pytest.mark.parametrize("room, both_visible", [(10_000, True), (0, False)])
def test_range_low_screen_fallback_keeps_one_grid(qtbot, room, both_visible):
    popup = _DateWindowPopup()
    qtbot.addWidget(popup)
    popup._fit_low_screen(room)
    assert popup.end_calendar.isHidden() is (not both_visible)


# ── NRI-0015 group 4: readable states of the «Выбор даты» popover ──────────
# (spec event-timeline «Панель выбора даты имеет читаемые состояния»:
#  P1 opens the empty window on today, P2 captions both grids from the
#  first frame, P3 shows no accent fill while the window is «Все дни».)


def _grid_page(grid: GameCalendarGrid) -> tuple[int, int]:
    """The page the grid shows, read through its own navigation widgets."""
    return grid._year_spin.value(), grid._month_combo.currentIndex() + 1


class TestEmptyWindowOpensOnTheCurrentDate:
    """P1: an absent bound opens its grid on the page containing the current
    game date, not at the head of calendar history («январь, год 1»);
    seeded bounds keep pre-filling exactly as before."""

    def test_reopened_empty_window_pages_both_grids_to_today(self, qtbot):
        popup = _DateWindowPopup()
        qtbot.addWidget(popup)
        # Land the grids somewhere far from today first, so the second open
        # proves a real navigation and not the construction default.
        popup.open_at(
            QRect(0, 0, 10, 10),
            ((MonthDay(500, 1, 1), False), (MonthDay(9000, 12, 31), False)),
        )
        popup.close()
        popup.open_at(QRect(0, 0, 10, 10), (None, None))
        today = date.today()
        for grid in (popup.start_calendar, popup.end_calendar):
            assert _grid_page(grid) == (today.year, today.month)
            # …as a page only: an empty window selects nothing (P3's model
            # half — «нет состояния «залита» при пустом окне»).
            assert grid.selection() is None
            assert grid.is_bc() is False
        popup.close()

    def test_empty_window_falls_to_year_one_without_a_room_for_today(
        self, qtbot
    ):
        # The wizard preview's «текущая игровая дата, иначе год 1» convention:
        # a calendar that cannot host today's numbers pages to year 1.
        popup = _DateWindowPopup()
        qtbot.addWidget(popup)
        popup.open_at(QRect(0, 0, 10, 10), ((MonthDay(44, 1, 1), False), None))
        with active(CustomCalendar(ONE_MASK)):
            popup.open_at(QRect(0, 0, 10, 10), None)
            # ONE_MASK has two months — September simply does not exist there.
            assert _grid_page(popup.start_calendar) == (1, 1)
            assert _grid_page(popup.end_calendar) == (1, 1)
            assert popup.start_calendar.selection() is None
        popup.close()

    def test_seeded_bounds_still_own_their_pages(self, qtbot):
        """Regression of the spec scenarios «c границами — как было»: a bound
        pre-fills its own page and today does not intrude."""
        popup = _DateWindowPopup()
        qtbot.addWidget(popup)
        popup.open_at(
            QRect(0, 0, 10, 10),
            ((MonthDay(500, 4, 3), False), (MonthDay(100, 12, 31), False)),
        )
        assert _grid_page(popup.start_calendar) == (500, 4)
        assert _grid_page(popup.end_calendar) == (100, 12)
        assert popup.start_calendar.selection() == MonthDay(500, 4, 3)
        assert popup.end_calendar.selection() == MonthDay(100, 12, 31)
        popup.close()

    def test_partial_window_pages_only_the_boundless_grid_to_today(self, qtbot):
        popup = _DateWindowPopup()
        qtbot.addWidget(popup)
        popup.open_at(QRect(0, 0, 10, 10), (None, (MonthDay(100, 12, 31), True)))
        today = date.today()
        assert _grid_page(popup.start_calendar) == (today.year, today.month)
        assert popup.start_calendar.selection() is None
        assert _grid_page(popup.end_calendar) == (100, 12)
        assert popup.end_calendar.selection() == MonthDay(100, 12, 31)
        assert popup.end_calendar.is_bc() is True
        popup.close()


class TestGridCaptionsBeforeAnyPick:
    """P2: every grid carries its own orienting caption, visible from the
    very first frame of the open — the second grid included."""

    def test_both_captions_are_there_before_the_first_tap(self, qtbot):
        popup = _DateWindowPopup()
        qtbot.addWidget(popup)
        popup.open_at(QRect(0, 0, 10, 10), None)
        assert popup.start_hint_label.text() == "Начало окна"
        assert popup.end_hint_label.text() == "Конец окна"
        assert popup.start_hint_label.isVisible()
        assert popup.end_hint_label.isVisible()
        popup.close()

    def test_captions_stay_in_place_after_a_choice(self, qtbot):
        popup = _DateWindowPopup()
        qtbot.addWidget(popup)
        popup.open_at(QRect(0, 0, 10, 10), None)
        popup._fit_low_screen(10_000)  # two grids take the taps
        popup.start_calendar.day_selected.emit(MonthDay(1200, 1, 5))
        # The tip moved to the second half, the captions stayed constant.
        assert popup.tip_label.text() == "Кликните дату окончания"
        assert popup.start_hint_label.text() == "Начало окна"
        assert popup.end_hint_label.text() == "Конец окна"
        assert popup.start_hint_label.isVisible()
        assert popup.end_hint_label.isVisible()
        popup.close()

    def test_low_screen_fallback_hides_the_end_caption_with_its_grid(
        self, qtbot
    ):
        popup = _DateWindowPopup()
        qtbot.addWidget(popup)
        popup._fit_low_screen(10_000)
        assert popup.end_hint_label.isHidden() is False
        popup._fit_low_screen(0)
        assert popup.end_hint_label.isHidden() is True  # caption follows its grid
        assert popup.start_hint_label.isHidden() is False


class TestEmptyWindowCarriesNoFillState:
    """P3 (delegate-model half): an empty window marks nobody — the selected
    property is the fill state, and only a seeded/armed bound may set it."""

    def test_all_days_window_leaves_no_cell_or_chip_marked(self, qtbot):
        with active(CustomCalendar(ONE_MASK)):
            popup = _DateWindowPopup()
            qtbot.addWidget(popup)
            popup.open_at(QRect(0, 0, 10, 10), None)
            shown = (
                popup.start_calendar.findChildren(GameCalendarCell)
                + popup.end_calendar.findChildren(GameCalendarCell)
            )
            assert shown  # the grids really painted their cells
            assert [w.text() for w in shown if w.selected] == []
            chips = (
                popup.start_calendar.findChildren(GameCalendarIntercalaryChip)
                + popup.end_calendar.findChildren(GameCalendarIntercalaryChip)
            )
            assert [chip.text() for chip in chips if chip.selected] == []
            popup.close()
