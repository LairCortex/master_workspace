"""Unit tests for the Qt-free timeline core (W3 1.1–1.6).

The module must import and lay out without a QApplication — enforced by this
file running as plain units (no qtbot, no Qt imports anywhere).
"""
from __future__ import annotations

from datetime import date

import pytest

from app.presentation.views.track_layout import (
    BarRect,
    EventSpan,
    TrackMetrics,
    TrackPlan,
    build_plan,
)


# ── 1.1 module purity ──────────────────────────────────────────────────────

def test_module_imports_without_qt_application():
    """The pure core carries no Qt imports (design D2) and runs plain units."""
    import app.presentation.views.track_layout as layout_mod

    source = open(layout_mod.__file__, encoding="utf-8").read()
    assert "PySide6" not in source  # dataclass/typing only (design D2)
    build_plan(_spans((1, date(1200, 1, 1), None)), M)


# ── 1.2 packing ────────────────────────────────────────────────────────────

M = TrackMetrics(viewport_w=400, viewport_h=200)


def _spans(*specs: tuple[int, date, date | None]) -> list[EventSpan]:
    return [EventSpan(eid, s, e) for eid, s, e in specs]


def test_three_mutually_overlapping_events_get_three_lanes():
    spans = _spans(
        (1, date(1200, 1, 1), date(1200, 1, 31)),
        (2, date(1200, 1, 15), date(1200, 2, 15)),
        (3, date(1200, 1, 20), date(1200, 2, 20)),
    )
    plan = build_plan(spans, M)
    assert plan.lane_count == 3
    assert sorted(bar.lane for bar in plan.bars) == [0, 1, 2]
    # No vertical overlap between any two lanes' bars at the same x position.
    for a in plan.bars:
        for b in plan.bars:
            if a.event_id >= b.event_id:
                continue
            overlap_x = a.x0 < b.x1 and b.x0 < a.x1
            overlap_y = a.y_top < b.y_bottom and b.y_top < a.y_bottom
            assert not (overlap_x and overlap_y)


def test_non_overlapping_events_share_one_lane():
    spans = _spans(
        (1, date(1200, 1, 1), date(1200, 1, 10)),
        (2, date(1200, 1, 11), date(1200, 1, 20)),
        (3, date(1200, 2, 1), date(1200, 2, 5)),
    )
    plan = build_plan(spans, M)
    assert plan.lane_count == 1
    assert all(bar.lane == 0 for bar in plan.bars)


def test_plan_is_deterministic_and_order_invariant():
    spans = _spans(
        (3, date(1200, 1, 20), date(1200, 2, 20)),
        (1, date(1200, 1, 1), date(1200, 1, 31)),
        (2, date(1200, 1, 15), date(1200, 2, 15)),
    )
    first = build_plan(spans, M)
    again = build_plan(spans, M)
    shuffled = build_plan(list(reversed(spans)), M)
    assert first == again
    assert (
        sorted(first.bars, key=lambda b: b.event_id)
        == sorted(shuffled.bars, key=lambda b: b.event_id)
    )


def test_duplicate_ids_rejected():
    spans = _spans((1, date(1200, 1, 1), None), (1, date(1200, 2, 1), None))
    with pytest.raises(ValueError, match="duplicate"):
        build_plan(spans, M)


def test_empty_input_yields_empty_plan():
    plan = build_plan([], M)
    assert plan.is_empty
    assert plan.lane_count == 0
    assert plan.hit_test(10, 10) is None
    assert plan.bar_for(1) is None
    assert plan.x_of(date(1200, 1, 1)) == M.padding
    assert plan.event_at_viewport(10, 10, 0) is None
    assert plan.required_scroll(1) == 0.0
    assert plan.content_h == 0.0


# ── 1.3 linear day scale ───────────────────────────────────────────────────

def test_day_is_exactly_one_scale_step():
    # Range Jan 1 .. Apr 1 (March 31 end): a bar starting Feb 1 sits
    # exactly 31 ordinal steps into the inner width.
    spans = _spans(
        (1, date(1200, 1, 1), date(1200, 3, 31)),
        (2, date(1200, 2, 1), date(1200, 4, 1)),
    )
    plan = build_plan(spans, M)
    inner_w = M.viewport_w - 2 * M.padding
    total = (date(1200, 4, 1) - date(1200, 1, 1)).days
    assert plan.range_start == date(1200, 1, 1)
    assert plan.range_end == date(1200, 4, 1)
    bar2 = plan.bar_for(2)
    assert bar2.x0 == pytest.approx(M.padding + 31 / total * inner_w)
    assert bar2.x1 == pytest.approx(plan.inner_right)  # ends at the range end


def test_longest_event_spans_full_inner_width():
    spans = _spans(
        (1, date(1200, 1, 1), date(1200, 12, 31)),
        (2, date(1200, 6, 1), date(1200, 6, 5)),
    )
    plan = build_plan(spans, M)
    longest = plan.bar_for(1)
    assert longest.x0 == M.padding
    assert longest.x1 == pytest.approx(plan.inner_right)


def test_single_event_bar_uses_whole_width():
    spans = _spans((7, date(1200, 5, 15), date(1200, 5, 16)))
    plan = build_plan(spans, M)
    bar = plan.bar_for(7)
    assert bar.x0 == M.padding
    assert bar.x1 == pytest.approx(plan.inner_right)


def test_single_day_event_gets_min_bar_w_centered_symmetrically():
    # One-day event in the exact middle of a wide range: natural width 0,
    # widened symmetrically (equal erosion on both sides of the day position).
    spans = _spans(
        (1, date(1200, 1, 1), date(1200, 12, 31)),
        (2, date(1200, 3, 1), date(1200, 3, 1)),
        (3, date(1200, 6, 1), None),
    )
    plan = build_plan(spans, M)
    bar = plan.bar_for(2)
    day_x = plan.x_of(date(1200, 3, 1))
    assert bar.width == pytest.approx(M.min_bar_w)
    assert (bar.x0 + bar.x1) / 2 == pytest.approx(day_x)


def test_min_width_widening_clamped_at_both_margins():
    # Day events on the closing range day: the widened bar must stay inside
    # the padding margins (right-side clamp of the symmetric widening).
    spans = _spans(
        (1, date(1200, 1, 1), date(1200, 12, 31)),
        (2, date(1200, 12, 31), date(1200, 12, 31)),
        (3, date(1200, 1, 1), date(1200, 1, 1)),
    )
    plan = build_plan(spans, M)
    right = plan.bar_for(2)
    left = plan.bar_for(3)
    assert right.x1 == pytest.approx(plan.inner_right)
    assert left.x0 == pytest.approx(M.padding)
    assert right.width >= M.min_bar_w
    assert left.width >= M.min_bar_w


# ── 1.4 open-ended events ──────────────────────────────────────────────────

def test_open_event_bar_reaches_right_edge_with_flag():
    spans = _spans(
        (1, date(1200, 1, 1), date(1200, 6, 30)),
        (2, date(1200, 3, 1), None),
    )
    plan = build_plan(spans, M)
    bar = plan.bar_for(2)
    assert bar.open_end is True
    assert bar.x1 == pytest.approx(plan.inner_right)  # inner right edge
    assert plan.bar_for(1).open_end is False


# ── 1.5 vertical density + text fit ────────────────────────────────────────

def _many_lanes(n: int, viewport_h: float) -> TrackPlan:
    # n pairwise-overlapping spans on one day → n lanes.
    spans = _spans(*[(i, date(1200, 1, 1), date(1200, 1, 2)) for i in range(n)])
    return build_plan(spans, TrackMetrics(viewport_w=400, viewport_h=viewport_h))


def test_lane_height_clamped_to_max_when_few_lanes():
    plan = _many_lanes(1, viewport_h=200)  # (200−18)/1 − 4 = 178 > MAX
    assert plan.lane_h == M.max_lane_h


def test_lane_height_adaptive_between_clamps():
    # 5 lanes, viewport 200: (200−18)/5 − 4 = 32.4 > MAX → max clamp; pick a
    # height where the formula lands inside (14, 26): 8 lanes → (182)/8 − 4 = 18.75.
    plan = _many_lanes(8, viewport_h=200)
    assert M.min_lane_h < plan.lane_h < M.max_lane_h
    assert plan.lane_h == pytest.approx((200 - M.axis_h) / 8 - M.lane_gap)


def test_lane_height_min_and_content_overflows_to_scroll():
    plan = _many_lanes(20, viewport_h=200)
    assert plan.lane_h == M.min_lane_h
    lane_viewport_h = 200 - M.axis_h
    assert plan.content_h > lane_viewport_h  # overflow → scrollable
    assert plan.max_scroll == pytest.approx(plan.content_h - lane_viewport_h)


def test_tiny_viewport_lane_viewport_floors_at_zero():
    plan = _many_lanes(1, viewport_h=10)  # viewport smaller than the axis
    assert plan.lane_viewport_h == 0.0
    # (0 − gap) clamps up to MIN, and MIN ≤ MAX keeps the result at MIN.
    assert plan.lane_h == M.min_lane_h


def test_text_fit_requires_width_and_lane_height():
    spans = _spans(
        (1, date(1200, 1, 1), date(1200, 12, 31)),  # full width
        (2, date(1200, 1, 1), date(1200, 1, 2)),  # tiny bar
    )
    plan = build_plan(spans, M, text_widths={1: 60.0, 2: 60.0})
    assert plan.bar_for(1).text_fits is True
    assert plan.bar_for(2).text_fits is False


def test_text_fit_unknown_or_missing_width_never_fits():
    spans = _spans((1, date(1200, 1, 1), date(1200, 12, 31)))
    plan_default = build_plan(spans, M)  # no widths at all
    plan_missing = build_plan(spans, M, text_widths={99: 10.0})
    assert plan_default.bar_for(1).text_fits is False
    assert plan_missing.bar_for(1).text_fits is False


def test_text_hidden_when_lane_below_min_text_height():
    # 30 lanes with an MIN lowered to 8 (below a MIN_TEXT_H of 10): the bars
    # are wide enough but the lane is too short — text must not fit.
    spans = _spans(*[(i, date(1200, 1, 1), date(1200, 1, 2)) for i in range(30)])
    tight = build_plan(
        spans,
        TrackMetrics(viewport_w=400, viewport_h=200, min_lane_h=8.0, min_text_h=10.0),
        text_widths={i: 10.0 for i in range(30)},
    )
    assert tight.lane_h == 8.0
    assert all(bar.text_fits is False for bar in tight.bars)


# ── 1.6 hit-test + scroll mapping ──────────────────────────────────────────

def test_hit_test_topmost_bar_wins_and_gaps_miss():
    spans = _spans(
        (1, date(1200, 1, 1), date(1200, 6, 30)),
        (2, date(1200, 3, 1), date(1200, 9, 30)),
    )
    plan = build_plan(spans, M)
    bar1 = plan.bar_for(1)
    bar2 = plan.bar_for(2)
    assert plan.hit_test((bar1.x0 + bar1.x1) / 2, bar1.y_top + 1) == 1
    assert plan.hit_test((bar2.x0 + bar2.x1) / 2, bar2.y_top + 1) == 2
    # Between lanes (the vertical gap) → no hit.
    gap_y = bar1.y_bottom + M.lane_gap / 2
    assert plan.hit_test((bar1.x0 + bar1.x1) / 2, gap_y) is None
    # Right of all bars → no hit.
    assert plan.hit_test(plan.inner_right + 1, bar1.y_top + 1) is None


def test_hit_test_inside_a_lane_prefers_the_bar_painted_on_top():
    # First-fit only keeps DATE ranges apart inside a lane; widening a
    # sub-pixel bar to min_bar_w can then push it sideways into the neighbor
    # bar of the same lane. The renderer paints in (start, id) order, so the
    # later bar is the visible one — the hit must agree with the paint
    # (spec: «при пересечении полос попадание доставается полосе, нарисованной поверх»).
    spans = _spans(
        (1, date(1200, 1, 1), date(1200, 6, 1)),  # ~half a year, lane 0
        (2, date(1200, 6, 2), date(1200, 6, 2)),  # one day → widened, same lane
    )
    plan = build_plan(spans, M)
    long_bar, short_bar = plan.bar_for(1), plan.bar_for(2)
    assert short_bar.lane == long_bar.lane == 0
    assert short_bar.x0 < long_bar.x1  # the widening really created an overlap
    inside_overlap = (short_bar.x0 + long_bar.x1) / 2.0
    lane_y = long_bar.y_top + long_bar.height / 2.0
    assert plan.hit_test(inside_overlap, lane_y) == 2  # topmost, not the lower
    assert plan.hit_test(long_bar.x0 + 1.0, lane_y) == 1  # left of the overlap


def test_hit_test_boundaries_are_inclusive():
    spans = _spans((1, date(1200, 1, 1), date(1200, 12, 31)))
    plan = build_plan(spans, M)
    bar = plan.bar_for(1)
    assert plan.hit_test(bar.x0, bar.y_top) == 1
    assert plan.hit_test(bar.x1, bar.y_bottom) == 1
    bar_width_probe = BarRect(1, 0, 10, 0, 5, 0, False, False)
    assert bar_width_probe.width == 10


def test_event_at_viewport_maps_visible_y_through_scroll():
    plan = _many_lanes(20, viewport_h=100)
    bar = plan.bar_for(0)
    # The bar sits at content y=0..lane_h; at scroll 0 it is visible right
    # below the axis; scrolled past it is not.
    assert plan.event_at_viewport(200, 1.0, 0.0) == 0
    assert plan.event_at_viewport(200, 1.0, bar.y_bottom + 1) is None
    # Points above the axis / below the lane area never hit.
    assert plan.event_at_viewport(200, -1, 0.0) is None
    assert plan.event_at_viewport(200, plan.lane_viewport_h + 1, 0.0) is None


def test_scroll_to_bring_offscreen_bar_into_view():
    plan = _many_lanes(20, viewport_h=100)
    lane_viewport_h = plan.lane_viewport_h
    # Last lane is far below the view at scroll 0.
    last = plan.bars[-1]
    assert last.y_top > lane_viewport_h
    scroll = plan.required_scroll(last.event_id, current_scroll=0.0)
    assert scroll > 0
    # After scrolling it is now hit-testable at the bottom of the viewport.
    visible_y = last.y_bottom - scroll - 0.5
    assert plan.event_at_viewport(200, visible_y, scroll) == last.event_id
    # Already-visible bar keeps the current offset.
    assert plan.required_scroll(0, current_scroll=0.0) == 0.0
    # Scrolled past the first bar → scroll-to pulls the view back up to it.
    assert plan.required_scroll(0, current_scroll=plan.max_scroll) == 0.0
    # Unknown id clamps the current scroll instead of jumping.
    assert plan.required_scroll(9999, current_scroll=5000.0) == plan.max_scroll
    assert plan.required_scroll(9999, current_scroll=-5.0) == 0.0


def test_clamped_scroll_range():
    plan = _many_lanes(20, viewport_h=100)
    assert plan.clamped_scroll(-10) == 0.0
    assert plan.clamped_scroll(10**6) == plan.max_scroll


def test_ticks_are_month_boundaries_only():
    spans = _spans((1, date(1200, 1, 15), date(1200, 4, 2)))
    plan = build_plan(spans, M)
    # The range start is the left edge of the scale, not a month boundary, and
    # never stands in for one (spec «Шкала времени»: подписи/разделители — на
    # границах месяцев; design D6).
    assert plan.ticks == (date(1200, 2, 1), date(1200, 3, 1), date(1200, 4, 1))


def test_range_start_on_a_month_border_is_ticked():
    spans = _spans((1, date(1200, 1, 1), date(1200, 2, 10)))
    plan = build_plan(spans, M)
    # Jan 1 IS a calendar boundary inside the range → it does get a tick.
    assert plan.ticks == (date(1200, 1, 1), date(1200, 2, 1))


def test_sub_month_range_has_no_ticks_but_still_maps_dates():
    spans = _spans((1, date(1200, 1, 10), date(1200, 1, 20)))
    plan = build_plan(spans, M)
    assert plan.ticks == ()
    assert plan.x_of(date(1200, 1, 15)) > M.padding


def test_month_tick_year_rollover():
    spans = _spans((1, date(1199, 10, 1), date(1200, 2, 1)))
    plan = build_plan(spans, M)
    assert date(1200, 1, 1) in plan.ticks


def test_plan_defaults_on_empty_reuse_via_construction():
    plan = TrackPlan(bars=(), metrics=M, lane_count=0, lane_h=0.0, content_h=0.0)
    assert plan.range_start is None
    assert plan.ticks == ()
