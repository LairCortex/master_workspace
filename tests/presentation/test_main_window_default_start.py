"""NRI-0018 group 4 — the main window starts whole (Д5).

Spec main-window «Размещение окон помнится и возвращается в экраны» (NRI-0018
half): without a remembered placement the window opens at 1280×800 — the size
the full tab captions and the snapshot date row read whole — and role "main"
is attached with the detail panel's all-tabs-whole width provider, so a narrow
saved frame comes back widened (the geometry mechanic itself is pinned in
test_geometry_memory.py). The splitter panels that can clip the strip or the
«Дата:» row — the detail panel and the splitter's right pane — carry that
threshold as their width floor. The OBS-1 live follow-up (NRI-0017 audit:
«Показать всё» clipped at the 1028×708 saved frame) is pinned HERE at the new
default: the whole «Дата:» action row of the world snapshot stands inside its
panel on a fresh start.
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


def test_splitter_panels_are_floored_with_the_tabs_threshold(qtbot):
    window = _main_window(qtbot)
    threshold = window.detail_panel.min_tabs_width()
    # The caption floor no longer a hand-tuned 280: the strip threshold and
    # the splitter's right pane — the OBS-1 pane — stand on the same number
    # the detail panel publishes (task 4.3).
    assert threshold > 300
    assert [
        _splitter(window).widget(i).minimumWidth() for i in range(3)
    ] == [220, threshold, threshold]


def test_tabs_are_whole_in_the_detail_column_at_the_default(qtbot):
    """Spec scenario «Все вкладки прочитаны с порога» on the composed window."""
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


async def test_main_role_is_attached_with_the_detail_panel_provider(
    qapp, tmp_path, monkeypatch
):
    """The composition root hands role "main" the detail panel's threshold as
    its width provider (NRI-0018 Д5) — asserted on the real start() contour."""
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
        provider = captured["min_width"]
        assert provider() == window.detail_panel.min_tabs_width()
    finally:
        window.close()
        await application.shutdown()
