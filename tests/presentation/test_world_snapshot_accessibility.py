"""Accessibility contract of the world-snapshot island (change
nri-0012-qml-accessibility, task 2.3).

Both row kinds of the WorldSnapshotRoot inline delegate get the design-map
face on the production WorldSnapshotWidget with a populated VM:
the entity row is a ListItem named by the delivered displayText whose single
Press drives the mouse's own single-click channel ``vm.select(index)`` (the
entity jump), the section header is a Button named the same displayText whose
Press runs ``toggleSection(index)`` (expand/collapse). Descriptions are read
through ``text(QAccessible.Description)`` (F4); the press reaches the QML
handler through ``doAction("Press")`` (F2/F6).
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from PySide6.QtGui import QAccessible

from app.presentation.views.world_snapshot_widget import WorldSnapshotWidget
from tests.presentation.qml_helpers import island_rows, track


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


def _populated(qtbot) -> WorldSnapshotWidget:
    widget = WorldSnapshotWidget()
    widget.resize(760, 520)
    qtbot.addWidget(widget)
    widget.populate([_event()], None)
    widget.show()
    return widget


def accessible_of(item):
    iface = QAccessible.queryAccessibleInterface(item)
    assert iface is not None, f"no accessibility interface on {item.objectName()!r}"
    return iface


def press(item) -> None:
    actions = accessible_of(item).actionInterface()
    assert "Press" in actions.actionNames()
    actions.doAction("Press")


def _row_by(rows, predicate):
    return next(row for row in rows if predicate(row))


def test_entity_row_is_list_item_named_by_display_text(qtbot):
    widget = _populated(qtbot)
    entity_rows = island_rows(widget.quick, "snapshotEntityRow")
    location = _row_by(entity_rows, lambda r: r.property("entityType") == "location")

    iface = accessible_of(location)
    assert iface.role() == QAccessible.Role.ListItem
    # The name is the VM-delivered displayText — the rating suffix included
    # (the row paints exactly what the model sends, no second rule engine).
    assert iface.text(QAccessible.Name) == location.property("displayText")
    assert iface.text(QAccessible.Name) == "Замок  [16/20]"
    assert iface.text(QAccessible.Description) == "Переходит к сущности"


def test_entity_press_selects_the_row_jump(qtbot):
    widget = _populated(qtbot)
    entity_rows = island_rows(widget.quick, "snapshotEntityRow")
    location = _row_by(entity_rows, lambda r: r.property("entityType") == "location")
    clicked = track(widget.entity_clicked)

    press(location)

    # Same channel as the mouse single click: vm.select(index) → the facade's
    # entity click for selectable rows.
    assert clicked == [("location", 20)]


def test_header_is_button_pressing_it_toggles_the_section(qtbot):
    widget = _populated(qtbot)
    headers = island_rows(widget.quick, "snapshotSectionRow")
    events_header = _row_by(headers, lambda r: r.property("sectionKey") == "events")

    iface = accessible_of(events_header)
    assert iface.role() == QAccessible.Role.Button
    assert iface.text(QAccessible.Name) == events_header.property("displayText")
    # The ▸/▾ glyph is paint, not part of the name (design map).
    assert "▸" not in iface.text(QAccessible.Name)
    assert iface.text(QAccessible.Description) == "Развернуть или свернуть раздел"

    # The snapshot ships collapsed; the first Press expands (the rows appear),
    # the second collapses them again — both directions run through the very
    # toggleSection channel the mouse header click uses. The toggle rebuilds
    # the row model, so the header must be re-read between the presses (the
    # delegate items are replaced, not reused).
    def events_head():
        return _row_by(island_rows(widget.quick, "snapshotSectionRow"),
                       lambda r: r.property("sectionKey") == "events")

    before = len(island_rows(widget.quick, "snapshotEntityRow"))
    press(events_head())
    expanded = island_rows(widget.quick, "snapshotEntityRow")
    assert len(expanded) > before

    press(events_head())
    assert len(island_rows(widget.quick, "snapshotEntityRow")) == before


def test_event_entity_row_has_the_list_item_face_too(qtbot):
    # A non-selectable row keeps the same contract surface; the VM's select
    # is what decides, the tree does not branch (press stays side-effect-free
    # for event rows — the island's own click path pins that today).
    widget = _populated(qtbot)
    # The events section starts collapsed — open it through its header so the
    # event row is materialized (rows live in the flickable, not the tree).
    headers = island_rows(widget.quick, "snapshotSectionRow")
    press(_row_by(headers, lambda r: r.property("sectionKey") == "events"))
    entity_rows = island_rows(widget.quick, "snapshotEntityRow")
    event_row = _row_by(entity_rows, lambda r: r.property("entityType") == "event")
    clicked = track(widget.entity_clicked)

    iface = accessible_of(event_row)
    assert iface.role() == QAccessible.Role.ListItem
    # The delivered event displayText carries the calendar range, not the
    # bare name — the tree exposes exactly what the row paints.
    assert iface.text(QAccessible.Name) == event_row.property("displayText")
    assert "Осада" in iface.text(QAccessible.Name)

    press(event_row)
    assert clicked == []
