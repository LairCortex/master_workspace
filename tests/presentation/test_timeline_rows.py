"""Unit tests for the Qt-free vertical-rows core (W3b 1.1–1.3, W3c 2.1).

The module must import and run without a QApplication — enforced by this file
being plain units (no qtbot, no Qt imports anywhere).
"""
from __future__ import annotations

from datetime import date

from app.presentation.views.timeline_rows import (
    Row,
    RowKind,
    build_rows,
    index_at_y,
    next_event_index,
    normalize_range,
    prev_event_index,
)


class _Ev:
    """Minimal event double: build_rows only reads id/start_date/end_date/name."""

    def __init__(self, eid: int, start: date, end: date | None = None, name: str = "") -> None:
        self.id = eid
        self.start_date = start
        self.end_date = end
        self.name = name or f"event-{eid}"


def _event_ids(rows: list[Row]) -> list[int | None]:
    return [row.event_id for row in rows]


# ── 1.1 module purity ──────────────────────────────────────────────────────

def test_module_imports_without_qt_application():
    """The pure core carries no Qt imports (design D3) and runs plain units."""
    import app.presentation.views.timeline_rows as rows_mod

    source = open(rows_mod.__file__, encoding="utf-8").read()
    assert "PySide6" not in source  # dataclass/typing only (design D3)
    assert build_rows([_Ev(1, date(1200, 1, 1))])  # call needs no QApplication


# ── 1.2 build_rows ─────────────────────────────────────────────────────────

def test_three_day_range_event_empty_event():
    """Spec «Пустой день внутри диапазона»: days 1..3, middle day has none."""
    rows = build_rows(
        [_Ev(1, date(1200, 1, 1)), _Ev(2, date(1200, 1, 3))],
        range_start=date(1200, 1, 1),
        range_end=date(1200, 1, 3),
    )
    assert [r.kind for r in rows] == [RowKind.EVENT, RowKind.EMPTY_DAY, RowKind.EVENT]
    assert [r.date for r in rows] == [date(1200, 1, 1), date(1200, 1, 2), date(1200, 1, 3)]
    assert _event_ids(rows) == [1, None, 2]
    empty = rows[1]
    assert empty.event_id is None and empty.end is None and empty.name == ""
    assert empty.start == date(1200, 1, 2)


def test_multiday_event_occupies_only_its_start_day():
    """Spec «Многодневка стоит на начале»: closed end outside the start day."""
    rows = build_rows([_Ev(7, date(1200, 1, 3), date(1200, 1, 5), name="поход")])
    # Derived range = start..end = 3..5 January; only position 3 is the event.
    assert [r.kind for r in rows] == [
        RowKind.EVENT, RowKind.EMPTY_DAY, RowKind.EMPTY_DAY,
    ]
    event_row = rows[0]
    assert event_row.date == date(1200, 1, 3)
    assert (event_row.start, event_row.end, event_row.name) == (
        date(1200, 1, 3), date(1200, 1, 5), "поход",
    )
    # The closed end day (5th) is present but empty — the event never repeats.
    assert rows[-1].date == date(1200, 1, 5)
    assert rows[-1].kind is RowKind.EMPTY_DAY


def test_sort_is_deterministic_by_start_then_id():
    """Same-day events ordered by id; input order never changes the output."""
    events = [
        _Ev(3, date(1200, 1, 2)),
        _Ev(1, date(1200, 1, 1)),
        _Ev(4, date(1200, 1, 2)),
        _Ev(2, date(1200, 1, 1)),
    ]
    expected = [1, 2, 3, 4]
    assert _event_ids(build_rows(events)) == expected
    assert _event_ids(build_rows(list(reversed(events)))) == expected
    assert build_rows(events) == build_rows(list(reversed(events)))


def test_single_event_range_spans_exactly_its_days():
    """Spec «Одиночное событие»: positions cover start..end and nothing else."""
    rows = build_rows([_Ev(1, date(1200, 1, 3), date(1200, 1, 3))])
    assert len(rows) == 1
    assert rows[0].kind is RowKind.EVENT and rows[0].date == date(1200, 1, 3)

    spanning = build_rows([_Ev(1, date(1200, 1, 3), date(1200, 1, 6))])
    assert [r.date for r in spanning] == [date(1200, 1, d) for d in (3, 4, 5, 6)]
    assert _event_ids(spanning) == [1, None, None, None]


def test_open_end_extends_the_derived_range_to_the_sample_end():
    """An open event contributes its start to max(end|start): the unbounded
    event sits last, so the no-filter range stretches to the sample's end."""
    rows = build_rows([
        _Ev(1, date(1200, 1, 1), date(1200, 1, 3)),
        _Ev(2, date(1200, 1, 9)),  # open end: end=None, latest date in sample
    ])
    assert rows[0].date == date(1200, 1, 1)
    assert rows[-1].date == date(1200, 1, 9)  # past closed end 3rd, up to the open start
    open_row = rows[-1]
    assert open_row.kind is RowKind.EVENT
    assert open_row.event_id == 2 and open_row.end is None  # row keeps "—" open end


def test_empty_sample_with_explicit_range_yields_only_empty_days():
    """Spec «Пустой диапазон фильтра»: filtered window with no events."""
    rows = build_rows(
        [],
        range_start=date(1200, 1, 1),
        range_end=date(1200, 1, 2),
    )
    assert [r.kind for r in rows] == [RowKind.EMPTY_DAY, RowKind.EMPTY_DAY]


def test_no_events_and_no_range_yields_no_rows():
    assert build_rows([]) == []


def test_inverted_explicit_range_yields_no_rows():
    rows = build_rows(
        [_Ev(1, date(1200, 1, 1))],
        range_start=date(1200, 2, 1),
        range_end=date(1200, 1, 1),
    )
    assert rows == []


# ── 1.3 jump helpers ───────────────────────────────────────────────────────

def _rows_with_empty_run() -> list[Row]:
    """Event 0, six empty days, event 7, event 8, one empty day."""
    return build_rows(
        [_Ev(1, date(1200, 1, 1)), _Ev(2, date(1200, 1, 8)), _Ev(3, date(1200, 1, 9))],
        range_start=date(1200, 1, 1),
        range_end=date(1200, 1, 10),
    )
    # indices: 0=EVENT, 1..6=EMPTY ×6, 7=EVENT, 8=EVENT, 9=EMPTY


def test_jump_skips_a_run_of_empty_days():
    rows = _rows_with_empty_run()
    assert prev_event_index(rows, 0) is None
    assert next_event_index(rows, 0) == 7  # over six empty days
    assert prev_event_index(rows, 9) == 8
    assert prev_event_index(rows, 8) == 7
    assert next_event_index(rows, 8) is None
    assert next_event_index(rows, 9) is None  # tail empty day: nothing after


def test_jump_from_edges_is_inert():
    rows = _rows_with_empty_run()
    assert prev_event_index(rows, -1) is None  # nothing before the head
    assert next_event_index(rows, len(rows) - 1) is None  # already at the tail
    assert next_event_index([], 0) is None and prev_event_index([], 0) is None


def test_jump_only_lands_on_event_rows():
    rows = _rows_with_empty_run()
    idx = 0
    for _ in range(3):
        nxt = next_event_index(rows, idx)
        if nxt is None:
            break
        assert rows[nxt].kind is RowKind.EVENT
        assert prev_event_index(rows, nxt) == idx
        idx = nxt
    assert idx == 8  # two hops: 0 → 7 → 8, then no further event


# ── W3c 2.1 rail geometry (design D3) ──────────────────────────────────────

_RAIL_ROW_H = 24  # any fixed height works; the helpers are Qt-free math


def _rail_rows() -> list[Row]:
    """Day Jan 1: two events (idx 0–1); Jan 2: empty (2); Jan 3: three (3–5).

    Day anchors: Jan 1 → 0, Jan 2 → 2, Jan 3 → 3; six rows in total.
    """
    return build_rows(
        [
            _Ev(1, date(1200, 1, 1)), _Ev(2, date(1200, 1, 1)),
            _Ev(3, date(1200, 1, 3)), _Ev(4, date(1200, 1, 3)),
            _Ev(5, date(1200, 1, 3)),
        ],
        range_start=date(1200, 1, 1),
        range_end=date(1200, 1, 3),
    )


def test_index_at_y_normalizes_to_first_row_of_the_day():
    """Spec «Якорь дня с несколькими событиями»: any row of a day → its head."""
    rows = _rail_rows()
    h = _RAIL_ROW_H
    assert index_at_y(rows, h, 0) == 0        # first row of day Jan 1
    assert index_at_y(rows, h, h) == 0        # second row of Jan 1 → its head
    assert index_at_y(rows, h, 2 * h) == 2    # empty Jan 2 is a single row
    assert index_at_y(rows, h, 3 * h) == 3    # head row of Jan 3
    assert index_at_y(rows, h, 4 * h) == 3    # middle of Jan 3 → its head
    assert index_at_y(rows, h, 5 * h) == 3    # last row of Jan 3 → its head
    assert index_at_y(rows, h, 5 * h + h - 1) == 3  # bottom pixel of the tail


def test_index_at_y_clamps_above_zero_and_below_the_tail():
    """Release outside the list lands on the first/last day (W3c risks)."""
    rows = _rail_rows()  # 6 rows, last day Jan 3 anchored at index 3
    assert index_at_y(rows, _RAIL_ROW_H, -1) == 0
    assert index_at_y(rows, _RAIL_ROW_H, -10 ** 6) == 0
    assert index_at_y(rows, _RAIL_ROW_H, 6 * _RAIL_ROW_H) == 3      # one row past
    assert index_at_y(rows, _RAIL_ROW_H, 10 ** 6) == 3              # far below


def test_index_at_y_without_rows_or_height_is_none():
    """Nothing to anchor on: empty rows (any y) or a non-positive height."""
    assert index_at_y([], _RAIL_ROW_H, 0) is None
    assert index_at_y([], _RAIL_ROW_H, -5) is None
    assert index_at_y([], _RAIL_ROW_H, 10 ** 6) is None
    assert index_at_y(_rail_rows(), 0, 0) is None
    assert index_at_y(_rail_rows(), -_RAIL_ROW_H, 0) is None


def test_normalize_range_orders_inverted_pairs_and_keeps_equal_days():
    """Spec «Drag снизу вверх нормализуется» + «Однодневный drag»."""
    early, late = date(1200, 1, 2), date(1200, 1, 9)
    assert normalize_range(early, late) == (early, late)  # top-down unchanged
    assert normalize_range(late, early) == (early, late)  # bottom-up → (min, max)
    assert normalize_range(early, early) == (early, early)  # single-day drag
