"""NRI-0018/NRI-0019 — the main window starts whole; the tabs follow the column.

Spec main-window «Размещение окон помнится и возвращается в экраны»: without
a remembered placement the window opens at 1280×800 — the size the snapshot
date row reads whole (the tab captions follow the column since the
2026-10-01 equal-share law, see below) — and role "main" is attached
plain: NRI-0019 retired the all-tabs-whole width provider (the tabs now
stretch/shrink with elision, so a narrow saved frame returns AS saved; the
geometry mechanic itself is pinned in test_geometry_memory.py). The splitter
panes stand on one modest usability floor — no more the tabs threshold —
while the default split hands the detail column its four EQUAL tab shares
(the 2026-10-01 re-pin of «Все вкладки прочитаны на дефолте» — renamed
«Вкладки делят колонку равными долями на дефолте» — for the
library's equal-share law — see the test's comment). The OBS-1 live
follow-up (NRI-0017 audit: «Показать всё» clipped at the 1028×708 saved frame)
is pinned HERE too,
on the snapshot's own home: since NRI-0022 (task 2.4) the whole «Дата:» action
row stands inside the «Обзор мира» window at its first-open default.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QPointF, QSize
from PySide6.QtWidgets import QApplication, QDialog, QSplitter

from app.presentation.views.main_window import MainWindow


def _main_window(qtbot) -> MainWindow:
    window = MainWindow(
        timeline_vm=MagicMock(),
        detail_vm=MagicMock(),
        search_vm=MagicMock(),
    )
    qtbot.addWidget(window)
    return window


def _splitter(window: MainWindow) -> QSplitter:
    return window.centralWidget().findChild(QSplitter)


def _whole_items_in_panel(quick_widget) -> list[tuple[str, float]]:
    """(objectName, right edge in island-root coords) for the date-row actions."""
    from tests.presentation.qml_helpers import walk_items

    root = quick_widget.rootObject()
    out = []
    for item in walk_items(root):
        if item.objectName() in (
            "snapshotShowButton", "snapshotResetButton", "snapshotShowAllButton",
        ):
            scene = item.mapToItem(root, QPointF(0, 0))
            out.append((item.objectName(), scene.x() + item.width()))
    return out


# ── the default frame (task 4.1/4.3) ────────────────────────────────────────


def test_main_window_opens_at_the_default_frame(qtbot):
    window = _main_window(qtbot)
    # The frame without any remembered placement: 1280×800 (spec «Первый
    # запуск шире прежнего минимума»)…
    assert window.size() == QSize(1280, 800)
    # …while the hard system floor of the window stays where NRI-0015 put it.
    assert window.minimumSize() == QSize(1024, 680)


def test_splitter_panels_stand_on_one_usability_floor(qtbot):
    window = _main_window(qtbot)
    # NRI-0019: the tabs shrink with the column now, so the all-tabs-whole
    # threshold retired as the splitter floor — every pane keeps one modest
    # usability minimum instead (the rail's old 220, promoted to the shared
    # constant; the tabs elide below their natural widths, they never clip).
    # NRI-0022 (tasks 2.4 + 4.1): the snapshot pane left for its own «Обзор
    # мира…» window and the preview island took the freed column — the floor
    # covers all three panes, so no column can be dragged out of usability
    # (spec entity-preview «колонка SHALL оставаться видимой и не схлопываться»).
    floor = window.detail_panel.minimumWidth()
    assert floor == 220
    assert [
        _splitter(window).widget(i).minimumWidth() for i in range(3)
    ] == [floor, floor, floor]


def test_tabs_share_the_detail_column_in_equal_shares_at_the_default(qtbot):
    """Spec scenario «Вкладки делят колонку равными долями на дефолте»
    (renamed from «Все вкладки прочитаны на дефолте»), re-pinned 2026-10-01
    for the library's equal-share law (spec qml-components «Вкладки делят
    ширину полосы»): at the default split the four tabs divide the bar into
    four EQUAL widths — the caption length buys no tab extra pixels. NOTE the
    honest deviation from the old whole-caption assertion: the proportional
    distribution used to hand «Организации» (natural 101.8 px) more than an
    equal share (99 px at the 396 px default column), so its caption now
    loses its tail to the ellipsis by a few pixels at the default column —
    the same mechanism the narrow-column scenario already blesses."""
    window = _main_window(qtbot)
    window.show()
    QApplication.processEvents()

    detail_root = window.detail_panel.quick.rootObject()
    tabs = [
        item
        for item in _walk(window.detail_panel.quick.rootObject())
        if item.metaObject().className().startswith("ThemeTabButton")
    ]
    tabs.sort(key=lambda tab: tab.mapToItem(detail_root, QPointF(0, 0)).x())
    assert len(tabs) == 4
    widths = [tab.width() for tab in tabs]
    # Equal shares: one width for all four captions of different lengths.
    assert max(widths) - min(widths) <= 1.0
    for tab in tabs:
        # …standing inside the island.
        scene = tab.mapToItem(detail_root, QPointF(0, 0))
        assert scene.x() + tab.width() <= detail_root.width() + 0.5


def _walk(root):
    stack = [root]
    while stack:
        for child in stack.pop().childItems():
            yield child
            stack.append(child)


def test_detail_tabs_read_whole_at_the_default_first_run_frame(qtbot):
    """PR-014 — spec «Первый запуск шире прежнего минимума» on the REAL layout.

    The retired whole-caption pin measured the panel in isolation at a 1280 px
    panel width (test_detail_tabs_labels), blind to the real splitter that in
    fact leaves the detail column ~404 px at the default frame — where
    «Организации» (natural 101.8 px) lost its tail to the ellipsis at the 99 px
    equal share. This pin walks the SHOWN MainWindow: the default split must
    land exactly on the splitter width at the first-run frame, and every tab
    caption must read whole in the column the splitter ACTUALLY hands the
    panel (detail default 390→434; the sum + 2×4 px handles fills the 1272 px
    splitter exactly, so no stretch surplus smears the nominal split)."""
    window = _main_window(qtbot)
    window.show()
    QApplication.processEvents()

    assert window.size() == QSize(1280, 800)
    splitter = _splitter(window)
    # 1280 content − the central layout's 2×4 px margins = 1272 px of splitter.
    assert splitter.width() == 1272
    # The default split at the first-run frame, exact and with no surplus:
    # 330 + 434 + 500 + 2 handles × 4 px = 1272. The preview pane keeps the
    # 500 px it inherited from the freed snapshot pane (NRI-0022).
    assert splitter.sizes() == [330, 434, 500]
    assert [splitter.widget(i).minimumWidth() for i in range(3)] == [220, 220, 220]

    detail_root = window.detail_panel.quick.rootObject()
    tabs = [
        item
        for item in _walk(detail_root)
        if item.metaObject().className().startswith("ThemeTabButton")
    ]
    tabs.sort(key=lambda tab: tab.mapToItem(detail_root, QPointF(0, 0)).x())
    captions = list(window.detail_panel.vm.tabTitles)
    assert len(tabs) == len(captions) == 4
    for tab, caption in zip(tabs, captions):
        assert tab.property("text") == caption
        # Whole, not elided: the tab keeps at least its natural width, and
        # the caption label inside it keeps the room its full text asks for.
        assert tab.width() >= tab.property("implicitWidth") - 0.5, caption
        label = tab.property("contentItem")
        assert label.width() >= label.property("implicitWidth") - 0.5, caption


# ── OBS-1 follow-up: the «Дата:» row whole at the snapshot's own default ────


def test_world_snapshot_date_row_stands_whole_at_the_window_default(qtbot):
    # NRI-0022 (task 2.4) moved the panel out of the columns into its own
    # «Обзор мира…» window; the OBS-1 whole-row pin rides along and now reads
    # at the window's first-open default 520×760: the row's last action sits
    # whole — right edge up to the island's own margin.
    from app.presentation.views.world_snapshot_widget import WorldSnapshotWindow

    window = WorldSnapshotWindow()
    qtbot.addWidget(window)
    window.show()
    QApplication.processEvents()
    assert window.size() == QSize(520, 760)

    snap_root = window.snapshot.quick.rootObject()
    reported = _whole_items_in_panel(window.snapshot.quick)
    assert [name for name, _ in reported] == [
        "snapshotShowButton", "snapshotResetButton", "snapshotShowAllButton",
    ]
    for name, right in reported:
        # OBS-1 (live NRI-0017): «Показать всё» used to lean on the panel edge
        # already at the 1028-class frame; the move keeps it standing whole.
        assert right <= snap_root.width() - 3, name


# ── the geometry memory is handed the panel provider (main.py wiring) ───────


@pytest.fixture(autouse=True)
def autoaccept_calendar_wizard(monkeypatch):
    """A freshly seeded game opens the first-entry wizard deferred after
    show(); offscreen must not block on its modal loop (the same seam
    tests/test_application_startup.py pins)."""
    from app.presentation.views.calendar_wizard import CalendarWizardDialog

    monkeypatch.setattr(
        CalendarWizardDialog,
        "exec",
        lambda self, *args: QDialog.DialogCode.Rejected,
    )


async def test_main_role_is_attached_without_the_retired_width_provider(
    qapp, tmp_path, monkeypatch
):
    """NRI-0019: role "main" is attached plain — the all-tabs-whole width
    provider retired with the threshold, so a narrow saved frame comes back
    as saved and the tab captions shorten with the column. Asserted on the
    real start() contour."""
    from app.main import Application
    from app.presentation.geometry_memory import WindowGeometryMemory

    captured: dict = {}
    real_attach = WindowGeometryMemory.attach

    def spy(self, window, role, **kwargs):
        if role == "main":
            captured["window"] = window
            captured.update(kwargs)
        return real_attach(self, window, role, **kwargs)

    monkeypatch.setattr(WindowGeometryMemory, "attach", spy)

    application = Application(qapp)
    db_path = tmp_path / "WholeTabs" / "game.db"
    db_path.parent.mkdir(parents=True)
    window = await application.start(str(db_path))
    try:
        assert captured.get("window") is window
        assert "min_width" not in captured
    finally:
        window.close()
        await application.shutdown()
