"""Time of day inside a possibly non-Earthly game day (NRI-0023, design Д2).

``events.start_time`` stores one NULLable INTEGER of minutes from the start
of the game day: linear storage gives the within-day order comparison without
pair columns (Д2), and ``NULL`` honestly means «без времени».  The storage
unit is the *active game calendar's* minute: a world whose hour holds
``minutes_per_hour`` minutes counts its day the same way, so both conversions
take the unit as a parameter.  Passing it explicitly is what keeps the stored
number monotonic in (hour, minute) under any spec — with a foreign 100-minute
hour a hardcoded 60 would collide ``0:99`` with ``1:39`` and order ``1:00``
before ``0:99``, breaking spec «Время участвует в порядке внутри дня».  The
default of 60 is the standard-preset / ``CalendarSpec`` unit, spelled in the
signatures so calendar-less call sites stay simple.

Pure domain code: the class carries no calendar knowledge of its own, bounds
of the active calendar are the consumer's question (spec game-calendar-core
«Нездешние сутки»), never a validation here.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TimeOfDay:
    """One wall-clock time of a game day: an ``hour`` and a ``minute``.

    Frozen like the rest of the domain's value objects (Д2) — identity is the
    pair itself, equality and hashing come from the dataclass.  The numbers
    are never checked against a calendar here: «does this hour exist» is
    decided by the active calendar that supplied the unit, never by the value.
    """

    hour: int
    minute: int

    def to_minutes(self, minutes_per_hour: int = 60) -> int:
        """Minutes from the start of the day, counting whole hours in the
        given minute unit (the active calendar's ``minutes_per_hour``)."""
        return self.hour * minutes_per_hour + self.minute

    @classmethod
    def from_minutes(cls, minutes: int, minutes_per_hour: int = 60) -> TimeOfDay:
        """Exact inverse of ``to_minutes``: whole hours plus the remainder
        minute, both in the given unit."""
        hour, minute = divmod(minutes, minutes_per_hour)
        return cls(hour=hour, minute=minute)

    def format_hhmm(self) -> str:
        """The «HH:MM» caption: hour and minute each zero-padded to two
        digits (spec event-time «Время на поверхностях события»)."""
        return f"{self.hour:02d}:{self.minute:02d}"
