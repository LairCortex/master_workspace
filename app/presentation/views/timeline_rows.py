"""Pure row model of the vertical event timeline (W3b D3) — no Qt imports.

Input: event-like objects (anything exposing ``id``/``start_date``/
``end_date``/``name``, e.g. domain ``Event`` instances), plus an optional
visible range. Output: ``build_rows`` — one entry per calendar day of the
range; an EVENT row per event starting that day (sorted ``(start, id)``) or a
single EMPTY_DAY row. Events stand only at their start position regardless of
duration; empty days never collapse. Without an explicit range the sample
derives its own: min(start) … max(end|start).

``prev_event_index`` / ``next_event_index`` are the jump helpers behind the
panel's "to previous/next event" commands (empty runs are skipped, edges are
inert). ``index_at_y`` / ``normalize_range`` are the rail's Qt-free geometry
helpers behind the W3c rail interactions: a y→first-row-of-day hit-test that
clamps to the list edges, and the (min, max) ordering of a drag pair.
Everything is plain deterministic data, testable without a QApplication.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Protocol, Sequence


class RowKind(Enum):
    """Row type: a line of an event, or the placeholder of an empty day."""

    EVENT = "event"
    EMPTY_DAY = "empty_day"


class _EventLike(Protocol):
    """The minimal shape ``build_rows`` reads off an event."""

    id: int
    start_date: date
    end_date: date | None
    name: str


@dataclass(frozen=True)
class Row:
    """One list position: an event line or an empty-day placeholder.

    ``date`` is the day this row occupies; an EVENT row repeats the event's
    own ``start``/``end`` (``end`` stays ``None`` for an open end) and its
    ``name`` so delegates never reach back into the domain objects. An
    EMPTY_DAY row carries ``event_id=None``, ``start`` equal to its day and
    an empty name.
    """

    kind: RowKind
    date: date
    event_id: int | None = None
    start: date | None = None
    end: date | None = None
    name: str = ""


def build_rows(
    events: Sequence[_EventLike],
    range_start: date | None = None,
    range_end: date | None = None,
) -> list[Row]:
    """Lay out ``events`` as one block of rows per day of the visible range.

    Range resolution: each bound defaults to the sample's own edge — the
    earliest ``start_date`` and the latest ``end_date`` (an open event
    contributes only its start to the maximum, never a synthetic future).
    An explicit pair of bounds (a live filter) enumerates exactly those days
    even when no event falls inside them (spec «Пустой диапазон фильтра»).
    No events and no bounds → no rows; inverted explicit bounds → no rows.

    Determinism: events are grouped by their start day and ordered by
    ``(start_date, id)`` regardless of input order; a multi-day event owns
    only its start position, and days without events become EMPTY_DAY.
    """
    ordered = sorted(events, key=lambda e: (e.start_date, e.id))

    if range_start is None and ordered:
        range_start = min(e.start_date for e in ordered)
    if range_end is None and ordered:
        range_end = max(e.end_date if e.end_date is not None else e.start_date for e in ordered)
    if range_start is None or range_end is None or range_end < range_start:
        return []

    by_start_day: dict[date, list[_EventLike]] = {}
    for event in ordered:
        by_start_day.setdefault(event.start_date, []).append(event)

    rows: list[Row] = []
    day = range_start
    one_day = timedelta(days=1)
    while day <= range_end:
        day_events = by_start_day.get(day, ())
        if day_events:
            rows.extend(
                Row(
                    kind=RowKind.EVENT,
                    date=day,
                    event_id=event.id,
                    start=event.start_date,
                    end=event.end_date,
                    name=event.name,
                )
                for event in day_events
            )
        else:
            rows.append(Row(kind=RowKind.EMPTY_DAY, date=day, start=day))
        day += one_day
    return rows


def prev_event_index(rows: Sequence[Row], from_idx: int) -> int | None:
    """Index of the nearest EVENT row strictly before ``from_idx``.

    Runs of empty days are skipped; nothing before the head → ``None``
    (the jump command stays inert at the edges).
    """
    for idx in range(min(from_idx, len(rows)) - 1, -1, -1):
        if rows[idx].kind is RowKind.EVENT:
            return idx
    return None


def next_event_index(rows: Sequence[Row], from_idx: int) -> int | None:
    """Index of the nearest EVENT row strictly after ``from_idx``.

    Mirror of :func:`prev_event_index`; nothing after the tail → ``None``.
    """
    for idx in range(max(from_idx, -1) + 1, len(rows)):
        if rows[idx].kind is RowKind.EVENT:
            return idx
    return None


def index_at_y(rows: Sequence[Row], row_height: int, y: int) -> int | None:
    """Index of the first row of the day sitting at viewport coordinate ``y``.

    The rail's hit-test (W3c D3): rows are equal-height, so the row under the
    cursor is ``y // row_height``. The result is clamped to the row block — a
    coordinate above the head lands on the first day, one below the tail on
    the last — which is what keeps a drag released outside the viewport on its
    last visible day. The clamp is then walked back to the first row of that
    row's day, so a click against the middle of a multi-event day anchors on
    the day's head. ``None`` when there is nothing to map onto (no rows, or a
    non-positive row height).
    """
    if not rows or row_height <= 0:
        return None
    idx = min(max(y // row_height, 0), len(rows) - 1)
    day = rows[idx].date
    while idx > 0 and rows[idx - 1].date == day:
        idx -= 1
    return idx


def normalize_range(day_a: date, day_b: date) -> tuple[date, date]:
    """Order a drag pair chronologically → ``(min, max)``.

    A drag stretched bottom-up yields the same bounds as top-down, and a
    single-day drag collapses to the day twice (spec «Drag снизу вверх
    нормализуется»).
    """
    return (day_a, day_b) if day_a <= day_b else (day_b, day_a)
