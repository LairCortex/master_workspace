"""NRI-0018/NRI-0019 — the main window starts whole; the tabs follow the column.

Spec main-window «Размещение окон помнится и возвращается в экраны»: without
a remembered placement the window opens at 1280×800 — the size the full tab
captions and the snapshot date row read whole — and role "main" is attached
plain: NRI-0019 retired the all-tabs-whole width provider (the tabs now
stretch/shrink with elision, so a narrow saved frame returns AS saved; the
geometry mechanic itself is pinned in test_geometry_memory.py). The splitter
panes stand on one modest usability floor — no more the tabs threshold —
while the default split still gives the detail column the whole-caption room
(spec «Все вкладки прочитаны на дефолте»). The OBS-1 live follow-up (NRI-0017
audit: «Показать всё» clipped at the 1028×708 saved frame) is pinned HERE at
the new default: the whole «Дата:» action row of the world snapshot stands
inside its panel on a fresh start.
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


def test_main_window_opens_at_the_whole_tabs_default_frame(qtbot):
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
    floor = window.detail_panel.minimumWidth()
    assert floor == 220
    assert [
        _splitter(window).widget(i).minimumWidth() for i in range(3)
    ] == [floor, floor, floor]


def test_tabs_are_whole_in_the_detail_column_at_the_default(qtbot):
    """Spec scenario «Все вкладки прочитаны на дефолте» on the composed window."""
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
    for tab in tabs:
        # Whole caption at the default split…
        assert tab.width() >= tab.property("implicitWidth") - 0.5
        # …standing inside the island.
        scene = tab.mapToItem(detail_root, QPointF(0, 0))
        assert scene.x() + tab.width() <= detail_root.width() + 0.5


def _walk(root):
    stack = [root]
    while stack:
        for child in stack.pop().childItems():
            yield child
            stack.append(child)


# ── OBS-1 follow-up: the «Дата:» row whole at the new start (task 4.4) ──────


def test_world_snapshot_date_row_stands_whole_at_the_default(qtbot):
    window = _main_window(qtbot)
    window.show()
    QApplication.processEvents()

    snap_root = window.world_snapshot.quick.rootObject()
    reported = _whole_items_in_panel(window.world_snapshot.quick)
    assert [name for name, _ in reported] == [
        "snapshotShowButton", "snapshotResetButton", "snapshotShowAllButton",
    ]
    for name, right in reported:
        # OBS-1 (live NRI-0017): «Показать всё» used to lean on the panel edge
        # already at the 1028-class frame. At the new default the row's last
        # action sits whole — right edge up to the island's own margin.
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
