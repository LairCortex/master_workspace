"""Tests for ViewModels — TDD: tests first."""
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.presentation.viewmodels.timeline_viewmodel import TimelineViewModel
from app.presentation.viewmodels.detail_viewmodel import DetailViewModel
from app.presentation.viewmodels.search_viewmodel import SearchViewModel
from app.presentation.viewmodels.event_dialog_viewmodel import EventDialogViewModel
from app.presentation.viewmodels.entity_viewmodel import EntityViewModel
from app.presentation.views.timeline_rows import RowKind


def _mock_event(id_=1, name="Battle"):
    e = MagicMock()
    e.id = id_
    e.name = name
    e.start_date = date(1200, 1, 1)
    e.end_date = date(1200, 12, 31)
    e.organizations = []
    e.characters = []
    e.items = []
    e.locations = []
    return e


# ── TimelineViewModel ────────────────────────────────────────────────────

class TestTimelineViewModel:
    @pytest.mark.asyncio
    async def test_load_events(self):
        service = AsyncMock()
        service.get_all_events.return_value = [_mock_event(1), _mock_event(2, "Siege")]
        vm = TimelineViewModel(service)
        await vm.load_events()
        assert len(vm.events) == 2

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
    async def test_select_event_by_id_respects_visible_filter(self):
        service = AsyncMock()
        e1 = _mock_event(1, "Early")
        e1.start_date = date(1100, 1, 1)
        e1.end_date = date(1100, 6, 1)
        e2 = _mock_event(2, "Mid")
        e2.start_date = date(1200, 1, 1)
        e2.end_date = date(1200, 12, 31)
        service.get_all_events.return_value = [e1, e2]
        vm = TimelineViewModel(service)
        await vm.load_events()
        vm.filter_by_dates(date(1150, 1, 1), date(1250, 12, 31))
        # id 1 is loaded but not visible → the miss clears (W3: visible set)
        vm.select_event_by_id(1)
        assert vm.selected_event is None

    @pytest.mark.asyncio
    async def test_filter_by_dates(self):
        service = AsyncMock()
        e1 = _mock_event(1, "Early")
        e1.start_date = date(1100, 1, 1)
        e1.end_date = date(1100, 6, 1)
        e2 = _mock_event(2, "Mid")
        e2.start_date = date(1200, 1, 1)
        e2.end_date = date(1200, 12, 31)
        e3 = _mock_event(3, "Late")
        e3.start_date = date(1300, 1, 1)
        e3.end_date = date(1300, 12, 31)
        service.get_all_events.return_value = [e1, e2, e3]
        vm = TimelineViewModel(service)
        await vm.load_events()
        assert len(vm.events) == 3

        vm.filter_by_dates(date(1150, 1, 1), date(1250, 12, 31))
        assert len(vm.events) == 1
        assert vm.events[0].name == "Mid"

    @pytest.mark.asyncio
    async def test_filter_clear(self):
        service = AsyncMock()
        e1 = _mock_event(1, "A")
        e1.start_date = date(1100, 1, 1)
        e1.end_date = date(1100, 6, 1)
        e2 = _mock_event(2, "B")
        e2.start_date = date(1200, 1, 1)
        e2.end_date = date(1200, 12, 31)
        service.get_all_events.return_value = [e1, e2]
        vm = TimelineViewModel(service)
        await vm.load_events()

        vm.filter_by_dates(date(1150, 1, 1), date(1250, 12, 31))
        assert len(vm.events) == 1

        vm.filter_by_dates(None, None)
        assert len(vm.events) == 2

    @pytest.mark.asyncio
    async def test_filter_prunes_selection_that_left_the_visible_set(self):
        service = AsyncMock()
        e1 = _mock_event(1, "Early")
        e1.start_date = date(1100, 1, 1)
        e1.end_date = date(1100, 6, 1)
        e2 = _mock_event(2, "Mid")
        e2.start_date = date(1200, 1, 1)
        e2.end_date = date(1200, 12, 31)
        service.get_all_events.return_value = [e1, e2]
        vm = TimelineViewModel(service)
        await vm.load_events()
        vm.select_event_by_id(1)
        signals: list = []
        vm.selected_event_changed.connect(lambda: signals.append(1))

        vm.filter_by_dates(date(1150, 1, 1), date(1250, 12, 31))  # e1 falls out

        # The canvas drops an invisible id on set_events; the VM must not keep
        # holding it (task 3.3: an id-contract selection lives exactly as long as
        # its event is visible), and the pruning has to be announced so the
        # canvas and the detail panel can follow.
        assert vm.selected_event is None
        assert signals == [1]

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

    @pytest.mark.asyncio
    async def test_filter_no_match(self):
        service = AsyncMock()
        e1 = _mock_event(1, "Only")
        e1.start_date = date(1200, 1, 1)
        e1.end_date = date(1200, 12, 31)
        service.get_all_events.return_value = [e1]
        vm = TimelineViewModel(service)
        await vm.load_events()

        vm.filter_by_dates(date(1300, 1, 1), date(1400, 1, 1))
        assert len(vm.events) == 0

    @pytest.mark.asyncio
    async def test_filter_persists_after_reload(self):
        service = AsyncMock()
        e1 = _mock_event(1, "Early")
        e1.start_date = date(1100, 1, 1)
        e1.end_date = date(1100, 6, 1)
        e2 = _mock_event(2, "Mid")
        e2.start_date = date(1200, 1, 1)
        e2.end_date = date(1200, 12, 31)
        service.get_all_events.return_value = [e1, e2]
        vm = TimelineViewModel(service)
        await vm.load_events()
        vm.filter_by_dates(date(1150, 1, 1), date(1250, 12, 31))
        assert [e.name for e in vm.events] == ["Mid"]

        # Simulate reload after creating a new event in the same range
        e3 = _mock_event(3, "New")
        e3.start_date = date(1200, 5, 1)
        e3.end_date = date(1200, 5, 10)
        service.get_all_events.return_value = [e1, e2, e3]
        await vm.load_events()
        names = sorted(e.name for e in vm.events)
        assert names == ["Mid", "New"]

    # ── derived visible rows (W3b task 4.1) ─────────────────────────────────

    @pytest.mark.asyncio
    async def test_rows_without_filter_span_min_to_max_with_empty_days(self):
        """No filter → rows cover min(start)…max(end|start); a gap day is
        exactly one EMPTY_DAY row (spec «Диапазон без фильтра»)."""
        service = AsyncMock()
        e1 = _mock_event(1, "First")
        e1.start_date = date(1200, 1, 1)
        e1.end_date = date(1200, 1, 1)
        e2 = _mock_event(2, "Third")
        e2.start_date = date(1200, 1, 3)
        e2.end_date = date(1200, 1, 3)
        service.get_all_events.return_value = [e1, e2]
        vm = TimelineViewModel(service)

        await vm.load_events()

        by_kind = [(r.kind, r.date) for r in vm.rows]
        assert by_kind == [
            (RowKind.EVENT, date(1200, 1, 1)),
            (RowKind.EMPTY_DAY, date(1200, 1, 2)),  # the gap day, not collapsed
            (RowKind.EVENT, date(1200, 1, 3)),
        ]
        assert [r.event_id for r in vm.rows] == [1, None, 2]

    @pytest.mark.asyncio
    async def test_rows_use_filter_range_even_when_empty(self):
        """A live filter seeds the row range: a range with no events yields
        empty-day rows for every day of it, not zero rows (spec «Пустой
        диапазон фильтра»)."""
        service = AsyncMock()
        e1 = _mock_event(1, "Only")
        e1.start_date = date(1200, 1, 1)
        e1.end_date = date(1200, 1, 1)
        service.get_all_events.return_value = [e1]
        vm = TimelineViewModel(service)

        await vm.load_events()
        vm.filter_by_dates(date(1300, 1, 1), date(1300, 1, 3))

        assert len(vm.events) == 0
        assert [r.kind for r in vm.rows] == [RowKind.EMPTY_DAY] * 3
        assert [r.date for r in vm.rows] == [
            date(1300, 1, 1), date(1300, 1, 2), date(1300, 1, 3),
        ]

    @pytest.mark.asyncio
    async def test_rows_without_events_without_filter_are_empty(self):
        """No events and no filter → no range to enumerate → no rows."""
        service = AsyncMock()
        service.get_all_events.return_value = []
        vm = TimelineViewModel(service)

        await vm.load_events()

        assert vm.rows == []

    @pytest.mark.asyncio
    async def test_rows_are_recomputed_on_filter_clear(self):
        """Clearing the filter returns the derived rows to the sample's own
        min–max range, consistent with the recomputed ``events``."""
        service = AsyncMock()
        e1 = _mock_event(1, "Only")
        e1.start_date = date(1300, 1, 1)
        e1.end_date = date(1300, 1, 1)
        service.get_all_events.return_value = [e1]
        vm = TimelineViewModel(service)

        await vm.load_events()
        vm.filter_by_dates(date(1200, 1, 1), date(1200, 1, 2))  # excludes e1
        assert [r.kind for r in vm.rows] == [RowKind.EMPTY_DAY, RowKind.EMPTY_DAY]

        vm.filter_by_dates(None, None)

        assert len(vm.events) == 1
        assert [r.kind for r in vm.rows] == [RowKind.EVENT]
        assert vm.rows[0].event_id == 1



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
