"""Pure minute-ladder rule of the event card's «Минута» list (NRI-0023,
task 7.2, spec event-time «Списки часов и минут в карточке события»).

The rule as designed (design Д8, requirement «…с шагом 5, если минуты в часе
делятся на 5…») is on minutes_per_hour % 5: a 60-minute hour gets the clean
five-minute ladder, an hour that does not divide by 5 is enumerated minute by
minute.  The spec's «Неровные минуты» scenario quotes 50 as the uneven sample
although 50 % 5 == 0 — the arithmetic of the requirement sentence, design and
task (the modulo test) wins here; the scenario's input value is the artifact
defect, reported up rather than silently rewritten into code.
"""
from __future__ import annotations

import pytest

from app.presentation.utils.time_options import minute_options


@pytest.mark.parametrize(
    ("minutes_per_hour", "expected"),
    [
        # Scenario «Ровные минуты»: 60 → 0, 5, …, 55 (43 is not selectable).
        (60, list(range(0, 60, 5))),
        # calendar-wizard spec «Сутки задают списки времени»: 100 → 0, 5, …, 95.
        (100, list(range(0, 100, 5))),
        # 50 divides by 5 too, so the designed rule puts it on the ladder as
        # well — 0, 5, …, 45 (see the module docstring about the scenario).
        (50, list(range(0, 50, 5))),
        # A non-divisible hour enumerates every minute of the hour.
        (47, list(range(0, 47))),
        # Low boundary: one-step and single-minute hours stay complete.
        (1, [0]),
        (4, [0, 1, 2, 3]),
        (5, [0]),
        (10, [0, 5]),
    ],
)
def test_minute_options_ladder_or_full_enumeration(minutes_per_hour, expected):
    assert minute_options(minutes_per_hour) == expected


def test_minute_options_is_a_plain_list_of_ints():
    ladder = minute_options(60)
    assert isinstance(ladder, list)
    assert all(isinstance(value, int) for value in ladder)
    # The empty «—» head is a caption the ViewModel owns, never a number here.
    assert ladder[0] == 0
    assert ladder[-1] == 55
