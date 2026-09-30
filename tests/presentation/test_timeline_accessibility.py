"""Accessibility contract of the timeline island (change
nri-0012-qml-accessibility, task 2.1; NRI-0023 task 5.3 for the tree:
the parent row's disclosure chevron and the window-only parent stub).

The flat-list row (TimelineRowDelegate) and the «+» header button
(TimelineRoot) carry the tree contract pinned by the design map: the row is
a ListItem named by the delivered caption whose single Press is the
double-click path — the event open (D3: accessibility has no double press),
the addButton is named «Добавить событие» because its only glyph is «+».
The chevron is the library ThemeIconButton (штатный Button role) named by
its action («Развернуть подсобытия»/«Свернуть подсобытия») with the fixed
«Развернуть или свернуть раздел» description; its Press runs the row's OWN
expand channel, never the row's select/open gesture. The stub row explains
its orphans and interacts as little as the contract allows: no description,
no open, no selection.
Description slots are read offscreen through ``text(QAccessible.Description)``
(F4); the press runs through ``actionInterface().doAction("Press")`` and must
land on the facade's ``event_double_clicked`` signal (F2/F6). The island is
the production facade with the REAL root QML and a seeded real ViewModel —
the mouse single/double click channels are owned by the existing timeline
suites (test_timeline_island / test_timeline_rows), this one only adds the
accessibility plane. NRI-0023 tasks 11.1/11.3 join it at the geometry edge:
the branch line's «└» angle on the group's last child, the expanded parent's
own segment, and the child band that starts at the trunk column are read off
the live delegate objects here (their pixels are pinned in
``tests/ui/test_e2e_timeline_theme.py``).
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
from tests.presentation.qml_helpers import find_item, island_rows, track, walk_items


@pytest.fixture(autouse=True)
def _default_months():
    """Captions come from the active calendar; assert against the preset map."""
    saved = current_calendar()
    reset_current_calendar()
    yield
    set_current_calendar(saved)


def _evt(eid: int, start: date, end: date | None = None, name: str | None = None,
         description=None, parent_id=None):
    event = SimpleNamespace(id=eid, name=name or f"event-{eid}", start_date=start,
                            end_date=end, description=description)
    if parent_id is not None:
        event.parent_id = parent_id
    return event


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


# ── the tree: chevron and parent stub (NRI-0023 task 5.3) ─────────────────────

TREE = [
    _evt(1, date(1200, 1, 1), date(1200, 1, 1), name="Поход"),
    _evt(2, date(1200, 1, 2), None, name="Разведка", parent_id=1),
    _evt(3, date(1200, 4, 1), None, name="Без детей"),
]


def _chevron(row):
    """The disclosure glyph the row PAINTS, or None when it wears none. The
    objectName is shared across recycled delegates (address it per row), and
    a not-painted chevron still lives in the visual tree as a hidden item —
    visibility is the painted/none answer the spec speaks of."""
    marks = [i for i in walk_items(row)
             if i.objectName() == "rowChevron" and i.isVisible()]
    assert len(marks) <= 1
    return marks[0] if marks else None


def _named_in(row, object_name: str):
    items = [i for i in walk_items(row) if i.objectName() == object_name]
    assert len(items) == 1
    return items[0]


def _row_by_id(rows, event_id: int):
    """The delegate painting ``event_id``'s row. Addressing rows BY ID rather
    than by scene y survives the штатный ``displaced`` transition the row
    shift rides (mid-animation a positional pick could read the wrong
    delegate), while the delegate's own bindings — indent, connector
    visibility, glyph — are instant and animation-free."""
    found = [r for r in rows if r.property("eventId") == event_id]
    assert len(found) == 1, f"{event_id}: {len(found)} delegates"
    return found[0]


def test_chevron_is_a_named_button_only_on_parents(qtbot):
    """Spec «Шеврон раскрытия дерева» + «Пустой родитель без шеврона»: the
    parent row carries the library glyph as a штатный Button named by its
    action («Развернуть подсобытия» while collapsed) and carrying the fixed
    map description; the childless main row wears none at all."""
    panel = _island(qtbot, TREE)
    rows = island_rows(panel.quick, "eventRow")
    assert len(rows) == 2  # collapsed: only the two top-level rows are listed

    chevron = _chevron(rows[0])
    assert chevron is not None
    assert _chevron(rows[1]) is None

    iface = accessible_of(chevron)
    assert iface.role() == QAccessible.Role.Button
    assert iface.text(QAccessible.Name) == "Развернуть подсобытия"
    assert iface.text(QAccessible.Description) == "Развернуть или свернуть раздел"


def test_chevron_press_opens_the_children_never_the_row_itself(qtbot):
    """The Press is the row's OWN expand channel (design Д8): it neither
    selects nor opens the parent, it re-models the ladder — the child row
    appears under the parent (indented, with its connector painted), and the
    glyph flips to «Свернуть подсобытия»/«▾» on the delivered open flag. A
    second Press collapses back and the name flips back with it."""
    panel = _island(qtbot, TREE)
    doubles = track(panel.event_double_clicked)
    selects = track(panel.event_selected)
    rows = island_rows(panel.quick, "eventRow")
    parent = _row_by_id(rows, 1)
    parent_x = _named_in(parent, "rowText").x()

    press(_chevron(parent))

    assert doubles == []  # never the row's open gesture…
    assert selects == []  # …nor its selection

    # An insert-delivery rebuilds the list one layout pass at a time
    # offscreen (the qtbot.waitUntil idiom of the island suites).
    qtbot.waitUntil(
        lambda: len(island_rows(panel.quick, "eventRow")) == 3, timeout=5000
    )
    rows = island_rows(panel.quick, "eventRow")  # «Разведка» rode in under it
    kid = _row_by_id(rows, 2)
    parent = _row_by_id(rows, 1)
    child_text = _named_in(kid, "rowText")
    assert child_text.property("text") == "02 Январь 1200 — ∞ · Разведка"
    assert child_text.x() == kid.property("textIndent") + kid.property(
        "childIndent")
    assert child_text.x() > parent_x  # spec «с горизонтальным отступом»
    assert _named_in(kid, "rowConnectorTrunk").property("visible") is True
    assert _named_in(kid, "rowConnectorElbow").property("visible") is True
    assert _named_in(parent, "rowConnectorTrunk").property("visible") is False

    chevron = _chevron(parent)
    assert chevron.property("text") == "▾"
    assert accessible_of(chevron).text(QAccessible.Name) == "Свернуть подсобытия"

    press(chevron)

    qtbot.waitUntil(
        lambda: len(island_rows(panel.quick, "eventRow")) == 2, timeout=5000
    )
    rows = island_rows(panel.quick, "eventRow")
    assert _chevron(_row_by_id(rows, 1)).property("text") == "▸"
    assert (doubles, selects) == ([], [])


def test_stub_row_explains_its_orphans_and_interacts_as_little_as_possible(qtbot):
    """Spec «Окно фильтрации и пустое состояние» (stub half): the name-only
    row above an orphaned child is a ListItem whose NAME is the parent's bare
    name (no dates in it, no description line, no type mark, no chevron), its
    description slot is unset («») and its Press opens and selects nothing."""
    events = [
        _evt(1, date(1200, 1, 1), date(1200, 1, 2), name="Поход"),
        _evt(2, date(1200, 5, 1), None, name="Дефиле", parent_id=1),
    ]
    vm = TimelineViewModel(_Service(events))
    vm._all_events = list(events)
    vm.window = (date(1200, 5, 1), date(1200, 5, 1))  # parent's span misses
    panel = TimelineWidget(vm)
    qtbot.addWidget(panel)
    panel.resize(300, 220)
    panel.show()
    QApplication.processEvents()

    stubs = island_rows(panel.quick, "stubRow")
    kids = island_rows(panel.quick, "eventRow")
    assert len(stubs) == 1 and len(kids) == 1
    stub = stubs[0]
    assert stub.property("caption") == "Поход"  # the bare name — no dates

    iface = accessible_of(stub)
    assert iface.role() == QAccessible.Role.ListItem
    assert iface.text(QAccessible.Name) == "Поход"
    assert iface.text(QAccessible.Description) == ""  # the unset slot

    assert _chevron(stub) is None  # «шеврон неактивен» — painted none
    assert _named_in(stub, "eventTypeMark").property("visible") is False
    assert _named_in(stub, "rowDetail").property("visible") is False

    doubles = track(panel.event_double_clicked)
    selects = track(panel.event_selected)
    press(stub)
    QApplication.processEvents()
    assert (doubles, selects) == ([], [])


# ── the tree geometry (NRI-0023 tasks 11.1/11.3, design Д11/Д13) ──────────────

GROUP = [
    _evt(1, date(1200, 1, 1), date(1200, 1, 1), name="Поход"),
    _evt(2, date(1200, 1, 2), None, name="Разведка", parent_id=1),
    _evt(3, date(1200, 1, 3), None, name="Охрана", parent_id=1),
]


def _expanded_island(qtbot, events):
    """The same seeded facade with the parent already OPEN — the geometry the
    delegate paints for an expanded group, without the press animation the
    live toggle rides."""
    vm = _real_vm(events)
    vm.toggle_expand(1)
    panel = TimelineWidget(vm)
    qtbot.addWidget(panel)
    panel.resize(300, 220)
    panel.show()
    QApplication.processEvents()
    return panel, vm


def _named_visible(root_panel, event_id, object_name: str):
    row = _row_by_id(island_rows(root_panel.quick, "eventRow"), event_id)
    return row, _named_in(row, object_name)


def test_last_child_closes_the_branch_middle_children_run_full(qtbot):
    """Task 11.1 (design Д11, spec scenario «Последний ребёнок завершает
    ветку»): the middle child's trunk runs to the row's bottom edge (the line
    continues to the next child), the LAST child's trunk stops AT its elbow
    line — the «└» angle — so no stem dangles below the group's end. The
    elbow line is the caption line's vertical center, the same height the
    elbow itself rides."""
    panel, _vm = _expanded_island(qtbot, GROUP)
    rows = island_rows(panel.quick, "eventRow")
    assert len(rows) == 3

    middle, trunk_m = _named_visible(panel, 2, "rowConnectorTrunk")
    last, trunk_l = _named_visible(panel, 3, "rowConnectorTrunk")

    # «├» — the middle child connects downward: trunk reaches the row bottom.
    assert float(trunk_m.property("height")) == float(middle.property("height"))
    # «└» — the last child closes: trunk reaches the elbow, NOT the bottom.
    line_l = float(last.property("captionLineY"))
    assert line_l < float(last.property("height"))
    assert float(trunk_l.property("height")) == line_l
    # The angle lands on the elbow's own line (the audit's exact coincidence —
    # the 1-px elbow's anchor may snap to the pixel grid, hence the tolerance).
    elbow = _named_in(last, "rowConnectorElbow")
    elbow_center = float(elbow.property("y")) + float(elbow.property("height")) / 2
    assert abs(elbow_center - line_l) <= 0.5


def test_expanded_parent_draws_the_branch_segment(qtbot):
    """Task 11.1 (design Д11, A4, spec «от левого края родителя до локтя
    первого ребёнка линия SHALL быть непрерывна»; live fix 2026-09-30 moved
    the trunk off the parent's type mark onto the row's left edge): the
    expanded parent paints the branch's first segment INSIDE its own row —
    from its caption line to the row's bottom edge, at x = 0, continuing the
    parent card's left border — while a collapsed parent shows no segment at
    all (its children are hidden anyway)."""
    panel, _vm = _expanded_island(qtbot, GROUP)
    parent = _row_by_id(island_rows(panel.quick, "eventRow"), 1)
    segment = _named_in(parent, "rowParentSegment")

    assert segment.property("visible") is True
    # The trunk column is the row's left edge itself (user fix: the line
    # continues the parent card's border, not the square of its type mark).
    assert float(parent.property("trunkX")) == 0.0
    assert float(segment.property("x")) == float(parent.property("trunkX")) == 0.0
    assert float(segment.property("y")) == float(parent.property("captionLineY"))
    # …and the segment reaches the delegate's bottom edge: contiguous rows make
    # the parent segment + first child trunk ONE line from label to elbow.
    assert float(segment.property("y")) + float(segment.property("height")) \
        == float(parent.property("height"))

    # Collapsed: the segment is painted away with the children themselves.
    _vm.toggle_expand(1)
    qtbot.waitUntil(
        lambda: len(island_rows(panel.quick, "eventRow")) == 1, timeout=5000
    )
    parent = _row_by_id(island_rows(panel.quick, "eventRow"), 1)
    assert _named_in(parent, "rowParentSegment").property("visible") is False


def test_child_wash_hangs_on_the_tree_line_parent_stays_full(qtbot):
    """Task 11.3 (design Д13, spec scenario «Выделение подсобытия не захватывает
    гуттер дерева»; live fix 2026-09-30): the tree line stands on the row's
    left edge (trunkX == 0), so the CHILD row's selection/hover band hangs on
    the child's indent column (``childWashX``) instead — the gutter between
    the line and the band stays the canvas' business — and the band is
    measurably narrower than the parent's, which keeps the full-width band
    (band width is the level's sign)."""
    panel, _vm = _expanded_island(qtbot, GROUP)
    parent = _row_by_id(island_rows(panel.quick, "eventRow"), 1)
    child = _row_by_id(island_rows(panel.quick, "eventRow"), 2)
    wash_p = _named_in(parent, "rowWash")
    wash_c = _named_in(child, "rowWash")

    # The line is the parent row's left edge; the band keeps its level step
    # one child-indent in, so line and band never fuse into one strip.
    assert float(child.property("trunkX")) == 0.0
    assert float(child.property("childWashX")) == float(child.property("childIndent"))
    assert float(wash_p.property("x")) == 0  # top level: full-width band as ever
    assert float(wash_p.property("width")) == float(parent.property("width"))
    assert float(wash_c.property("x")) == float(child.property("childWashX"))
    assert float(wash_c.property("width")) == (
        float(child.property("width")) - float(child.property("childWashX"))
    )
    # Same row width in the one list — the narrower band is the shift itself.
    assert float(wash_c.property("width")) < float(wash_p.property("width"))
