"""The ladder's encounter ring on a real delegate (add-dnd-game-face task
11.2, spec event-timeline «Пометки строк от внешних источников»).

The Qt-free merge is pinned in ``test_timeline_marks``, the delivery channel
in ``test_timeline_row_model``; this file pins the LAST inch — the delegate
painting the delivered token (design-задача 1.1 §4, эталон
docs/qa/references/2026-10-10-dnd-tabs-ladder-marks-{dark,light}.png):

* only a row whose marks carry the ``encounter`` token shows the ring —
  without the token the delegate paints ZERO new pixels;
* the ring is the эталон's hollow square: 12×12, transparent body, 1 px
  accent border, centred on the caption line on the type-dot's street
  (x = textLeftPad + contentShift − 2);
* over the selection wash the border flips to the accent foreground (the
  row-glyph rule «Дерево не грязнит акцент на залировке») — the source-level
  token contract, the paint proof being the accent≠canvas probe below;
* a save that only moves the mark re-delivers the row through the scoped
  repaint and the live delegate re-reads it — the ring appears without the
  list ever being rebuilt from scratch (the model-level no-reset pin of
  ``test_timeline_row_model`` seen from the scene).

Pattern of ``test_timeline_now_surfaces`` (production facade, seeded VM,
grabbed-pixel probes)."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from app.domain.game_calendar import (
    current_calendar,
    reset_current_calendar,
    set_current_calendar,
)
from app.presentation.viewmodels.timeline_viewmodel import TimelineViewModel
from app.presentation.views.timeline_island import TimelineWidget
from tests.presentation.qml_helpers import island_rows


@pytest.fixture(autouse=True)
def _default_months():
    saved = current_calendar()
    reset_current_calendar()
    yield
    set_current_calendar(saved)


def _evt(eid):
    return SimpleNamespace(
        id=eid, name=f"event-{eid}", start_date=date(1200, 1, 4 + eid),
        end_date=None, event_type=None, description=None,
    )


class _Service:
    async def get_all_events(self):
        return [_evt(1), _evt(2)]


class _Source:
    """Duck of DndEncounterSource: a set of marked ids the ladder asks."""

    def __init__(self, encountered=()):
        self.encountered = set(encountered)
        self.visible = True

    def event_marks(self, event_ids):
        return {i: "encounter" for i in event_ids if i in self.encountered}


def _island(qtbot, source=None):
    vm = TimelineViewModel(
        _Service(), external_sources=([source] if source is not None else [])
    )
    # The seeded-VM idiom of test_timeline_now_surfaces: the sample lands
    # synchronously, the projection runs before the island wakes up.
    vm._all_events = [_evt(1), _evt(2)]
    vm.events = list(vm._all_events)
    vm._rebuild_rows()
    panel = TimelineWidget(vm)
    qtbot.addWidget(panel)
    panel.resize(320, 240)
    panel.show()
    QApplication.processEvents()
    assert panel.quick.status() == panel.quick.Status.Ready, panel.quick.errors()
    return panel, vm


def _retire(panel, qtbot) -> None:
    panel.close()
    qtbot.waitUntil(lambda: panel.quick.source().isEmpty(), timeout=2000)


def _ring(row_item):
    return next(i for i in row_item.childItems()
                if i.objectName() == "rowEncounterRing")


def _caption(row_item):
    return next(i for i in row_item.childItems() if i.objectName() == "rowText")


def _ring_visible(panel) -> list[bool]:
    return [bool(_ring(row).property("visible"))
            for row in island_rows(panel.quick, "eventRow")]


def _pixel(panel, item, fx: float, fy: float) -> QColor:
    image = panel.quick.grab().toImage()
    scene = item.mapToScene(QPointF(item.width() * fx, item.height() * fy))
    scale = image.width() / max(panel.quick.width(), 1)
    x = min(max(int(scene.x() * scale), 0), image.width() - 1)
    y = min(max(int(scene.y() * scale), 0), image.height() - 1)
    return image.pixelColor(x, y)


# ── visibility follows the delivered token ─────────────────────────────────


def test_only_a_marked_row_wears_the_ring(qtbot):
    panel, _vm = _island(qtbot, source=_Source({2}))
    assert _ring_visible(panel) == [False, True]
    _retire(panel, qtbot)


def test_without_sources_the_ring_is_invisible_everywhere(qtbot):
    panel, _vm = _island(qtbot)
    assert _ring_visible(panel) == [False, False]
    _retire(panel, qtbot)


def test_the_ring_actually_paints_and_the_plain_row_paints_nothing_there(qtbot):
    """Pixel truth: the ring's left border line on the marked row differs
    from the very same scene point on the unmarked row (whose canvas stays
    the row's own wash) — the zero-pixel rule seen from the grab."""
    panel, _vm = _island(qtbot, source=_Source({1}))
    rows = island_rows(panel.quick, "eventRow")
    edge_marked = _pixel(panel, _ring(rows[0]), 0.04, 0.5)  # the 1-px border
    edge_plain = _pixel(panel, _ring(rows[1]), 0.04, 0.5)
    assert edge_marked != edge_plain
    _retire(panel, qtbot)


# ── the эталон geometry and the token contract ─────────────────────────────


def test_the_ring_sits_on_the_type_street_centred_on_the_caption_line(qtbot):
    panel, _vm = _island(qtbot, source=_Source({1}))
    row = island_rows(panel.quick, "eventRow")[0]
    ring = _ring(row)
    # top-level: textLeftPad(8) + contentShift(0) − 2 px halo → 6.
    assert ring.property("x") == 6
    assert ring.property("width") == 12
    assert ring.property("height") == 12
    text = _caption(row)
    centre = ring.property("y") + 12 / 2
    assert abs(centre - (text.property("y") + text.property("height") / 2)) <= 1
    _retire(panel, qtbot)


def test_the_ring_block_reads_the_mark_token_and_the_selection_flip():
    """Source-level token contract (the grep-grade idiom of the outline pin):
    the ring is driven by the delivered marks token only, never re-derives
    anything, paints a transparent body with a 1 px border, and over the
    selection flips from ``color.accent`` to the row's accent foreground —
    the fill token itself never becomes the body."""
    from pathlib import Path

    from app.presentation.qml.engine import QML_IMPORT_PATH

    source = (
        Path(QML_IMPORT_PATH) / "TimelineRowDelegate.qml"
    ).read_text(encoding="utf-8")
    block = source.split('objectName: "rowEncounterRing"', 1)[1].split("\n    }", 1)[0]
    assert "row.encounterMark" in block
    assert 'color: "transparent"' in block
    assert "border.width: 1" in block
    assert "row.selectedRow ? row.accentFgColor : row.accentColor" in block
    # The token vocabulary is exactly one word, tested on the delivered list.
    assert '"encounter"' in source.split("readonly property bool encounterMark", 1)[1]


# ── the live save rides the scoped repaint ─────────────────────────────────


async def test_a_save_without_date_moves_the_ring_without_a_rewind(qtbot):
    """The save flow end to end at the island: the source reconciles its
    cache (the wiring's hook), the ordinary ladder reload re-asks the marks,
    and the live delegate lights the ring — no model reset (the scoped
    repaint pin of test_timeline_row_model is the model half; here the scene
    half: the same delegate items survive the frame)."""
    source = _Source()
    panel, vm = _island(qtbot, source=source)
    rows_before = island_rows(panel.quick, "eventRow")
    assert _ring_visible(panel) == [False, False]

    source.encountered.add(1)
    await vm.load_events()
    QApplication.processEvents()

    assert _ring_visible(panel) == [True, False]
    assert island_rows(panel.quick, "eventRow") == rows_before  # same items
    _retire(panel, qtbot)
