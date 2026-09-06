"""Facade tests for the timeline QML island (simplify-event-timeline-flat-list).

The island root ships with the change, but these tests keep driving the
facade against a STUB root QML declaring the exact contract the facade wires
against (module docstring of ``timeline_island``) — everything on the Python
side (context properties, the panel API, the system menus, the date-window
popover) is exercised for real; only the QML-side rendering is stubbed away.
The flat-list rewrite deleted the ladder channels (drop/inline/sticky/zoom/
hideEmpty/jump and their signals); tests for those left with the features.
Full flat-list acceptance lives in the group-5 suites.

Entry points follow the contract (3.1): the chip popover is triggered by the
root's ``datePopupRequested`` signal with QML-reported scene coordinates, the
menu by ``addMenuRequested`` (QMenu mocked for the selection, mirroring the
acceptance harness); a miss past the rows arrives as ``selectionMissed``.
Real ``TimelineViewModel``s drive the data paths (the ``test_timeline_scale_
widget`` pattern); stand-in VMs pin the defensive guards.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QDate, QPoint
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QWidget

from app.presentation.utils.date_utils import get_custom_months, set_custom_months
from app.presentation.viewmodels.timeline_viewmodel import TimelineViewModel
from app.presentation.views import timeline_island
from app.presentation.views.timeline_date_popup import WINDOW_CHIP_ALL
from app.presentation.views.timeline_island import ADD_MENU_ITEMS, TimelineWidget

ROOT_QML_STUB = """
import QtQuick

Item {
    id: root
    objectName: "timelineRootStub"
    implicitWidth: 300
    implicitHeight: 200

    // Chrome surface the facade writes (windowText/selectedId) plus the
    // scroll-request recording pin of the stub itself.
    property string windowText: ""
    property int selectedId: -1
    property int lastScrollIndex: -2
    // Context-names probe: what the real root binds against must resolve for
    // the real root too (QQmlContext cannot read setContextProperty back from
    // Python, so the contract is pinned from INSIDE the declared scope).
    property string contextNames:
        [typeof vm, typeof islandPalette, typeof tooltipBridge].join(",")
    signal scrollToIndex(int index)
    onScrollToIndex: (index) => { root.lastScrollIndex = index }

    // Root -> facade contract (the documented island surface).
    signal addRequested()
    signal addMenuRequested(real x, real y)
    signal datePopupRequested(real x, real y, real width, real height)
    signal eventClicked(int eventId)
    signal eventDoubleClicked(int eventId)
    signal selectionMissed()
}
"""


@pytest.fixture(autouse=True)
def _default_months():
    """Month names are process-global (date_utils); tests assert the default map."""
    saved = get_custom_months()
    set_custom_months(None)
    yield
    set_custom_months(saved)


@pytest.fixture
def root_qml(tmp_path):
    path = tmp_path / "TimelineRootStub.qml"
    path.write_text(ROOT_QML_STUB, encoding="utf-8")
    return str(path)


def _evt(eid: int, start: date, end: date | None = None, name: str | None = None,
         description=None):
    return SimpleNamespace(id=eid, name=name or f"event-{eid}", start_date=start,
                           end_date=end, description=description)


class _Service:
    def __init__(self, events=()):
        self._events = list(events)

    async def get_all_events(self):
        return list(self._events)


def _real_vm(events):
    """A seeded-but-unscheduled ViewModel (pattern of test_timeline_scale_widget)."""
    vm = TimelineViewModel(_Service(events))
    vm._all_events = list(events)
    vm.events = list(events)
    vm._rebuild_rows()
    return vm


class _StubVM:
    """The old widget-test stand-in: no knobs a window predicate recognizes."""

    events: list = []


def _island(qtbot, vm, root_qml):
    panel = TimelineWidget(vm, root_qml=root_qml)
    qtbot.addWidget(panel)
    panel.resize(300, 200)
    panel.show()
    QApplication.processEvents()
    return panel


# ── QMenu stand-in (task 3.3: «тесты меню через mock выбора») ────────────────


class FakeMenu:
    """Stands in for ``QMenu`` inside ``timeline_island``: records the built
    items and the exec position, and answers the pick through ``decide``."""

    menus: list = []
    decide = None  # callable(FakeMenu) -> QAction | None

    def __init__(self, parent=None):
        self.items: list = []  # QAction entries, None marks separators
        self.exec_pos = None
        self.exec_calls = 0
        FakeMenu.menus.append(self)

    def addAction(self, action):  # noqa: N802 — mirrors the QMenu API
        if isinstance(action, str):
            action = QAction(action, None)
        self.items.append(action)
        return action

    def addSeparator(self):  # noqa: N802 — mirrors the QMenu API
        self.items.append(None)

    def exec(self, pos):  # noqa: N802 — mirrors the QMenu API
        self.exec_calls += 1
        self.exec_pos = pos
        return FakeMenu.decide(self) if FakeMenu.decide is not None else None

    @property
    def captions(self) -> list:
        return [None if item is None else item.text() for item in self.items]

    def pick(self, caption: str | None) -> QAction | None:
        if caption is None:
            return None
        return next(a for a in self.items if a is not None and a.text() == caption)


@pytest.fixture
def fake_menu(monkeypatch):
    FakeMenu.menus = []
    FakeMenu.decide = None
    monkeypatch.setattr(timeline_island, "QMenu", FakeMenu)
    return FakeMenu


# ── 3.1 — construction, context contract, teardown ──────────────────────────


class TestIslandConstruction:
    def test_island_loads_ready_with_the_context_contract(self, qtbot, root_qml):
        vm = _real_vm([_evt(1, date(1200, 1, 5))])
        panel = _island(qtbot, vm, root_qml)
        assert panel.quick.status() == timeline_island.QQuickWidget.Status.Ready
        assert panel._root.objectName() == "timelineRootStub"
        context = panel.quick.rootContext()
        # The context names every island binds against — read through the
        # stub root's own scope (typeof per name).
        assert panel._root.property("contextNames") == "object,object,object"
        assert context is not None
        # Those names live in the panel's OWN context, never in the shared
        # engine root: a name written there is one global slot, nulled for
        # every other island when its writer dies (a closed dialog used to
        # leave the tape off-skin).
        assert panel._context.parentContext() is panel._engine.rootContext()
        assert panel._engine.rootContext().contextProperty("islandPalette") is None
        assert panel._engine.rootContext().contextProperty("vm") is None
        # Token bridge and VM outlive the island at teardown: the context that
        # owns the palette is created AFTER the island widget, so child
        # destruction takes the island first (module docstring).
        assert panel._palette.parent() is panel._context
        assert panel._context.parent() is panel

    def test_missing_root_qml_asserts_ready(self, qtbot, tmp_path):
        # Honest failure pinned by the launcher precedent: a root that cannot
        # load must abort construction, never open an empty panel.
        host = QWidget()
        qtbot.addWidget(host)
        with pytest.raises(AssertionError):
            TimelineWidget(_StubVM(), parent=host,
                           root_qml=str(tmp_path / "TimelineRoot.qml"))

    def test_public_surface_is_the_frozen_wiring_contract(self):
        """Task 3.1: the wiring-facing surface of the FLAT panel is frozen
        (design D4): the pinning sets below ARE the panel API ``wiring.py``
        is textually unchanged against — the ladder-era channels
        (event_dates_moved, event_create_requested, jump_*, cover_window_
        for_span) are deleted, not stubbed."""
        import inspect

        frozen_signals = {
            "event_selected", "event_double_clicked", "add_event_requested",
            "add_entity_requested", "event_types_requested", "window_changed",
        }
        frozen_methods = {
            "update_events", "set_selected", "scroll_to_event",
        }

        marker = type(TimelineWidget.event_selected)
        signals = {n for n, v in vars(TimelineWidget).items()
                   if isinstance(v, marker)}
        methods = {
            n for n, v in vars(TimelineWidget).items()
            if inspect.isfunction(v) and not n.startswith("_")
        }

        assert signals == frozen_signals
        assert methods >= frozen_methods
        # The deleted channels stay deleted (grep-grade pin).
        assert not signals & {"event_dates_moved", "event_create_requested"}

    def test_close_defers_the_island_release(self, qtbot, root_qml):
        panel = _island(qtbot, _StubVM(), root_qml)
        assert panel.quick.rootObject() is not None
        panel.close()
        qtbot.wait(20)  # the deferred singleShot runs after the stack unwinds
        assert panel.quick.rootObject() is None


# ── 3.1 — panel API fed through the real VM ─────────────────────────────────


SPREAD = [
    _evt(1, date(1200, 1, 1), date(1200, 1, 1), name="Старт"),
    _evt(2, date(1200, 3, 1), date(1200, 3, 1), name="Середина"),
    _evt(3, date(1200, 6, 1), date(1200, 6, 1), name="Финиш"),
]
CHIP_RECT = (20.0, 30.0, 140.0, 24.0)  # a plausible chip rect in scene px


class TestPanelDataContract:
    def test_update_events_mirrors_the_window_caption(self, qtbot, root_qml):
        """The wiring's reload channel: vm.window moves, update_events mirrors
        the chrome caption (the old header-button text, now ``windowText``)."""
        vm = _real_vm(SPREAD)
        panel = _island(qtbot, vm, root_qml)
        vm.window = (date(1200, 1, 1), date(1200, 3, 9))
        panel.update_events(vm.events)
        assert panel._root.property("windowText") == "01 Январь 1200 — 09 Март 1200 ▾"
        vm.window = None  # an external reset lives past the chip
        panel.update_events(vm.events)
        assert panel._root.property("windowText") == WINDOW_CHIP_ALL

    def test_set_selected_washes_and_reveals_via_vm_index(self, qtbot, root_qml):
        vm = _real_vm(SPREAD)
        panel = _island(qtbot, vm, root_qml)
        panel.set_selected(2)
        assert panel._root.property("selectedId") == 2
        assert panel._root.property("lastScrollIndex") == vm.index_for_event(2)
        panel.set_selected(None)
        assert panel._root.property("selectedId") == -1

    def test_scroll_to_event_unknown_id_keeps_the_scroll(self, qtbot, root_qml):
        """The widget's ``scroll_to_event`` no-op 1:1: no index, no request."""
        vm = _real_vm(SPREAD)
        panel = _island(qtbot, vm, root_qml)
        panel.scroll_to_event(1)
        recorded = panel._root.property("lastScrollIndex")
        assert recorded == vm.index_for_event(1)
        panel.scroll_to_event(999)
        assert panel._root.property("lastScrollIndex") == recorded

    def test_id_contract_signals_are_forwarded(self, qtbot, root_qml):
        panel = _island(qtbot, _StubVM(), root_qml)
        clicks: list = []
        doubles: list = []
        panel.event_selected.connect(clicks.append)
        panel.event_double_clicked.connect(doubles.append)
        panel._root.eventClicked.emit(7)
        panel._root.eventDoubleClicked.emit(7)
        assert clicks == [7] and doubles == [7]

    def test_selection_missed_clears_layers_without_emitting(self, qtbot, root_qml):
        """Spec «Клик-промах сбрасывает выбор»: the wash drops, the VM drops
        the selection through its own channel (wiring mirrors the detail
        panel off ``selected_event_changed``), and NO id-contract signal
        leaves the facade."""
        vm = _real_vm(SPREAD)
        panel = _island(qtbot, vm, root_qml)
        vm.select_event_by_id(2)  # the wiring twin: the selection lives
        panel.set_selected(2)
        received: list = []
        panel.event_selected.connect(received.append)
        panel._root.selectionMissed.emit()
        assert panel._root.property("selectedId") == -1
        assert vm.selected_event is None
        assert received == []

    def test_selection_missed_is_inert_for_a_stub_vm(self, qtbot, root_qml):
        """The old widget tolerated stand-in VMs; the miss path must too."""
        panel = _island(qtbot, _StubVM(), root_qml)
        panel._root.selectionMissed.emit()
        assert panel._root.property("selectedId") == -1

    def test_stub_vm_paths_stay_inert(self, qtbot, root_qml):
        """The old widget tolerated stand-in VMs; the facade must too."""
        panel = _island(qtbot, _StubVM(), root_qml)
        panel.update_events([_evt(1, date(1200, 1, 1))])
        panel.set_selected(5)
        panel.scroll_to_event(5)
        # No invokables on the stand-in → no scroll requests were issued.
        assert panel._root.property("lastScrollIndex") == -2


class TestStandInKnobGuards:
    """The old widget survived stand-in VMs by checking knob TYPES
    (``MagicMock`` answers every attribute); the island's mirrors keep that
    acceptance — a bad knob neutralizes the sync, never crashes it."""

    class BadWindowVM:
        events: list = []
        window = "не кортеж"

    class AnsweringVM:
        """The invokable is present but answers with a stand-in object, not an index."""

        events: list = []
        rows: list = []
        window = None

        def scrollToEvent(self, event_id):
            return object()

    class RefusingSignalVM:
        """The look-alike carries an ``events_changed`` knob whose connect is
        refused — a stand-in signal double is not a Qt signal anyway."""

        class _RefusingSignal:
            def connect(self, slot):
                raise TypeError("not a Qt signal")

        events: list = []
        window = None
        events_changed = _RefusingSignal()

    class RefusingSelectVM:
        """The look-alike answers ``select_event_by_id`` but refuses the
        ``None`` a selection miss passes — the drop must swallow that."""

        events: list = []
        window = None

        def select_event_by_id(self, event_id):
            if event_id is None:
                raise TypeError("the look-alike refuses the miss")

    def test_events_changed_refused_connection_is_swallowed(self, qtbot, root_qml):
        """The subscription sits in try/except for the widget-era stand-in
        tolerance: a refused connect (TypeError/AttributeError) neither drops
        nor crashes the island — such a stand-in never fires regardless."""
        panel = _island(qtbot, self.RefusingSignalVM(), root_qml)
        assert panel._root.property("selectedId") == -1  # spun up normally

    def test_selection_missed_swallows_a_refusing_select(self, qtbot, root_qml):
        """The miss path drops through the VM in try/except too: a look-alike
        that throws TypeError on ``None`` neither drops nor crashes the island
        (the real ViewModel accepts ``None`` as a deselection)."""
        panel = _island(qtbot, self.RefusingSelectVM(), root_qml)
        panel._root.selectionMissed.emit()
        assert panel._root.property("selectedId") == -1  # wash still dropped

    def test_unrecognizable_window_neutralizes_the_mirrors(self, qtbot, root_qml):
        panel = _island(qtbot, self.BadWindowVM(), root_qml)
        panel.update_events([])
        assert panel._root.property("windowText") == ""  # never seeded, never poisoned
        assert panel._view_knobs() is timeline_island._UNREADABLE_KNOB

    def test_invokable_answering_non_index_lands_nowhere(self, qtbot, root_qml):
        panel = _island(qtbot, self.AnsweringVM(), root_qml)
        panel.set_selected(3)  # wash lands, the bogus scroll index does not
        panel.scroll_to_event(3)
        assert panel._root.property("lastScrollIndex") == -2
        assert panel._root.property("selectedId") == 3


# ── 3.4 — «Выбор даты» popover through the chip-signal entry ────────────────


def _open_via_chip(panel) -> QWidget:
    panel._root.datePopupRequested.emit(*CHIP_RECT)
    return panel.window_popup


class TestDateWindowPopupEntry:
    def test_chip_signal_opens_popover_seeded_with_the_window(self, qtbot, root_qml):
        """Task 3.4: вызов по сигналу чипа, позиция от прямоугольника чипа,
        предзаполнение текущим окном."""
        panel = _island(qtbot, _StubVM(), root_qml)
        panel._on_window_range(date(1200, 4, 3), None)
        moves: list = []
        real_move = panel.window_popup.move
        panel.window_popup.move = lambda p: (moves.append(QPoint(p)), real_move(p))[1]
        popup = _open_via_chip(panel)
        assert popup.isVisible()
        assert popup.start_calendar.selectedDate() == QDate(1200, 4, 3)
        # The move target is anchored under the chip's reported bottom-left
        # (+2px), exactly where the native-button anchor put it; X is clamped
        # into the screen, Y travels untouched (the old mechanics verbatim).
        top_left = panel.quick.mapToGlobal(QPoint(20, 30))
        assert len(moves) == 1
        assert moves[0].y() == top_left.y() + 24 + 2
        assert moves[0].x() <= top_left.x()
        popup.close()

    def test_two_taps_live_apply_through_the_old_channel(self, qtbot, root_qml):
        """Live-apply stays on the unchanged ``window_changed`` pair."""
        panel = _island(qtbot, _StubVM(), root_qml)
        received: list = []
        panel.window_changed.connect(lambda s, e: received.append((s, e)))
        popup = _open_via_chip(panel)
        popup.start_calendar.clicked.emit(QDate(1200, 1, 5))
        assert received == []  # start alone is not a window yet
        popup.start_calendar.clicked.emit(QDate(1200, 1, 9))
        assert received == [(date(1200, 1, 5), date(1200, 1, 9))]
        assert not popup.isVisible()
        assert panel._root.property("windowText") == (
            "05 Январь 1200 — 09 Январь 1200 ▾"
        )

    def test_earlier_second_tap_rearms_instead_of_backwards_range(
        self, qtbot, root_qml
    ):
        panel = _island(qtbot, _StubVM(), root_qml)
        received: list = []
        panel.window_changed.connect(lambda s, e: received.append((s, e)))
        popup = _open_via_chip(panel)
        popup.start_calendar.clicked.emit(QDate(1200, 1, 9))
        popup.start_calendar.clicked.emit(QDate(1200, 1, 3))  # earlier
        assert received == []
        assert popup._pending_start == date(1200, 1, 3)
        popup.start_calendar.clicked.emit(QDate(1200, 1, 12))
        assert received == [(date(1200, 1, 3), date(1200, 1, 12))]

    def test_finish_may_land_on_the_second_calendar(self, qtbot, root_qml):
        panel = _island(qtbot, _StubVM(), root_qml)
        received: list = []
        panel.window_changed.connect(lambda s, e: received.append((s, e)))
        popup = _open_via_chip(panel)
        popup._fit_low_screen(10_000)  # keep both calendars regardless of room
        popup.start_calendar.clicked.emit(QDate(1200, 2, 1))
        popup.end_calendar.clicked.emit(QDate(1200, 2, 20))
        assert received == [(date(1200, 2, 1), date(1200, 2, 20))]

    def test_reset_restores_all_days_and_hides(self, qtbot, root_qml):
        panel = _island(qtbot, _StubVM(), root_qml)
        _open_via_chip(panel).start_calendar.clicked.emit(QDate(1200, 1, 5))
        panel.window_popup.start_calendar.clicked.emit(QDate(1200, 1, 9))
        received: list = []
        panel.window_changed.connect(lambda s, e: received.append((s, e)))
        _open_via_chip(panel)
        panel.window_popup.reset_button.click()
        assert received == [(None, None)]
        assert not panel.window_popup.isVisible()
        assert panel._root.property("windowText") == WINDOW_CHIP_ALL

    def test_reopening_rearms_a_finished_pick(self, qtbot, root_qml):
        """open_at re-seeds the pick state through the chip entry too."""
        panel = _island(qtbot, _StubVM(), root_qml)
        popup = _open_via_chip(panel)
        popup.start_calendar.clicked.emit(QDate(1200, 1, 5))
        popup.start_calendar.clicked.emit(QDate(1200, 1, 9))
        _open_via_chip(panel)
        assert popup._pending_start is None
        popup.close()

    def test_low_screen_fallback_assigns_both_dates(self, qtbot, root_qml):
        """Fallback mechanics moved intact: one calendar, two taps assign both."""
        panel = _island(qtbot, _StubVM(), root_qml)
        popup = panel.window_popup
        popup._fit_low_screen(10_000)
        assert not popup.end_calendar.isHidden()
        popup._fit_low_screen(0)
        assert popup.end_calendar.isHidden()
        received: list = []
        panel.window_changed.connect(lambda s, e: received.append((s, e)))
        popup.start_calendar.clicked.emit(QDate(1200, 1, 1))
        popup.start_calendar.clicked.emit(QDate(1200, 1, 4))
        assert received == [(date(1200, 1, 1), date(1200, 1, 4))]


# ── 3.3 — system menus through the mocked-choice harness ────────────────────


class TestAddMenu:
    def test_items_match_the_flat_menu(self, qtbot, fake_menu, root_qml):
        """Task 3.3: ровно шесть пунктов — пять «создать» + «Типы событий…»."""
        panel = _island(qtbot, _StubVM(), root_qml)
        panel._root.addMenuRequested.emit(15.0, 25.0)
        assert len(fake_menu.menus) == 1
        menu = fake_menu.menus[0]
        assert menu.captions == [
            caption for caption, _ in ADD_MENU_ITEMS
        ] + [None, "Типы событий…"]
        assert menu.exec_pos == panel.quick.mapToGlobal(QPoint(15, 25))

    @pytest.mark.parametrize(
        "caption, event, entity",
        [
            ("Новое событие", True, None),
            ("Новый персонаж", False, "character"),
            ("Новая локация", False, "location"),
            ("Новая организация", False, "organization"),
            ("Новый предмет", False, "item"),
        ],
    )
    def test_each_item_dispatches_its_signal(
        self, qtbot, fake_menu, root_qml, caption, event, entity
    ):
        panel = _island(qtbot, _StubVM(), root_qml)
        events: list = []
        entities: list = []
        panel.add_event_requested.connect(lambda: events.append(None))
        panel.add_entity_requested.connect(entities.append)
        fake_menu.decide = lambda menu, c=caption: menu.pick(c)
        panel._root.addMenuRequested.emit(0.0, 0.0)
        assert len(events) == (1 if event else 0)
        assert entities == ([entity] if entity else [])

    def test_types_item_and_cancel(self, qtbot, fake_menu, root_qml):
        panel = _island(qtbot, _StubVM(), root_qml)
        types: list = []
        panel.event_types_requested.connect(lambda: types.append(None))
        fake_menu.decide = lambda menu: menu.pick("Типы событий…")
        panel._root.addMenuRequested.emit(0.0, 0.0)
        assert types == [None]
        # Esc/промах = cancel без emit (task 3.3): the picked action is None.
        fake_menu.decide = lambda menu: None
        panel._root.addMenuRequested.emit(0.0, 0.0)
        assert types == [None]
        # …and an action from another menu is ignored as well.
        stray = QAction("чужое", None)
        fake_menu.decide = lambda menu: stray
        panel._root.addMenuRequested.emit(0.0, 0.0)
        assert types == [None]
