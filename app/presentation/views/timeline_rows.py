"""Pure row model of the event timeline — no Qt imports.

simplify-event-timeline-flat-list (design D1): the core is a flat
«event → one row» builder. ``build_rows(events, window)`` keeps every event
whose interval crosses the «Выбор даты» *window* (an open end never asserts a
closing date) and sorts the rows ``(chronological start, id)`` ascending —
chronological order comes from the shared era key of ``app.domain.date_era``
(add-era-aware-dates, design D2/D4), and the window only filters, it never
reorders. There is exactly one row per event — a multi-day event is not
duplicated per day, an open event does not run to any bottom. The ladder
machinery (empty days, collapsed gaps, period cards, sticky/zoom/drill/jump/
drop helpers) was deleted with the ladder itself.

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
not only as a date range. All of this is plain deterministic data, testable
without a QApplication.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from app.domain.date_era import era_key
from app.domain.game_calendar import GameCoord
from app.presentation.utils.date_utils import (
    era_flag,
    format_game_date,
    split_date_era,
)

#: Explicit open-end mark shown instead of an end date (spec «Бессрочные
#: события в списке»): the row never invents a closing date.
OPEN_END_MARK = "∞"

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
    anything not int/bool reads as «н.э.».
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

    Dates go through :func:`format_game_date` with the event's own era flags,
    i.e. the live game month map is re-read on every rebuild — a month rename
    repaints without any extra wiring, and a BC bound prints the
    «N г. до н.э.» suffix (add-era-aware-dates, spec «Отображение эры»).
    """
    end = (
        OPEN_END_MARK
        if event.end_date is None
        else format_game_date(event.end_date, is_bc=_end_bc(event))
    )
    return (
        f"{format_game_date(event.start_date, is_bc=_start_bc(event))} "
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


def _crosses_window(
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
    a one-day window works with both bounds on the same day.
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
    ``"color.chart.N"`` type-dot token (``None`` = untyped mark); ``caption`` is
    the finished display text ``start — end · name`` (open end shown as
    :data:`OPEN_END_MARK`, BC years with the «N г. до н.э.» suffix); ``detail``
    is the bounded one-line description (:func:`row_detail`, ``""`` = nothing to
    show) the delegate paints under the caption.
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


def build_rows(
    events: Sequence[_EventLike],
    window: (
        tuple[
            GameCoord | tuple[GameCoord | None, bool] | None,
            GameCoord | tuple[GameCoord | None, bool] | None,
        ]
        | None
    ) = None,
) -> list[Row]:
    """Lay ``events`` out as the flat list's rows, filtered by ``window``.

    One row per crossing event (rule :func:`_crosses_window`), ordered
    ``(chronological start, id)`` ascending — the start rides the shared era
    key (design D2), so BC rows precede our-era rows and BC days run in their
    natural order; the window filters but never reorders. An empty sample or a
    window no event crosses yields ``[]`` — the view paints its own emptiness
    hint.
    """
    rows = [
        Row(
            event_id=event.id,
            start=event.start_date,
            end=event.end_date,
            name=event.name,
            token_key=_event_token_key(event),
            caption=_row_caption(event),
            detail=row_detail(event),
            start_bc=_start_bc(event),
            end_bc=_end_bc(event),
        )
        for event in events
        if _crosses_window(event, window)
    ]
    rows.sort(key=lambda row: (era_key(row.start, row.start_bc), row.event_id))
    return rows
