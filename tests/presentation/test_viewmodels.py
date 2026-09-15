"""Tests for ViewModels — TDD: tests first."""
import gc
import weakref
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.presentation.viewmodels.timeline_viewmodel import (
    TimelineViewModel,
    _RowEntry,
)
from app.presentation.viewmodels.detail_viewmodel import DetailViewModel
from app.presentation.viewmodels.search_viewmodel import SearchViewModel
from app.presentation.viewmodels.event_dialog_viewmodel import EventDialogViewModel
from app.presentation.viewmodels.entity_viewmodel import EntityViewModel
from app.presentation.utils.date_utils import get_custom_months, set_custom_months
from app.presentation.views.timeline_rows import build_rows


@pytest.fixture(autouse=True)
def _default_game_months():
    """Rows now carry game-formatted captions — pin the default month map
    around every unit regardless of what other suites left in the shared
    module state."""
    saved = get_custom_months()
    set_custom_months(None)
    yield
    set_custom_months(saved)


def _mock_event(id_=1, name="Battle"):
    e = MagicMock()
    e.id = id_
    e.name = name
    e.start_date = date(1200, 1, 1)
    e.end_date = date(1200, 12, 31)
    e.event_type = None
    e.description = None
    e.organizations = []
    e.characters = []
    e.items = []
    e.locations = []
    return e


def _span(id_, name, start, end, description=None):
    """Plain event double on explicit dates (the flat core reads id/dates/name,
    the type token and the description off it — all three pinned here)."""
    e = MagicMock()
    e.id = id_
    e.name = name
    e.start_date = start
    e.end_date = end
    e.event_type = None
    e.description = description
    return e


# ── TimelineViewModel ────────────────────────────────────────────────────

class TestTimelineViewModel:
    @staticmethod
    def _w2_events():
        """Two one-day events in distinct months of 1200 (January + March)."""
        e1 = _span(1, "Winter council", date(1200, 1, 5), date(1200, 1, 5))
        e2 = _span(2, "Spring fair", date(1200, 3, 7), date(1200, 3, 7))
        return e1, e2

    @staticmethod
    def _vm_with(*events):
        service = AsyncMock()
        service.get_all_events.return_value = list(events)
        return service, TimelineViewModel(service)

    @pytest.mark.asyncio
    async def test_load_events(self):
        service = AsyncMock()
        service.get_all_events.return_value = [_mock_event(1), _mock_event(2, "Siege")]
        vm = TimelineViewModel(service)
        await vm.load_events()
        assert len(vm.events) == 2

    def test_view_state_defaults_and_is_not_serialized(self):
        """View state is session-only: a window set on one ViewModel leaves a
        freshly constructed one on «Все дни» with an empty list — nothing is
        restored from anywhere (the ladder rung and hide-empty toggle retired
        with the ladder itself)."""
        service, _ = self._vm_with()
        first = TimelineViewModel(service)
        first.window = (date(1200, 1, 1), date(1200, 3, 31))

        reopened = TimelineViewModel(service)
        assert reopened.window is None
        assert reopened.events == []
        assert reopened.rows == []
        assert reopened.selected_event is None
        assert not hasattr(first, "level")  # the ladder knob is gone for real

    @pytest.mark.asyncio
    async def test_reload_keeps_the_window_and_its_cut(self):
        """Design D3: the «Выбор даты» window lives on for the session across
        reloads and keeps cutting the same sample."""
        e1, _ = self._w2_events()
        service, vm = self._vm_with(e1)
        await vm.load_events()
        vm.window = (date(1200, 1, 1), date(1200, 1, 31))

        await vm.load_events()

        assert vm.window == (date(1200, 1, 1), date(1200, 1, 31))
        assert [e.id for e in vm.events] == [1]

    # ── selection (W3 id-contract) ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_select_event_by_id(self):
        service = AsyncMock()
        events = [_mock_event(1), _mock_event(2, "Siege")]
        service.get_all_events.return_value = events
        vm = TimelineViewModel(service)
        await vm.load_events()
        signals: list = []
        vm.selected_event_changed.connect(lambda: signals.append(1))
        vm.select_event_by_id(2)
        assert vm.selected_event.id == 2
        assert signals == [1]

    @pytest.mark.asyncio
    async def test_select_event_by_id_missing_clears(self):
        service = AsyncMock()
        events = [_mock_event(1)]
        service.get_all_events.return_value = events
        vm = TimelineViewModel(service)
        await vm.load_events()
        vm.select_event_by_id(1)
        assert vm.selected_event.id == 1
        # a miss resets the selection (same emitting semantics as before)
        vm.select_event_by_id(999)
        assert vm.selected_event is None

    @pytest.mark.asyncio
    async def test_unknown_id_miss_clears_without_touching_the_window(self):
        """A miss is nobody's business to reset the window for: an id no event
        owns clears the selection (announced) and leaves the window exactly
        where it was."""
        e1, _ = self._w2_events()
        service, vm = self._vm_with(e1)
        await vm.load_events()
        vm.window = (date(1200, 1, 1), date(1200, 1, 31))
        selection_signals: list = []
        vm.selected_event_changed.connect(lambda: selection_signals.append(1))

        vm.select_event_by_id(999)

        assert vm.selected_event is None
        assert selection_signals == [1]  # the clear is announced (panel follows)
        assert vm.window == (date(1200, 1, 1), date(1200, 1, 31))

    @pytest.mark.asyncio
    async def test_reload_keeps_selection_that_is_still_visible(self):
        service = AsyncMock()
        service.get_all_events.return_value = [_mock_event(1), _mock_event(2, "Siege")]
        vm = TimelineViewModel(service)
        await vm.load_events()
        vm.select_event_by_id(2)
        signals: list = []
        vm.selected_event_changed.connect(lambda: signals.append(1))

        await vm.load_events()  # mutation reload: the ids are still visible

        assert vm.selected_event.id == 2
        assert signals == [1]  # re-asserted once, never pruned

    # ── external selections and the window (task 2.1, design D3) ────────────

    @pytest.mark.asyncio
    async def test_external_selection_inside_window_keeps_window(self):
        """An event already visible inside the window is selected without
        spending a reset: neither the window nor the rows move (spec «Клик по
        строке» / «Selection from search» inside the window)."""
        e1, _ = self._w2_events()
        service, vm = self._vm_with(e1)
        await vm.load_events()
        vm.window = (date(1200, 1, 1), date(1200, 1, 31))
        rows_before = vm.rows
        events_signals: list = []
        vm.events_changed.connect(lambda: events_signals.append(1))

        vm.select_event_by_id(e1.id)

        assert vm.selected_event is e1
        assert vm.window == (date(1200, 1, 1), date(1200, 1, 31))
        assert vm.rows is rows_before  # nothing to re-model for it
        assert events_signals == []  # selecting never re-models rows

    @pytest.mark.asyncio
    async def test_external_selection_outside_window_resets_window_then_selects(self):
        """«Выбор вне окна сбрасывает окно»: an event the window excludes is
        not represented → window=None («Все дни») and only then the selection;
        the re-model (``events_changed``) precedes the selection assertion
        (spec «Внешний выбор вне окна сбрасывает окно»)."""
        e1, e2 = self._w2_events()
        service, vm = self._vm_with(e1, e2)
        await vm.load_events()
        vm.window = (date(1200, 1, 1), date(1200, 1, 31))  # e2 sits outside it
        events_signals: list = []
        selection_signals: list = []
        vm.events_changed.connect(lambda: events_signals.append(1))
        vm.selected_event_changed.connect(lambda: selection_signals.append(1))

        vm.select_event_by_id(e2.id)

        assert vm.window is None  # reset to «Все дни»
        assert vm.selected_event is e2
        assert e2.id in [r.event_id for r in vm.rows]
        assert events_signals == [1]  # rows re-modelled before the selection
        assert selection_signals == [1]

    # ── window semantics (design D1/D3, spec «Окно фильтрации…») ────────────

    @pytest.mark.asyncio
    async def test_window_keeps_one_row_of_every_crossing_event(self):
        """Spec «Пересекающее событие видно в окне»: an event starting before
        and ending inside the window stays with its SINGLE row; a fully
        outside event leaves the sample — and a multi-day event is never
        duplicated per day."""
        crossing = _span(1, "Crossing", date(1200, 7, 1), date(1200, 9, 5))
        outside = _span(2, "Outside", date(1201, 5, 1), date(1201, 5, 9))
        service, vm = self._vm_with(crossing, outside)
        await vm.load_events()

        vm.window = (date(1200, 8, 10), date(1200, 8, 20))

        assert [e.id for e in vm.events] == [1]
        assert [r.event_id for r in vm.rows] == [1]  # one row, not one per day

    @pytest.mark.asyncio
    async def test_open_event_is_visible_in_a_later_window(self):
        """«Бессрочное видно в окне»: an open end crosses every window at/after
        its start; the row is the ∞ caption, no closing date is invented."""
        open_end = _span(1, "Осада", date(1200, 1, 1), None)
        ended = _span(2, "Пир", date(1200, 8, 1), date(1200, 8, 5))
        service, vm = self._vm_with(open_end, ended)
        await vm.load_events()

        vm.window = (date(1200, 8, 10), date(1200, 8, 20))

        assert [e.id for e in vm.events] == [1]
        assert [r.caption for r in vm.rows] == ["01 Январь 1200 — ∞ · Осада"]

    @pytest.mark.asyncio
    async def test_empty_window_prunes_selection_without_placeholders(self):
        """A valid window with no crossing events shows NOTHING (no empty-day
        placeholders exist any more), and the selection the window excluded
        resets in every layer, announced; it does not revive on its own when
        the events return (spec «Окно исключило выбранное событие»)."""
        e1, e2 = self._w2_events()
        service, vm = self._vm_with(e1, e2)
        await vm.load_events()
        vm.window = (date(1200, 1, 1), date(1200, 1, 31))  # e1 in, e2 out
        assert [e.id for e in vm.events] == [e1.id]
        vm.select_event_by_id(e1.id)  # the selected event is inside the window
        prune_signals: list = []
        vm.selected_event_changed.connect(lambda: prune_signals.append(1))

        vm.window = (date(1200, 2, 1), date(1200, 2, 3))

        assert vm.events == []
        assert vm.rows == []  # the flat list paints no placeholder rows
        assert vm.row_model.rowCount() == 0  # …and the island model agrees
        assert vm.selected_event is None  # excluded → dropped in every layer
        assert prune_signals == [1]  # …and the drop is announced (panel follows)

        # …and the selection does not revive on its own when the events return
        vm.window = None
        assert vm.selected_event is None
        assert [e.id for e in vm.events] == [e1.id, e2.id]

    @pytest.mark.asyncio
    async def test_window_setter_emits_once_and_same_value_is_noop(self):
        """The window setter re-models ``rows`` and announces them exactly
        once; an unchanged window is a complete no-op."""
        e1, _ = self._w2_events()
        service, vm = self._vm_with(e1)
        await vm.load_events()
        signals: list = []
        vm.events_changed.connect(lambda: signals.append(1))

        vm.window = (date(1200, 1, 1), date(1200, 1, 31))
        assert signals == [1]

        vm.window = (date(1200, 1, 1), date(1200, 1, 31))  # the same window
        assert signals == [1]  # no rebuild, no echo

    # ── rows projection via the flat core (design D1/D3) ─────────────────────

    @pytest.mark.asyncio
    async def test_rows_are_one_per_event_sorted_by_start_then_id(self):
        """The rows are exactly ``build_rows`` over the visible sample: one
        row per event, ``(start_date, id)`` ascending regardless of input
        order; empty days are never enumerated."""
        e3 = _span(3, "Third", date(1200, 1, 3), date(1200, 1, 3))
        e_late_id = _span(9, "Late id, same day", date(1200, 1, 1), date(1200, 1, 2))
        e_first = _span(4, "First", date(1200, 1, 1), date(1200, 1, 1))
        service, vm = self._vm_with(e3, e_late_id, e_first)

        await vm.load_events()

        assert [(r.start, r.event_id) for r in vm.rows] == [
            (date(1200, 1, 1), 4),
            (date(1200, 1, 1), 9),
            (date(1200, 1, 3), 3),
        ]
        assert vm.rows == build_rows(vm.events, vm.window)

    @pytest.mark.asyncio
    async def test_rows_without_events_without_window_are_empty(self):
        """No events → no rows (the text hint is the view's overlay, not a
        row)."""
        service = AsyncMock()
        service.get_all_events.return_value = []
        vm = TimelineViewModel(service)

        await vm.load_events()

        assert vm.rows == []
        assert vm.row_model.rowCount() == 0

    @pytest.mark.asyncio
    async def test_rows_are_recomputed_on_window_clear(self):
        """Clearing the window returns every event to the list, consistent
        with the recomputed ``events``."""
        e1 = _span(1, "Only", date(1300, 1, 1), date(1300, 1, 1))
        service, vm = self._vm_with(e1)

        await vm.load_events()
        vm.window = (date(1200, 1, 1), date(1200, 1, 2))  # beyond event e1
        assert vm.rows == []

        vm.window = None  # «Все дни»: the window resets

        assert [e.id for e in vm.events] == [1]
        assert [(r.start, r.event_id) for r in vm.rows] == [(date(1300, 1, 1), 1)]

    @pytest.mark.asyncio
    async def test_identical_reload_does_not_rebuild_rows(self):
        """The ``_version_of`` memo behind the rows re-model (design «update_events
        no-op for the same slice»): an identical sample at an identical window
        rebuilds nothing; a window change does (so the memo never swallows the
        new cut)."""
        e1, e2 = self._w2_events()
        service, vm = self._vm_with(e1, e2)
        await vm.load_events()
        rows_before = vm.rows

        await vm.load_events()  # identical sample, window the same

        assert vm.rows is rows_before  # no re-model: the same row list

        vm.window = (date(1200, 1, 1), date(1200, 1, 31))  # the new key field

        assert vm.rows is not rows_before
        assert [e.id for e in vm.events] == [e1.id]

    @pytest.mark.asyncio
    async def test_mixed_era_sample_orders_rows_by_chronological_moment(self):
        """add-era-aware-dates 4.2: the VM projects rows through the shared era
        key — 500 г. до н.э. precedes 1 г. н.э. and 2026, ties break by id."""
        bc_early = _span(1, "Эллины", date(500, 1, 1), None)
        bc_early.start_bc = True
        bc_late = _span(2, "Римляне", date(1, 12, 31), None)
        bc_late.start_bc = True
        ce = _span(3, "Наши дни", date(2026, 1, 1), None)
        same_moment_a = _span(5, "Дубль b", date(1, 12, 31), None)
        same_moment_a.start_bc = True
        service, vm = self._vm_with(ce, bc_late, bc_early, same_moment_a)

        await vm.load_events()

        assert [r.event_id for r in vm.rows] == [1, 2, 5, 3]

    @pytest.mark.asyncio
    async def test_window_across_the_era_border_cuts_both_eras(self):
        """Spec «Границы окна через эпохи»: a (500 г. до н.э. … 100 г. н.э.)
        window keeps the events of both eras inside it and drops the rest;
        the pairs ride the ``window`` knob whole (the 4.2 channel)."""
        inside_bc = _span(1, "Эллины", date(400, 1, 1), date(300, 1, 1))
        inside_bc.start_bc = True
        inside_bc.end_bc = True
        crossing = _span(2, "Через границу", date(2, 1, 1), date(50, 1, 1))
        outside_old = _span(3, "Слишком рано", date(700, 1, 1), date(600, 1, 1))
        outside_old.start_bc = True
        outside_old.end_bc = True
        outside_new = _span(4, "Слишком поздно", date(150, 1, 1), None)
        service, vm = self._vm_with(inside_bc, crossing, outside_old, outside_new)

        await vm.load_events()
        vm.window = ((date(500, 1, 1), True), (date(100, 12, 31), False))

        assert vm.window == ((date(500, 1, 1), True), (date(100, 12, 31), False))
        assert [e.id for e in vm.events] == [1, 2]
        assert [r.event_id for r in vm.rows] == [1, 2]
        assert vm.rows[0].caption.startswith("01 Январь 400 г. до н.э.")

    @pytest.mark.asyncio
    async def test_era_flip_alone_rebuilds_rows(self):
        """The era flags join the rebuild memo: moving an event across the era
        border without touching any date repaints the list."""
        event = _span(1, "Храм", date(1, 1, 1), None)
        service, vm = self._vm_with(event)
        await vm.load_events()
        rows_before = vm.rows
        assert rows_before[0].caption == "01 Январь 1 — ∞ · Храм"

        event.start_bc = True  # the same numbers, another era
        await vm.load_events()

        assert vm.rows is not rows_before
        assert rows_before[0].start == vm.rows[0].start  # the date did not move
        assert vm.rows[0].caption == "01 Январь 1 г. до н.э. — ∞ · Храм"

    @pytest.mark.asyncio
    async def test_description_edit_rebuilds_rows(self):
        """Rows carry the description line, so editing ONLY the description must
        re-model the list: no date, name or type moved, yet the second line the
        delegate paints changed."""
        e1 = _span(1, "Council", date(1200, 1, 5), date(1200, 1, 5))
        service, vm = self._vm_with(e1)
        await vm.load_events()
        rows_before = vm.rows
        assert rows_before[0].detail == ""

        e1.description = SimpleNamespace(
            characteristics="подписали перемирие", backstory="")
        await vm.load_events()  # identical sample but for the description

        assert vm.rows is not rows_before
        assert [r.detail for r in vm.rows] == ["подписали перемирие"]


# ── TimelineViewModel — QML island model & invokables (flat list) ─────────

class TestTimelineViewModelIslandModel:
    """``row_model`` and the sync invokables the QML island calls.

    Seed style mirrors :class:`TestTimelineViewModel` (AsyncMock service,
    ``_span`` event doubles); windows are pinned so row indices are exact."""

    JAN = (date(1200, 1, 4), date(1200, 1, 9))
    MAR = (date(1200, 3, 1), date(1200, 3, 31))

    @staticmethod
    def _vm_with(*events):
        service = AsyncMock()
        service.get_all_events.return_value = list(events)
        return service, TimelineViewModel(service)

    async def _loaded(self, *events, window=None):
        service, vm = self._vm_with(*events)
        if window is not None:
            vm.window = window
        await vm.load_events()
        return vm

    # ── row_model property (single model, lockstep with rows) ───────────────

    @pytest.mark.asyncio
    async def test_row_model_is_stable_and_synced_with_rows(self):
        e1 = _span(1, "Council", date(1200, 1, 5), date(1200, 1, 5))
        e2 = _span(2, "Fair", date(1200, 3, 7), date(1200, 3, 7))
        vm = await self._loaded(e1, e2, window=self.JAN)
        model = vm.row_model
        assert model is vm.row_model  # the one model instance for the session
        assert model.rowCount() == len(vm.rows) == 1
        vm.window = self.MAR  # the window knob re-feeds the same model object
        assert model is vm.row_model
        assert model.rowCount() == len(vm.rows) == 1
        assert vm.rowModel is model  # the QML alias exposes the same object

    @pytest.mark.asyncio
    async def test_identical_reload_never_re_resets_the_model(self):
        """The memoized identical-slice path (design «update_events no-op»)
        keeps feeding NO model reset — QML never re-delivers the whole array
        without a reason."""
        e1 = _span(1, "Council", date(1200, 1, 5), date(1200, 1, 5))
        service, vm = self._vm_with(e1)
        resets: list[int] = []
        vm.row_model.modelReset.connect(lambda: resets.append(1))
        await vm.load_events()
        assert len(resets) == 1  # the first real re-model is a reset
        vm.select_event_by_id(1)  # selection repaints via root properties…
        await vm.load_events()    # …an identical reload stays silent
        assert len(resets) == 1
        assert vm.row_model.rowCount() == len(vm.rows)

    @pytest.mark.asyncio
    async def test_model_reset_replaces_entries_on_window_change(self):
        e1 = _span(1, "Council", date(1200, 1, 5), date(1200, 1, 5))
        e2 = _span(2, "Fair", date(1200, 3, 7), date(1200, 3, 7))
        vm = await self._loaded(e1, e2, window=self.JAN)
        assert [entry.event_id for entry in vm.row_model.entries] == [1]

        vm.window = self.MAR

        after = [entry.event_id for entry in vm.row_model.entries]
        assert after == [row.event_id for row in build_rows(vm.events, vm.window)]
        assert after == [2]  # the reset re-fed the whole flat list

    # ── scrollToEvent / index_for_event ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_scroll_to_event_returns_the_single_row_index(self):
        e1 = _span(1, "Council", date(1200, 1, 5), date(1200, 1, 7))
        e2 = _span(2, "Fair", date(1200, 1, 6), date(1200, 1, 6))  # inside e1's span
        vm = await self._loaded(e1, e2, window=self.JAN)
        idx = vm.scrollToEvent(2)
        assert isinstance(idx, int) and vm.rows[idx].event_id == 2
        model = vm.row_model
        assert model.data(model.index(idx), model.EVENT_ID_ROLE) == 2
        # one event = one row: the index is the only one answering this id
        assert [r.event_id for r in vm.rows].count(2) == 1
        assert vm.index_for_event(2) == idx

    @pytest.mark.asyncio
    async def test_scroll_to_event_unknown_id_returns_minus_one(self):
        e1 = _span(1, "Council", date(1200, 1, 5), date(1200, 1, 5))
        vm = await self._loaded(e1, window=self.JAN)
        assert vm.scrollToEvent(999) == -1

    @pytest.mark.asyncio
    async def test_scroll_to_event_on_empty_tape_returns_minus_one(self):
        _, vm = self._vm_with()
        await vm.load_events()
        assert vm.scrollToEvent(1) == -1

    @pytest.mark.asyncio
    async def test_scroll_to_event_window_excluded_event_returns_minus_one(self):
        e1 = _span(1, "Council", date(1200, 3, 7), date(1200, 3, 7))
        vm = await self._loaded(e1, window=self.JAN)  # e1 is outside JAN
        assert vm.scrollToEvent(1) == -1

    def test_index_for_event_none_id_is_a_plain_miss(self):
        _, vm = self._vm_with()
        assert vm.index_for_event(None) is None

    # ── uniqueness invariant ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_row_model_holds_no_second_copy_of_the_events(self):
        """Мемо-хозяйство панелей не наследуется: the VM keeps the ONE source
        set (``events``/``all_events``); the render path (rows + model) is
        pure derived state — entries carry scalars only and an event object
        never survives anywhere inside the VM once the sample is replaced."""
        e1 = _span(1, "Council", date(1200, 1, 5), date(1200, 1, 7))
        e2 = _span(2, "Fair", date(1200, 1, 8), None)
        service, vm = self._vm_with(e1, e2)
        refs = [weakref.ref(e) for e in (e1, e2)]
        await vm.load_events()
        vm.select_event_by_id(1)
        vm.scrollToEvent(1)

        source_ids = {e.id for e in vm.events}
        allowed = (str, int, bool, type(None), dict)
        for entry in vm.row_model.entries:
            for slot in _RowEntry.__slots__:
                value = getattr(entry, slot)
                assert isinstance(value, allowed), (slot, type(value))
                if isinstance(value, dict):
                    for nested in value.values():
                        assert isinstance(nested, (str, bool))
            assert entry.event_id in source_ids
        # Derived, not stored: the model equals a fresh projection of the SAME
        # single source — never a second maintained copy.
        assert vm.row_model.rowCount() == len(
            build_rows(vm.events, vm.window)
        )

        service.get_all_events.return_value = [
            _span(9, "Next", date(1201, 1, 1), date(1201, 1, 1))
        ]
        await vm.load_events()
        del e1, e2
        gc.collect()
        assert all(ref() is None for ref in refs)  # nothing in the VM kept them


# ── DetailViewModel ──────────────────────────────────────────────────────

class TestDetailViewModel:
    @pytest.mark.asyncio
    async def test_load_event_details(self):
        service = AsyncMock()
        event = _mock_event(1)
        event.organizations = [MagicMock(name="Org1")]
        event.characters = [MagicMock(name="Char1")]
        service.get_event.return_value = event
        vm = DetailViewModel(service)
        await vm.load_details(1)
        assert vm.event is not None
        assert len(vm.organizations) == 1
        assert len(vm.characters) == 1

    @pytest.mark.asyncio
    async def test_load_nonexistent_event(self):
        service = AsyncMock()
        service.get_event.return_value = None
        vm = DetailViewModel(service)
        await vm.load_details(999)
        assert vm.event is None


# ── SearchViewModel ──────────────────────────────────────────────────────

class TestSearchViewModel:
    @pytest.mark.asyncio
    async def test_search(self):
        service = AsyncMock()
        service.search_all.return_value = {
            "events": [_mock_event(1, "Battle")],
            "organizations": [],
            "characters": [],
            "items": [],
            "locations": [],
        }
        vm = SearchViewModel(service)
        await vm.search("Battle")
        assert len(vm.results["events"]) == 1

    @pytest.mark.asyncio
    async def test_search_empty_query(self):
        service = AsyncMock()
        vm = SearchViewModel(service)
        await vm.search("")
        assert vm.results == {}
        service.search_all.assert_not_awaited()


# ── EventDialogViewModel ─────────────────────────────────────────────────

class TestEventDialogViewModel:
    @pytest.mark.asyncio
    async def test_save_event(self):
        service = AsyncMock()
        service.create_event.return_value = _mock_event(1)
        vm = EventDialogViewModel(service)
        vm.name = "Battle"
        vm.characteristics = "Big"
        vm.backstory = "Old"
        vm.start_date = date(1200, 1, 1)
        vm.end_date = date(1200, 12, 31)

        result = await vm.save()
        assert result is not None
        service.create_event.assert_awaited_once()

    def test_is_valid_true(self):
        service = AsyncMock()
        vm = EventDialogViewModel(service)
        vm.name = "Battle"
        vm.characteristics = "Big"
        vm.backstory = "Old"
        vm.start_date = date(1200, 1, 1)
        vm.end_date = date(1200, 12, 31)
        assert vm.is_valid is True

    def test_is_valid_false_no_name(self):
        service = AsyncMock()
        vm = EventDialogViewModel(service)
        vm.name = ""
        vm.characteristics = "Big"
        vm.backstory = "Old"
        vm.start_date = date(1200, 1, 1)
        vm.end_date = date(1200, 12, 31)
        assert vm.is_valid is False

    def test_is_valid_false_no_dates(self):
        service = AsyncMock()
        vm = EventDialogViewModel(service)
        vm.name = "Battle"
        vm.characteristics = "Big"
        vm.backstory = "Old"
        vm.start_date = None
        vm.end_date = None
        assert vm.is_valid is False

    def test_is_valid_false_end_before_start(self):
        service = AsyncMock()
        vm = EventDialogViewModel(service)
        vm.name = "Battle"
        vm.characteristics = "Big"
        vm.backstory = "Old"
        vm.start_date = date(1200, 12, 31)
        vm.end_date = date(1200, 1, 1)
        assert vm.is_valid is False

    def test_is_valid_equal_dates(self):
        # The end-before-start check moved to cmp_era_dates (add-era-aware-dates):
        # the boundary must keep the old `<` semantics — equal dates are a valid
        # one-day range, the helper rejects only strictly-earlier ends.
        service = AsyncMock()
        vm = EventDialogViewModel(service)
        vm.name = "Battle"
        vm.characteristics = "Big"
        vm.backstory = "Old"
        vm.start_date = date(1200, 6, 1)
        vm.end_date = date(1200, 6, 1)
        assert vm.is_valid is True


# ── EntityViewModel ──────────────────────────────────────────────────────

class TestEntityViewModel:
    @pytest.mark.asyncio
    async def test_load_entity(self):
        service = AsyncMock()
        mock_obj = MagicMock()
        mock_obj.id = 5
        mock_obj.name = "Guild"
        service.get_entity.return_value = mock_obj
        vm = EntityViewModel(service)
        await vm.load(5)
        assert vm.entity.name == "Guild"

    @pytest.mark.asyncio
    async def test_save_entity(self):
        service = AsyncMock()
        service.update_entity.return_value = MagicMock(id=5)
        vm = EntityViewModel(service)
        vm.entity = MagicMock(id=5)
        await vm.save(name="Updated")
        service.update_entity.assert_awaited_once_with(5, name="Updated")

    @pytest.mark.asyncio
    async def test_delete_entity(self):
        service = AsyncMock()
        service.delete_entity.return_value = True
        vm = EntityViewModel(service)
        vm.entity = MagicMock(id=5)
        result = await vm.delete()
        assert result is True
