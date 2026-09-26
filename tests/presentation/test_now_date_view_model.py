"""Unit tests for the «now» widget view model (NRI-0021 task 3.1, design Д2).

The VM is exercised without any QML island (spec qml-shell scenario «VM не
знает про QML»): caption wording of the active calendar (era suffix, the
intercalary day by its rule name), the applied-value slot semantics (one
``captionChanged`` + one ``nowChanged`` per real edit, silence on the same
value), the sync popup-request channel and the ThemeDateField width floor.
"""
from __future__ import annotations

import pytest

from app.domain.game_calendar import (
    CalendarSpec,
    CustomCalendar,
    IntercalaryDay,
    IntercalarySpec,
    MonthDay,
    MonthSpec,
    reset_current_calendar,
    set_current_calendar,
)
from app.presentation.utils.date_utils import worst_case_date_caption
from app.presentation.viewmodels.now_date_view_model import (
    NOW_CAPTION_PREFIX,
    NowDateViewModel,
)
from tests.presentation.qml_helpers import track

# A two-month game calendar with one intercalary rule — the «Зимостой» name
# echoes the spec scenario «3 Зимостой 44 г. до н.э.».
CUSTOM = CalendarSpec(
    months=(MonthSpec("Первомес", 30), MonthSpec("Зимостой", 20)),
    week_names=("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"),
    intercalary=(IntercalarySpec("День Маски", 1),),
)


@pytest.fixture(autouse=True)
def _fresh_active_calendar():
    reset_current_calendar()
    yield
    reset_current_calendar()


def test_caption_reads_now_prefix_over_the_active_calendar():
    vm = NowDateViewModel(MonthDay(2027, 3, 14))
    assert vm.caption == NOW_CAPTION_PREFIX + "14 Март 2027"
    # Python-side reads the derived surfaces (groups 4–6) compute from.
    assert vm.coord == MonthDay(2027, 3, 14)
    assert vm.is_bc is False


def test_caption_carries_the_bc_era_suffix():
    vm = NowDateViewModel(MonthDay(44, 11, 3), is_bc=True)
    assert vm.caption == "Сейчас: 03 Ноябрь 44 г. до н.э."
    assert vm.is_bc is True


def test_caption_of_an_intercalary_day_uses_its_rule_name():
    set_current_calendar(CustomCalendar(CUSTOM))
    vm = NowDateViewModel(IntercalaryDay(44, 0), True)
    assert vm.caption == "Сейчас: День Маски 44 г. до н.э."


def test_worst_case_display_is_the_prefixed_worst_caption():
    # Design F1 convention: the VM assembles the floor so the «Сейчас: »
    # prefix can never be elided by the field's minimum width.
    vm = NowDateViewModel(MonthDay(1, 1, 1))
    assert vm.worstCaseDisplay == NOW_CAPTION_PREFIX + worst_case_date_caption()


def test_apply_now_moves_caption_and_broadcasts_once_per_edit():
    vm = NowDateViewModel(MonthDay(2027, 3, 14))
    captions = track(vm.captionChanged)
    nows = track(vm.nowChanged)

    vm.applyNow(MonthDay(44, 11, 3), 1)  # the storage era arrives as int 0/1

    assert vm.caption == "Сейчас: 03 Ноябрь 44 г. до н.э."
    assert vm.coord == MonthDay(44, 11, 3)
    assert vm.is_bc is True  # normalized to bool
    assert captions == [()]
    assert nows == [()]


def test_apply_now_is_silent_for_the_value_it_already_serves():
    vm = NowDateViewModel(MonthDay(2027, 3, 14))
    captions = track(vm.captionChanged)
    nows = track(vm.nowChanged)

    vm.applyNow(MonthDay(2027, 3, 14), False)

    assert captions == []
    assert nows == []


def test_era_flip_alone_is_an_edit_too():
    vm = NowDateViewModel(MonthDay(44, 11, 3), is_bc=True)
    nows = track(vm.nowChanged)

    vm.applyNow(MonthDay(44, 11, 3), False)

    assert nows == [()]
    assert vm.caption == "Сейчас: 03 Ноябрь 44"


def test_request_date_popup_forwards_the_chip_rectangle():
    vm = NowDateViewModel(MonthDay(1, 1, 1))
    requested = track(vm.datePopupRequested)

    vm.requestDatePopup(12.0, 30.0, 140.0, 24.0)

    assert requested == [(12.0, 30.0, 140.0, 24.0)]
