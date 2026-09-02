"""Pure row model of the vertical event timeline (W3b D3, W4 scale ladder) — no Qt imports.

Input: event-like objects (anything exposing ``id``/``start_date``/
``end_date``/``name``, e.g. domain ``Event`` instances), plus an optional
visible range and the W4 view knobs — the *scale unit* (сутки/месяц/год) and a
per-event entity grouping map. Output: ``build_rows``.

* ``unit=DAY`` (the default, the whole W3b/W3c contract): one entry per
  calendar day of the range; an EVENT row per event starting that day (sorted
  ``(start, id)``) or a single EMPTY_DAY row. Events stand only at their start
  position regardless of duration; empty days never collapse. Without an
  explicit range the sample derives its own: min(start) … max(end|start).
* ``unit=MONTH``/``YEAR``: every calendar unit of the window (bounds aligned to
  unit edges) gets exactly one UNIT row — an empty unit stays as a stub with
  ``unit_count=0``. An event touches every unit whose extent crosses
  ``[start, end|range_end]`` (an open end is anchored at the window's end).
* ``groups`` (event id → entity names): on DAY it only reorders events inside
  a day by ``(has_group, group_name, start, id)``; on MONTH/YEAR the list is
  sectioned — a SECTION header per entity, alphabetical, «Без привязки» last,
  inside each section only the units its events touched (an event is counted
  into every section it is linked to).

EVENT rows carry ``token_key`` — ``"color.chart.{color_index}"`` when the event
has a ``event_type.color_index`` (duck-typed, the core never imports the
domain), ``None`` otherwise — so delegates color type dots without knowing
about types (W4 D5).

``prev_event_index`` / ``next_event_index`` are the jump helpers behind the
panel's "to previous/next event" commands (empty runs are skipped, edges are
inert; on MONTH/YEAR there are no EVENT rows at all, so they hand back ``None``
and the view reads that as "drop the ladder a step"). ``index_at_y`` /
``normalize_range`` are the rail's Qt-free geometry helpers behind the W3c rail
interactions: a y→first-row-of-the-position's-unit hit-test that clamps to the
list edges, and the (min, max) ordering of a drag pair. The equal-height-rows
contract (``y // row_height``) is invariant to row kind. ``bracket_lanes`` is
the rail-bracket lane packer (W3b D6, moved into the core by W4 D7): events in
``(start, id)`` order take the first free lane, the assignment wraps around
:data:`BRACKET_MAX_LANES`; in unit mode a span is mapped to
``[first_unit, last_unit]`` before packing. The W5 drag-editing geometry lives
here too: ``target_day`` (target day under the cursor, extrapolated past the
block's edges by :data:`EXTRAPOLATION_STEP_PX`), ``translate_span`` (shift a
closed span, duration intact) and the ``serif_targets``/``serif_hit`` pair
behind the bottom-serif stretch handle (D8). Everything is plain deterministic
data, testable without a QApplication.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Mapping, Protocol, Sequence

#: Group key (and section header) collecting events with no link of the
#: grouped kind — always the last section (spec «Группировка по сущностям»).
NO_GROUP_KEY = "Без привязки"

#: Rail bracket lanes before the assignment wraps around (W3b D6 / W4 3.4).
BRACKET_MAX_LANES = 4

#: First bracket lane x and the x step of the neighbouring lanes (W5 1.4:
#: moved out of the widget so the Qt-free serif hit-test (D8) computes the
#: same centers the delegate paints; the view imports these back for painting).
BRACKET_X0 = 6
BRACKET_LANE_STEP = 5

#: Pixel pitch a drag target extrapolates by past the row block (W5 D7):
#: the equal-height row pitch — intentionally equal to the view's
#: ``ROW_HEIGHT`` (the core cannot import the view; the view hands its
#: ``ROW_HEIGHT`` to :func:`target_day` as ``row_height``).
EXTRAPOLATION_STEP_PX = 24

#: Half-width of the bottom-serif drag handle's hit zone (W5 D7): a press at
#: ``|x - center| ≤ SERIF_HIT_PX`` from the serif's lane center arms the
#: end-stretch gesture, everything beside it stays the rail's (spec
#: «Промах мимо засечки остаётся рейкой»).
SERIF_HIT_PX = 4

#: Inclusive calendar bounds of ``CustomDateEdit`` (W5 D2/D7). A drag target
#: never leaves this interval — the gesture cannot mint a date the card
#: cannot display.
CALENDAR_MIN = date(100, 1, 1)
CALENDAR_MAX = date(9999, 12, 31)


class ScaleUnit(Enum):
    """One rung of the W4 view ladder: the unit a position stands for."""

    DAY = "day"
    MONTH = "month"
    YEAR = "year"


class RowKind(Enum):
    """Row type: an event line, an empty day, a unit position, a section head."""

    EVENT = "event"
    EMPTY_DAY = "empty_day"
    UNIT = "unit"
    SECTION = "section"


class _EventLike(Protocol):
    """The minimal shape ``build_rows`` reads off an event.

    An optional ``event_type`` attribute (duck-typed, ``.color_index`` read off
    it) only decorates EVENT rows with ``token_key``; doubles may omit it.
    """

    id: int
    start_date: date
    end_date: date | None
    name: str


@dataclass(frozen=True)
class Row:
    """One list position: event line, empty day, unit position or section head.

    ``date`` is the position anchor: the day (DAY rungs) or the first day of
    the unit this row stands for. An EVENT row repeats the event's own
    ``start``/``end`` (``end`` stays ``None`` for an open end), its ``name``
    and its type-dot ``token_key`` so delegates never reach back into the
    domain objects. An EMPTY_DAY row carries ``event_id=None``, ``start`` equal
    to its day and an empty name. A UNIT row carries ``unit`` plus the
    ``unit_count`` of events touching it (0 → the muted empty stub); a SECTION
    row carries the section's ``group_key``. On sectioned rungs UNIT rows
    repeat the owning ``group_key``.
    """

    kind: RowKind
    date: date
    event_id: int | None = None
    start: date | None = None
    end: date | None = None
    name: str = ""
    unit: ScaleUnit = ScaleUnit.DAY
    unit_count: int | None = None
    group_key: str | None = None
    token_key: str | None = None


def _unit_start(day: date, unit: ScaleUnit) -> date:
    """First day of the unit of the ladder ``unit`` that contains ``day``."""
    if unit is ScaleUnit.MONTH:
        return date(day.year, day.month, 1)
    if unit is ScaleUnit.YEAR:
        return date(day.year, 1, 1)
    return day


def _next_unit_start(unit_first: date, unit: ScaleUnit) -> date:
    """First day of the unit following the one starting at ``unit_first``."""
    if unit is ScaleUnit.MONTH:
        if unit_first.month == 12:
            return date(unit_first.year + 1, 1, 1)
        return date(unit_first.year, unit_first.month + 1, 1)
    if unit is ScaleUnit.YEAR:
        return date(unit_first.year + 1, 1, 1)
    return unit_first + timedelta(days=1)


def _iter_window_units(range_start: date, range_end: date, unit: ScaleUnit) -> list[date]:
    """First days of every unit of ``unit`` overlapping [range_start, range_end]."""
    starts: list[date] = []
    cursor = _unit_start(range_start, unit)
    while cursor <= range_end:
        starts.append(cursor)
        cursor = _next_unit_start(cursor, unit)
    return starts


def _event_token_key(event: _EventLike) -> str | None:
    """Type-dot token of an event ("color.chart.N"), None when untyped.

    Duck-typed on purpose: the core stays Qt-free *and* domain-free, it only
    mirrors the token key the ui-theme palette defines (W4 D5).
    """
    event_type = getattr(event, "event_type", None)
    color_index = getattr(event_type, "color_index", None)
    if color_index is None:
        return None
    return f"color.chart.{color_index}"


def _group_names(groups: Mapping[int, Sequence[str]] | None, event_id: int) -> tuple[str, ...]:
    """Names of the groups ``event_id`` belongs to, «Без привязки» normalized away.

    An empty mapping result means "no link" and lands the event in the
    NO_GROUP_KEY section instead of letting a literal name sort alphabetically.
    """
    if groups is None:
        return ()
    return tuple(name for name in groups.get(event_id, ()) if name and name != NO_GROUP_KEY)


def build_rows(
    events: Sequence[_EventLike],
    range_start: date | None = None,
    range_end: date | None = None,
    unit: ScaleUnit = ScaleUnit.DAY,
    groups: Mapping[int, Sequence[str]] | None = None,
) -> list[Row]:
    """Lay ``events`` out as rows of the scale ladder ``unit``.

    Range resolution (all rungs): each bound defaults to the sample's own edge
    — the earliest ``start_date`` and the latest ``end_date`` (an open event
    contributes only its start to the maximum, never a synthetic future). An
    explicit pair of bounds (a live filter) enumerates the window even when no
    event falls inside it (spec «Пустой диапазон фильтра»). No events and no
    bounds → no rows; inverted explicit bounds → no rows.

    ``unit=DAY`` reproduces the W3b/W3c output exactly when ``groups`` is
    ``None``: one block per day, EVENT rows sorted ``(start, id)`` or one
    EMPTY_DAY; ``groups`` then only reorders events inside each day by
    ``(has_group, group_name, start, id)`` (spec «Сутки остаются хронологией»).

    ``unit=MONTH``/``YEAR`` enumerates every unit of the window (edges aligned
    to unit boundaries) as a UNIT row with its ``unit_count``; ``groups``
    sections the list instead — SECTION header, then only the units that
    section touched, the event counted into every section it links to.
    """
    ordered = sorted(events, key=lambda e: (e.start_date, e.id))

    if range_start is None and ordered:
        range_start = min(e.start_date for e in ordered)
    if range_end is None and ordered:
        range_end = max(e.end_date if e.end_date is not None else e.start_date for e in ordered)
    if range_start is None or range_end is None or range_end < range_start:
        return []

    if unit is ScaleUnit.DAY:
        return _build_day_rows(ordered, range_start, range_end, groups)
    return _build_unit_rows(ordered, range_start, range_end, unit, groups)


def _build_day_rows(
    ordered: Sequence[_EventLike],
    range_start: date,
    range_end: date,
    groups: Mapping[int, Sequence[str]] | None,
) -> list[Row]:
    """The W3b/W3c daily layout — bit-for-bit identical without ``groups``."""

    def day_sort_key(event: _EventLike) -> tuple[int, str, date, int]:
        names = _group_names(groups, event.id)
        return (0 if names else 1, names[0] if names else "", event.start_date, event.id)

    by_start_day: dict[date, list[_EventLike]] = {}
    for event in ordered:
        by_start_day.setdefault(event.start_date, []).append(event)
    if groups is not None:
        # Grouping never moves days around, it only orders events inside a day
        # (spec «Сутки остаются хронологией»): linked first by group name,
        # then unlinked by (start, id).
        for day_events in by_start_day.values():
            day_events.sort(key=day_sort_key)

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
                    token_key=_event_token_key(event),
                )
                for event in day_events
            )
        else:
            rows.append(Row(kind=RowKind.EMPTY_DAY, date=day, start=day))
        day += one_day
    return rows


def _touches(event: _EventLike, unit_first: date, unit_last: date, window_end: date) -> bool:
    """Whether the event's interval crosses the unit [unit_first, unit_last].

    The interval is ``[start, end]``, an open end anchored at the window's end
    (W4 3.2) — an ongoing event is painted through the very last unit.
    """
    eff_end = window_end if event.end_date is None else event.end_date
    return event.start_date <= unit_last and eff_end >= unit_first


def _build_unit_rows(
    ordered: Sequence[_EventLike],
    range_start: date,
    range_end: date,
    unit: ScaleUnit,
    groups: Mapping[int, Sequence[str]] | None,
) -> list[Row]:
    """MONTH/YEAR layout: one UNIT row per window unit, optionally sectioned."""
    units = _iter_window_units(range_start, range_end, unit)

    def unit_counts(members: Sequence[_EventLike]) -> list[tuple[date, int]]:
        counts: list[tuple[date, int]] = []
        for first in units:
            last = _next_unit_start(first, unit) - timedelta(days=1)
            count = sum(1 for e in members if _touches(e, first, last, range_end))
            counts.append((first, count))
        return counts

    if groups is None:
        return [
            Row(kind=RowKind.UNIT, date=first, unit=unit, unit_count=count)
            for first, count in unit_counts(ordered)
        ]

    sections: dict[str, list[_EventLike]] = {}
    for event in ordered:
        names = _group_names(groups, event.id) or (NO_GROUP_KEY,)
        for name in names:
            sections.setdefault(name, []).append(event)

    ordered_keys = sorted(name for name in sections if name != NO_GROUP_KEY)
    if NO_GROUP_KEY in sections:
        ordered_keys.append(NO_GROUP_KEY)

    rows: list[Row] = []
    for name in ordered_keys:
        # Inside a section only the units its own events touched (spec
        # «Пустой месяц не показан в секции»); a section whose events all
        # live outside the window owns no position and is skipped.
        touched = [
            (first, count)
            for first, count in unit_counts(sections[name])
            if count > 0
        ]
        if not touched:
            continue
        rows.append(Row(kind=RowKind.SECTION, date=touched[0][0], unit=unit, group_key=name))
        rows.extend(
            Row(kind=RowKind.UNIT, date=first, unit=unit, unit_count=count, group_key=name)
            for first, count in touched
        )
    return rows


def prev_event_index(rows: Sequence[Row], from_idx: int) -> int | None:
    """Index of the nearest EVENT row strictly before ``from_idx``.

    Runs of empty days are skipped; nothing before the head → ``None``
    (the jump command stays inert at the edges). A MONTH/YEAR model carries no
    EVENT rows at all, so the helpers never invent an event target there — the
    view reads ``None`` as "drop the ladder to DAY first".
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
    """Index of the first row of the unit sitting at viewport coordinate ``y``.

    The rail's hit-test (W3c D3): rows are equal-height regardless of kind —
    the contract W4 keeps intact — so the row under the cursor is
    ``y // row_height``. The result is clamped to the row block — a
    coordinate above the head lands on the first position, one below the tail
    on the last — which is what keeps a drag released outside the viewport on
    its last visible unit. The clamp is then walked back to the first row of
    that row's own date block, so a click against the middle of a multi-event
    day anchors on the day's head; on unit rungs a position is a single row
    (a contiguous date block is the section head plus its same-dated unit, the
    block's head is a valid jump anchor). ``None`` when there is nothing to map
    onto (no rows, or a non-positive row height).
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
    нормализуется»). Unit rungs pass unit anchor dates through the same helper;
    snapping the anchors to full unit boundaries (1-е число / last-day) is the
    view's emit-time mapping (W4 D3), not this pair ordering.
    """
    return (day_a, day_b) if day_a <= day_b else (day_b, day_a)


def target_day(
    rows: Sequence[Row], row_height: int, y: int, scroll: int = 0
) -> date | None:
    """The day a drag points at — viewport ``y`` over the scrolled model (W5 D2).

    Inside the row block this is the :func:`index_at_y` hit-test on the equal
    -height contract (whole-row ``scroll``, floor division rides negative y
    into negative steps): the day of the row under the cursor. Past the edges
    there is no row to hit-test, so the target is *extrapolated* from the
    model's own edge day — every :data:`EXTRAPOLATION_STEP_PX`-sized pitch
    beyond the head steps one earlier day back, beyond the tail one later day
    on (``ceil(Δy / pitch)`` days, spelled as the same floor-division step).
    Crossing month/December→January/February-29 needs no rules of its own:
    plain calendar arithmetic walks the steps (spec «без специальных правил»).
    ``None`` only for a non-positive pitch or an empty model — the edge days
    themselves always extend, which is what lets a release outside the list
    commit on its extrapolated target (spec «Release вне списка — обычный
    commit»). Drag editing is a DAY-rung gesture; the row model handed in is
    the daily one. Every result is clamped to :data:`CALENDAR_MIN` /
    :data:`CALENDAR_MAX` (inside the block and past the edges alike).
    """
    if not rows or row_height <= 0:
        return None
    pitch = row_height  # the view passes its ROW_HEIGHT == EXTRAPOLATION_STEP_PX
    row = (y + scroll * pitch) // pitch
    if 0 <= row < len(rows):
        return clamp_calendar(rows[row].date)
    if row < 0:  # ceil(-content/pitch) == -row steps above the head day
        return _shift_day(rows[0].date, row)
    return _shift_day(rows[-1].date, row - (len(rows) - 1))


def clamp_calendar(day: date) -> date:
    """Clip ``day`` to :data:`CALENDAR_MIN` … :data:`CALENDAR_MAX` (W5 1.5)."""
    if day < CALENDAR_MIN:
        return CALENDAR_MIN
    if day > CALENDAR_MAX:
        return CALENDAR_MAX
    return day


def _shift_day(day: date, steps: int) -> date:
    """``day + steps``, clamped; ``OverflowError`` at the datetime edges."""
    try:
        shifted = day + timedelta(days=steps)
    except OverflowError:
        return CALENDAR_MIN if steps < 0 else CALENDAR_MAX
    return clamp_calendar(shifted)


def translate_span(start: date, end: date, delta_days: int) -> tuple[date, date]:
    """Shift a closed span by ``delta_days``, duration intact (W5 1.3).

    Both bounds move by the same amount, so the length never changes and the
    pair never inverts (for a closed input, ``end ≥ start`` is
    shift-invariant). This layer is *only* the shift — clamping to the model
    or the filter is the view/wiring's business, not the arithmetic's.
    """
    shift = timedelta(days=delta_days)
    return start + shift, end + shift


def bracket_lanes(
    events: Sequence[_EventLike],
    range_end: date | None,
    unit: ScaleUnit = ScaleUnit.DAY,
) -> dict[int, int]:
    """Deterministic rail lane per event bracket (moved into the core by W4 3.4).

    Brackets spanning the same position must not collide (spec «Пересекающиеся
    привязки»): events are taken in ``(start, id)`` order and each takes the
    first lane whose last bracket already ended before its start; when all
    :data:`BRACKET_MAX_LANES` lanes are busy the assignment wraps — the
    overlap is then visually accepted, still deterministically.

    An open end reaches ``range_end`` without asserting a "current" date; a
    span of a single position owns no bracket lane (on DAY its day tick
    already marks it, spec «Привязка событий к рейке»). ``unit=MONTH``/``YEAR``
    maps the span onto ``[first_unit, last_unit]`` — bracketing units the span
    touches (spec «Скобка через месяцы») — otherwise the packing is unchanged.
    """
    if range_end is None:
        return {}
    spans: list[tuple[_EventLike, date]] = []
    for event in events:
        first_unit = _unit_start(event.start_date, unit)
        eff_end = range_end if event.end_date is None else min(event.end_date, range_end)
        last_unit = _unit_start(eff_end, unit)
        if last_unit > first_unit:
            spans.append((event, last_unit))
    spans.sort(key=lambda pair: (pair[0].start_date, pair[0].id))
    lane_free_until: dict[int, date] = {}
    lanes: dict[int, int] = {}
    for event, last_unit in spans:
        first_unit = _unit_start(event.start_date, unit)
        lane = next(
            (cand for cand in range(BRACKET_MAX_LANES)
             if lane_free_until.get(cand, first_unit) < first_unit),
            len(lanes) % BRACKET_MAX_LANES,
        )
        lane_free_until[lane] = last_unit
        lanes[event.id] = lane
    return lanes


@dataclass(frozen=True)
class SerifTarget:
    """One draggable bottom serif (W5 D8): which event, which row, which lane.

    ``center_x`` is the x the delegate paints that serif at — the single
    source of truth both painter and hit-test share (no "serif is there but
    the hit zone is elsewhere" drift).
    """

    event_id: int
    row_index: int
    lane: int

    @property
    def center_x(self) -> int:
        return BRACKET_X0 + self.lane * BRACKET_LANE_STEP


def serif_targets(
    rows: Sequence[Row],
    events: Sequence[_EventLike],
    lanes: Mapping[int, int],
) -> dict[int, tuple[SerifTarget, ...]]:
    """row index → the bottom serifs painted there, for the stretch hit-test.

    A target exists exactly where ``_rebuild`` paints a ``serif_bottom``
    segment of a **closed multi-day** span (D8): on the last row of the span's
    end day, on the event's bracket lane, with the same clamp to the model's
    last day the painter applies (an end beyond the window serifs on the edge
    row). One-day spans own no handle (and usually no lane at all), and open
    ends stay pure decoration — both excluded even if a lane is handed in
    (spec «Засечка открытой скобки не ручка», «Однодневное нельзя растянуть»).
    Two spans ending on one day stack up as a tuple, input order kept.
    """
    targets: dict[int, list[SerifTarget]] = {}
    if not rows or not lanes:
        return {}
    last_index_by_date = {row.date: idx for idx, row in enumerate(rows)}
    window_end = rows[-1].date  # the edge open/crossing spans clamp onto
    for event in events:
        lane = lanes.get(event.id)
        if lane is None:
            continue  # spans without a bracket have no serif to press either
        if event.end_date is None or event.end_date <= event.start_date:
            continue  # decoration only: open end or one-day pin
        row_index = last_index_by_date.get(min(event.end_date, window_end))
        if row_index is None:
            continue  # the clamped end day is not part of this model
        targets.setdefault(row_index, []).append(
            SerifTarget(event_id=event.id, row_index=row_index, lane=lane)
        )
    return {idx: tuple(items) for idx, items in targets.items()}


def serif_hit(
    targets: Sequence[SerifTarget], x: int
) -> SerifTarget | None:
    """The serif whose vertical hit strip contains ``x``, else ``None``.

    A press within :data:`SERIF_HIT_PX` of a serif's center arms the
    end-stretch; every other x in the rail keeps jumping/filter-dragging as
    before (spec «Промах мимо засечки остаётся рейкой»). Overlapping lane
    strips (lanes sit :data:`BRACKET_LANE_STEP` apart, the strip is wider)
    resolve to the first target in input order — deterministic, like the
    lane packer itself.
    """
    for target in targets:
        if abs(x - target.center_x) <= SERIF_HIT_PX:
            return target
    return None
