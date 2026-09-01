"""Unit tests for the Qt-free vertical-rows core (W3b 1.1–1.3, W3c 2.1, W4 3.1–3.5).

The module must import and run without a QApplication — enforced by this file
being plain units (no qtbot, no Qt imports anywhere).
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.presentation.views.timeline_rows import (
    BRACKET_MAX_LANES,
    NO_GROUP_KEY,
    Row,
    RowKind,
    ScaleUnit,
    bracket_lanes,
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


# ── W4 3.1 scale ladder vocabulary (design D1) ──────────────────────────────

def test_scale_unit_and_row_kind_vocabulary():
    """ScaleUnit carries the three ladder rungs; RowKind the four row kinds."""
    assert [u.value for u in ScaleUnit] == ["day", "month", "year"]
    assert [k.value for k in RowKind] == ["event", "empty_day", "unit", "section"]


def test_row_new_fields_defaults_and_explicit_values():
    """W4 fields are additive: every old construction site keeps its defaults."""
    plain = Row(kind=RowKind.EVENT, date=date(1200, 1, 1))
    assert plain.unit is ScaleUnit.DAY
    assert (plain.unit_count, plain.group_key, plain.token_key) == (None, None, None)

    month_row = Row(
        kind=RowKind.UNIT, date=date(1200, 3, 1), unit=ScaleUnit.MONTH,
        unit_count=4, group_key="Анна", token_key="color.chart.2",
    )
    assert month_row.unit is ScaleUnit.MONTH
    assert month_row.unit_count == 4
    assert month_row.group_key == "Анна"
    assert month_row.token_key == "color.chart.2"


class _TypedEv(_Ev):
    """Event double carrying a duck-typed event_type with a palette index."""

    def __init__(self, eid, start, end=None, name="", color_index=None):
        super().__init__(eid, start, end, name)
        self.event_type = None if color_index is None else SimpleNamespace(color_index=color_index)


def test_build_rows_accepts_unit_and_groups_kwargs_with_day_defaults():
    """The old positional call is bit-for-bit the DAY output."""
    events = [_Ev(1, date(1200, 1, 1)), _Ev(2, date(1200, 1, 3))]
    legacy = build_rows(events)
    assert build_rows(events, unit=ScaleUnit.DAY) == legacy
    assert build_rows(events, unit=ScaleUnit.DAY, groups=None) == legacy


def test_event_rows_carry_token_key_from_duck_typed_event_type():
    """D5: EVENT rows mirror «color.chart.N»; untyped and non-event rows → None."""
    rows = build_rows([
        _TypedEv(1, date(1200, 1, 1), color_index=3),
        _TypedEv(2, date(1200, 1, 2)),
    ])
    by_id = {r.event_id: r for r in rows}
    assert by_id[1].token_key == "color.chart.3"
    assert by_id[2].token_key is None
    units = build_rows([_Ev(1, date(1200, 1, 1), date(1200, 3, 1))], unit=ScaleUnit.MONTH)
    assert all(r.token_key is None for r in units)


# ── W4 3.2 MONTH/YEAR rollout (unit × фильтр × пустой день) ─────────────────

def test_month_window_lists_every_unit_including_empty_stubs():
    """Spec «Пустой месяц на ступени месяца»: all units stay positions."""
    rows = build_rows(
        [_Ev(1, date(1200, 1, 5), date(1200, 1, 6)), _Ev(2, date(1200, 3, 10))],
        unit=ScaleUnit.MONTH,
    )
    assert [r.kind for r in rows] == [RowKind.UNIT] * 3
    assert [r.date for r in rows] == [date(1200, 1, 1), date(1200, 2, 1), date(1200, 3, 1)]
    assert [r.unit_count for r in rows] == [1, 0, 1]  # February is the stub
    assert all(r.unit is ScaleUnit.MONTH for r in rows)
    assert all(r.event_id is None and r.group_key is None for r in rows)


def test_year_window_lists_every_year_including_empty_stubs():
    rows = build_rows(
        [_Ev(1, date(1240, 6, 1), date(1240, 6, 2)), _Ev(2, date(1243, 1, 1))],
        unit=ScaleUnit.YEAR,
    )
    assert [r.date for r in rows] == [date(y, 1, 1) for y in (1240, 1241, 1242, 1243)]
    assert [r.unit_count for r in rows] == [1, 0, 0, 1]
    assert all(r.unit is ScaleUnit.YEAR for r in rows)


def test_event_hits_every_touched_unit_by_span_intersection():
    """Task 3.2 intersection: Feb 20 … Apr 10 touches February through April."""
    rows = build_rows(
        [_Ev(9, date(1200, 2, 20), date(1200, 4, 10))],
        range_start=date(1200, 2, 1),
        range_end=date(1200, 4, 30),
        unit=ScaleUnit.MONTH,
    )
    assert [r.unit_count for r in rows] == [1, 1, 1]  # Feb, Mar, Apr all touched


def test_unit_window_edges_align_to_unit_boundaries():
    """Derived bounds align to units: an event on the 15th anchors on day 1."""
    rows = build_rows([_Ev(1, date(1200, 1, 15), date(1200, 1, 20))], unit=ScaleUnit.MONTH)
    assert [(r.kind, r.date) for r in rows] == [(RowKind.UNIT, date(1200, 1, 1))]

    years = build_rows([_Ev(1, date(1245, 7, 1))], unit=ScaleUnit.YEAR)
    assert [(r.kind, r.date) for r in years] == [(RowKind.UNIT, date(1245, 1, 1))]


def test_open_end_anchor_is_the_window_end():
    """Task 3.2 «якорь открытого конца — конец окна»: the open span paints
    through the very last unit of the window, no synthetic future."""
    rows = build_rows(
        [_Ev(1, date(1200, 1, 10), None)],
        range_start=date(1200, 1, 1),
        range_end=date(1200, 4, 1),
        unit=ScaleUnit.MONTH,
    )
    assert [r.unit_count for r in rows] == [1, 1, 1, 1]

    # Without a filter the open event stretches the window only to its start.
    derived = build_rows(
        [_Ev(1, date(1200, 11, 10), None)],
        unit=ScaleUnit.MONTH,
    )
    assert [(r.date, r.unit_count) for r in derived] == [(date(1200, 11, 1), 1)]


def test_month_empty_sample_with_filter_is_all_stubs():
    """Matrix cell (MONTH × filter × empty): every filtered month is a stub."""
    rows = build_rows(
        [],
        range_start=date(1200, 3, 5),
        range_end=date(1200, 5, 20),
        unit=ScaleUnit.MONTH,
    )
    assert [r.kind for r in rows] == [RowKind.UNIT] * 3
    assert [r.unit_count for r in rows] == [0, 0, 0]


def test_unit_rungs_keep_derivation_guards():
    """Same edges as DAY: no events and no bounds → [], inverted bounds → []."""
    assert build_rows([], unit=ScaleUnit.MONTH) == []
    assert build_rows([], unit=ScaleUnit.YEAR) == []
    assert build_rows(
        [_Ev(1, date(1200, 1, 1))],
        range_start=date(1200, 5, 1),
        range_end=date(1200, 1, 1),
        unit=ScaleUnit.MONTH,
    ) == []


def test_filter_window_smaller_than_a_unit_still_occupies_the_full_unit():
    """The May 5–20 filter enumerates May as one anchored unit position."""
    rows = build_rows(
        [_Ev(1, date(1200, 5, 10))],
        range_start=date(1200, 5, 5),
        range_end=date(1200, 5, 20),
        unit=ScaleUnit.MONTH,
    )
    assert [(r.kind, r.date, r.unit_count) for r in rows] == [
        (RowKind.UNIT, date(1200, 5, 1), 1)
    ]


# ── W4 3.3 sectioning & DAY grouping order ──────────────────────────────────

def _grouped_events():
    """Анна: Jan + Mar, Борис: Jan + Feb, id 4: no group, closed Jan15…Mar15."""
    events = [
        _Ev(1, date(1200, 1, 5), date(1200, 1, 6)),
        _Ev(2, date(1200, 2, 5), date(1200, 2, 6)),
        _Ev(3, date(1200, 3, 5), date(1200, 3, 6)),
        _Ev(4, date(1200, 1, 15), date(1200, 3, 15)),  # closed span, ungrouped
    ]
    groups = {1: ("Борис", "Анна"), 2: ("Борис",), 3: ("Анна",)}
    return events, groups


def test_section_headers_alphabetical_no_group_last():
    """Spec «Порядок секций»: alphabetical, «Без привязки» always last."""
    events, groups = _grouped_events()
    rows = build_rows(
        events, range_start=date(1200, 1, 1), range_end=date(1200, 3, 31),
        unit=ScaleUnit.MONTH, groups=groups,
    )
    heads = [r for r in rows if r.kind is RowKind.SECTION]
    assert [h.group_key for h in heads] == ["Анна", "Борис", NO_GROUP_KEY]
    assert all(r.kind is not RowKind.SECTION or r.unit is ScaleUnit.MONTH for r in rows)


def test_section_contains_only_units_it_touched():
    """Spec «Пустой месяц не показан в секции»: a section skips its empty units."""
    events, groups = _grouped_events()
    rows = build_rows(
        events, range_start=date(1200, 1, 1), range_end=date(1200, 3, 31),
        unit=ScaleUnit.MONTH, groups=groups,
    )
    by_section: dict[str | None, list[Row]] = {}
    current = None
    for row in rows:
        if row.kind is RowKind.SECTION:
            current = row.group_key
            by_section[current] = []
        else:
            by_section[current].append(row)
    # Анна: events on Jan (id 1) and Mar (id 3) — February is not hers.
    assert [r.date for r in by_section["Анна"]] == [date(1200, 1, 1), date(1200, 3, 1)]
    assert [r.unit_count for r in by_section["Анна"]] == [1, 1]
    # Борис: Jan + Feb only.
    assert [r.date for r in by_section["Борис"]] == [date(1200, 1, 1), date(1200, 2, 1)]
    # «Без привязки»: the ungrouped event spans Jan…Mar.
    assert [r.unit_count for r in by_section[NO_GROUP_KEY]] == [1, 1, 1]
    # Every UNIT row repeats the group_key of its section.
    for name, unit_rows in by_section.items():
        assert all(r.group_key == name for r in unit_rows)


def test_event_duplicated_into_every_linked_section():
    """Spec «Событие в двух секциях»: one double-linked event is in both counts."""
    rows = build_rows(
        [_Ev(1, date(1200, 1, 5))],
        range_start=date(1200, 1, 1), range_end=date(1200, 1, 31),
        unit=ScaleUnit.MONTH, groups={1: ("Алиса", "Боб")},
    )
    units = [r for r in rows if r.kind is RowKind.UNIT]
    assert [(r.group_key, r.unit_count) for r in units] == [("Алиса", 1), ("Боб", 1)]
    # No ungrouped events at all → no «Без привязки» section.
    assert not [r for r in rows if r.group_key == NO_GROUP_KEY]


def test_no_group_literal_in_groups_collapses_into_the_no_group_section():
    """The VM may hand over the literal key; the core still normalizes it."""
    rows = build_rows(
        [_Ev(1, date(1200, 1, 5))],
        range_start=date(1200, 1, 1), range_end=date(1200, 1, 31),
        unit=ScaleUnit.MONTH, groups={1: (NO_GROUP_KEY,)},
    )
    assert [r.group_key for r in rows] == [NO_GROUP_KEY, NO_GROUP_KEY]


def test_day_grouping_orders_by_has_group_name_then_start_id():
    """Spec «Сутки остаются хронологией» + order (has_group, group_name, start, id)."""
    events = [
        _Ev(1, date(1200, 1, 1)),                      # unlinked
        _Ev(2, date(1200, 1, 1), name="Борисов"),      # linked «Борис»
        _Ev(3, date(1200, 1, 1), name="Анин"),         # linked «Анна»
        _Ev(4, date(1200, 1, 2)),                      # unlinked, later day
        _Ev(5, date(1200, 1, 2), name="Анин2"),        # linked «Анна», later day
    ]
    groups = {2: ("Борис",), 3: ("Анна",), 5: ("Анна",)}
    rows = build_rows(
        events, range_start=date(1200, 1, 1), range_end=date(1200, 1, 2),
        groups=groups,
    )
    # Days stay chronological; inside Jan: Анна(3), Борис(2), unlinked(1).
    assert [(r.kind, r.date, r.event_id) for r in rows] == [
        (RowKind.EVENT, date(1200, 1, 1), 3),
        (RowKind.EVENT, date(1200, 1, 1), 2),
        (RowKind.EVENT, date(1200, 1, 1), 1),
        (RowKind.EVENT, date(1200, 1, 2), 5),
        (RowKind.EVENT, date(1200, 1, 2), 4),
    ]
    assert not any(r.kind in (RowKind.SECTION, RowKind.UNIT) for r in rows)


def test_day_sectionless_even_when_grouping_is_on():
    """DAY + groups never produces SECTION/UNIT rows (sectioning is MONTH/YEAR)."""
    rows = build_rows([_Ev(1, date(1200, 1, 1), date(1200, 1, 3))], groups={1: ("Анна",)})
    assert [r.kind for r in rows] == [RowKind.EVENT, RowKind.EMPTY_DAY, RowKind.EMPTY_DAY]


# ── W4 3.4 bracket_lanes in the core, unit mode (moved from the widget) ─────

def test_day_bracket_lanes_packing_is_unchanged():
    """The moved DAY packer: one-day spans own no lane, overlaps split lanes."""
    closed_one_day = _Ev(1, date(1200, 1, 1), date(1200, 1, 1))
    assert bracket_lanes([closed_one_day], date(1200, 1, 5)) == {}  # closed one day
    assert bracket_lanes([_Ev(1, date(1200, 1, 1))], None) == {}    # no window
    lanes = bracket_lanes(
        [
            _Ev(1, date(1200, 1, 1), date(1200, 1, 4)),
            _Ev(2, date(1200, 1, 2), date(1200, 1, 5)),   # overlaps 1 → lane 1
            _Ev(3, date(1200, 1, 6), date(1200, 1, 8)),   # lane 0 is free again
        ],
        date(1200, 1, 8),
    )
    assert lanes == {1: 0, 2: 1, 3: 0}


def test_month_span_brackets_across_all_touched_months():
    """Spec «Скобка через месяцы»: Feb 20 … Apr 10 owns a bracket on MONTH."""
    lanes = bracket_lanes(
        [_Ev(1, date(1200, 2, 20), date(1200, 4, 10))],
        date(1200, 4, 30),
        unit=ScaleUnit.MONTH,
    )
    assert lanes == {1: 0}

    # A span inside one month owns no lane (the unit tick already marks it)…
    assert bracket_lanes(
        [_Ev(2, date(1200, 2, 5), date(1200, 2, 27))],
        date(1200, 4, 30),
        unit=ScaleUnit.MONTH,
    ) == {}


def test_month_bracket_lanes_wrap_around_and_honor_open_end():
    """Оборот дорожек + открытый конец: five overlapping month-spans cycle lanes."""
    events = [_Ev(i, date(1200, 1, 15), date(1200, 3, 15)) for i in range(1, 6)]
    lanes = bracket_lanes(events, date(1200, 6, 1), unit=ScaleUnit.MONTH)
    assert list(lanes.values()) == [0, 1, 2, 3, 0]
    assert BRACKET_MAX_LANES == 4

    # Open end: the anchor is the window's end, so Feb…(Jun) brackets; a window
    # ending inside the start month produces a single-unit span → no lane.
    assert bracket_lanes([_Ev(7, date(1200, 2, 10), None)], date(1200, 6, 3),
                         unit=ScaleUnit.MONTH) == {7: 0}
    assert bracket_lanes([_Ev(7, date(1200, 2, 10), None)], date(1200, 2, 25),
                         unit=ScaleUnit.MONTH) == {}


def test_year_bracket_lanes_bridge_years():
    """A span Dec 1244 … Jan 1246 bridges years on the YEAR rung."""
    lanes = bracket_lanes(
        [_Ev(1, date(1244, 12, 20), date(1246, 1, 5))],
        date(1246, 1, 31),
        unit=ScaleUnit.YEAR,
    )
    assert lanes == {1: 0}
    # Same YEAR span seen through MONTH lanes touches 3 months (brackets too).
    assert bracket_lanes(
        [_Ev(1, date(1244, 12, 20), date(1246, 1, 5))],
        date(1246, 1, 31),
        unit=ScaleUnit.MONTH,
    ) == {1: 0}


# ── W4 3.5 helpers against the new row model (equal-height contract) ────────

def test_month_rows_expose_no_event_targets_to_jump_helpers():
    """«На MONTH нет EVENT-строк → хелперы не выдают event-цели»."""
    rows = build_rows(
        [_Ev(1, date(1200, 1, 5), date(1200, 1, 6)), _Ev(2, date(1200, 3, 5))],
        unit=ScaleUnit.MONTH,
    )
    assert all(r.kind is RowKind.UNIT for r in rows)
    assert prev_event_index(rows, len(rows)) is None
    assert next_event_index(rows, -1) is None
    assert prev_event_index(rows, 1) is None
    assert next_event_index(rows, 0) is None


def test_index_at_y_on_month_maps_units_one_row_each():
    """Equal-height contract: on MONTH unit rows are single — y // h directly."""
    rows = build_rows(
        [_Ev(1, date(1200, 1, 5), date(1200, 1, 6)), _Ev(2, date(1200, 4, 5))],
        unit=ScaleUnit.MONTH,
    )
    h = _RAIL_ROW_H
    assert index_at_y(rows, h, 0) == 0        # January
    assert index_at_y(rows, h, h) == 1        # the empty February stub…
    assert index_at_y(rows, h, 2 * h) == 2    # …through April
    assert index_at_y(rows, h, 10 ** 6) == 3  # clamps onto the last unit


def test_normalize_range_passes_unit_anchors_through():
    """Unit rungs feed month anchors into the same pair ordering (W4 D3)."""
    march, may = date(1200, 3, 1), date(1200, 5, 1)
    assert normalize_range(may, march) == (march, may)
