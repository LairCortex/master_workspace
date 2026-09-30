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
    NOW_HOUR_SELECTOR_PREFIX,
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


def test_request_hour_popup_forwards_the_combo_rectangle():
    """Task 12.6 (A1 host half): the hour list request uses the same sync
    forward as the chip's grid — the VM knows no QML, no widget, only the
    island-local rectangle for the wiring's bridge."""
    vm = NowDateViewModel(MonthDay(1, 1, 1))
    requested = track(vm.hourPopupRequested)

    vm.requestHourPopup(263.0, 78.0, 70.0, 24.0)

    assert requested == [(263.0, 78.0, 70.0, 24.0)]


# ── NRI-0023 task 9.1 — «сейчас» с часом ────────────────────────────────────

# A narrow-day calendar (spec «Сужение суток»): the hour list bounds must
# follow it, nothing may hardcode 24.
NARROW = CalendarSpec(
    months=(MonthSpec("Кратень", 15),),
    week_names=("А", "Б"),
    day_hours=10,
)


def test_caption_appends_the_hour_only_when_set():
    vm = NowDateViewModel(MonthDay(44, 11, 3), False, 20)
    assert vm.caption == "Сейчас: 03 Ноябрь 44, 20:00"
    assert vm.hour == 20
    # «HH:00» carries the leading zero (spec «…, HH:00», minutes always :00)
    vm.applyNow(MonthDay(44, 11, 3), False, 3)
    assert vm.caption == "Сейчас: 03 Ноябрь 44, 03:00"


def test_caption_without_an_hour_reads_exactly_as_before_0023():
    vm = NowDateViewModel(MonthDay(44, 11, 3), False, None)
    assert vm.caption == "Сейчас: 03 Ноябрь 44"


def test_hour_list_offers_the_empty_option_plus_the_active_day():
    vm = NowDateViewModel(MonthDay(1, 1, 1))
    assert list(vm.hourOptions) == ["—"] + [str(h) for h in range(24)]
    # the bounds are the ACTIVE calendar's, not a constant (design Д4)
    set_current_calendar(CustomCalendar(NARROW))
    assert list(vm.hourOptions) == ["—"] + [str(h) for h in range(10)]


def test_selected_hour_index_counts_the_empty_option():
    vm = NowDateViewModel(MonthDay(1, 1, 1), False, 14)
    assert vm.selectedHourIndex == 15  # index of hour H is H + 1
    vm.applyNow(MonthDay(1, 1, 1), False, None)
    assert vm.selectedHourIndex == 0  # «—»


def test_request_hour_maps_the_index_onto_the_hour_or_none():
    vm = NowDateViewModel(MonthDay(1, 1, 1), False, 5)
    requests = track(vm.hourChangeRequested)

    vm.requestHour(0)   # «—» — час снимается
    vm.requestHour(21)  # 21-я строка списка — это час 20

    assert requests == [(None,), (20,)]


def test_request_hour_outside_the_active_day_is_ignored():
    set_current_calendar(CustomCalendar(NARROW))  # valid list positions 0 … 10
    vm = NowDateViewModel(MonthDay(1, 1, 1), False, 5)
    requests = track(vm.hourChangeRequested)

    vm.requestHour(11)
    vm.requestHour(-1)

    assert requests == []


def test_hour_display_labels_the_selector_while_rows_stay_bare():
    """Д14.2 (H1/A4/A7): the closed selector explains itself — the display text
    carries «Час: » before any pick, while the LIST rows stay bare numbers
    (spec qml-components: a popup row never reads «Час: N»)."""
    vm = NowDateViewModel(MonthDay(1, 1, 1))
    assert vm.hourDisplay == NOW_HOUR_SELECTOR_PREFIX + "—" == "Час: —"
    vm.applyNow(MonthDay(1, 1, 1), False, 14)
    assert vm.hourDisplay == "Час: 14"
    assert not any("Час:" in str(row) for row in vm.hourOptions)


def test_worst_case_hour_option_is_the_active_days_widest_label():
    """Д14.3 (A5): the selector's fixed width is the widest label the ACTIVE
    calendar prints, so «—»/1/23 can never resize the control."""
    vm = NowDateViewModel(MonthDay(1, 1, 1))
    assert vm.worstCaseHourOption == "Час: 23"
    set_current_calendar(CustomCalendar(NARROW))  # сутки из 10 часов
    assert vm.worstCaseHourOption == "Час: 9"


def test_worst_case_floor_carries_the_widest_hour_tail():
    vm = NowDateViewModel(MonthDay(1, 1, 1))
    plain_floor = NOW_CAPTION_PREFIX + worst_case_date_caption()
    assert vm.worstCaseDisplay == plain_floor  # unset — the pre-0023 floor
    vm.applyNow(MonthDay(1, 1, 1), False, 7)
    # with a set hour the floor must contain the widest tail of the day («23»)
    assert vm.worstCaseDisplay == plain_floor + ", 23:00"
    set_current_calendar(CustomCalendar(NARROW))
    vm.applyNow(MonthDay(1, 1, 1), False, 7)
    assert (
        vm.worstCaseDisplay
        == NOW_CAPTION_PREFIX + worst_case_date_caption() + ", 09:00"
    )


def test_hour_only_edit_moves_the_caption_but_not_the_broadcast():
    """Spec «Час меняет только подпись»: the day reads the derived surfaces
    compute from stay put, and the one ``nowChanged`` channel — every
    derived surface's only trigger — does not fire for an hour edit."""
    vm = NowDateViewModel(MonthDay(2027, 3, 14))
    captions = track(vm.captionChanged)
    nows = track(vm.nowChanged)

    vm.applyNow(MonthDay(2027, 3, 14), False, 20)

    assert vm.caption == "Сейчас: 14 Март 2027, 20:00"
    assert vm.coord == MonthDay(2027, 3, 14)
    assert vm.is_bc is False
    assert captions == [()]
    assert nows == []


def test_hour_removal_is_a_caption_only_edit_too():
    vm = NowDateViewModel(MonthDay(2027, 3, 14), False, 20)
    captions = track(vm.captionChanged)
    nows = track(vm.nowChanged)

    vm.applyNow(MonthDay(2027, 3, 14), False, None)

    assert vm.caption == "Сейчас: 14 Март 2027"
    assert captions == [()]
    assert nows == []


def test_apply_now_is_silent_for_the_same_hour_it_already_serves():
    vm = NowDateViewModel(MonthDay(2027, 3, 14), False, 20)
    captions = track(vm.captionChanged)
    nows = track(vm.nowChanged)

    vm.applyNow(MonthDay(2027, 3, 14), False, 20)

    assert captions == []
    assert nows == []


def test_day_edit_with_the_hour_moves_both_channels_once():
    vm = NowDateViewModel(MonthDay(2027, 3, 14), False, 20)
    captions = track(vm.captionChanged)
    nows = track(vm.nowChanged)

    vm.applyNow(MonthDay(44, 11, 3), False, 20)  # тот же час, другой день

    assert vm.caption == "Сейчас: 03 Ноябрь 44, 20:00"
    assert captions == [()]
    assert nows == [()]
