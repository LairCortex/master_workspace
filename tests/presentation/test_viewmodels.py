"""Tests for ViewModels — TDD: tests first."""
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.presentation.viewmodels.timeline_viewmodel import TimelineViewModel
from app.presentation.viewmodels.detail_viewmodel import DetailViewModel
from app.presentation.viewmodels.search_viewmodel import SearchViewModel
from app.presentation.viewmodels.event_dialog_viewmodel import EventDialogViewModel
from app.presentation.viewmodels.entity_viewmodel import EntityViewModel
from app.presentation.views.timeline_rows import (
    DayHeaderRow,
    EmptyDayRow,
    EventRow,
    PeriodCardRow,
    PeriodHeaderRow,
    ScaleUnit,
)


def _mock_event(id_=1, name="Battle"):
    e = MagicMock()
    e.id = id_
    e.name = name
    e.start_date = date(1200, 1, 1)
    e.end_date = date(1200, 12, 31)
    e.event_type = None
    e.organizations = []
    e.characters = []
    e.items = []
    e.locations = []
    return e


def _span(id_, name, start, end):
    """Plain event double on explicit dates (the ladder reads id/dates/name only)."""
    e = MagicMock()
    e.id = id_
    e.name = name
    e.start_date = start
    e.end_date = end
    e.event_type = None
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

    @pytest.mark.asyncio
    async def test_view_state_defaults_and_is_not_serialized(self):
        """Spec «Вид не переживает перезапуск»: a fresh ViewModel always opens
        «сутки · Все дни · тумблер выключен» — level/window/hide_empty are
        plain session state, never restored from anywhere."""
        service, _ = self._vm_with()
        first = TimelineViewModel(service)
        first.level = ScaleUnit.YEAR
        first.window = (date(1200, 1, 1), date(1200, 3, 31))
        first.hide_empty = True

        reopened = TimelineViewModel(service)
        assert reopened.level is ScaleUnit.DAY
        assert reopened.window is None
        assert reopened.hide_empty is False

    @pytest.mark.asyncio
    async def test_load_resets_level_but_keeps_window_and_toggle(self):
        """Design D7: the rung re-defaults to DAY on every load, while the
        «Выбор даты» window and the hide toggle live on for the session."""
        e1, _ = self._w2_events()
        service, vm = self._vm_with(e1)
        await vm.load_events()
        vm.level = ScaleUnit.MONTH
        vm.window = (date(1200, 1, 1), date(1200, 1, 31))
        vm.hide_empty = True

        await vm.load_events()

        assert vm.level is ScaleUnit.DAY
        assert vm.window == (date(1200, 1, 1), date(1200, 1, 31))
        assert vm.hide_empty is True

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
    async def test_unknown_id_miss_clears_without_touching_knobs(self):
        """A miss is nobody's business to descend for: an id no event owns
        clears the selection (announced) and leaves level and window exactly
        where they were."""
        e1, _ = self._w2_events()
        service, vm = self._vm_with(e1)
        await vm.load_events()
        vm.level = ScaleUnit.MONTH
        vm.window = (date(1200, 1, 1), date(1200, 1, 31))
        selection_signals: list = []
        vm.selected_event_changed.connect(lambda: selection_signals.append(1))

        vm.select_event_by_id(999)

        assert vm.selected_event is None
        assert selection_signals == [1]  # the clear is announced (panel follows)
        assert vm.level is ScaleUnit.MONTH
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

    # ── external selections descend the ladder (task 2.2) ───────────────────

    @pytest.mark.asyncio
    async def test_external_selection_from_month_descends_to_day(self):
        """Selection from the month step descends to days: setting level=DAY
        puts the event into ``rows``, then selects it (spec «External selection
        from a coarse step descends the ladder»), without touching it on its own
        window."""
        e1, e2 = self._w2_events()
        service, vm = self._vm_with(e1, e2)
        await vm.load_events()
        vm.level = ScaleUnit.MONTH
        assert not any(isinstance(r, EventRow) for r in vm.rows)

        events_signals: list = []
        selection_signals: list = []
        vm.events_changed.connect(lambda: events_signals.append(1))
        vm.selected_event_changed.connect(lambda: selection_signals.append(1))

        vm.select_event_by_id(e2.id)

        assert vm.level is ScaleUnit.DAY
        assert e2.id in [r.event_id for r in vm.rows if isinstance(r, EventRow)]
        assert vm.selected_event is e2
        # rows were re-modelled before the selection was asserted (D4 order)
        assert events_signals == [1]
        assert selection_signals == [1]

    @pytest.mark.asyncio
    async def test_external_selection_inside_window_keeps_window(self):
        """An event already visible inside the window is selected without
        spending a reset: neither the window nor the rung moves (spec «Selection
        from search»)."""
        e1, _ = self._w2_events()
        service, vm = self._vm_with(e1)
        await vm.load_events()
        vm.window = (date(1200, 1, 1), date(1200, 1, 31))
        rows_before = vm.rows

        vm.select_event_by_id(e1.id)

        assert vm.selected_event is e1
        assert vm.window == (date(1200, 1, 1), date(1200, 1, 31))
        assert vm.rows is rows_before  # nothing to re-model for it

    @pytest.mark.asyncio
    async def test_external_selection_outside_window_resets_window_then_selects(self):
        """An event excluded by the window is not represented → «All days»:
        level=DAY, window=None, and only then the selection (spec «When an
        external selection from a coarse step descends the ladder» + task 2.2:
        outside-window selection from search)."""
        e1, e2 = self._w2_events()
        service, vm = self._vm_with(e1, e2)
        await vm.load_events()
        vm.window = (date(1200, 1, 1), date(1200, 1, 31))  # e2 sits outside it

        vm.select_event_by_id(e2.id)

        assert vm.window is None  # reset to «Все дни»
        assert vm.level is ScaleUnit.DAY
        assert vm.selected_event is e2
        assert e2.id in [r.event_id for r in vm.rows if isinstance(r, EventRow)]

    # ── window semantics (design D7, spec «Window, empty positions…») ───────

    @pytest.mark.asyncio
    async def test_window_keeps_events_that_overlap_it(self):
        """Spec «Event crossing the window is visible in the window»: an event
        starting before and ending after the window crosses it through all its
        days and stays in the sample; a fully outside event leaves it."""
        crossing = _span(1, "Crossing", date(1200, 7, 1), date(1200, 9, 5))
        outside = _span(2, "Outside", date(1201, 5, 1), date(1201, 5, 9))
        service, vm = self._vm_with(crossing, outside)
        await vm.load_events()

        vm.window = (date(1200, 8, 10), date(1200, 8, 20))

        assert [e.id for e in vm.events] == [1]
        cards = [r for r in vm.rows if isinstance(r, EventRow)]
        assert {r.event_id for r in cards} == {1}
        # every window day carries the card (spec «crosses through all days»)
        assert len(cards) == 11

    @pytest.mark.asyncio
    async def test_empty_window_shows_placeholders_and_prunes_selection(self):
        """Spec «Empty window shows the emptiness»: a valid day range with no
        events keeps its days as empty placeholders, and the selection an
        excluded window resets in every layer (announced — the spec «Window
        excluded the selected event»; the window itself keeps painting days)."""
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
        assert vm.selected_event is None  # excluded → dropped in every layer
        assert prune_signals == [1]  # …and the drop is announced (panel follows)
        assert [(type(r), r.date) for r in vm.rows] == [
            (DayHeaderRow, date(1200, 2, 1)), (EmptyDayRow, date(1200, 2, 1)),
            (DayHeaderRow, date(1200, 2, 2)), (EmptyDayRow, date(1200, 2, 2)),
            (DayHeaderRow, date(1200, 2, 3)), (EmptyDayRow, date(1200, 2, 3)),
        ]
        # …and the selection does not revive on its own when the days return
        vm.window = None
        assert vm.selected_event is None
        assert [e.id for e in vm.events] == [e1.id, e2.id]

    @pytest.mark.asyncio
    async def test_window_and_level_setters_emit_events_changed(self):
        """Every knob setter re-models ``rows`` and announces them exactly
        once; an unchanged value is a complete no-op."""
        e1, _ = self._w2_events()
        service, vm = self._vm_with(e1)
        await vm.load_events()
        signals: list = []
        vm.events_changed.connect(lambda: signals.append(1))

        vm.window = (date(1200, 1, 1), date(1200, 1, 31))
        vm.level = ScaleUnit.MONTH
        vm.hide_empty = True
        assert signals == [1, 1, 1]

        vm.window = (date(1200, 1, 1), date(1200, 1, 31))  # the same window
        vm.level = ScaleUnit.MONTH  # the same rung
        vm.hide_empty = True  # the same toggle state
        assert signals == [1, 1, 1]  # no rebuild, no echo

    # ── rows projection via the day-ladder core (design D2/D7) ──────────────

    @pytest.mark.asyncio
    async def test_rows_without_window_lay_days_events_and_placeholders(self):
        """No window → the content span min(start)…bottom; day headers with
        event cards, the gap day one exact placeholder (spec «Диапазон без
        окна» in the new layout)."""
        e1 = _span(1, "First", date(1200, 1, 1), date(1200, 1, 1))
        e2 = _span(2, "Third", date(1200, 1, 3), date(1200, 1, 3))
        service, vm = self._vm_with(e1, e2)

        await vm.load_events()

        assert [(type(r), r.date, getattr(r, "event_id", None)) for r in vm.rows] == [
            (DayHeaderRow, date(1200, 1, 1), None),
            (EventRow, date(1200, 1, 1), 1),
            (DayHeaderRow, date(1200, 1, 2), None),
            (EmptyDayRow, date(1200, 1, 2), None),  # the gap day, not collapsed
            (DayHeaderRow, date(1200, 1, 3), None),
            (EventRow, date(1200, 1, 3), 2),
        ]

    @pytest.mark.asyncio
    async def test_month_rung_rolls_days_up_to_counter_cards(self):
        """MONTH level paints header+card per period with the crossing-event
        counter; the empty February keeps its «no events» stub position (spec
        «Empty month on the month step»); sample and selection are untouched."""
        e1, e2 = self._w2_events()
        service, vm = self._vm_with(e1, e2)
        await vm.load_events()
        vm.select_event_by_id(e1.id)
        events_before = list(vm.events)
        selection_signals: list = []
        vm.selected_event_changed.connect(lambda: selection_signals.append(1))

        vm.level = ScaleUnit.MONTH

        assert [(type(r), r.date, getattr(r, "count", None)) for r in vm.rows] == [
            (PeriodHeaderRow, date(1200, 1, 1), None),
            (PeriodCardRow, date(1200, 1, 1), 1),
            (PeriodHeaderRow, date(1200, 2, 1), None),
            (PeriodCardRow, date(1200, 2, 1), 0),   # «no events» stub
            (PeriodHeaderRow, date(1200, 3, 1), None),
            (PeriodCardRow, date(1200, 3, 1), 1),
        ]
        assert vm.events == events_before
        assert vm.selected_event is e1  # the rung is nobody's business here
        assert selection_signals == []

        vm.level = ScaleUnit.DAY  # …and the daily projection comes back
        assert not any(
            isinstance(r, (PeriodHeaderRow, PeriodCardRow)) for r in vm.rows
        )
        assert {r.event_id for r in vm.rows if isinstance(r, EventRow)} == {e1.id, e2.id}
        assert vm.selected_event is e1

    @pytest.mark.asyncio
    async def test_hide_empty_cuts_empty_positions_on_both_levels(self):
        """Spec «Empty days disappear» + «Empty periods disappear» for the VM
        knob: turning the toggle hides empty days (with their headers) and
        «no events» periods, turning it off returns them; the selection never
        blinks."""
        e1 = _span(1, "New year", date(1200, 1, 1), date(1200, 1, 1))
        e2 = _span(2, "Third day", date(1200, 1, 3), date(1200, 1, 3))
        service, vm = self._vm_with(e1, e2)
        await vm.load_events()
        vm.window = (date(1200, 1, 1), date(1200, 1, 3))  # Jan 2 is the empty day
        vm.select_event_by_id(e1.id)
        assert sum(1 for r in vm.rows if isinstance(r, EmptyDayRow)) == 1
        assert len(vm.rows) == 6  # two days with cards, one placeholder day
        selection_signals: list = []
        vm.selected_event_changed.connect(lambda: selection_signals.append(1))

        vm.hide_empty = True

        assert not any(isinstance(r, EmptyDayRow) for r in vm.rows)
        assert len(vm.rows) == 4  # the empties left the tape with their headers
        assert [e.id for e in vm.events] == [e1.id, e2.id]  # sample never moved
        assert selection_signals == []  # the toggle never touches the selection

        selection_signals.clear()
        vm.level = ScaleUnit.MONTH
        vm.window = (date(1200, 1, 1), date(1200, 3, 31))
        # the window change re-asserts the surviving selection exactly once
        # (legacy emitting semantics: the signal fires, the event never blinks)
        assert selection_signals == [1]
        assert [r.count for r in vm.rows if isinstance(r, PeriodCardRow)] == [2]
        vm.hide_empty = False  # the empty months' «no events» stubs are back
        assert [r.count for r in vm.rows if isinstance(r, PeriodCardRow)] == [2, 0, 0]
        assert vm.selected_event is e1

    @pytest.mark.asyncio
    async def test_rows_without_events_without_window_are_empty(self):
        """No events and no window → no span to enumerate → no rows (the
        text hint is the view's overlay, not a row)."""
        service = AsyncMock()
        service.get_all_events.return_value = []
        vm = TimelineViewModel(service)

        await vm.load_events()

        assert vm.rows == []

    @pytest.mark.asyncio
    async def test_rows_are_recomputed_on_window_clear(self):
        """Clearing the window returns the tape from the window's days to the
        sample's own content span, consistent with the recomputed ``events``."""
        e1 = _span(1, "Only", date(1300, 1, 1), date(1300, 1, 1))
        service, vm = self._vm_with(e1)

        await vm.load_events()
        vm.window = (date(1200, 1, 1), date(1200, 1, 2))  # beyond event e1
        assert not any(isinstance(r, EventRow) for r in vm.rows)

        vm.window = None  # «Все дни»: the window resets

        assert [e.id for e in vm.events] == [1]
        cards = [r for r in vm.rows if isinstance(r, EventRow)]
        assert [(r.date, r.event_id) for r in cards] == [(date(1300, 1, 1), 1)]

    @pytest.mark.asyncio
    async def test_identical_reload_does_not_rebuild_rows(self):
        """The ``_version_of`` memo behind the rows re-model (design «update_events
        no-op for the same slice»): an identical sample at identical knobs
        rebuilds nothing; a window change does (so the memo never swallows the
        new fields)."""
        e1, e2 = self._w2_events()
        service, vm = self._vm_with(e1, e2)
        await vm.load_events()
        rows_before = vm.rows

        await vm.load_events()  # identical sample, knobs the same

        assert vm.rows is rows_before  # no re-model: the same row list

        vm.window = (date(1200, 1, 1), date(1200, 1, 31))  # the new key field

        assert vm.rows is not rows_before
        assert [e.id for e in vm.events] == [e1.id]

    # ── inline creation from an empty day (task 6.1, design D4) ────────────────

    @staticmethod
    def _create_service(new_event):
        """A service double that records the create call and reloads to
        ``[new_event]``; its shared session's commit/rollback are spies."""
        service = AsyncMock()
        service.get_all_events.return_value = [new_event]
        service.create_event = AsyncMock(return_value=new_event)
        service._session = MagicMock()
        service._session.commit = AsyncMock()
        service._session.rollback = AsyncMock()
        return service

    @pytest.mark.asyncio
    async def test_create_event_at_writes_a_single_day_event_then_selects(self):
        """Spec «Быстрое создание»: Enter on the empty-day field writes one
        event with ``start == end == the clicked day`` and no type, commits,
        reloads and selects the new record."""
        day = date(1200, 8, 14)
        new = _span(3, "Засека", day, day)
        service = self._create_service(new)
        vm = TimelineViewModel(service)

        event = await vm.create_event_at(day, "Засека")

        assert event is new and vm.selected_event is new
        service.create_event.assert_awaited_once_with(
            name="Засека", characteristics="", backstory="",
            start_date=day, end_date=day, event_type_id=None,
        )
        service._session.commit.assert_awaited_once()
        # reload landed the card and the selection followed it
        assert [e.id for e in vm.events] == [3]
        assert isinstance(vm.rows[1], EventRow) and vm.rows[1].event_id == 3

    @pytest.mark.asyncio
    async def test_create_event_at_whitespace_name_creates_nothing(self):
        """Spec «Пустое поле не создаёт»: an empty/whitespace name is not a
        create — no write, no commit, no reload, no selection."""
        service = self._create_service(_span(3, "x", date(1200, 8, 14), date(1200, 8, 14)))
        vm = TimelineViewModel(service)

        assert await vm.create_event_at(date(1200, 8, 14), "   ") is None

        service.create_event.assert_not_called()
        service._session.commit.assert_not_called()
        service.get_all_events.assert_not_called()  # not even a reload
        assert vm.selected_event is None

    async def test_create_event_at_write_failure_rolls_back_and_reraises(self):
        """A failed write leaves the shared session usable: rollback, then the
        wiring reports it (the VM owns no dialog of its own)."""
        day = date(1200, 8, 14)
        service = self._create_service(_span(3, "Засека", day, day))
        service.create_event = AsyncMock(side_effect=RuntimeError("db write failed"))
        vm = TimelineViewModel(service)

        with pytest.raises(RuntimeError, match="db write failed"):
            await vm.create_event_at(day, "Засека")

        service._session.rollback.assert_awaited_once()
        service._session.commit.assert_not_called()
        service.get_all_events.assert_not_called()  # no reload across a failure
        assert vm.selected_event is None

    @pytest.mark.asyncio
    async def test_create_event_at_trims_the_name_before_writing(self):
        """The name is stripped so a padded draft does not persist stray
        whitespace (the field's own display is trimmed the same way)."""
        day = date(1200, 9, 1)
        service = self._create_service(_span(4, "Tavern", day, day))
        vm = TimelineViewModel(service)

        await vm.create_event_at(day, "  Tavern  ")

        assert service.create_event.await_args.kwargs["name"] == "Tavern"



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
