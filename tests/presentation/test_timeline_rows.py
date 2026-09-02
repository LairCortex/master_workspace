"""Unit tests for the Qt-free ladder core's surviving date helpers.

redesign-timeline-day-ladder task 8.2 cut the pre-redesign builder together
with its row vocabulary, rail geometry and hit helpers; their W3b–W5 unit
tests retired with them (the ladder contract itself is covered by
``test_timeline_day_ladder.py`` and the widget/e2e suites). What stayed in the
core is calendar arithmetic: the clamp and the duration-preserving span shift
the drop gesture commits through — those plain units live here. The module
must import and run without a QApplication, enforced by this file being plain
units (no qtbot, no Qt imports anywhere).
"""
from __future__ import annotations

from datetime import date

from app.presentation.views.timeline_rows import (
    CALENDAR_MAX,
    CALENDAR_MIN,
    build_rows,
    clamp_calendar,
    translate_span,
)


# ── module purity ─────────────────────────────────────────────────────────

def test_module_imports_without_qt_application():
    """The pure core carries no Qt imports (design D3) and runs plain units."""
    import app.presentation.views.timeline_rows as rows_mod

    source = open(rows_mod.__file__, encoding="utf-8").read()
    assert "PySide6" not in source  # dataclass/typing only (design D3)
    event = type("Ev", (), {})()
    event.id, event.start_date, event.end_date, event.name = (
        1, date(1200, 1, 1), None, "event-1",
    )
    assert build_rows([event])  # the ladder core needs no QApplication


# ── clamp_calendar — the app-calendar clip (W5 1.5 / drop clamp) ───────────

def test_clamp_calendar_pins_to_the_card_calendar_bounds():
    """Bounds match ``CustomDateEdit`` (year 100 … 9999-12-31); no date the
    card cannot display ever leaves the core. Nothing above MAX is
    representable as ``date``, so the upper side is the edge itself — the
    overflow paths (_add_one_year) clamp on their own."""
    assert CALENDAR_MIN == date(100, 1, 1)
    assert CALENDAR_MAX == date(9999, 12, 31)
    assert clamp_calendar(date(99, 12, 31)) == CALENDAR_MIN
    assert clamp_calendar(CALENDAR_MAX) == CALENDAR_MAX
    inside = date(1200, 6, 15)
    assert clamp_calendar(inside) is inside


# ── translate_span — duration-preserving shift of a closed span ─────────────

def test_translate_span_shifts_both_dates_keeping_duration():
    """Spec «Перенос многодневки сохраняет длительность»: 3–10 + 5 → 8–15."""
    start, end = date(1200, 3, 3), date(1200, 3, 10)
    assert translate_span(start, end, 5) == (date(1200, 3, 8), date(1200, 3, 15))
    assert translate_span(start, end, -5) == (date(1200, 2, 27), date(1200, 3, 5))
    for delta in range(-400, 401, 37):
        new_start, new_end = translate_span(start, end, delta)
        assert new_end - new_start == end - start  # shift only, duration intact


def test_translate_span_on_a_single_day_pin_moves_it_around():
    """A closed one-day span (start == end) is still translatable."""
    day = date(1200, 3, 3)
    assert translate_span(day, day, 7) == (date(1200, 3, 10), date(1200, 3, 10))
    assert translate_span(day, day, 0) == (day, day)


def test_translate_span_walks_calendar_boundaries_by_plain_arithmetic():
    """No special month/year/leap rules (spec «без специальных правил»)."""
    assert translate_span(date(1200, 1, 30), date(1200, 2, 2), 2) == (
        date(1200, 2, 1), date(1200, 2, 4),
    )
    assert translate_span(date(2023, 12, 30), date(2024, 1, 2), 3) == (
        date(2024, 1, 2), date(2024, 1, 5),
    )
    assert translate_span(date(2024, 2, 27), date(2024, 3, 1), 1) == (
        date(2024, 2, 28), date(2024, 3, 2),
    )


def test_translate_span_never_inverts_or_clamps():
    """Order is shift-invariant; this layer has no clamp — just the shift."""
    start, end = date(1200, 3, 3), date(1200, 3, 10)
    for delta in (-100000, -10, -1, 0, 1, 10, 100000):
        new_start, new_end = translate_span(start, end, delta)
        assert new_start < new_end  # never inverted, also far in the past
    # No clamp against any model edge: the view decides reachability, the core
    # shifts by exactly the delta, however far. (The drop commit clamps on its
    # own — see ``apply_drop_action``.)
    far_back = translate_span(start, end, -100000)
    assert (start - far_back[0]).days == (end - far_back[1]).days == 100000
