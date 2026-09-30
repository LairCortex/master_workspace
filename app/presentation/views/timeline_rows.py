"""Pure row model of the event timeline — no Qt imports.

simplify-event-timeline-flat-list (design D1): the core is an
«event → one row» builder. ``build_rows(events, window)`` keeps every event
whose interval crosses the «Выбор даты» *window* (an open end never asserts a
closing date) and sorts the rows chronologically — chronological order comes
from the shared era key of ``app.domain.date_era``
(add-era-aware-dates, design D2/D4), and the window only filters, it never
reorders. There is exactly one row per event — a multi-day event is not
duplicated per day, an open event does not run to any bottom. The ladder
machinery (empty days, collapsed gaps, period cards, sticky/zoom/drill/jump/
drop helpers) was deleted with the ladder itself.

NRI-0023 (task 5.1, design Д3/Д6): the flat list grew a two-level tree. Rows
carry ``kind`` (event/stub), ``depth`` (0/1) and ``parent_id``; a child rides
directly under its EXPANDED parent, and both levels order by
``(start_key, время, id)`` where untimed events precede timed ones (the shared
secondary sort key of event-time, mirroring the repository's
``_chronological_order`` — the SQL sort is an optimization, this is the rule
the surfaces obey). A window that captured a child but excludes its parent
puts a parent STUB row (``kind=stub``: name only, no dates, no type mark,
never selectable, no chevron) directly above the orphaned children; outside a
window there are no stubs. With nothing expanded the list of a nesting-free
sample is word-for-word what it always was — a pin, not a hope.

Input contract: event-like objects (anything exposing ``id``/``start_date``/
``end_date``/``name``, e.g. domain ``Event`` instances — since piece C3a their
dates are game calendar coordinates, a plain ``date`` stays legal input), the
navigation ``window``. Era flags are duck-typed like the rest: optional
``start_bc``/``end_bc`` attributes (absent or non-``int``/``bool`` values read
as «н.э.», exactly like the ``DEFAULT 0`` columns of design D3). Window bounds
stay flexible: a bare coordinate (or legacy ``date``) is a legal «н.э.» bound,
a ``(coordinate, is_bc)`` pair carries its own era. ``token_key`` carries the
duck-typed ``"color.chart.N"`` type-dot token (``None`` = untyped) so
delegates paint the type mark without knowing about types. Captions are
pre-built with the game calendar (live month names, intercalary rule names)
and era, so the row text is display-ready. Every row also carries
``detail`` — the event's own description as one collapsed, bounded line the
delegate may wrap over two painted lines, so the list reads as a digest and
not only as a date range. Since NRI-0021 (task 5.1) ``build_rows`` also carries
the game's «now»: exactly one row — the first in sort order starting the very
day of that «now», same era included — gets ``is_now`` for the delegate's
outline. All of this is plain deterministic data, testable without a
QApplication.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Container, Protocol, Sequence

from app.domain.date_era import era_key
from app.domain.game_calendar import GameCoord, InvalidGameDateError
from app.presentation.utils.date_utils import (
    era_flag,
    event_start_time,
    format_event_start,
    format_game_date,
    split_date_era,
)

#: Explicit open-end mark shown instead of an end date (spec «Бессрочные
#: события в списке»): the row never invents a closing date.
OPEN_END_MARK = "∞"

#: Row kinds of the two-level tree (NRI-0023 task 5.1, spec «Дерево событий»):
#: a regular event row, and the parent stub a window-excluded parent of a
#: shown child gets (name only — no dates, no mark, never selectable).
ROW_EVENT = "event"
ROW_STUB = "stub"

#: Character budget of the row's second line (spec «Плоский список событий»):
#: the list shows a GLIMPSE of the description, never its whole text — the
#: delegate owns how many painted lines that glimpse takes.
DETAIL_MAX_CHARS = 160


class _EventLike(Protocol):
    """The minimal shape ``build_rows`` reads off an event.

    An optional ``event_type`` attribute (duck-typed, ``.color_index`` read off
    it) only decorates rows with ``token_key``; doubles may omit it. An
    optional ``description`` attribute (duck-typed, ``.characteristics`` first,
    ``.backstory`` as the fallback) only feeds ``detail``. Optional
    ``start_bc``/``end_bc`` attributes carry the date eras (add-era-aware-dates);
    anything not int/bool reads as «н.э.». NRI-0023 adds two more duck-typed
    optionals read through :func:`event_parent_id`/:func:`event_time_minutes`:
    ``parent_id`` (the self-FK of the sub-event link) and ``start_time_raw``
    (minutes from the start of the game day, the storage column behind the
    event's ``TimeOfDay``) — anything not an int reads as absent. The caption
    reads the domain face instead (NRI-0023 task 8.1, via the shared
    ``event_start_time`` reader): an optional ``start_time`` attribute that
    is an actual ``TimeOfDay`` gains the row the ', HH:MM' tail, anything
    else prints the plain date word-for-word as before.
    """

    id: int
    start_date: GameCoord
    end_date: GameCoord | None
    name: str


def _start_bc(event: _EventLike) -> bool:
    """The event's start era flag, duck-typed like every other era reader."""
    return era_flag(getattr(event, "start_bc", False))


def _end_bc(event: _EventLike) -> bool:
    """The event's end era flag (``False`` for an open end reads as «н.э.»)."""
    return era_flag(getattr(event, "end_bc", False))


def _start_key(event: _EventLike) -> int:
    """The chronological key of an event's start (design D2)."""
    return era_key(event.start_date, _start_bc(event))


def event_parent_id(event: _EventLike) -> int | None:
    """The event's parent id, duck-typed like every other optional reader
    (NRI-0023 task 5.1): only an int counts, absent/foreign values (the
    auto-Mock of a test double, say) read as «no parent» — exactly how the
    NULLable self-FK column reads in storage."""
    parent_id = getattr(event, "parent_id", None)
    if isinstance(parent_id, bool) or not isinstance(parent_id, int):
        return None
    return parent_id


def event_time_minutes(event: _EventLike) -> int | None:
    """Minutes from the start of the game day behind the event's optional
    start time (NRI-0023 task 5.1, design Д2), read off the raw storage
    column; duck-typed like every other optional reader — absent/foreign
    values read as «без времени»."""
    raw = getattr(event, "start_time_raw", None)
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw


def _row_order(event: _EventLike) -> tuple:
    """The one order of every event row (NRI-0023 task 5.1, design Д3): the
    day-level era key, then within one day the time (untimed first — the −1
    bucket precedes any real minute), then ``id`` for a full tie. The same
    tuple the repository's SQL order applies; here it is the rule, there the
    optimization (spec event-time «Время участвует в порядке внутри дня»)."""
    minutes = event_time_minutes(event)
    return (_start_key(event), -1 if minutes is None else minutes, event.id)


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


def _row_caption(event: _EventLike) -> str:
    """Display-ready row text ``start — end · name`` (open end → ``∞``).

    The start side goes through :func:`format_event_start` with the event's
    own era flag and time, so a chosen wall-clock time rides the date as the
    ', HH:MM' tail while an untimed event keeps the plain caption (NRI-0023
    task 8.1, design Д9 — spec event-time «Время на поверхностях события»);
    the end side stays a day (``format_game_date``) — only the start carries
    a time. Both read the live game calendar on every rebuild, so a month
    rename repaints without any extra wiring, and a BC bound prints the
    «N г. до н.э.» suffix (add-era-aware-dates, spec «Отображение эры»).
    """
    end = (
        OPEN_END_MARK
        if event.end_date is None
        else format_game_date(event.end_date, is_bc=_end_bc(event))
    )
    return (
        f"{format_event_start(event.start_date, _start_bc(event), event_start_time(event))} "
        f"— {end} · {event.name}"
    )


def row_detail(event: _EventLike) -> str:
    """The row's second line: the event's own description, one bounded line.

    The text is the event's ``description`` — ``characteristics`` first,
    ``backstory`` only when there are no characteristics (spec «Плоский список
    событий»: a glimpse of the description under the date line). Whitespace is
    collapsed so the line stays a single logical line whatever the source holds,
    and the text is bounded by :data:`DETAIL_MAX_CHARS` — the row is a digest,
    the card owns the full text. A doubled call on the same event costs two
    ``getattr`` reads, which is why the ViewModel's rebuild key reads it too.
    """
    description = getattr(event, "description", None)
    for attribute in ("characteristics", "backstory"):
        raw = getattr(description, attribute, None)
        if not raw:
            continue
        collapsed = " ".join(str(raw).split())
        if not collapsed:
            continue
        if len(collapsed) > DETAIL_MAX_CHARS:
            return collapsed[:DETAIL_MAX_CHARS].rstrip() + "…"
        return collapsed
    return ""


def _bound_key(bound: GameCoord | tuple[GameCoord | None, bool] | None) -> int | None:
    """Era key of one window bound (design D2/D4).

    A bound arrives either bare (a legacy ``date`` or plain coordinate ==
    «н.э.», piece C3a) or as the ``(coordinate, is_bc)`` pair the range
    popover applies; ``None`` is the unbounded side of a partial pair.
    """
    day, is_bc = split_date_era(bound)
    if day is None:
        return None
    return era_key(day, bool(is_bc))


def crosses_window(
    event: _EventLike,
    window: (
        tuple[
            GameCoord | tuple[GameCoord | None, bool] | None,
            GameCoord | tuple[GameCoord | None, bool] | None,
        ]
        | None
    ),
) -> bool:
    """Whether ``event``'s interval intersects ``window`` (design D1).

    Every comparison runs on the shared chronological key (design D2,
    add-era-aware-dates task 4.2), so a BC interval crossing into our era is
    judged correctly on both sides of the era border. An event is visible when
    the window is empty (``None`` or a partial pair — both mean «Все дни») or
    when ``start_key <= window.end`` and the event either is open
    (``end is None``) or has ``end_key >= window.start``. Events starting
    before the window and open events started earlier therefore stay visible;
    a one-day window works with both bounds on the same day. Public since
    NRI-0023 (task 5.2): the ViewModel reads window membership through THIS
    rule (children of collapsed parents cross the window even while no row of
    theirs is emitted), so «crosses the window» never lives twice.
    """
    if window is None:
        return True
    win_start, win_end = window
    start_key = _bound_key(win_start)
    end_key = _bound_key(win_end)
    if start_key is None or end_key is None:
        return True
    return (
        _start_key(event) <= end_key
        and (
            event.end_date is None
            or era_key(event.end_date, _end_bc(event)) >= start_key
        )
    )


@dataclass(frozen=True)
class Row:
    """One event's single flat-list row.

    ``start``/``end`` mirror the event's REAL bounds (game coordinates since
    piece C3a; ``end is None`` = open),
    ``start_bc``/``end_bc`` mirror its era flags (absent/foreign values read as
    «н.э.», like the storage default); ``token_key`` is the duck-typed
    ``"color.chart.N"`` type-dot token (``None`` = untyped mark; a stub never
    wears one); ``caption`` is the finished display text ``start — end · name``
    (open end shown as :data:`OPEN_END_MARK`, BC years with the «N г. до н.э.»
    suffix; a stub's caption is the parent's bare NAME — no dates, spec
    «Окно фильтрации и пустое состояние»); ``detail`` is the bounded one-line
    description (:func:`row_detail`, ``""`` = nothing to show, always empty on
    a stub) the delegate paints under the caption; ``is_now`` marks the ONE row
    the delegate outlines (NRI-0021 task 5.1, spec «Обводка события,
    начинающегося „сегодня“») — the rule lives in :func:`build_rows`, stubs
    never carry it.

    The tree fields (NRI-0023 task 5.1): ``kind`` is :data:`ROW_EVENT` or
    :data:`ROW_STUB`; ``depth`` is the indent level (0 top, 1 under a parent);
    ``parent_id`` is the id of the row's parent event (``None`` at the top);
    ``has_children`` says whether the sample holds children for this event —
    the chevron's single source (a stub renders none whatever its value).
    ``is_last_sibling`` (NRI-0023 task 11.1, design Д11) closes a group: true
    on the LAST EMITTED child of an expanded parent or orphan group (a single
    child is its own last sibling too), false on top-level rows and stubs —
    the delegate paints the «└» angle instead of a trunk that dangles below
    the elbow, so the branch never promises a child that does not exist.
    """

    event_id: int
    start: GameCoord
    end: GameCoord | None
    name: str
    token_key: str | None
    caption: str
    detail: str = ""
    start_bc: bool = False
    end_bc: bool = False
    is_now: bool = False
    kind: str = ROW_EVENT
    depth: int = 0
    parent_id: int | None = None
    has_children: bool = False
    is_last_sibling: bool = False


def window_contains(
    window: (
        tuple[
            GameCoord | tuple[GameCoord | None, bool] | None,
            GameCoord | tuple[GameCoord | None, bool] | None,
        ]
        | None
    ),
    coord: GameCoord,
    is_bc: bool,
) -> bool:
    """Whether ``(coord, is_bc)`` falls INSIDE the «Выбор даты» window
    (NRI-0021 task 5.2, spec «Кнопка прокрутки „➜ Сейчас“»).

    This is the containment twin of :func:`crosses_window` — a different
    question («is this date one of the window's days», not «does this
    interval cross the window»), answered on the same shared era key. An
    absent or partial window is «Все дни» and contains every date, exactly
    like the filter treats it. A coordinate the active calendar does not
    contain raises its own ``InvalidGameDateError`` — the caller decides the
    posture (the button goes inactive, design Д6)."""
    if window is None:
        return True
    start_key = _bound_key(window[0])
    end_key = _bound_key(window[1])
    if start_key is None or end_key is None:
        return True
    key = era_key(coord, bool(is_bc))
    return start_key <= key <= end_key


def _event_row(
    event: _EventLike,
    *,
    kind: str,
    depth: int,
    parent_id: int | None,
    has_children: bool,
    is_last_sibling: bool = False,
) -> Row:
    """One delivered row for ``event``. An event row is the full caption/detail
    pair; a stub row (kind ROW_STUB) carries only the parent's NAME as caption
    — no dates, no type mark, no description line (spec «Окно фильтрации и
    пустое состояние»: the stub explains who the orphan below belongs to and
    interacts as little as possible)."""
    is_stub = kind == ROW_STUB
    return Row(
        event_id=event.id,
        start=event.start_date,
        end=event.end_date,
        name=event.name,
        token_key=None if is_stub else _event_token_key(event),
        caption=event.name if is_stub else _row_caption(event),
        detail="" if is_stub else row_detail(event),
        start_bc=_start_bc(event),
        end_bc=_end_bc(event),
        kind=kind,
        depth=depth,
        parent_id=parent_id,
        has_children=has_children,
        is_last_sibling=is_last_sibling,
    )


def _parent_of(event: _EventLike, by_id: dict) -> _EventLike | None:
    """The parent event of ``event`` inside the sample, or ``None`` when the
    event is top-level: a root carries no parent id, points at itself (the
    service guard makes that unrepresentable in the DB; the core just does not
    loop), or names an id the sample never held (a dangling FK is nobody's
    parent — the event rides the top level unchanged)."""
    parent_id = event_parent_id(event)
    if parent_id is None or parent_id == event.id:
        return None
    return by_id.get(parent_id)


def build_rows(
    events: Sequence[_EventLike],
    window: (
        tuple[
            GameCoord | tuple[GameCoord | None, bool] | None,
            GameCoord | tuple[GameCoord | None, bool] | None,
        ]
        | None
    ) = None,
    now: GameCoord | None = None,
    now_bc: bool = False,
    expanded: Container[int] = frozenset(),
) -> list[Row]:
    """Lay ``events`` out as the ladder's tree rows, filtered by ``window``.

    One row per crossing EVENT (rule :func:`crosses_window`); the window
    filters but never reorders. Top level: parents ordered
    ``(chronological start, время, id)`` (design Д3 — the shared :func:`_row_order`
    tuple, so BC rows precede our-era rows and untimed rows precede timed ones
    within a day). Directly under an EXPANDED parent (an id in ``expanded``,
    NRI-0023 task 5.1) ride its visible children, same order, ``depth=1``;
    while the parent is collapsed its children emit no rows at all (spec
    «Свёрнутый родитель детей прячет»). The group's last emitted child carries
    ``is_last_sibling`` (NRI-0023 task 11.1, design Д11) so the delegate can
    close the branch with an angle instead of a trunk dangling below the
    elbow; a stub is top-level decoration and never carries the flag.
    A crossing child whose parent did not
    become a top-level row (window-excluded or itself a child — the two-level
    chain the service guard keeps degenerate) gets the parent's STUB row
    directly above it; the group sits where the parent's own order key places
    it. Outside the nesting (or with nothing expanded) the emitted rows are
    word-for-word the old flat list — the defaults keep every pre-tree output
    byte-identical. An empty sample or a window no event crosses yields ``[]``
    — the view paints its own emptiness hint.

    ``now``/``now_bc`` (NRI-0021 task 5.1, spec «Обводка события,
    начинающегося „сегодня“») mark exactly one row: the FIRST emitted EVENT
    row whose start is the same day of the same era as the game's «now» (the
    shared era key settles the «тот же день той же эры» check, BC never
    confuses our era; stubs never outline — they show no date). Without
    ``now`` nobody is marked; a «now» the active calendar refuses (the
    Д1-seeded real today on a custom calendar) marks nobody either — the
    outline simply stays absent (the group-4 posture: derived lines hide, the
    list never breaks).
    """
    now_key: int | None = None
    if now is not None:
        try:
            now_key = era_key(now, era_flag(now_bc))
        except InvalidGameDateError:
            now_key = None
    by_id: dict = {}
    children_of: dict[int, list] = {}
    for event in events:
        by_id.setdefault(event.id, event)
    for event in events:
        parent = _parent_of(event, by_id)
        if parent is not None:
            children_of.setdefault(parent.id, []).append(event)
    visible = [event for event in events if crosses_window(event, window)]
    visible_ids = {event.id for event in visible}

    def visible_children(parent_id: int) -> list:
        return sorted(
            (kid for kid in children_of.get(parent_id, ()) if kid.id in visible_ids),
            key=_row_order,
        )

    def child_rows(kids: list, parent_id: int) -> list[Row]:
        """The delivered depth-1 rows of one group in order; the LAST row
        carries ``is_last_sibling`` (design Д11 — the delegate closes the
        branch with the «└» angle on it and runs a full trunk to the next
        row on every middle child; a single child is its own last sibling)."""
        last = len(kids) - 1
        return [
            _event_row(
                kid,
                kind=ROW_EVENT,
                depth=1,
                parent_id=parent_id,
                has_children=bool(children_of.get(kid.id)),
                is_last_sibling=kid_index == last,
            )
            for kid_index, kid in enumerate(kids)
        ]

    # Top-level entries — a rendered parent (plus, when expanded, its visible
    # children) or an orphan group (stub + its visible children) — each keyed
    # by the parent's own order so the merge below stays chronological.
    entries: list[tuple[tuple, list[Row]]] = []
    top_ids: set[int] = set()
    for parent in sorted(
        (e for e in visible if _parent_of(e, by_id) is None), key=_row_order
    ):
        top_ids.add(parent.id)
        rows = [
            _event_row(
                parent,
                kind=ROW_EVENT,
                depth=0,
                parent_id=None,
                has_children=bool(children_of.get(parent.id)),
            )
        ]
        if parent.id in expanded:
            rows += child_rows(visible_children(parent.id), parent.id)
        entries.append((_row_order(parent), rows))
    for parent_id, kids in children_of.items():
        if parent_id in top_ids:
            continue  # rendered above: expanded rode the parent, collapsed hides
        orphans = sorted(
            (kid for kid in kids if kid.id in visible_ids), key=_row_order
        )
        if not orphans:
            continue
        parent = by_id[parent_id]
        group = [
            _event_row(
                parent,
                kind=ROW_STUB,
                depth=0,
                parent_id=None,
                has_children=True,
            )
        ]
        # The orphan children close their group the same way (Д11); the stub
        # itself is top-level decoration — never a last sibling.
        group += child_rows(orphans, parent_id)
        entries.append((_row_order(parent), group))
    entries.sort(key=lambda entry: entry[0])
    rows = [row for _, group in entries for row in group]
    if now_key is not None:
        for index, row in enumerate(rows):
            if (
                row.kind == ROW_EVENT
                and era_key(row.start, row.start_bc) == now_key
            ):
                rows[index] = replace(row, is_now=True)
                break
    return rows
