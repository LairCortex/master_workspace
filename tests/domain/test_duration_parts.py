"""Table tests for the duration family of NRI-0021 (tasks 1.2/1.4, design Д3).

``duration_parts`` counts through the calendar's contiguous ``day_index``:
order and the «до н.э. → н.э.» crossing come from ``era_key`` (no year zero),
the greedy decomposition walks actual calendar positions — whole anniversary
years first, same-day month steps from the starting month next, the remainder
in days.  The mandatory table covers zero duration, less than a month, less
than a year, the era crossing without year zero, intercalary days (custom
calendars) and sign symmetry.  ``entity_age_duration`` is the single entity-age
rule of design Д5: count to «now», to the end when the end is earlier, forward
(«через») when the start has not arrived yet — word assembly itself lives in
presentation (``format_age_words``), the domain carries no text.
"""
from datetime import date

import pytest

import app.domain.date_era as date_era_module
from app.domain.date_era import DurationParts, duration_parts, entity_age_duration
from app.domain.game_calendar import (
    CalendarSpec,
    CustomCalendar,
    IntercalaryDay,
    IntercalarySpec,
    MonthDay,
    MonthSpec,
    current_calendar,
    reset_current_calendar,
    set_current_calendar,
)

WEEK = ("Восход", "Тень", "Полдень", "Закат")


@pytest.fixture(autouse=True)
def _isolated_active_calendar():
    """The duration functions dispatch on the active calendar (module global,
    design D3) — restore whatever the previous test left installed."""
    saved = current_calendar()
    reset_current_calendar()
    yield
    set_current_calendar(saved)


def expected(years: int, months: int, days: int, ahead: bool = False):
    """Readable comparison helper: the dataclass fields are what tables pin."""
    return (years, months, days, ahead)


def observed(parts: DurationParts):
    return (parts.years, parts.months, parts.days, parts.ahead)


# ── task 1.2: greedy decomposition on the standard preset ─────────────────


class TestDurationPartsStandard:
    DURATION_TABLE = [
        # нулевая длительность — в обе стороны знака не имеет
        pytest.param(
            date(2024, 5, 1), False, date(2024, 5, 1), False,
            expected(0, 0, 0), id="zero-same-day",
        ),
        pytest.param(
            date(44, 3, 5), True, date(44, 3, 5), True,
            expected(0, 0, 0), id="zero-in-bc-era",
        ),
        # меньше месяца — только целые дни
        pytest.param(
            date(2024, 1, 1), False, date(2024, 1, 20), False,
            expected(0, 0, 19), id="less-than-a-month",
        ),
        pytest.param(
            date(2024, 1, 31), False, date(2024, 2, 27), False,
            expected(0, 0, 27), id="month-not-yet-reached",
        ),
        # меньше года — целые месяцы от месяца начала
        pytest.param(
            date(2024, 1, 1), False, date(2024, 4, 1), False,
            expected(0, 3, 0), id="less-than-a-year",
        ),
        # годы и месяцы (spec «Словесная формула», сценарий «Годы и месяцы»)
        pytest.param(
            date(2088, 1, 1), False, date(2090, 5, 1), False,
            expected(2, 4, 0), id="years-and-months",
        ),
        pytest.param(
            date(2088, 5, 1), False, date(2091, 5, 1), False,
            expected(3, 0, 0), id="whole-years-no-zero-months",
        ),
        pytest.param(
            date(2088, 1, 1), False, date(2090, 5, 20), False,
            expected(2, 4, 19), id="years-months-day-remainder",
        ),
        # вставной день григорианского календаря: годовщина 29 февраля
        # существует не в каждом году — считается по последнему дню месяца
        pytest.param(
            date(2024, 2, 29), False, date(2025, 2, 28), False,
            expected(1, 0, 0), id="feb-29-anniversary-clamped",
        ),
        pytest.param(
            date(2024, 2, 29), False, date(2025, 3, 1), False,
            expected(1, 0, 1), id="feb-29-anniversary-plus-one",
        ),
        pytest.param(
            date(2023, 1, 31), False, date(2023, 2, 28), False,
            expected(0, 1, 0), id="month-anniversary-clamped",
        ),
        # переход «до н.э. → н.э.» без нулевого года
        pytest.param(
            date(1, 12, 31), True, date(1, 1, 1), False,
            expected(0, 0, 1), id="era-crossing-one-day-no-year-zero",
        ),
        pytest.param(
            date(1, 8, 10), True, date(2, 8, 10), False,
            expected(2, 0, 0), id="era-crossing-anniversaries-no-year-zero",
        ),
        pytest.param(
            date(1, 11, 20), True, date(2, 2, 10), False,
            expected(1, 2, 21), id="era-crossing-mid-year",
        ),
        pytest.param(
            date(44, 1, 1), True, date(44, 1, 1), False,
            expected(87, 0, 0), id="bc44-to-ad44-is-87-years",
        ),
        pytest.param(
            date(44, 3, 5), True, date(43, 3, 5), True,
            expected(1, 0, 0), id="inside-bc-years-count-down",
        ),
        # знак отдельно: второй координата раньше первой — ahead=True
        pytest.param(
            date(2090, 1, 1), False, date(2088, 1, 1), False,
            expected(2, 0, 0, True), id="ahead-whole-years",
        ),
        pytest.param(
            date(2091, 4, 1), False, date(2091, 1, 1), False,
            expected(0, 3, 0, True), id="ahead-three-months",
        ),
        # верхняя граница шкалы: у последнего года н.э. нет следующего
        pytest.param(
            date(9998, 6, 1), False, date(9999, 12, 15), False,
            expected(1, 6, 14), id="ad-scale-top-guard",
        ),
        pytest.param(
            date(9999, 12, 1), False, date(9999, 12, 15), False,
            expected(0, 0, 14), id="last-month-of-last-year",
        ),
    ]

    @pytest.mark.parametrize(
        ("a", "bc_a", "b", "bc_b", "want"), DURATION_TABLE
    )
    def test_duration_table(self, a, bc_a, b, bc_b, want):
        assert observed(duration_parts(a, bc_a, b, bc_b)) == want

    def test_plain_date_and_equal_coordinate_key_identically(self):
        # координата и равная ей дата (C3a: date — частный случай MonthDay)
        # дают тот же расчёт; смешанный вход заодно покрывает обе ветки
        # приведения координат в duration_parts
        coord_row = observed(duration_parts(date(2088, 5, 1), False, MonthDay(2091, 5, 1), False))
        assert coord_row == expected(3, 0, 0)

    @pytest.mark.parametrize(("a", "bc_a", "b", "bc_b"), [
        pytest.param(date(2024, 1, 1), False, date(2090, 5, 20), False, id="across-years"),
        pytest.param(date(44, 3, 5), True, date(1, 1, 1), False, id="across-eras"),
        pytest.param(date(2024, 2, 29), False, date(2025, 2, 28), False, id="leap-clamp"),
    ])
    def test_parts_are_symmetric_sign_is_antisymmetric(self, a, bc_a, b, bc_b):
        forward = duration_parts(a, bc_a, b, bc_b)
        backward = duration_parts(b, bc_b, a, bc_a)
        assert (forward.years, forward.months, forward.days) == (
            backward.years, backward.months, backward.days
        )
        assert forward.ahead is False
        assert backward.ahead is True

    def test_zero_duration_stays_directionless_both_ways(self):
        same = (date(2024, 5, 1), False)
        assert duration_parts(*same, *same).ahead is False


# ── task 1.2: вставные дни кастомного календаря ───────────────────────────


class TestDurationPartsCustomCalendar:
    # L = 30 + 50 + 20 + 1 = 101; слот вставного дня — после первого месяца
    MONTHS = (MonthSpec("Зимостой", 30), MonthSpec("Талолист", 50), MonthSpec("Сухочивень", 20))
    MAIN = CustomCalendar(
        CalendarSpec(months=MONTHS, week_names=WEEK,
                     intercalary=(IntercalarySpec("День Маски", 1),))
    )
    # вставной день после последнего месяца — месячный шаг переводит в год
    HOST_LAST = CustomCalendar(
        CalendarSpec(months=(MonthSpec("Кр1", 30), MonthSpec("Кр2", 30)),
                     week_names=WEEK, intercalary=(IntercalarySpec("Праздник", 2),))
    )
    # вставной день после второго месяца — проверка «хозяин не первый»
    HOST_SECOND = CustomCalendar(
        CalendarSpec(months=MONTHS, week_names=WEEK,
                     intercalary=(IntercalarySpec("Гром", 2),))
    )

    def test_whole_year_includes_the_intercalary_slot(self):
        set_current_calendar(self.MAIN)
        got = duration_parts(MonthDay(1, 1, 1), False, MonthDay(2, 1, 1), False)
        assert observed(got) == expected(1, 0, 0)  # 101 день = ровно год

    def test_days_count_past_the_intercalary_slot(self):
        set_current_calendar(self.MAIN)
        got = duration_parts(MonthDay(1, 1, 1), False, IntercalaryDay(1, 0), False)
        assert observed(got) == expected(0, 0, 30)  # 30 дней месяца + сам слот не включается

    def test_month_step_from_an_intercalary_day(self):
        set_current_calendar(self.MAIN)
        got = duration_parts(IntercalaryDay(44, 0), False, MonthDay(44, 2, 15), False)
        assert observed(got) == expected(0, 1, 14)

    def test_month_step_from_intercalary_after_last_month_crosses_the_year(self):
        set_current_calendar(self.HOST_LAST)
        got = duration_parts(IntercalaryDay(7, 0), False, MonthDay(8, 1, 1), False)
        assert observed(got) == expected(0, 1, 0)
        got = duration_parts(IntercalaryDay(7, 0), False, MonthDay(8, 1, 10), False)
        assert observed(got) == expected(0, 1, 9)

    def test_month_step_from_intercalary_with_second_host(self):
        set_current_calendar(self.HOST_SECOND)
        got = duration_parts(IntercalaryDay(7, 0), False, MonthDay(7, 3, 5), False)
        assert observed(got) == expected(0, 1, 4)

    def test_intercalary_anniversaries_count_whole_years(self):
        set_current_calendar(self.MAIN)
        got = duration_parts(IntercalaryDay(44, 0), False, IntercalaryDay(46, 0), False)
        assert observed(got) == expected(2, 0, 0)

    def test_era_crossing_from_an_intercalary_day(self):
        set_current_calendar(self.MAIN)
        got = duration_parts(IntercalaryDay(1, 0), True, MonthDay(1, 1, 5), False)
        assert observed(got) == expected(0, 3, 4)

    def test_custom_calendar_sign_is_carried_separately(self):
        set_current_calendar(self.MAIN)
        got = duration_parts(MonthDay(44, 2, 15), False, IntercalaryDay(44, 0), False)
        assert observed(got) == expected(0, 1, 14, True)


# ── task 1.4: единое правило возраста сущности (без слов) ─────────────────


class TestEntityAgeRule:
    AGE_TABLE = [
        # живущая сущность: от начала до «сейчас»
        pytest.param(
            date(2088, 5, 1), False, None, False, date(2091, 5, 1), False,
            expected(3, 0, 0), id="alive-counts-to-now",
        ),
        # законченная: возраст до даты конца, а не дальше («10 лет» из спеки)
        pytest.param(
            date(2080, 5, 1), False, date(2090, 5, 1), False, date(2095, 1, 1), False,
            expected(10, 0, 0), id="closed-ages-to-its-end",
        ),
        # конец позже «сейчас» — считается до «сейчас»
        pytest.param(
            date(2080, 5, 1), False, date(2095, 5, 1), False, date(2091, 1, 1), False,
            expected(10, 8, 0), id="open_until_now",
        ),
        # ещё не начавшаяся: «через N» (направление вперёд, ahead=True)
        pytest.param(
            date(2091, 4, 1), False, None, False, date(2091, 1, 1), False,
            expected(0, 3, 0, True), id="future-start-reads-ahead",
        ),
        pytest.param(
            date(2091, 4, 1), False, date(2092, 4, 1), False, date(2091, 1, 1), False,
            expected(0, 3, 0, True), id="future-start-wins-over-end",
        ),
        # начало ровно «сегодня» — нулевая длительность без направления
        pytest.param(
            date(2091, 5, 1), False, None, False, date(2091, 5, 1), False,
            expected(0, 0, 0), id="started-today-is-zero",
        ),
        # конец ровно «сейчас» — строго «раньше» не выполнено, но тот же итог
        pytest.param(
            date(2088, 5, 1), False, date(2091, 5, 1), False, date(2091, 5, 1), False,
            expected(3, 0, 0), id="end-equal-to-now",
        ),
        # битые данные (конец раньше начала) — абсолютный промежуток, без «через»
        pytest.param(
            date(2090, 1, 10), False, date(2085, 1, 10), False, date(2095, 1, 1), False,
            expected(5, 0, 0), id="corrupt_end_before_start",
        ),
        # эра «до н.э.» — то же правило через era_key
        pytest.param(
            date(44, 3, 5), True, None, False, date(43, 3, 5), True,
            expected(1, 0, 0), id="bc-entity-ages-in-bc-era",
        ),
    ]

    @pytest.mark.parametrize(
        ("start", "start_bc", "end", "end_bc", "now", "now_bc", "want"), AGE_TABLE
    )
    def test_age_rule_table(self, start, start_bc, end, end_bc, now, now_bc, want):
        got = entity_age_duration(start, start_bc, end, end_bc, now, now_bc)
        assert observed(got) == want

    def test_age_rule_follows_the_custom_calendar(self):
        set_current_calendar(
            CustomCalendar(
                CalendarSpec(months=TestDurationPartsCustomCalendar.MONTHS,
                             week_names=WEEK,
                             intercalary=(IntercalarySpec("День Маски", 1),))
            )
        )
        got = entity_age_duration(
            IntercalaryDay(44, 0), False, None, False, MonthDay(44, 2, 15), False
        )
        assert observed(got) == expected(0, 1, 14)


# ── hand-off binding (тот же явный контракт, что у era_key) ───────────────


class TestDurationHelpersBinding:
    def test_game_calendar_import_binds_the_duration_helpers(self):
        assert date_era_module._CALENDAR_PROVIDER is not None
        assert date_era_module._MONTH_DAY is MonthDay
        assert date_era_module._INTERCALARY_DAY is IntercalaryDay

    @pytest.mark.parametrize("piece", ["_CALENDAR_PROVIDER", "_MONTH_DAY", "_INTERCALARY_DAY"])
    def test_unbound_pieces_refuse_with_import_hint(self, monkeypatch, piece):
        monkeypatch.setattr(date_era_module, piece, None)
        with pytest.raises(RuntimeError, match="app.domain.game_calendar"):
            duration_parts(date(2025, 1, 1), False, date(2025, 1, 2), False)
