"""Pure option ladders for the event card's time lists (NRI-0023, task 7.2).

The card's «Час»/«Минута» combos take their bounds from the active game
calendar (spec event-time «Списки часов и минут в карточке события»); the
hour ladder is the plain unit step ``0 … day_hours−1`` and lives with its
consumer, while the minute ladder carries the one rule worth isolating and
testing on its own: step 5 when the hour divides by 5 on the nose
(``minutes_per_hour % 5 == 0``, design Д8), otherwise the full enumeration
``0 … minutes_per_hour−1``.  Qt-free by contract: the ViewModel feeds these
numbers into its QML-facing string lists, the empty «—» head is a caption
the ViewModel owns.
"""
from __future__ import annotations

#: Caption spacing of the «ровный» minute ladder (spec «Ровные минуты»).
MINUTE_STEP = 5


def minute_options(minutes_per_hour: int) -> list[int]:
    """The minute values the card's «Минута» list offers for a calendar whose
    hour holds ``minutes_per_hour`` minutes.

    Step 5 (``0, 5, …, minutes_per_hour−5``) when the hour divides by 5 with
    no remainder; the full minute-by-minute enumeration otherwise — a world
    whose hour has e.g. 47 minutes still lets the user name any of them.
    """
    step = MINUTE_STEP if minutes_per_hour % MINUTE_STEP == 0 else 1
    return list(range(0, minutes_per_hour, step))
