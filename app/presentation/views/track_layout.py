"""Pure geometry core of the event timeline (W3 D2) — no Qt imports.

Input: event spans ``(event_id, start, end|None)`` plus a `TrackMetrics`
viewport description. Output: a `TrackPlan` — lane-packed bar rects, text-fit
flags, lane count, content/scroll heights, month-boundary ticks. All math is
deterministic so the same event set always yields the identical plan (the
spec's "детерминированная раскладка" scenario), and hit-test / scroll mapping
are plain data operations testable without a QApplication.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Mapping, Sequence


#: Horizontal size (logical px) of the open-end arrow marker painted by the
#: renderer at a bar's right edge (the geometry core does not draw it).
SKEW_W = 7.0


def _next_month_start(d: date) -> date:
    """First day of the month following ``d``'s month (year rollover safe)."""
    total = d.year * 12 + d.month
    return date(total // 12, total % 12 + 1, 1)


@dataclass(frozen=True)
class EventSpan:
    """One event's placement input: id plus its (possibly open) date range."""

    event_id: int
    start: date
    end: date | None


@dataclass(frozen=True)
class TrackMetrics:
    """Viewport size plus every geometry constant the layout respects."""

    viewport_w: float
    viewport_h: float
    axis_h: float = 18.0
    padding: float = 8.0
    lane_gap: float = 4.0
    min_lane_h: float = 14.0
    max_lane_h: float = 26.0
    min_text_h: float = 13.0
    min_bar_w: float = 10.0
    text_inset: float = 8.0


@dataclass(frozen=True)
class BarRect:
    """A packed bar in lane-area content coordinates (y=0 at the axis bottom)."""

    event_id: int
    x0: float
    x1: float
    y_top: float
    height: float
    lane: int
    text_fits: bool
    open_end: bool

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def y_bottom(self) -> float:
        return self.y_top + self.height

    def contains(self, x: float, y: float) -> bool:
        """True if a content point lies on the bar (inclusive edges)."""
        return self.x0 <= x <= self.x1 and self.y_top <= y <= self.y_bottom


@dataclass(frozen=True)
class TrackPlan:
    """Immutable layout result: bars, scale mapping, vertical metrics, ticks."""

    bars: tuple[BarRect, ...]
    metrics: TrackMetrics
    lane_count: int
    lane_h: float
    content_h: float
    range_start: date | None = None
    range_end: date | None = None
    ticks: tuple[date, ...] = ()
    _bar_by_id: Mapping[int, BarRect] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        # frozen dataclass: bypass __setattr__ to install the id→bar lookup.
        object.__setattr__(self, "_bar_by_id", {bar.event_id: bar for bar in self.bars})

    @property
    def is_empty(self) -> bool:
        return not self.bars

    @property
    def lane_viewport_h(self) -> float:
        """Height available to the lane area (viewport minus the axis strip)."""
        return max(0.0, self.metrics.viewport_h - self.metrics.axis_h)

    @property
    def max_scroll(self) -> float:
        """Largest legal vertical scroll offset for the lane area."""
        return max(0.0, self.content_h - self.lane_viewport_h)

    @property
    def inner_right(self) -> float:
        """Right edge of the bar drawing area (inside the padding)."""
        return self.metrics.viewport_w - self.metrics.padding

    def bar_for(self, event_id: int) -> BarRect | None:
        return self._bar_by_id.get(event_id)

    def x_of(self, d: date) -> float:
        """Linear map: the sample range spans exactly the inner width (W3 D2)."""
        m = self.metrics
        if self.range_start is None or self.range_end is None:
            return m.padding
        total_days = max(1, (self.range_end - self.range_start).days)
        frac = (d - self.range_start).days / total_days
        inner_w = max(0.0, m.viewport_w - 2 * m.padding)
        return m.padding + frac * inner_w

    def hit_test(self, x: float, content_y: float) -> int | None:
        """Event id of the bar painted on top at a lane-area content point.

        The renderer paints ``bars`` in ``(start, id)`` order, so among the
        bars containing the point the last one is on top — and containing
        overlaps do happen inside a lane: the ``min_bar_w`` widening pushes a
        short bar sideways into its neighbor. The topmost bar therefore wins
        (spec: «при пересечении полос попадание доставается полосе,
        нарисованной поверх»).
        """
        for bar in reversed(self.bars):
            if bar.contains(x, content_y):
                return bar.event_id
        return None

    def event_at_viewport(self, x: float, visible_y: float, scroll_y: float) -> int | None:
        """Hit-test a lane-area viewport point (``visible_y`` measured below the axis)."""
        if not 0.0 <= visible_y <= self.lane_viewport_h:
            return None
        return self.hit_test(x, visible_y + scroll_y)

    def required_scroll(self, event_id: int, current_scroll: float = 0.0) -> float:
        """Smallest adjustment of ``current_scroll`` that brings the bar fully into view.

        A bar that is already visible keeps the current offset (scroll-to
        never jumps when there is nothing to reveal).
        """
        bar = self._bar_by_id.get(event_id)
        if bar is None:
            return self.clamped_scroll(current_scroll)
        view = self.lane_viewport_h
        scroll = current_scroll
        if bar.y_top < scroll:
            scroll = bar.y_top
        if bar.y_bottom > scroll + view:
            scroll = bar.y_bottom - view
        return self.clamped_scroll(scroll)

    def clamped_scroll(self, scroll: float) -> float:
        """Clip a scroll offset into the legal ``[0, max_scroll]`` range."""
        return min(max(0.0, scroll), self.max_scroll)


def build_plan(
    spans: Sequence[EventSpan],
    metrics: TrackMetrics,
    text_widths: Mapping[int, float] | None = None,
) -> TrackPlan:
    """Pack ``spans`` into lanes and lay the whole plan out.

    Packing: sort by ``(start, event_id)`` then greedy first-fit per lane (a
    bar joins the first lane whose previous bar ends at or before its start) —
    deterministic for an unchanged event set regardless of input order.

    ``text_widths`` maps event id → measured label width (the caller supplies
    it through Qt's QFontMetrics; this module stays Qt-free). A bar whose text
    width is unknown never claims text fit.
    """
    ids = {span.event_id for span in spans}
    if len(ids) != len(spans):
        raise ValueError("duplicate event ids in track spans")
    if not spans:
        return TrackPlan(bars=(), metrics=metrics, lane_count=0, lane_h=0.0, content_h=0.0)

    ordered = sorted(spans, key=lambda s: (s.start, s.event_id))
    range_start = min(s.start for s in ordered)
    # Open spans contribute only their start: their bar runs to the right
    # edge of the area, not to some synthetic far-future date.
    range_end = max(s.end if s.end is not None else s.start for s in ordered)

    # Greedy first-fit. A closed bar occupies its lane through its end day;
    # the next admissible start is the ordinal after that last covered step.
    lane_last_free: list[int] = []  # per lane: first start ordinal NOT overlapping
    lanes: list[int] = []
    for span in ordered:
        start_ord = span.start.toordinal()
        # Steps the bar spans on the day scale; open bars run to the range end.
        if span.end is None:
            occupied_until = range_end.toordinal() + 1
        else:
            occupied_until = span.end.toordinal() + 1
        for lane_idx, first_free in enumerate(lane_last_free):
            if start_ord >= first_free:
                lanes.append(lane_idx)
                lane_last_free[lane_idx] = occupied_until
                break
        else:
            lanes.append(len(lane_last_free))
            lane_last_free.append(occupied_until)

    lane_count = len(lane_last_free)
    lane_viewport_h = max(0.0, metrics.viewport_h - metrics.axis_h)
    lane_h = min(
        metrics.max_lane_h,
        max(metrics.min_lane_h, lane_viewport_h / lane_count - metrics.lane_gap),
    )
    content_h = lane_count * lane_h + max(0, lane_count - 1) * metrics.lane_gap

    single = len(ordered) == 1
    inner_right = metrics.viewport_w - metrics.padding
    text_inset = metrics.text_inset
    bars: list[BarRect] = []
    for span, lane in zip(ordered, lanes):
        open_end = span.end is None
        if single:
            # One event fills the whole scale regardless of its duration.
            x0, x1 = metrics.padding, inner_right
        else:
            x0 = _clamp(_x_of(span.start, range_start, range_end, metrics), metrics.padding, inner_right)
            x1 = (
                inner_right
                if open_end
                else _clamp(_x_of(span.end, range_start, range_end, metrics), metrics.padding, inner_right)
            )
            if x1 - x0 < metrics.min_bar_w:
                # Sub-pixel spans stay clickable: widen symmetrically around
                # the natural center, then keep the bar inside the margins.
                # Consequence: a widened bar can overlap its lane neighbor
                # horizontally — painting order plus the topmost-wins
                # hit_test (see TrackPlan.hit_test) resolve such overlaps.
                center = (x0 + x1) / 2.0
                x0 = max(metrics.padding, center - metrics.min_bar_w / 2.0)
                x1 = min(inner_right, x0 + metrics.min_bar_w)
                x0 = max(metrics.padding, x1 - metrics.min_bar_w)
        text_fits = lane_h >= metrics.min_text_h and _text_fits(
            span.event_id, x1 - x0, text_widths, text_inset
        )
        bars.append(
            BarRect(
                event_id=span.event_id,
                x0=x0,
                x1=x1,
                y_top=lane * (lane_h + metrics.lane_gap),
                height=lane_h,
                lane=lane,
                text_fits=text_fits,
                open_end=open_end,
            )
        )

    return TrackPlan(
        bars=tuple(bars),
        metrics=metrics,
        lane_count=lane_count,
        lane_h=lane_h,
        content_h=content_h,
        range_start=range_start,
        range_end=range_end,
        ticks=_month_ticks(range_start, range_end),
    )


def _text_fits(
    event_id: int,
    bar_w: float,
    text_widths: Mapping[int, float] | None,
    text_inset: float,
) -> bool:
    """Bar wide enough for the label (unknown width never fits)."""
    if text_widths is None:
        return False
    text_w = text_widths.get(event_id)
    if text_w is None:
        return False
    return bar_w >= text_w + text_inset


def _x_of(d: date, range_start: date, range_end: date, metrics: TrackMetrics) -> float:
    total_days = max(1, (range_end - range_start).days)
    frac = (d - range_start).days / total_days
    inner_w = max(0.0, metrics.viewport_w - 2 * metrics.padding)
    return metrics.padding + frac * inner_w


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(low, value), high)


def _month_ticks(range_start: date, range_end: date) -> tuple[date, ...]:
    """Month-boundary ticks inside ``[range_start, range_end]`` (W3 D6).

    Only genuine first-of-month dates become ticks. The range start is the
    left edge of the scale, not a calendar boundary, so it never stands in for
    one (spec «Шкала времени»: подписи и разделители — на границах месяцев);
    a window shorter than a month therefore legitimately carries no ticks.
    Label collisions are handled by the renderer (clipping), not by thinning
    the tick schedule here.
    """
    current = range_start if range_start.day == 1 else _next_month_start(range_start)
    ticks: list[date] = []
    while current <= range_end:
        ticks.append(current)
        current = _next_month_start(current)
    return tuple(ticks)
