"""Facade tests for the timeline QML island (Q2.5a tasks 3.1–3.4).

The island root arrives with group 4, so these tests drive the facade against
a STUB root QML declaring the exact contract the facade wires against (module
docstring of ``timeline_island``) — everything on the Python side (context
properties, the 1:1 panel API, the system menus, the migrated date-window
popover, the Alt+Up/Down shortcuts) is exercised for real; only the QML-side
rendering is stubbed away.

Entry points follow the migrated contract (task 3.2): the chip popover is
triggered by the root's ``datePopupRequested`` signal with QML-reported scene
coordinates, the menus by ``addMenuRequested``/``dropMenuRequested`` (QMenu
mocked for the selection, mirroring the planned acceptance harness), and the
date-window mechanics tests moved with the new popup module. Real
``TimelineViewModel``s drive the data paths (the ``test_timeline_scale_widget``
pattern); stand-in VMs pin the defensive guards.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QDate, QEvent, QPoint, Qt
from PySide6.QtGui import QAction, QKeyEvent
from PySide6.QtWidgets import QApplication, QWidget

from app.presentation.utils.date_utils import get_custom_months, set_custom_months
from app.presentation.viewmodels.timeline_viewmodel import TimelineViewModel
from app.presentation.views import timeline_island
from app.presentation.views.timeline_date_popup import WINDOW_CHIP_ALL, window_chip_text
from app.presentation.views.timeline_island import ADD_MENU_ITEMS, TimelineWidget
from app.presentation.views.timeline_rows import (
    DayHeaderRow, EmptyDayRow, GapCollapsedRow, ScaleUnit, apply_drop_action,
)

ROOT_QML_STUB = """
import QtQuick

Item {
    id: root
    objectName: "timelineRootStub"
    implicitWidth: 300
    implicitHeight: 200

    // Chrome surface the facade writes (windowText/hideEmpty/selectedId)
    // plus the scroll-request recording pin of the stub itself.
    property string windowText: ""
    property bool hideEmpty: false
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
    signal datePopupRequested(int gapIndex, real x, real y, real width, real height)
    signal hideEmptyToggled(bool checked)
    signal eventClicked(int eventId)
    signal eventDoubleClicked(int eventId)
    signal inlineCreateCommitted(int dayIndex, string name)
    signal dropMenuRequested(int eventId, int targetIndex, real x, real y)
    signal jumpRequested(int step)
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


def _evt(eid: int, start: date, end: date | None = None, name: str | None = None):
    return SimpleNamespace(id=eid, name=name or f"event-{eid}", start_date=start, end_date=end)


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
    """The old widget-test stand-in: no knobs a ladder recognizes."""

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


def _press(widget, key: int) -> None:
    """Real Alt+key events through the app dispatcher, as the shortcut needs."""
    for etype in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        QApplication.sendEvent(
            widget, QKeyEvent(etype, key, Qt.KeyboardModifier.AltModifier)
        )


# ── 3.1 — construction, context contract, teardown ──────────────────────────


class TestIslandConstruction:
    def test_island_loads_ready_with_the_context_contract(self, qtbot, root_qml):
        vm = _real_vm([_evt(1, date(1200, 1, 5))])
        panel = _island(qtbot, vm, root_qml)
        assert panel.quick.status() == timeline_island.QQuickWidget.Status.Ready
        assert panel._root.objectName() == "timelineRootStub"
        context = panel.quick.rootContext()
        # The context names every island binds against (design D1/D9/D2) —
        # read through the stub root's own scope (typeof per name).
        assert panel._root.property("contextNames") == "object,object,object"
        assert context is not None
        # Token bridge and VM outlive the island at teardown: the palette is
        # parented to the panel AFTER the island widget was constructed, so
        # child destruction takes the island first (module docstring).
        assert panel._palette.parent() is panel

    def test_missing_root_qml_asserts_ready(self, qtbot, tmp_path):
        # Honest failure pinned by the launcher precedent: a root that cannot
        # load must abort construction, never open an empty panel.
        host = QWidget()
        qtbot.addWidget(host)
        with pytest.raises(AssertionError):
            TimelineWidget(_StubVM(), parent=host,
                           root_qml=str(tmp_path / "TimelineRoot.qml"))

    def test_public_surface_is_1to1_with_the_migrated_widget(self):
        """Task 3.1 «публичные методы/сигналы — 1:1 текущего виджета».

        The widgets widget died with task 5.2, so its former surface is now
        the frozen contract it was ported from (wiring textually unchanged,
        design D1): the pinned sets below ARE the migrated panel's API.
        """
        import inspect

        frozen_signals = {
            "event_selected", "event_double_clicked", "add_event_requested",
            "add_entity_requested", "event_types_requested", "window_changed",
            "event_dates_moved", "event_create_requested",
        }
        frozen_methods = {
            "update_events", "set_selected", "scroll_to_event",
            "jump_prev_event", "jump_next_event", "cover_window_for_span",
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
GAP_EVENTS = [
    _evt(1, date(1200, 1, 1), date(1200, 1, 1)),
    _evt(2, date(1200, 3, 10), date(1200, 3, 10)),
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
        vm.window = None  # an external descent resets past the chip
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

    def test_inline_create_resolves_day_and_forwards(self, qtbot, root_qml):
        # Two close events keep Jan 2–4 as (uncollapsed) empty days to click.
        vm = _real_vm([
            _evt(1, date(1200, 1, 1), date(1200, 1, 1)),
            _evt(2, date(1200, 1, 5), date(1200, 1, 5)),
        ])
        panel = _island(qtbot, vm, root_qml)
        received: list = []
        panel.event_create_requested.connect(lambda day, name: received.append((day, name)))
        empty_idx = next(
            i for i, r in enumerate(vm.rows) if isinstance(r, EmptyDayRow)
        )
        panel._root.inlineCreateCommitted.emit(empty_idx, "  заяц  ")
        assert received == [(vm.rows[empty_idx].date, "заяц")]
        # Esc/пусто (task 4.4 contract): blank commits nothing, off-row index
        # and unknown index stay silent too.
        panel._root.inlineCreateCommitted.emit(empty_idx, "   ")
        panel._root.inlineCreateCommitted.emit(10_000, "ёж")
        assert len(received) == 1

    def test_hide_empty_toggle_writes_the_vm(self, qtbot, root_qml):
        """Task 7.3 channel kept 1:1: QML toggle → VM knob → remodel. The
        collapsed gap of GAP_EVENTS is the empty position the toggle cuts."""
        vm = _real_vm(GAP_EVENTS)
        assert any(isinstance(r, GapCollapsedRow) for r in vm.rows)
        panel = _island(qtbot, vm, root_qml)
        before = vm.row_model.rowCount()
        panel._root.hideEmptyToggled.emit(True)
        assert vm.hide_empty is True
        assert panel._root.property("hideEmpty") is True
        assert vm.row_model.rowCount() < before
        panel._root.hideEmptyToggled.emit(False)
        assert vm.row_model.rowCount() == before

    def test_stub_vm_paths_stay_inert(self, qtbot, root_qml):
        """The old widget tolerated stand-in VMs; the facade must too."""
        panel = _island(qtbot, _StubVM(), root_qml)
        panel.update_events([_evt(1, date(1200, 1, 1))])
        panel.set_selected(5)
        panel.scroll_to_event(5)
        panel.jump_prev_event()
        panel.jump_next_event()
        # No invokables on the stand-in → no scroll requests were issued.
        assert panel._root.property("lastScrollIndex") == -2

    def test_find_event_falls_back_to_the_visible_sample(self, qtbot, root_qml):
        """Records resolve from ``vm.events`` when the VM owns no whole-sample
        view (the move-commit lookup never keeps a panel-side copy)."""
        class EventsVM:
            events = [_evt(1, date(1200, 1, 1), date(1200, 1, 1))]

        panel = _island(qtbot, EventsVM(), root_qml)
        assert panel._find_event(1) is EventsVM.events[0]
        assert panel._find_event(42) is None


class TestStandInKnobGuards:
    """The old widget survived stand-in VMs by checking knob TYPES
    (``MagicMock`` answers every attribute); the island's mirrors keep that
    acceptance — bad knobs neutralize the sync, never crash it."""

    class BadWindowVM:
        events: list = []
        level = ScaleUnit.DAY
        window = "не кортеж"
        hide_empty = False

    class BadHideVM:
        events: list = []
        level = ScaleUnit.DAY
        window = None
        hide_empty = "ложь"

    class AnsweringVM:
        """Invokables are present but answer with stand-in objects, not indices."""

        events: list = []
        rows: list = []
        level = ScaleUnit.DAY
        window = None
        hide_empty = False

        def jump(self, step):
            return object()

        def scrollToEvent(self, event_id):
            return object()

    class RefusingSignalVM:
        """The look-alike carries an ``events_changed`` knob whose connect is
        refused — a stand-in signal double is not a Qt signal anyway."""

        class _RefusingSignal:
            def connect(self, slot):
                raise TypeError("not a Qt signal")

        events: list = []
        level = ScaleUnit.DAY
        window = None
        hide_empty = False
        events_changed = _RefusingSignal()

    def test_events_changed_refused_connection_is_swallowed(self, qtbot, root_qml):
        """The subscription sits in try/except for the widget-era stand-in
        tolerance: a refused connect (TypeError/AttributeError) neither drops
        nor crashes the island — such a stand-in never fires regardless."""
        panel = _island(qtbot, self.RefusingSignalVM(), root_qml)
        assert panel._root.property("selectedId") == -1  # spun up normally

    def test_unrecognizable_window_neutralizes_the_mirrors(self, qtbot, root_qml):
        panel = _island(qtbot, self.BadWindowVM(), root_qml)
        panel.update_events([])
        assert panel._root.property("windowText") == ""  # never seeded, never poisoned
        assert panel._view_knobs() is None

    def test_unrecognizable_hide_empty_neutralizes_the_mirrors(self, qtbot, root_qml):
        panel = _island(qtbot, self.BadHideVM(), root_qml)
        assert panel._root.property("windowText") == WINDOW_CHIP_ALL  # real None
        assert panel._root.property("hideEmpty") is False  # truthy stand-in ≠ True
        panel.update_events([])
        assert panel._root.property("hideEmpty") is False

    def test_invokables_answering_non_indices_land_nowhere(self, qtbot, root_qml):
        panel = _island(qtbot, self.AnsweringVM(), root_qml)
        panel.set_selected(3)  # wash lands, the bogus scroll index does not
        panel.scroll_to_event(3)
        panel.jump_prev_event()
        panel.jump_next_event()
        assert panel._root.property("lastScrollIndex") == -2
        assert panel._root.property("selectedId") == 3


# ── 3.2 — «Выбор даты» popover through the chip-signal entry ────────────────


def _open_via_chip(panel) -> QWidget:
    panel._root.datePopupRequested.emit(-1, *CHIP_RECT)
    return panel.window_popup


class TestDateWindowPopupEntry:
    def test_chip_signal_opens_popover_seeded_with_the_window(self, qtbot, root_qml):
        """Task 3.2: вызов по сигналу чипа, позиция от прямоугольника чипа,
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
        """open_at re-seeds the pick state through the new entry too."""
        panel = _island(qtbot, _StubVM(), root_qml)
        popup = _open_via_chip(panel)
        popup.start_calendar.clicked.emit(QDate(1200, 1, 5))
        popup.start_calendar.clicked.emit(QDate(1200, 1, 9))
        _open_via_chip(panel)
        assert popup._pending_start is None
        popup.close()

    def test_gap_click_reopens_prefilled_without_applying(self, qtbot, root_qml):
        """Spec «Схлопнутый провал кликабелен для окна»: the gap delegate's
        reported row index seeds the bounds — the chip position is kept."""
        vm = _real_vm(GAP_EVENTS)
        panel = _island(qtbot, vm, root_qml)
        gap_idx = next(
            i for i, r in enumerate(vm.rows) if isinstance(r, GapCollapsedRow)
        )
        gap = vm.rows[gap_idx]
        received: list = []
        panel.window_changed.connect(lambda s, e: received.append((s, e)))
        panel._root.datePopupRequested.emit(gap_idx, *CHIP_RECT)
        popup = panel.window_popup
        assert popup.isVisible()
        assert popup.start_calendar.selectedDate() == QDate(
            gap.date.year, gap.date.month, gap.date.day
        )
        assert popup.end_calendar.selectedDate() == QDate(
            gap.end.year, gap.end.month, gap.end.day
        )
        assert received == []  # a pre-fill is not an application
        popup.close()

    def test_invalid_gap_index_falls_back_to_the_applied_window(
        self, qtbot, root_qml
    ):
        vm = _real_vm(GAP_EVENTS)
        panel = _island(qtbot, vm, root_qml)
        panel._on_window_range(date(1200, 2, 1), date(1200, 2, 2))
        header_idx = next(i for i, r in enumerate(vm.rows) if isinstance(r, DayHeaderRow))
        panel._root.datePopupRequested.emit(header_idx, *CHIP_RECT)
        popup = panel.window_popup
        # the reported row is no gap → the chip semantics (current window) seed
        assert popup.start_calendar.selectedDate() == QDate(1200, 2, 1)
        assert popup.end_calendar.selectedDate() == QDate(1200, 2, 2)
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


class TestCoverWindowForSpan:
    def test_expansion_rides_the_window_channel(self, qtbot, root_qml):
        panel = _island(qtbot, _StubVM(), root_qml)
        received: list = []
        panel.window_changed.connect(lambda s, e: received.append((s, e)))
        # No window yet: pure no-op (spec «Унос за окно …» only widens live).
        panel.cover_window_for_span(date(1200, 1, 5), date(1200, 1, 9))
        assert received == []
        panel._on_window_range(date(1200, 2, 1), date(1200, 2, 10))
        panel.cover_window_for_span(date(1200, 1, 25), None)
        assert received[-1] == (date(1200, 1, 25), date(1200, 2, 10))
        assert panel._root.property("windowText") == window_chip_text(
            date(1200, 1, 25), date(1200, 2, 10)
        )
        # A span fully inside the window: nothing happens.
        n = len(received)
        panel.cover_window_for_span(date(1200, 2, 3), date(1200, 2, 4))
        assert len(received) == n


# ── 3.3 — system menus through the mocked-choice harness ────────────────────


class TestAddMenu:
    def test_items_match_the_migrated_menu(self, qtbot, fake_menu, root_qml):
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


class TestDropMenu:
    # The tape stays materialized where the tests drop: Jan 10–20 is one
    # covered span (Jan 15 lives inside it), Jan 21–24 empty days survive the
    # 14-day collapse threshold, and the open June event owns cards down the
    # tape. The long emptiness after Jan 25 is exactly the collapsed run the
    # gesture must refuse.
    CLOSED = [
        _evt(1, date(1200, 1, 10), date(1200, 1, 20)),
        _evt(2, date(1200, 1, 25), date(1200, 1, 25)),
        _evt(3, date(1200, 6, 1)),  # open — its cards run the tape to the bottom
    ]

    def _panel(self, qtbot, root_qml):
        vm = _real_vm(self.CLOSED)
        return _island(qtbot, vm, root_qml), vm

    def _day_index(self, vm, day: date) -> int:
        return next(
            i for i, r in enumerate(vm.rows)
            if isinstance(r, DayHeaderRow) and r.date == day
        )

    def test_items_follow_the_core_verdict(self, qtbot, fake_menu, root_qml):
        panel, vm = self._panel(qtbot, root_qml)
        # Below the end → «Перенести» + «Расширить вниз…»; «Начать раньше» absent.
        panel._root.dropMenuRequested.emit(1, self._day_index(vm, date(1200, 1, 23)), 0, 0)
        assert fake_menu.menus[0].captions == [
            "Перенести", "Расширить вниз до этого дня",
        ]
        # Above the start → «Перенести» + «Начать раньше…».
        panel._root.dropMenuRequested.emit(2, self._day_index(vm, date(1200, 1, 12)), 0, 0)
        assert fake_menu.menus[1].captions == [
            "Перенести", "Начать раньше в этом дне",
        ]
        # Inside the span → «Перенести» alone; an open event never extends.
        panel._root.dropMenuRequested.emit(1, self._day_index(vm, date(1200, 1, 15)), 0, 0)
        assert fake_menu.menus[2].captions == ["Перенести"]
        panel._root.dropMenuRequested.emit(3, self._day_index(vm, date(1200, 6, 5)), 0, 0)
        assert fake_menu.menus[3].captions == ["Перенести"]

    def test_choice_commits_through_event_dates_moved(self, qtbot, fake_menu, root_qml):
        panel, vm = self._panel(qtbot, root_qml)
        received: list = []
        panel.event_dates_moved.connect(lambda *a: received.append(a))
        target = date(1200, 1, 23)
        source = next(e for e in vm.all_events if e.id == 1)
        fake_menu.decide = lambda menu: menu.pick("Расширить вниз до этого дня")
        panel._root.dropMenuRequested.emit(1, self._day_index(vm, target), 33.0, 44.0)
        expected = apply_drop_action(source, "extend_down", target)
        assert received == [(1, expected[0], expected[1])]
        assert fake_menu.menus[0].exec_pos == panel.quick.mapToGlobal(QPoint(33, 44))

    def test_close_without_choice_emits_nothing(self, qtbot, fake_menu, root_qml):
        """Esc/промах = cancel без emit (task 3.3 / spec «без действия»)."""
        panel, vm = self._panel(qtbot, root_qml)
        received: list = []
        panel.event_dates_moved.connect(lambda *a: received.append(a))
        fake_menu.decide = lambda menu: None
        panel._root.dropMenuRequested.emit(1, self._day_index(vm, date(1200, 1, 23)), 0, 0)
        assert fake_menu.menus[0].exec_calls == 1
        assert received == []

    def test_gap_target_never_opens_a_menu(self, qtbot, fake_menu, root_qml):
        """The old list's acceptance stays enforced: gaps cancel silently."""
        panel, vm = self._panel(qtbot, root_qml)
        received: list = []
        panel.event_dates_moved.connect(lambda *a: received.append(a))
        fake_menu.decide = lambda menu: menu.pick("Перенести")
        gap_idx = next(i for i, r in enumerate(vm.rows) if isinstance(r, GapCollapsedRow))
        panel._root.dropMenuRequested.emit(1, gap_idx, 0, 0)
        panel._root.dropMenuRequested.emit(1, 10_000, 0, 0)  # off-tape too
        panel._root.dropMenuRequested.emit(99, self._day_index(vm, date(1200, 1, 23)), 0, 0)
        assert fake_menu.menus == [] and received == []


# ── 3.4 — Alt+Up/Down jump shortcuts, «jump никогда не выбирает» ────────────


class TestJumpShortcuts:
    def _focused(self, qtbot, root_qml, events=SPREAD):
        vm = _real_vm(events)
        panel = _island(qtbot, vm, root_qml)
        panel.quick.setFocus(Qt.FocusReason.OtherFocusReason)
        QApplication.processEvents()
        return panel, vm

    def _pressed_scroll(self, panel, key: int) -> int:
        before = panel._root.property("lastScrollIndex")
        _press(panel.quick, key)
        assert panel._root.property("lastScrollIndex") != before
        return panel._root.property("lastScrollIndex")

    def test_alt_shortcuts_walk_event_cards(self, qtbot, root_qml):
        """Task 3.4: Alt+Down/Alt+Up are the shortcut twins of the jump path."""
        panel, vm = self._focused(qtbot, root_qml)
        landed = self._pressed_scroll(panel, Qt.Key.Key_Down)
        assert landed == vm.index_for_event(1)
        landed = self._pressed_scroll(panel, Qt.Key.Key_Down)
        assert landed == vm.index_for_event(2)
        landed = self._pressed_scroll(panel, Qt.Key.Key_Up)
        assert landed == vm.index_for_event(1)

    def test_jump_never_selects_never_emits(self, qtbot, root_qml):
        """Navigation is not selection (D8): every layer of the id-contract
        stays put while the tape walks."""
        panel, vm = self._focused(qtbot, root_qml)
        received: list = []
        selected_changed: list = []
        panel.event_selected.connect(received.append)
        vm.selected_event_changed.connect(lambda: selected_changed.append(None))
        self._pressed_scroll(panel, Qt.Key.Key_Down)
        self._pressed_scroll(panel, Qt.Key.Key_Down)
        assert received == []
        assert selected_changed == []
        assert vm.selected_event is None
        assert panel._root.property("selectedId") == -1

    def test_inert_at_the_head(self, qtbot, root_qml):
        """Spec «Навигация к событиям»: бездействие на краю ленты."""
        panel, vm = self._focused(qtbot, root_qml)
        self._pressed_scroll(panel, Qt.Key.Key_Down)  # → the head card
        recorded = panel._root.property("lastScrollIndex")
        assert recorded == vm.index_for_event(1)
        _press(panel.quick, Qt.Key.Key_Up)  # no event above: inert
        assert panel._root.property("lastScrollIndex") == recorded

    def test_period_rung_descent_then_jump(self, qtbot, root_qml):
        """The old ``_descend_for_jump`` retry, facade-side: a counter rung has
        no cards, the jump drops the ladder to DAY and lands."""
        panel, vm = self._focused(qtbot, root_qml)
        vm.level = ScaleUnit.MONTH
        panel._sync_from_vm()
        _press(panel.quick, Qt.Key.Key_Down)
        assert vm.level is ScaleUnit.DAY
        assert panel._root.property("lastScrollIndex") == vm.index_for_event(1)

    def test_jump_button_channel_is_the_same_path(self, qtbot, root_qml):
        """Header buttons (QML D6) reach the same jump commands as Alt+keys."""
        panel, vm = self._focused(qtbot, root_qml, [])
        panel.jump_next_event()  # empty tape: nothing explodes, no scroll
        assert panel._root.property("lastScrollIndex") == -2
        # (SPREAD) jumpRequested(step) mirrors prev/next buttons.
        panel2, vm2 = self._focused(qtbot, root_qml)
        panel2._root.jumpRequested.emit(1)
        assert panel2._root.property("lastScrollIndex") == vm2.index_for_event(1)
        panel2._root.jumpRequested.emit(-1)
        assert panel2._root.property("lastScrollIndex") == vm2.index_for_event(1)
