// panelHeader.js — the one home of the shared header band of the three
// main-window columns (live fix 2026-09-26, docs/qa/2026-09-26-header-alignment.md).
//
// Timeline, detail and world snapshot are separate QQuickWidget islands,
// each rooted at its own y=0, so before this file the vertical entry of the
// header line was the private business of each QML root: the timeline
// centered its title in a 32 px band, the snapshot title sat flush against
// the top margin (center 12.5 px), and the detail tab strip rode at center
// 61 px below two rows that stay empty without a selected event. One band,
// one axis: every usage site lays its header row inside this band and seats
// the caption on the band's vertical center, so the three captions read on
// one horizontal line — centered in the band, neither pinned to its top nor
// to its bottom.
//
// 32 is not a new number: it is the gauge the app already standardized on
// (NRI-0018: the shared 32×32 ThemeIconButton, the 32 px calendar nav band,
// the timeline chip/add row). The live measurements confirmed the detail tab
// strip and the timeline chip are exactly 32 tall, so the strip fits the
// band whole and the axis stays where the timeline header always was.
// The top inset stays each island's own space.xs margin (4 px) — all three
// roots already share it; only the band needed one home.

.pragma library

// Height of the shared header band in px. Usage sites: TimelineRoot.qml,
// DetailPanelRoot.qml (tab strip + collapsed event-meta rows),
// WorldSnapshotRoot.qml.
function band() { return 32 }
