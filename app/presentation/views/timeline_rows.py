"""Pure row model of the event timeline — no Qt imports.

simplify-event-timeline-flat-list (design D1): the core is a flat
«event → one row» builder. ``build_rows(events, window)`` keeps every event
whose interval crosses the «Выбор даты» *window* (an open end never asserts a
closing date) and sorts the rows ``(start_date, id)`` ascending; the window
only filters, it never reorders. There is exactly one row per event — a
multi-day event is not duplicated per day, an open event does not run to any
bottom. The ladder machinery (empty days, collapsed gaps, period cards,
sticky/zoom/drill/jump/drop helpers) was deleted with the ladder itself.

Input contract: event-like objects (anything exposing ``id``/``start_date``/
``end_date``/``name``, e.g. domain ``Event`` instances), the navigation
``window``. ``token_key`` carries the duck-typed ``"color.chart.N"`` type-dot
token (``None`` = untyped) so delegates paint the type mark without knowing
about types. Captions are pre-built with the game calendar (live month names),
so the row text is display-ready. Every row also carries ``detail`` — the
event's own description as one collapsed, bounded line the delegate may wrap
over two painted lines, so the list reads as a digest and not only as a date
range. All of this is plain deterministic data, testable without a QApplication.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, Sequence

from app.presentation.utils.date_utils import format_game_date

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
    ``.backstory`` as the fallback) only feeds ``detail``.
    """

    id: int
    start_date: date
    end_date: date | None
    name: str


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

    Dates go through :func:`format_game_date`, i.e. the live game month map is
    re-read on every rebuild — a month rename repaints without any extra wiring.
    """
    end = OPEN_END_MARK if event.end_date is None else format_game_date(event.end_date)
    return f"{format_game_date(event.start_date)} — {end} · {event.name}"


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


def _crosses_window(event: _EventLike, window: tuple[date | None, date | None] | None) -> bool:
    """Whether ``event``'s interval intersects ``window`` (design D1).

    An event is visible when the window is empty (``None`` or a partial pair —
    both mean «Все дни») or when ``start <= window.end`` and the event either
    is open (``end is None``) or has ``end >= window.start``. Events starting
    before the window and open events started earlier therefore stay visible;
    a one-day window works with both bounds on the same day.
    """
    if window is None:
        return True
    win_start, win_end = window
    if win_start is None or win_end is None:
        return True
    return (
        event.start_date <= win_end
        and (event.end_date is None or event.end_date >= win_start)
    )


@dataclass(frozen=True)
class Row:
    """One event's single flat-list row.

    ``start``/``end`` mirror the event's REAL bounds (``end is None`` = open);
    ``token_key`` is the duck-typed ``"color.chart.N"`` type-dot token
    (``None`` = untyped mark); ``caption`` is the finished display text
    ``start — end · name`` (open end shown as :data:`OPEN_END_MARK`); ``detail``
    is the bounded one-line description (:func:`row_detail`, ``""`` = nothing to
    show) the delegate paints under the caption.
    """

    event_id: int
    start: date
    end: date | None
    name: str
    token_key: str | None
    caption: str
    detail: str = ""


def build_rows(
    events: Sequence[_EventLike],
    window: tuple[date | None, date | None] | None = None,
) -> list[Row]:
    """Lay ``events`` out as the flat list's rows, filtered by ``window``.

    One row per crossing event (rule :func:`_crosses_window`), ordered
    ``(start_date, id)`` ascending; the window filters but never reorders. An
    empty sample or a window no event crosses yields ``[]`` — the view paints
    its own emptiness hint.
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
        )
        for event in events
        if _crosses_window(event, window)
    ]
    rows.sort(key=lambda row: (row.start, row.event_id))
    return rows
