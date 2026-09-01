from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EventType:
    """A per-game event type (W4): name + a palette color index.

    ``color_index`` addresses a ``color.chart.{1..8}`` theme token — it is an
    index, never a color literal (validation of the 1..8 range lives in the
    application service, not here). Ordering is explicit via ``sort_order``.
    """

    name: str
    color_index: int
    sort_order: int = 0
    id: int | None = None
