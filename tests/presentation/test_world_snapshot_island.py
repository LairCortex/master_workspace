from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtQuickWidgets import QQuickWidget

from app.presentation.views.world_snapshot_widget import WorldSnapshotWidget
from tests.presentation.qml_helpers import click_item, find_item, island_rows


def _entity(entity_id, name, rating=1):
    return SimpleNamespace(
        id=entity_id,
        name=name,
        rating=rating,
        image_ref=None,
        description=SimpleNamespace(characteristics=""),
    )


def _event():
    return SimpleNamespace(
        id=10,
        name="Осада",
        start_date=date(1200, 1, 1),
        end_date=None,
        locations=[_entity(20, "Замок", 16)],
        organizations=[],
        characters=[],
        items=[],
    )


def test_root_contract_and_isolated_context(qtbot):
    widget = WorldSnapshotWidget()
    qtbot.addWidget(widget)
    assert isinstance(widget.quick, QQuickWidget)
    assert widget.quick.status() == QQuickWidget.Status.Ready
    assert widget.quick.rootObject().objectName() == "worldSnapshotRoot"
    for name in (
        "snapshotTitle", "snapshotDateField", "snapshotShowButton",
        "snapshotResetButton", "snapshotShowAllButton", "snapshotList",
        "snapshotStats",
    ):
        assert find_item(widget.quick, name) is not None
    assert widget._context.contextProperty("worldSnapshotVm") is widget.vm
    assert widget._context.contextProperty("islandPalette") is widget._palette
    assert widget._context.contextProperty("tooltipBridge") is widget._tooltip_bridge
    assert widget._context.contextProperty("snapshotFacade") is None


def test_actions_keep_public_signal_semantics(qtbot):
    widget = WorldSnapshotWidget()
    widget.resize(760, 420)
    qtbot.addWidget(widget)
    widget.show()
    emitted = []
    widget.snapshot_requested.connect(emitted.append)
    widget.vm.set_date(date(1200, 6, 15))

    click_item(widget.quick, find_item(widget.quick, "snapshotShowButton"))
    click_item(widget.quick, find_item(widget.quick, "snapshotShowAllButton"))
    assert emitted == [date(1200, 6, 15), None]

    widget.populate([_event()], None)
    assert widget.vm.clearEnabled is True
    click_item(widget.quick, find_item(widget.quick, "snapshotResetButton"))
    assert widget.vm.clearEnabled is False


def test_section_toggle_entity_click_and_event_no_emit(qtbot):
    widget = WorldSnapshotWidget()
    widget.resize(760, 520)
    qtbot.addWidget(widget)
    widget.populate([_event()], None)
    widget.show()
    emitted = []
    widget.entity_clicked.connect(lambda kind, entity_id: emitted.append((kind, entity_id)))

    headers = island_rows(widget.quick, "snapshotSectionRow")
    assert headers
    event_header = next(row for row in headers if row.property("sectionKey") == "events")
    click_item(widget.quick, event_header)
    event_row = next(
        row for row in island_rows(widget.quick, "snapshotEntityRow")
        if row.property("entityType") == "event"
    )
    click_item(widget.quick, event_row)
    assert emitted == []

    location_row = next(
        row for row in island_rows(widget.quick, "snapshotEntityRow")
        if row.property("entityType") == "location"
    )
    assert location_row.property("iconSize") == 24
    click_item(widget.quick, location_row)
    assert emitted == [("location", 20)]


def test_date_popup_and_deferred_release(qtbot, monkeypatch):
    widget = WorldSnapshotWidget()
    qtbot.addWidget(widget)
    opened = []
    monkeypatch.setattr(
        widget.date_popup,
        "open_at",
        lambda anchor, current: opened.append((anchor, current)),
    )
    widget.vm.requestDatePopup(3, 4, 120, 30)
    assert opened and opened[0][1] == widget.vm._date

    widget.close()
    QCoreApplication.processEvents()
    qtbot.wait(1)
    assert widget.quick.source() == QUrl()


def test_live_retheme_keeps_expansion_and_scroll(qtbot, tmp_path):
    from app.infrastructure.ui_prefs.config import UiPrefsManager
    from app.presentation.theme.compiler import tokens_file_path
    from app.presentation.theme.runtime import ThemeRuntime

    runtime = ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"),
        tokens_path=tokens_file_path(),
    )
    widget = WorldSnapshotWidget(theme=runtime)
    widget.resize(520, 220)
    qtbot.addWidget(widget)
    widget.populate([_event()], None)
    widget.show()
    list_view = find_item(widget.quick, "snapshotList")
    list_view.setProperty("contentY", 8.0)
    before = list_view.property("contentY")
    expanded = dict(widget.vm._expanded)

    assert runtime.toggle() is True
    assert widget.quick.rootObject().objectName() == "worldSnapshotRoot"
    assert widget.vm._expanded == expanded
    assert list_view.property("contentY") == before
