"""Tests for ``app.domain.time_of_day`` (NRI-0023 task 1.1).

The contract under test is the storage arithmetic of design Д2: a frozen
``TimeOfDay(hour, minute)`` converting to and from minutes-from-day-start
(``to_minutes``/``from_minutes``), the minute unit being the active game
calendar's — the default parameter is the earthly 60, the custom-calendar
call passes its own ``minutes_per_hour``; and the ``format_hhmm`` caption of
spec event-time «Время на поверхностях события» («HH:MM» with leading zeros).
Boundaries are checked on both sides of each scale, the alien 10×100 day of
spec game-calendar-core «Нездешние сутки» included.
"""
import pytest
from dataclasses import FrozenInstanceError

from app.domain.time_of_day import TimeOfDay


class TestToMinutes:
    @pytest.mark.parametrize(
        ("hour", "minute", "expected"),
        [
            (0, 0, 0),        # нижняя граница суток
            (0, 1, 1),
            (1, 0, 60),       # ровно один земной час
            (14, 30, 870),    # «встреча в 14:30» из proposal
            (23, 59, 1439),   # верхняя граница земных суток
        ],
    )
    def test_default_unit_is_the_earthly_60(self, hour, minute, expected):
        assert TimeOfDay(hour, minute).to_minutes() == expected

    @pytest.mark.parametrize(
        ("hour", "minute", "minutes_per_hour", "expected"),
        [
            (0, 0, 100, 0),      # нижняя граница нездешних суток
            (1, 0, 100, 100),    # час начинается на единицу их минуты
            (2, 30, 100, 230),
            (9, 99, 100, 999),   # верхняя граница 10×100-суток
            (0, 99, 100, 99),    # 0:99 ≠ 1:39=… — без чужой единицы коллизии нет
        ],
    )
    def test_custom_unit_counts_hours_in_it(self, hour, minute, minutes_per_hour, expected):
        assert TimeOfDay(hour, minute).to_minutes(minutes_per_hour) == expected

    def test_minutes_are_monotonic_in_hour_then_minute(self):
        # спека event-time «Время участвует в порядке внутри дня»: в чужих
        # сутках число растёт по (час, минута) — иначе SQL-сортировка врёт
        unit = 100
        ordered = [TimeOfDay(0, 0), TimeOfDay(0, 99), TimeOfDay(1, 0),
                   TimeOfDay(1, 5), TimeOfDay(9, 99)]
        assert sorted(ordered, key=lambda t: t.to_minutes(unit)) == ordered


class TestFromMinutes:
    @pytest.mark.parametrize(
        ("minutes", "expected"),
        [
            (0, TimeOfDay(0, 0)),        # нижняя граница
            (1, TimeOfDay(0, 1)),
            (60, TimeOfDay(1, 0)),
            (870, TimeOfDay(14, 30)),
            (1439, TimeOfDay(23, 59)),   # верхняя граница земных суток
        ],
    )
    def test_default_unit_is_the_earthly_60(self, minutes, expected):
        assert TimeOfDay.from_minutes(minutes) == expected

    @pytest.mark.parametrize(
        ("minutes", "minutes_per_hour", "expected"),
        [
            (0, 100, TimeOfDay(0, 0)),
            (99, 100, TimeOfDay(0, 99)),
            (100, 100, TimeOfDay(1, 0)),
            (230, 100, TimeOfDay(2, 30)),
            (999, 100, TimeOfDay(9, 99)),  # верхняя граница 10×100-суток
        ],
    )
    def test_custom_unit_splits_by_it(self, minutes, minutes_per_hour, expected):
        assert TimeOfDay.from_minutes(minutes, minutes_per_hour) == expected

    @pytest.mark.parametrize("unit", [1, 5, 60, 100])
    @pytest.mark.parametrize("minutes", [0, 1, 7, 59, 60, 241, 999])
    def test_round_trip_is_exact_under_any_unit(self, minutes, unit):
        # часы могут выйти за «земные» границы — значение честное, единица своя
        tod = TimeOfDay.from_minutes(minutes, unit)
        assert tod.to_minutes(unit) == minutes


class TestFormatHHMM:
    @pytest.mark.parametrize(
        ("hour", "minute", "expected"),
        [
            (9, 5, "09:05"),    # сценарий «Время в строке» — оба поля с нулём
            (0, 0, "00:00"),    # нижняя граница формата
            (14, 30, "14:30"),  # двузначные пишутся как есть
            (10, 0, "10:00"),   # нули минут не теряются
            (23, 59, "23:59"),  # верхняя граница земных суток
            (9, 95, "09:95"),   # нездешняя минута 95 — тоже два знака
        ],
    )
    def test_hhmm_with_leading_zeros(self, hour, minute, expected):
        assert TimeOfDay(hour, minute).format_hhmm() == expected


class TestValueSemantics:
    def test_frozen(self):
        tod = TimeOfDay(9, 5)
        with pytest.raises(FrozenInstanceError):
            tod.hour = 10  # type: ignore[misc]

    def test_equal_pairs_are_one_value(self):
        assert TimeOfDay(9, 5) == TimeOfDay(9, 5)
        assert hash(TimeOfDay(9, 5)) == hash(TimeOfDay(9, 5))
        assert len({TimeOfDay(9, 5), TimeOfDay(9, 5), TimeOfDay(9, 6)}) == 2
