from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtQuickWidgets import QQuickWidget

from app.domain.game_calendar import MonthDay
from app.presentation.views.world_snapshot_widget import WorldSnapshotWidget
from tests.presentation.qml_helpers import (
    click_item,
    find_item,
    find_items,
    island_rows,
    walk_items,
)


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
    # NRI-0024 (task 2.4, live audit F3): the island carries no «Обзор мира»
    # title anymore — the SheetFrame header of the sheet is the caption
    # carrier (spec world-snapshot), so snapshotTitle/snapshotHeaderBand are
    # deliberately NOT part of the contract (their absence is the next test).
    for name in (
        "snapshotDateField", "snapshotShowButton",
        "snapshotResetButton", "snapshotShowAllButton", "snapshotList",
        "snapshotStats",
    ):
        assert find_item(widget.quick, name) is not None
    assert widget._context.contextProperty("worldSnapshotVm") is widget.vm
    assert widget._context.contextProperty("islandPalette") is widget._palette
    assert widget._context.contextProperty("tooltipBridge") is widget._tooltip_bridge
    assert widget._context.contextProperty("snapshotFacade") is None


def test_no_duplicate_title_under_the_sheet_header(qtbot):
    """Live audit F3 (docs/qa/2026-10-01-modal-sheets.md): the sheet header
    already reads «Обзор мира», so the content must not print the caption a
    second time — neither the retired band's items nor any «Обзор мира» text
    may return into the island."""
    widget = WorldSnapshotWidget()
    qtbot.addWidget(widget)
    for name in ("snapshotTitle", "snapshotHeaderBand"):
        assert find_items(widget.quick, name) == [], name
    texts = [
        item.property("text")
        for item in walk_items(widget.quick.rootObject())
        if item.property("text") is not None
    ]
    assert "Обзор мира" not in texts


def test_header_buttons_stay_text_only_for_the_obs1_margin(qtbot):
    """Lucide icon pass 2026-09-30: the offscreen fit probe (capW/right-edge
    vs the root width at 520/1028) showed the header row carries zero slack
    for the OBS-1 clipper («Показать всё», docs/qa/2026-09-25-accessibility-
    audit.md) — pinning that no header button got a glyph."""
    widget = WorldSnapshotWidget()
    qtbot.addWidget(widget)
    for name in (
        "snapshotShowButton", "snapshotResetButton", "snapshotShowAllButton",
    ):
        button = find_item(widget.quick, name)
        assert button.property("iconName") == "", name
        assert button.property("text") != "", name


def test_bc_era_facet_and_the_suffix_reach_the_qml_date_field(qtbot):
    """Task 4.1: the snapshot viewmodel exposes a ready ``dateBc`` facet and
    the pre-built display string — the island's field shows the «до н.э.»
    suffix without computing an era in QML."""
    widget = WorldSnapshotWidget()
    qtbot.addWidget(widget)
    widget.vm.set_date((date(44, 3, 5), True))
    assert widget.vm.dateBc is True
    assert widget.vm.dateDisplay.endswith("44 г. до н.э.")
    field = find_item(widget.quick, "snapshotDateField")
    assert field.property("display") == widget.vm.dateDisplay
    assert field.property("display").endswith("44 г. до н.э.")
    assert field.property("isoDate") == "0044-03-05"
    # nri-0017 1.1: the VM's worst-form caption arrives as the field's
    # width floor.
    assert field.property("worstCaseText") == widget.vm.worstCaseDisplay


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
    # Task 3.4: the snapshot bridge transports a (date, era) pair; «Показать
    # всё» stays None.
    assert emitted == [(MonthDay(1200, 6, 15), False), None]

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


def test_tree_stub_renders_name_only_and_stays_unclickable(qtbot):
    """NRI-0023 task 8.3 in QML: the always-expanded tree arrives as ordinary
    rows — the child's indent rides inside displayText (the caption is the
    QML-independent channel), the orphan's parent stub carries the NAME and
    answers the click channel with nothing (vm.select ignores its rowKind)."""
    widget = WorldSnapshotWidget()
    widget.resize(760, 520)
    qtbot.addWidget(widget)
    orphan = SimpleNamespace(
        id=4,
        name="Сирота",
        start_date=date(1200, 1, 1),
        end_date=None,
        locations=[],
        organizations=[],
        characters=[],
        items=[],
        parent_id=9,
    )
    widget.populate([orphan], None, {9: "Ушедший отец"})
    widget.show()
    emitted = []
    widget.entity_clicked.connect(
        lambda kind, entity_id: emitted.append((kind, entity_id))
    )

    header = next(
        row for row in island_rows(widget.quick, "snapshotSectionRow")
        if row.property("sectionKey") == "events"
    )
    click_item(widget.quick, header)  # open the collapsed section (the tree)
    rows = [
        row
        for row in island_rows(widget.quick, "snapshotEntityRow")
        if row.property("sectionKey") == "events"
    ]
    texts = [row.property("displayText") for row in rows]
    assert "Ушедший отец" in texts  # the stub — the parent's bare name
    orphan_row = next(row for row in rows if "Сирота" in row.property("displayText"))
    assert orphan_row.property("displayText").startswith("\u00a0" * 4)  # indented

    click_item(widget.quick, rows[texts.index("Ушедший отец")])
    click_item(widget.quick, orphan_row)  # event rows never emitted jumps anyway
    assert emitted == []


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
    # Since piece C3b (design D3) the popup grid receives the snapshot's own
    # coordinate pair — today's coordinate arrives as today's numbers painted
    # by the grid itself, no picture-only clamp in between.
    assert opened and opened[0][1] == (widget.vm._date, widget.vm._date_bc)

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
