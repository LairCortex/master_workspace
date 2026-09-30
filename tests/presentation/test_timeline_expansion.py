"""Expansion state of the timeline tree (NRI-0023 task 5.2, design Д6).

``expanded_parent_ids`` is screen state exactly like the «Выбор даты» window:
empty by default (the tree opens collapsed), never persisted, rebuilt through
the Qt-free core with the set passed down. ``toggle_expand`` is the chevron's
channel, ``expand_to`` reveals a sub-event's parent before an external
selection lands, and every selection point that reaches the ladder funnels
through ``select_event_by_id`` — search clicks included (spec «Переход к
свёрнутому подсобытию раскрывает цепочку»). Window membership is answered by
the EVENTS (a collapsed child still belongs to the windowed sample while its
row stays hidden), never by the emitted rows."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QApplication

from app.presentation.viewmodels.timeline_viewmodel import TimelineViewModel
from app.presentation.views.timeline_island import TimelineWidget
from tests.presentation.qml_helpers import find_items


class _Ev:
    """Duck-typed event double in the tree shape the ViewModel reads."""

    def __init__(self, id_, start, end, name, parent_id=None, start_time_raw=None):
        self.id = id_
        self.start_date = start
        self.end_date = end
        self.name = name
        self.event_type = None
        if parent_id is not None:
            self.parent_id = parent_id
        if start_time_raw is not None:
            self.start_time_raw = start_time_raw


class _Service:
    def __init__(self, events):
        self._events = list(events)

    async def get_all_events(self):
        return list(self._events)


def _vm_with(*events) -> TimelineViewModel:
    return TimelineViewModel(_Service(events))


async def _loaded(*events) -> TimelineViewModel:
    vm = _vm_with(*events)
    await vm.load_events()
    return vm


PARENT = _Ev(1, date(1200, 1, 5), date(1200, 1, 9), "Поход")
CHILD = _Ev(2, date(1200, 1, 6), None, "Разведка", parent_id=1)
OTHER = _Ev(3, date(1200, 2, 1), None, "Постороннее")
# The stub scenarios need a parent the day window genuinely EXCLUDES — an
# interval that ended before the window opens (the spec's «осиротевший» case).
FAR_PARENT = _Ev(1, date(1200, 1, 1), date(1200, 1, 2), "Поход")


class TestExpansionState:
    """The set itself: screen-scoped, per-VM, tolerant."""

    async def test_a_fresh_view_model_is_collapsed(self):
        """Spec «По умолчанию дерево свернуто»: empty set, no child rows; a
        second ViewModel over the same service (another game open) starts
        collapsed again — nothing here is persisted anywhere."""
        vm = await _loaded(PARENT, CHILD, OTHER)
        assert vm.expanded_parent_ids == frozenset()
        assert [row.event_id for row in vm.rows] == [1, 3]
        reopened = await _loaded(PARENT, CHILD, OTHER)
        assert reopened.expanded_parent_ids == frozenset()

    async def test_toggle_expand_opens_and_closes_the_children(self):
        vm = await _loaded(PARENT, CHILD, OTHER)
        model = vm.row_model
        expanded_role = model.EXPANDED_ROLE

        vm.toggle_expand(1)

        assert vm.expanded_parent_ids == frozenset({1})
        assert [row.event_id for row in vm.rows] == [1, 2, 3]
        assert model.data(model.index(0), expanded_role) is True

        vm.toggle_expand(1)

        assert vm.expanded_parent_ids == frozenset()
        assert [row.event_id for row in vm.rows] == [1, 3]
        assert model.data(model.index(0), expanded_role) is False

    async def test_the_qml_slot_channel_drives_the_same_state(self):
        """``toggleExpand`` is the QML side of the chevron (the snapshot-VM
        camelCase-slot pattern)."""
        vm = await _loaded(PARENT, CHILD, OTHER)
        vm.toggleExpand(1)
        assert vm.expanded_parent_ids == frozenset({1})
        assert [row.event_id for row in vm.rows] == [1, 2, 3]

    async def test_toggle_is_tolerant_about_childless_and_unknown_ids(self):
        """The delegate only ever wears a chevron the core marked with
        ``hasChildren``; a stray call adds an id the next re-model simply
        ignores (the expanded set alone must not fabricate or drop rows)."""
        vm = await _loaded(PARENT, CHILD, OTHER)
        before = list(vm.rows)

        vm.toggle_expand(3)  # main event, childless
        vm.toggle_expand(404)  # id the sample never held

        assert [row.event_id for row in vm.rows] == [e.event_id for e in before]

    async def test_expand_to_reveals_only_the_parents_of_a_subevent(self):
        vm = await _loaded(PARENT, CHILD, OTHER)
        assert vm.expand_to(CHILD.id) is True
        assert vm.expanded_parent_ids == frozenset({1})
        assert [row.event_id for row in vm.rows] == [1, 2, 3]
        # Already open — silent no-op; a main event or an unknown id never
        # touch the set either (the two-level chain has exactly one link).
        assert vm.expand_to(CHILD.id) is False
        assert vm.expand_to(PARENT.id) is False
        assert vm.expand_to(404) is False
        assert vm.expand_to(None) is False
        assert vm.expanded_parent_ids == frozenset({1})


class TestSelectionAutoExpansion:
    """Spec «Переход к свёрнутому подсобытию раскрывает цепочку»: every
    selection that reaches the ladder (the wiring funnels both the search
    click and the detail-panel open through ``select_event_by_id``) opens the
    parent BEFORE the highlight-and-scroll runs, so the caller always finds
    the child's row."""

    async def test_selecting_a_collapsed_child_opens_its_parent(self):
        vm = await _loaded(PARENT, CHILD, OTHER)
        vm.select_event_by_id(CHILD.id)
        assert vm.expanded_parent_ids == frozenset({1})
        assert vm.selected_event is CHILD
        index = vm.index_for_event(CHILD.id)
        assert index is not None and vm.rows[index].event_id == CHILD.id

    async def test_the_child_selection_needs_no_expansion_when_open(self):
        vm = await _loaded(PARENT, CHILD, OTHER)
        vm.toggle_expand(1)
        vm.select_event_by_id(CHILD.id)  # already visible: nothing re-models
        assert vm.selected_event is CHILD
        assert vm.expanded_parent_ids == frozenset({1})

    async def test_window_reset_and_expansion_land_before_the_selection(self):
        """The compound path: a child the window excluded resets «Все дни»
        first (existing spec), the chain then expands, and the scroll target
        (index_for_event) resolves on the same call — the wiring's
        scroll-to-event runs after it."""
        closed_child = _Ev(2, date(1200, 1, 6), date(1200, 1, 7), "Разведка",
                           parent_id=1)
        vm = await _loaded(PARENT, closed_child, OTHER)
        vm.window = (date(1200, 2, 1), date(1200, 2, 1))  # only OTHER crosses
        assert [row.event_id for row in vm.rows] == [3]

        vm.select_event_by_id(closed_child.id)

        assert vm.window is None  # «Все дни» (spec «Внешний выбор вне окна»)
        assert vm.expanded_parent_ids == frozenset({1})
        assert vm.selected_event is closed_child
        assert [row.event_id for row in vm.rows] == [1, 2, 3]


class TestWindowMembershipAndStubs:
    """Membership is answered by EVENTS crossing the window, rows by the
    tree: a collapsed child belongs to ``events`` while no row of its is
    emitted, and the window-excluded parent of a shown child exists on the
    ladder only as its unselectable stub."""

    async def test_collapsed_child_stays_in_the_windowed_sample(self):
        day = (date(1200, 1, 6), date(1200, 1, 6))
        vm = _vm_with(FAR_PARENT, CHILD, OTHER)
        vm.window = day
        await vm.load_events()
        assert [e.id for e in vm.events] == [2]  # the child crosses…
        assert [row.event_id for row in vm.rows] == [1, 2]  # …as a stub+row
        assert [row.kind for row in vm.rows] == ["stub", "event"]

    async def test_stub_keeps_the_excluded_parent_unselectable(self):
        """The stub row explains the orphan; the parent itself did not cross
        and the selection layers must agree: a parent the window excludes is
        dropped from the ViewModel even while its stub stays on screen."""
        day = (date(1200, 1, 6), date(1200, 1, 6))
        vm = _vm_with(FAR_PARENT, CHILD, OTHER)
        await vm.load_events()
        vm.select_event_by_id(FAR_PARENT.id)
        assert vm.selected_event is FAR_PARENT

        vm.window = day  # the parent's interval misses the new window

        assert vm.selected_event is None  # cleared in every layer
        assert [row.event_id for row in vm.rows] == [1, 2]  # stub still shown
        assert vm.rows[0].kind == "stub"

    async def test_rechain_and_time_moves_invalidated_the_rebuild_memo(self):
        """Rows are built from the WHOLE sample now (stubs quote parents the
        window cuts), so the memo key reads the parent link and the time — a
        reload that only re-chains (or retimes) must still re-model."""
        vm = _vm_with(PARENT, CHILD)
        await vm.load_events()
        assert [row.event_id for row in vm.rows] == [1]  # collapsed, hidden

        # The child rose to the main level (field cleared → new sample).
        risen = _Ev(2, date(1200, 1, 6), None, "Разведка")
        vm._event_service._events = [PARENT, risen]
        await vm.load_events()
        assert [row.event_id for row in vm.rows] == [1, 2]

        # A time-only move (same dates, same fields but start_time_raw)
        # reorders within the day — the key must not swallow it. Both events
        # start January 6: untimed-first says [1, 2], the 20:00 parent says
        # [2, 1], and nothing but the raw minutes differs between reloads.
        same_day = _Ev(1, date(1200, 1, 6), date(1200, 1, 9), "Поход")
        vm._event_service._events = [same_day, risen]
        await vm.load_events()
        assert [row.event_id for row in vm.rows] == [1, 2]  # tie: ids
        timed_parent = _Ev(1, date(1200, 1, 6), date(1200, 1, 9), "Поход",
                           start_time_raw=20 * 60)
        vm._event_service._events = [timed_parent, risen]
        await vm.load_events()
        assert [row.event_id for row in vm.rows] == [2, 1]  # untimed first


class TestDeliveredOpenState:
    """The model side of the chevron (role pin beside the diff pins of
    test_timeline_row_model): the tree scalars reach ``data()`` under their
    declared role names for every delivered row."""

    async def test_roles_answer_for_every_row_kind(self):
        day = (date(1200, 1, 6), date(1200, 1, 6))
        vm = _vm_with(FAR_PARENT, CHILD, OTHER)
        vm.toggleExpand(FAR_PARENT.id)  # expanded — the child rides as a stub…
        vm.window = day  # …and here comes the stub+orphan pair
        await vm.load_events()
        model = vm.row_model
        rows = [(model.data(model.index(i), model.KIND_ROLE),
                 model.data(model.index(i), model.EVENT_ID_ROLE),
                 model.data(model.index(i), model.DEPTH_ROLE),
                 model.data(model.index(i), model.HAS_CHILDREN_ROLE),
                 model.data(model.index(i), model.EXPANDED_ROLE),
                 model.data(model.index(i), Qt.ItemDataRole.DisplayRole))
                for i in range(model.rowCount())]
        assert rows == [
            ("stub", 1, 0, True, False, None),
            ("event", 2, 1, False, False, None),
        ]


class TestExpansionOnTheView:
    """The view half of the expansion (task 5.3, design Д6): the expansion
    animation is the ListView's штатные ``add``/``displaced`` transitions
    running over the model's insert/remove delivery — no new timing code,
    and the view keeps its position (the no-reset delivery is pinned in
    test_timeline_row_model). The transitions are declared under names the
    offscreen test can address off the real root."""

    def test_the_list_declares_the_expansion_transitions(self, qtbot):
        panel = TimelineWidget(_vm_with(PARENT, CHILD, OTHER))
        qtbot.addWidget(panel)
        panel.resize(300, 220)
        panel.show()
        QApplication.processEvents()
        event_list = find_items(panel.quick, "eventList")[0]
        for name in ("eventAddTransition", "eventDisplacedTransition"):
            assert event_list.findChild(QObject, name) is not None, name
