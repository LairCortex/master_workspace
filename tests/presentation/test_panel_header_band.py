"""The three main-window column headers sit on ONE shared band (live fix
2026-09-26, docs/qa/2026-09-26-header-alignment.md).

Timeline, detail and world snapshot are separate QQuickWidget islands, each
rooted at its own y=0, so the header line of each column used to enter at its
own height: the timeline centered its title in a 32 px band, the snapshot
title hugged the top margin (center 12.5 px) and the detail tab strip rode at
center 61 px below the two event-meta rows that stay empty without a selected
event — the live audit measured the three caption centers on 19.5 / 12.5 /
61.0 px. The fix is the shared band of panelHeader.js: the same 32 px band
below the same 4 px top margin in all three roots, every header caption
seated on the band's vertical center (the timeline's pre-existing look), the
empty event-meta rows leaving the layout so the strip is not pushed down.

Pins (measured on the production roots, no stubs):
* the three caption centers — the timeline title, the snapshot title and a
  detail tab caption — coincide within 1 px and lie on the band's axis;
* each island lays its header on the shared band: the band item is 32 px
  tall below the 4 px margin, the tab strip fills its band whole, and the
  empty event-meta rows are invisible (they must not push the strip down);
* selecting an event grows the detail header DOWNWARD: the title/date enter
  above the strip in order, nothing overlaps, the pane keeps its place under
  the strip — the band and the strip themselves do not move up or apart;
* the band constant lives in one home: panelHeader.js is imported by all
  three roots, and no root re-declares a private ``implicitHeight: 32``.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from app.presentation import qml as qml_shell
from app.presentation.viewmodels.timeline_viewmodel import TimelineViewModel
from app.presentation.views.detail_panel import DetailPanel
from app.presentation.views.timeline_island import TimelineWidget
from app.presentation.views.world_snapshot_widget import WorldSnapshotWidget
from tests.presentation.qml_helpers import find_item, walk_items

#: The shared header band of panelHeader.js (its Python mirror for the pins).
BAND = 32
#: The islands' shared top inset (space.xs) — the band starts below it.
TOP_MARGIN = 4
#: The band's vertical axis: where every header caption centers.
AXIS = TOP_MARGIN + BAND / 2  # 20.0

_TAB_CAPTIONS = ("Организации", "Персонажи", "Предметы", "Локации")


class _Service:
    def __init__(self, events=()):
        self._events = list(events)

    async def get_all_events(self):
        return list(self._events)


def _timeline(events=()):
    """A seeded-but-unscheduled timeline island (the accessibility-suite
    pattern: the real ViewModel behind the production root)."""
    vm = TimelineViewModel(_Service(events))
    vm._all_events = list(events)
    vm.events = list(events)
    vm._rebuild_rows()
    return TimelineWidget(vm)


def _shown(widget, qtbot, width=420, height=600):
    """Size, show and let the QQuickWidget scene settle (the island test
    convention: grab, then process the layout pass)."""
    widget.resize(width, height)
    qtbot.addWidget(widget)
    widget.show()
    widget.quick.grab()
    QApplication.processEvents()
    return widget


def _center_y(item) -> float:
    """Island-local y of the item's vertical center (every root starts at
    its own y=0, so scene coordinates ARE the comparable column coordinates)."""
    top = item.mapToScene(QPointF(0, 0)).y()
    return top + item.height() / 2


def _island_y(item) -> float:
    return item.mapToScene(QPointF(0, 0)).y()


def _tab_caption_center_y(detail) -> float:
    """Center of the first detail tab's caption text — the line of the tab
    strip the user sees (the strip's own frame is 32 tall; the caption is
    what must sit on the header axis)."""
    for tab in walk_items(detail.quick.rootObject()):
        if tab.objectName() != "detailTab":
            continue
        for sub in walk_items(tab):
            if sub.property("text") in _TAB_CAPTIONS:
                return _center_y(sub)
    raise AssertionError("no detail tab caption found in the tree")


def _entity(i, name):
    return SimpleNamespace(
        id=i, name=name, rating=1, image_ref=None,
        description=SimpleNamespace(characteristics="", backstory=""),
        personality=None, tasks=None,
    )


def _event():
    return SimpleNamespace(
        id=1, name="Начало похода", start_date=date(1200, 1, 1),
        end_date=date(1200, 12, 31),
        locations=[_entity(2, "Замок")], organizations=[_entity(3, "Гильдия")],
        characters=[], items=[],
    )


# ── the one line across the three islands ───────────────────────────────────


def test_the_three_header_captions_share_the_band_axis(qtbot):
    timeline = _shown(_timeline(), qtbot)
    detail = _shown(DetailPanel(SimpleNamespace()), qtbot)
    snapshot = _shown(WorldSnapshotWidget(), qtbot)

    centers = {
        "timeline": _center_y(find_item(timeline.quick, "timelineTitle")),
        "detail": _tab_caption_center_y(detail),
        "snapshot": _center_y(find_item(snapshot.quick, "snapshotTitle")),
    }
    # Every caption sits on the band's axis (±1 px of text-line rounding)…
    for name, center in centers.items():
        assert abs(center - AXIS) <= 1.0, (name, centers)
    # …so the three coincide on ONE horizontal line (the live defect spread
    # them across 48.5 px: 19.5 / 12.5 / 61.0).
    values = list(centers.values())
    assert max(values) - min(values) <= 1.0, centers


def test_each_island_lays_its_header_on_the_shared_band(qtbot):
    timeline = _shown(_timeline(), qtbot)
    detail = _shown(DetailPanel(SimpleNamespace()), qtbot)
    snapshot = _shown(WorldSnapshotWidget(), qtbot)

    for island, name in (
        (timeline, "timelineHeaderBand"),
        (detail, "detailTabBand"),
        (snapshot, "snapshotHeaderBand"),
    ):
        band = find_item(island.quick, name)
        assert _island_y(band) == TOP_MARGIN, name
        assert band.height() == BAND, name

    # Without a selected event the empty event-meta rows leave the layout
    # (an invisible child is skipped by ColumnLayout) — they must never
    # push the tab strip down, and the strip fills its band whole.
    assert find_item(detail.quick, "detailTitle").property("visible") is False
    assert find_item(detail.quick, "detailDate").property("visible") is False
    bar = find_item(detail.quick, "detailTabBar")
    assert _island_y(bar) == TOP_MARGIN
    assert bar.height() == BAND


def test_a_selected_event_grows_the_detail_header_downward(qtbot):
    """The selected state stays coherent: the title/date rows enter the
    header block above the strip in order, the block only grows DOWN, and
    the pane keeps its place below the strip (nothing overlaps, the strip
    itself keeps its band height)."""
    detail = _shown(DetailPanel(SimpleNamespace()), qtbot)
    detail.show_event(_event())

    title = find_item(detail.quick, "detailTitle")
    date_row = find_item(detail.quick, "detailDate")
    bar = find_item(detail.quick, "detailTabBar")
    stack = find_item(detail.quick, "detailStack")
    assert title.property("visible") is True
    assert date_row.property("visible") is True

    # The rows re-entering the ColumnLayout resize it on the next polish
    # pass (asynchronous, like every QQuickLayout change) — wait for the
    # settled frame, the same reason grab() precedes delegate reads.
    qtbot.waitUntil(
        lambda: _island_y(date_row) >= _island_y(title) + title.height(),
        timeout=2000,
    )

    title_y = _island_y(title)
    date_y = _island_y(date_row)
    bar_y = _island_y(bar)
    stack_y = _island_y(stack)
    # The block only grows downward: title first, then the date, the strip
    # under both (its band height kept), the pane under the strip — a row
    # never rises into its neighbour, so the header cannot tear apart.
    assert title_y >= TOP_MARGIN
    assert date_y >= title_y + title.height()
    assert bar_y >= date_y + date_row.height()
    assert bar.height() == BAND
    assert stack_y >= bar_y + bar.height()


# ── one knowledge, one place: the band constant ─────────────────────────────


def _qml_text(name: str) -> str:
    return (Path(qml_shell.__file__).resolve().parent / name).read_text(
        encoding="utf-8"
    )


def test_the_band_constant_lives_in_one_home():
    js = _qml_text("nri/components/panelHeader.js")
    assert ".pragma library" in js
    assert "function band() { return 32 }" in js
    for name in (
        "TimelineRoot.qml",
        "DetailPanelRoot.qml",
        "WorldSnapshotRoot.qml",
    ):
        qml = _qml_text(name)
        assert 'import "nri/components/panelHeader.js" as PanelHeader' in qml, name
        assert "PanelHeader.band()" in qml, name
        # No private re-declaration of the band height may reappear: the
        # header bands all read the shared constant.
        assert "implicitHeight: 32" not in qml, name
