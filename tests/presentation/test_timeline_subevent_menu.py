"""The row context menu of the timeline tree (NRI-0023 task 6.1, design Д7).

Right-clicking a MAIN event row requests the native «Создать подсобытие»
menu (spec «Создание подсобытия правым кликом»): the delegate reports the
pick through the island contract, the facade builds the one-item QMenu at
the reported scene point, and the pick is re-broadcast on the ViewModel's
``subevent_create_requested`` — the connector, not the ladder, owns the
prefilled dialog (pinned in the E2E suite). A sub-event row and a stub row
never reach the menu at all: the delegate's right-button TapHandler is
disabled on them, so no request signal leaves the island for those rows
(«меню не создаётся вовсе»).

Facade-level pins drive the STUB root declared by ``test_timeline_island``
(the menu is mocked exactly like the «+» menu); the gate itself is pinned on
the PRODUCTION root with synthetic right-button input through the e2e
timeline probe.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from app.presentation.viewmodels.timeline_viewmodel import TimelineViewModel
from app.presentation.views.timeline_island import SUBEVENT_MENU_ITEM, TimelineWidget
from tests.presentation.test_timeline_island import (
    FakeMenu,
    _evt,
    _island,
    _real_vm,
    _Service,
    _StubVM,
    fake_menu,  # noqa: F401 — the shared QMenu stand-in fixture
    root_qml,  # noqa: F401 — the shared stub-root fixture
)
from tests.ui import timeline_probe


def _tree_evt(eid: int, start: date, end: date | None = None,
              name: str | None = None, parent_id: int | None = None):
    """An event double in the tree shape the ViewModel reads (the
    test_timeline_expansion ``_Ev`` shape over the island-suite factory)."""
    event = _evt(eid, start, end, name=name)
    if parent_id is not None:
        event.parent_id = parent_id
    return event


def _as_window(panel: TimelineWidget):
    """Shim the main-window shape around a bare panel: the e2e probe reads
    the island as ``window.timeline_widget``/``window.timeline_widget._vm``."""
    return SimpleNamespace(timeline_widget=panel)


def _right_click(panel: TimelineWidget, idx: int) -> None:
    """A synthetic right click on row ``idx`` (the user gesture the spec's
    «правый клик по строке» is made of offscreen)."""
    window = _as_window(panel)
    timeline_probe.click(
        window,
        timeline_probe.row_center(window, idx),
        button=Qt.MouseButton.RightButton,
    )


def _production_island(qtbot, vm: TimelineViewModel) -> TimelineWidget:
    panel = TimelineWidget(vm)
    qtbot.addWidget(panel)
    panel.resize(300, 220)
    panel.show()
    QApplication.processEvents()
    return panel


class TestSubeventRequestChannel:
    """The ViewModel is the request's channel (design Д7): the menu pick
    re-broadcasts the parent id, the ladder itself opens nothing."""

    async def test_the_slot_rebroadcasts_the_parent_id(self):
        vm = TimelineViewModel(_Service([]))
        requests: list = []
        vm.subevent_create_requested.connect(lambda parent_id: requests.append(parent_id))
        vm.requestSubeventCreate(7)
        assert requests == [7]


class TestFacadeRowContextMenu:
    """The facade half of the channel (stub root, mocked QMenu — the «+»
    menu pattern of this suite): one item, exec at the reported point, the
    pick lands on the ViewModel, a closed menu asks nothing."""

    def test_the_menu_carries_the_single_item_and_picks_the_parent(
        self, qtbot, root_qml, fake_menu  # noqa: F811 — pytest injects the imported fixtures by name
    ):
        vm = _real_vm([_evt(1, date(1200, 1, 5))])
        panel = _island(qtbot, vm, root_qml)
        FakeMenu.decide = lambda menu: menu.pick(SUBEVENT_MENU_ITEM)
        requests: list = []
        vm.subevent_create_requested.connect(lambda parent_id: requests.append(parent_id))

        panel._root.rowContextMenuRequested.emit(1, 15.0, 25.0)

        menu = FakeMenu.menus[-1]
        assert menu.captions == [SUBEVENT_MENU_ITEM]
        assert menu.exec_calls == 1
        assert menu.exec_pos == panel.quick.mapToGlobal(QPoint(15, 25))
        assert requests == [1]

    def test_closing_the_menu_without_a_pick_requests_nothing(
        self, qtbot, root_qml, fake_menu  # noqa: F811 — pytest injects the imported fixtures by name
    ):
        vm = _real_vm([_evt(1, date(1200, 1, 5))])
        panel = _island(qtbot, vm, root_qml)
        requests: list = []
        vm.subevent_create_requested.connect(lambda parent_id: requests.append(parent_id))

        panel._root.rowContextMenuRequested.emit(1, 0.0, 0.0)  # decide = None

        assert FakeMenu.menus[-1].exec_calls == 1
        assert requests == []

    def test_a_stand_in_vm_survives_the_pick(self, qtbot, root_qml, fake_menu):  # noqa: F811 — fixtures injected by name
        """The facade's stand-in tolerance (the mirror/slot guards of this
        panel): a VM without the channel simply does not carry the request."""
        panel = _island(qtbot, _StubVM(), root_qml)
        FakeMenu.decide = lambda menu: menu.pick(SUBEVENT_MENU_ITEM)

        panel._root.rowContextMenuRequested.emit(1, 0.0, 0.0)  # no raise


class TestDelegateContextMenuGate:
    """The gate itself, on the production root: a main event row (with or
    without children) reports the right click and the facade really builds
    its one-item menu (the QMenu stand-in keeps the modal offscreen); a
    child and a stub build NOTHING — the menu is never created for them
    («ни у детей, ни у заглушек меню нет»)."""

    def test_a_main_row_with_children_reports_the_right_click(
        self, qtbot, fake_menu  # noqa: F811 — pytest injects the imported fixture by name
    ):
        parent = _tree_evt(1, date(1200, 1, 5), date(1200, 1, 9), name="Поход")
        child = _tree_evt(2, date(1200, 1, 6), name="Разведка", parent_id=1)
        vm = _real_vm([parent, child])
        panel = _production_island(qtbot, vm)
        requests: list = []
        panel._root.rowContextMenuRequested.connect(lambda *a: requests.append(a))

        _right_click(panel, 0)  # the collapsed parent is still a main event

        assert [args[0] for args in requests] == [1]
        # The reported point is the row's scene position the facade maps.
        _, x, y = requests[0]
        assert x > 0 and y > 0
        # Downstream of the same gesture the facade built its menu: exactly
        # the one «Создать подсобытие» item (decide=None — nobody picks).
        assert [m.captions for m in FakeMenu.menus] == [[SUBEVENT_MENU_ITEM]]

    def test_a_childless_main_row_reports_the_right_click(self, qtbot, fake_menu):  # noqa: F811 — fixture injected by name
        parent = _tree_evt(1, date(1200, 1, 5), date(1200, 1, 9), name="Поход")
        other = _tree_evt(3, date(1200, 2, 1), name="Постороннее")
        vm = _real_vm([parent, other])
        panel = _production_island(qtbot, vm)
        requests: list = []
        panel._root.rowContextMenuRequested.connect(lambda *a: requests.append(a))

        _right_click(panel, 1)  # «Постороннее» — main, no children

        assert [args[0] for args in requests] == [3]
        assert [m.captions for m in FakeMenu.menus] == [[SUBEVENT_MENU_ITEM]]

    def test_a_subevent_row_never_requests_the_menu(self, qtbot, fake_menu):  # noqa: F811 — fixture injected by name
        parent = _tree_evt(1, date(1200, 1, 5), date(1200, 1, 9), name="Поход")
        child = _tree_evt(2, date(1200, 1, 6), name="Разведка", parent_id=1)
        vm = _real_vm([parent, child])
        vm.toggle_expand(parent.id)  # the child's row is on screen now
        panel = _production_island(qtbot, vm)
        requests: list = []
        panel._root.rowContextMenuRequested.connect(lambda *a: requests.append(a))

        _right_click(panel, 1)  # the child row, right under its parent

        assert requests == []
        assert FakeMenu.menus == []  # «меню не создаётся вовсе»

    async def test_a_stub_row_never_requests_the_menu(self, qtbot, fake_menu):  # noqa: F811 — fixture injected by name
        """The window-only parent stub (spec «Окно фильтрации…»: the stub is
        no interaction target) stays silent under the right button too."""
        far_parent = _tree_evt(1, date(1200, 1, 1), date(1200, 1, 2), name="Поход")
        child = _tree_evt(2, date(1200, 1, 6), name="Разведка", parent_id=1)
        vm = TimelineViewModel(_Service([far_parent, child]))
        vm.window = (date(1200, 1, 6), date(1200, 1, 6))  # the parent misses
        await vm.load_events()
        assert [row.kind for row in vm.rows] == ["stub", "event"]

        panel = _production_island(qtbot, vm)
        requests: list = []
        panel._root.rowContextMenuRequested.connect(lambda *a: requests.append(a))

        _right_click(panel, 0)  # the stub row
        _right_click(panel, 1)  # and the orphaned child row — still no menu

        assert requests == []
        assert FakeMenu.menus == []

    def test_a_left_click_keeps_its_selection_channel(self, qtbot):
        """The right-button TapHandler leaves the штатные gestures alone: a
        left click on the same main row still selects (spec «Контракт
        строки» unchanged by task 6.1)."""
        parent = _tree_evt(1, date(1200, 1, 5), date(1200, 1, 9), name="Поход")
        vm = _real_vm([parent])
        panel = _production_island(qtbot, vm)
        selects: list = []
        panel.event_selected.connect(lambda event_id: selects.append(event_id))

        window = _as_window(panel)
        timeline_probe.click(window, timeline_probe.row_center(window, 0))

        assert selects == [1]
