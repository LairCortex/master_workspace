"""Shared-engine and deferred-teardown contract for the three R4 panels."""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QEvent, QUrl

from app.presentation.qml.engine import qml_engine
from app.presentation.viewmodels.search_viewmodel import SearchViewModel
from app.presentation.views.detail_panel import DetailPanel
from app.presentation.views.search_bar import SearchBar
from app.presentation.views.world_snapshot_widget import WorldSnapshotWidget


def _panels(qtbot):
    panels = (
        SearchBar(SearchViewModel(None)),
        DetailPanel(SimpleNamespace()),
        WorldSnapshotWidget(),
    )
    for panel in panels:
        qtbot.addWidget(panel)
    return panels


def test_panels_share_engine_isolate_context_and_reopen(qtbot, qapp):
    panels = _panels(qtbot)
    shared = qml_engine()
    assert all(panel.quick.engine() is shared for panel in panels)
    root_context = shared.rootContext()
    for name in ("searchBarVm", "detailPanelVm", "worldSnapshotVm", "tooltipBridge"):
        assert root_context.contextProperty(name) is None

    for panel in panels:
        panel.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    qtbot.wait(1)
    assert all(panel.quick.rootObject() is None for panel in panels)
    assert all(panel.quick.source() == QUrl() for panel in panels)

    reopened = _panels(qtbot)
    assert all(panel.quick.engine() is shared for panel in reopened)
    assert all(panel.quick.rootObject() is not None for panel in reopened)
