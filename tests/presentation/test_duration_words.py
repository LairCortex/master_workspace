"""Unit tests of the duration word formula (NRI-0021 tasks 1.3/1.4).

``format_duration_words`` is the single wording of spec «Словесная формула
длительности»: whole years and months («3 года 2 мес.»; whole years carry no
zero-months remainder), less than a year — whole months, less than a month —
whole days, zero — «сегодня», the forward direction prefixed with «через ».
The year and day units decline by the Russian counting rule (1 год / 2 года /
5 лет, 1 день / 2 дня / 5 дней); the month unit stays the fixed «мес.» — the
spec scenarios pin «2 года 3 мес.» and «через 3 мес.».  ``format_age_words``
is the single word entry of the entity-age rule for the summary and the card:
to «now», to the end when the end is earlier, «через N» when the start has
not arrived.
"""
from datetime import date

import pytest

from app.domain.date_era import DurationParts
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
from app.presentation.utils.date_utils import format_age_words, format_duration_words


@pytest.fixture(autouse=True)
def _isolated_active_calendar():
    """Age words dispatch on the active calendar — pin «Стандартный» around
    each unit and hand the previously active calendar object back."""
    saved = current_calendar()
    reset_current_calendar()
    yield
    set_current_calendar(saved)


class TestFormatDurationWords:
    WORD_TABLE = [
        # годы и месяцы: словесное склонение у года, месяц — сокращение
        pytest.param(DurationParts(3, 2, 0), False, "3 года 2 мес.", id="three-years-two-months"),
        pytest.param(DurationParts(2, 4, 0), False, "2 года 4 мес.", id="spec-two-years-four-months"),
        # ровно годы — без нулевого остатка месяцев
        pytest.param(DurationParts(3, 0, 0), False, "3 года", id="whole-years-no-zero-months"),
        pytest.param(DurationParts(10, 0, 0), False, "10 лет", id="ten-years"),
        # остаток дней не выводится, когда есть годы или месяцы
        pytest.param(DurationParts(2, 4, 19), False, "2 года 4 мес.", id="days-dropped-with-years"),
        pytest.param(DurationParts(0, 2, 15), False, "2 мес.", id="days-dropped-with-months"),
        # меньше года — целые месяцы
        pytest.param(DurationParts(0, 1, 0), False, "1 мес.", id="one-month"),
        pytest.param(DurationParts(0, 2, 0), False, "2 мес.", id="two-months"),
        pytest.param(DurationParts(0, 5, 0), False, "5 мес.", id="five-months"),
        pytest.param(DurationParts(0, 11, 0), False, "11 мес.", id="eleven-months"),
        # меньше месяца — целые дни со склонением
        pytest.param(DurationParts(0, 0, 1), False, "1 день", id="one-day"),
        pytest.param(DurationParts(0, 0, 2), False, "2 дня", id="two-days-spec"),
        pytest.param(DurationParts(0, 0, 5), False, "5 дней", id="five-days"),
        pytest.param(DurationParts(0, 0, 12), False, "12 дней", id="twelve-days-spec"),
        pytest.param(DurationParts(0, 0, 11), False, "11 дней", id="eleven-days"),
        pytest.param(DurationParts(0, 0, 21), False, "21 день", id="twenty-one-days"),
        pytest.param(DurationParts(0, 0, 25), False, "25 дней", id="twenty-five-days"),
        # падежные формы года по русскому правилу счёта
        pytest.param(DurationParts(1, 0, 0), False, "1 год", id="one-year"),
        pytest.param(DurationParts(2, 0, 0), False, "2 года", id="two-years"),
        pytest.param(DurationParts(5, 0, 0), False, "5 лет", id="five-years"),
        pytest.param(DurationParts(11, 0, 0), False, "11 лет", id="eleven-years"),
        pytest.param(DurationParts(14, 0, 0), False, "14 лет", id="fourteen-years"),
        pytest.param(DurationParts(21, 0, 0), False, "21 год", id="twenty-one-years"),
        pytest.param(DurationParts(22, 0, 0), False, "22 года", id="twenty-two-years"),
        pytest.param(DurationParts(101, 0, 0), False, "101 год", id="hundred-one-years"),
        pytest.param(DurationParts(111, 0, 0), False, "111 лет", id="hundred-eleven-years"),
        # ноль — «сегодня» и без направления, и с ним (нулевая длительность
        # не имеет смысла «вперёд»)
        pytest.param(DurationParts(0, 0, 0), False, "сегодня", id="zero-is-today"),
        pytest.param(DurationParts(0, 0, 0), True, "сегодня", id="zero-ignores-ahead"),
        # направление вперёд — префикс «через »
        pytest.param(DurationParts(0, 0, 5), True, "через 5 дней", id="ahead-five-days-spec"),
        pytest.param(DurationParts(0, 3, 0), True, "через 3 мес.", id="ahead-three-months-spec"),
        pytest.param(DurationParts(3, 2, 0), True, "через 3 года 2 мес.", id="ahead-years-months"),
    ]

    @pytest.mark.parametrize("parts, ahead, words", WORD_TABLE)
    def test_word_table(self, parts, ahead, words):
        assert format_duration_words(parts, ahead) == words

    def test_direction_carried_by_the_parts_is_used_by_default(self):
        # duration_parts вернул знак отдельно — формат подхватывает его сам
        assert format_duration_words(DurationParts(2, 0, 0, True)) == "через 2 года"
        assert format_duration_words(DurationParts(2, 0, 0)) == "2 года"

    def test_explicit_ahead_overrides_the_parts_flag(self):
        assert format_duration_words(DurationParts(0, 0, 5, True), False) == "5 дней"
        assert format_duration_words(DurationParts(0, 0, 5, False), True) == "через 5 дней"


class TestFormatAgeWords:
    AGE_TABLE = [
        # сценарий «Живущая сущность»: 1 мая 2088 → «сейчас» 1 мая 2091
        pytest.param(
            date(2088, 5, 1), False, None, False, date(2091, 5, 1), False,
            "3 года", id="alive-three-years",
        ),
        # сценарий «Сущность с закрытым концом»: возраст считается до 2090
        pytest.param(
            date(2080, 5, 1), False, date(2090, 5, 1), False, date(2095, 1, 1), False,
            "10 лет", id="closed-ages-to-end",
        ),
        # конец позже «сейчас» — считаем до «сейчас» (2080-05 → 2091-01 = 10 л. 8 м.)
        pytest.param(
            date(2080, 5, 1), False, date(2095, 5, 1), False, date(2091, 1, 1), False,
            "10 лет 8 мес.", id="end-later-counts-to-now",
        ),
        # сценарий «Ещё не начавшаяся сущность»
        pytest.param(
            date(2091, 4, 1), False, None, False, date(2091, 1, 1), False,
            "через 3 мес.", id="future-start-ahead",
        ),
        # начало ровно «сейчас»
        pytest.param(
            date(2091, 5, 1), False, None, False, date(2091, 5, 1), False,
            "сегодня", id="started-today",
        ),
        # конец ровно «сейчас» — тот же итог (считаем до текущего дня)
        pytest.param(
            date(2088, 5, 1), False, date(2091, 5, 1), False, date(2091, 5, 1), False,
            "3 года", id="end-equal-now",
        ),
        # эра «до н.э.» — правило то же, через era_key
        pytest.param(
            date(44, 3, 5), True, None, False, date(44, 3, 6), True,
            "1 день", id="bc-era-same-era-day",
        ),
        # переход через границу эр без нулевого года
        pytest.param(
            date(1, 12, 31), True, None, False, date(1, 1, 1), False,
            "1 день", id="era-crossing-birthday-tomorrow",
        ),
    ]

    @pytest.mark.parametrize(
        ("start", "start_bc", "end", "end_bc", "now", "now_bc", "words"), AGE_TABLE
    )
    def test_age_word_table(self, start, start_bc, end, end_bc, now, now_bc, words):
        assert format_age_words(start, start_bc, end, end_bc, now, now_bc) == words

    def test_age_words_follow_the_active_custom_calendar(self):
        set_current_calendar(
            CustomCalendar(
                CalendarSpec(
                    months=(
                        MonthSpec("Зимостой", 30),
                        MonthSpec("Талолист", 50),
                        MonthSpec("Сухочивень", 20),
                    ),
                    week_names=("Восход", "Тень", "Полдень", "Закат"),
                    intercalary=(IntercalarySpec("День Маски", 1),),
                )
            )
        )
        # вставной день как дата начала — часть той же формулы
        assert format_age_words(
            IntercalaryDay(44, 0), False, None, False, MonthDay(44, 2, 15), False
        ) == "1 мес."
