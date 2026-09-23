"""Accessibility contract of the timeline island (change
nri-0012-qml-accessibility, task 2.1).

The flat-list row (TimelineRowDelegate) and the «+» header button
(TimelineRoot) carry the tree contract pinned by the design map: the row is
a ListItem named by the delivered caption whose single Press is the
double-click path — the event open (D3: accessibility has no double press),
the addButton is named «Добавить событие» because its only glyph is «+».
Description slots are read offscreen through ``text(QAccessible.Description)``
(F4); the press runs through ``actionInterface().doAction("Press")`` and must
land on the facade's ``event_double_clicked`` signal (F2/F6). The island is
the production facade with the REAL root QML and a seeded real ViewModel —
the mouse single/double click channels are owned by the existing timeline
suites (test_timeline_island / test_timeline_rows), this one only adds the
accessibility plane.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QApplication

from app.domain.game_calendar import (
    current_calendar,
    reset_current_calendar,
    set_current_calendar,
)
from app.presentation.viewmodels.timeline_viewmodel import TimelineViewModel
from app.presentation.views.timeline_island import TimelineWidget
from tests.presentation.qml_helpers import find_item, island_rows, track


@pytest.fixture(autouse=True)
def _default_months():
    """Captions come from the active calendar; assert against the preset map."""
    saved = current_calendar()
    reset_current_calendar()
    yield
    set_current_calendar(saved)


def _evt(eid: int, start: date, end: date | None = None, name: str | None = None,
         description=None):
    return SimpleNamespace(id=eid, name=name or f"event-{eid}", start_date=start,
                           end_date=end, description=description)


def _real_vm(events):
    """A seeded-but-unscheduled ViewModel (the test_timeline_island pattern)."""
    vm = TimelineViewModel(_Service(events))
    vm._all_events = list(events)
    vm.events = list(events)
    vm._rebuild_rows()
    return vm


class _Service:
    def __init__(self, events=()):
        self._events = list(events)

    async def get_all_events(self):
        return list(self._events)


def _island(qtbot, events):
    panel = TimelineWidget(_real_vm(events))
    qtbot.addWidget(panel)
    panel.resize(300, 220)
    panel.show()
    QApplication.processEvents()
    return panel


def accessible_of(item):
    iface = QAccessible.queryAccessibleInterface(item)
    assert iface is not None, f"no accessibility interface on {item.objectName()!r}"
    return iface


def press(item) -> None:
    actions = accessible_of(item).actionInterface()
    assert "Press" in actions.actionNames()
    actions.doAction("Press")


ROWS = [
    _evt(1, date(1200, 1, 1), date(1200, 1, 1), name="Старт"),
    _evt(2, date(1200, 3, 1), description="Описание второго события"),
]


def test_row_is_list_item_named_by_caption_with_open_description(qtbot):
    panel = _island(qtbot, ROWS)
    rows = island_rows(panel.quick, "eventRow")
    assert len(rows) == 2

    iface = accessible_of(rows[0])
    assert iface.role() == QAccessible.Role.ListItem
    # Name follows the delivered caption (the model pre-formats it; the row
    # never re-derives — the delegate contract).
    assert iface.text(QAccessible.Name) == rows[0].property("caption")
    assert rows[0].property("caption") == "01 Январь 1200 — 01 Январь 1200 · Старт"
    assert iface.text(QAccessible.Description) == "Открывает событие"


def test_row_press_opens_the_event_through_the_double_click_channel(qtbot):
    panel = _island(qtbot, ROWS)
    rows = island_rows(panel.quick, "eventRow")
    doubles = track(panel.event_double_clicked)
    selects = track(panel.event_selected)

    press(rows[1])

    # Accessibility has no double press: one Press == one open (design D3),
    # and it is NOT a selection (clicks are the selection, spec-pinned).
    assert doubles == [(2,)]
    assert selects == []


def test_add_button_is_named_add_event(qtbot):
    panel = _island(qtbot, ROWS)
    add_button = find_item(panel.quick, "addButton")

    iface = accessible_of(add_button)
    assert iface.text(QAccessible.Name) == "Добавить событие"
