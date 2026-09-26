"""The ui-layout-grid width scale — the ONE home of the 40 px step.

Spec ui-layout-grid «Естественная ширина окна берётся из шкалы кратной 40»:
every window and sheet has a natural width that is a multiple of this step and
is never narrower than its own content; «при несовместимости шкалы и
содержимого ширина SHALL подниматься к ближайшей ступени вверх» — when the
content outgrows the port's floor, the ask is climbed to the NEXT step
(change nri-0018-grid-alignment-and-card, owner decision on OBS-2,
2026-09-26, closing the live finding «content-driven widths leave the scale»).

Consumers (AGENTS principle «одно знание — одно место»: the constant and the
tie-break exist exactly once, here):

* :func:`app.presentation.qml.island_size.fit_dialog_to_island` — the
  content-driven island dialogs (entity card, sheet list, event types);
* :mod:`app.presentation.views.calendar_wizard` — the content-sized step
  column and the recounted window minimum (design Д7).

The step is a Python-side layout-law constant, not a theme token (NRI-0018
non-goal «новые токены не заводим»: geometry of the scale is not a knob the
theme may turn). Heights are not on the scale — only widths climb steps.
"""
from __future__ import annotations

import math

#: One step of the width scale (px), spec «Единая шкала естественных ширин».
WIDTH_STEP = 40


def ceil_to_width_step(value: float) -> int:
    """``value`` climbed UP to the next multiple of :data:`WIDTH_STEP`.

    Exact steps pass through unchanged (scenario «Uзкое содержимое не
    растягивается до следующей ступени с пустотой» — a window whose content
    already fits a step opens on exactly that step), anything off-step rises
    to the nearest one above (817→840, 620→640) rather than opening
    off-scale.
    """
    return math.ceil(value / WIDTH_STEP) * WIDTH_STEP
