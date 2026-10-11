"""External marks on the ladder's rows (add-dnd-game-face task 11.2).

The ladder asks, the sources know (design Д9): the ViewModel merges the
``event_marks`` answers of the live external sources into the ``build_rows``
pass and the marks join the rebuild memo. Pins here (ViewModel level, the
core's copying pinned in test_timeline_rows.py, the delegate's ring in the
island tests):

* without sources the ladder is the old ladder — every row ``marks`` empty;
* a visible source marks its events on every row the sample holds (the door
  answers for the WHOLE sample, not only the visible window);
* tolerance all the way: a hidden (detached) source contributes nothing, a
  source without the door is skipped, a raising source is journalled and
  skipped — a broken module must never eat the ladder, and its healthy
  neighbour still marks;
* tokens stack in source order when several sources mark the same event;
* the marks are memo fuel: a swap that changes nobody's marks keeps the very
  same ``rows`` object, a saved/cleared encounter re-models exactly once.
"""
from __future__ import annotations

import logging
from datetime import date

from app.presentation.viewmodels.timeline_viewmodel import TimelineViewModel


class _Ev:
    def __init__(self, id_, start, end, name, parent_id=None):
        self.id = id_
        self.start_date = start
        self.end_date = end
        self.name = name
        self.event_type = None
        if parent_id is not None:
            self.parent_id = parent_id


class _Service:
    def __init__(self, events):
        self._events = list(events)

    async def get_all_events(self):
        return list(self._events)


class _Source:
    """Duck of DndEncounterSource in the volume the ladder knocks at."""

    def __init__(self, encountered=(), visible=True, raises=False,
                 token="encounter"):
        self.encountered = set(encountered)
        self.visible = visible
        self.raises = raises
        self.token = token
        self.queried: list[tuple[int, ...]] = []

    def event_marks(self, event_ids):
        self.queried.append(tuple(event_ids))
        if self.raises:
            raise RuntimeError("модуль упал")
        return {i: self.token for i in event_ids if i in self.encountered}


class _NoDoor:
    """A card-tab source the composition hands the ladder anyway: no
    ``event_marks`` at all — the ladder must not notice."""

    visible = True


FIRST = _Ev(1, date(1200, 1, 5), None, "Совет")
SECOND = _Ev(2, date(1200, 1, 6), None, "Пир")
# Outside the default day-window arithmetic of the other files but inside
# the sample — the door answers for the WHOLE sample, window irrelevant.
FAR = _Ev(3, date(1201, 6, 1), None, "Далёкое")


def _vm(*events, sources=()) -> TimelineViewModel:
    return TimelineViewModel(_Service(list(events)), external_sources=sources)


def _marks(vm: TimelineViewModel) -> list[tuple[int, tuple]]:
    return [(row.event_id, row.marks) for row in vm.rows]


async def _loaded(vm: TimelineViewModel) -> TimelineViewModel:
    await vm.load_events()
    return vm


class TestMarksOnRows:
    async def test_without_sources_the_ladder_is_the_old_ladder(self):
        vm = await _loaded(_vm(FIRST, SECOND))
        assert _marks(vm) == [(1, ()), (2, ())]

    async def test_a_visible_source_marks_its_events(self):
        vm = await _loaded(_vm(FIRST, SECOND, sources=[_Source({2})]))
        assert _marks(vm) == [(1, ()), (2, ("encounter",))]

    async def test_the_door_answers_for_the_whole_sample(self):
        vm = _vm(FIRST, SECOND, FAR)
        source = _Source({3})
        await _loaded(vm)
        vm.set_external_sources([source])
        assert source.queried[-1] == (1, 2, 3)
        assert _marks(vm) == [(1, ()), (2, ()), (3, ("encounter",))]

    async def test_a_hidden_source_marks_nothing(self):
        """Spec «при выключенном модуле … пометки быть НЕ SHALL»: a detached
        source is hidden data — the same rows stay, not even a re-delivery."""
        hidden = _Source({1, 2}, visible=False)
        vm = await _loaded(_vm(FIRST, SECOND))
        before = vm.rows
        vm.set_external_sources([hidden])
        assert vm.rows is before  # memo intact: nobody's marks moved
        assert _marks(vm) == [(1, ()), (2, ())]
        hidden.visible = True
        await _loaded(vm)  # the module's own reload re-models with marks
        assert _marks(vm) == [(1, ("encounter",)), (2, ("encounter",))]

    async def test_a_source_without_the_door_is_skipped(self):
        vm = await _loaded(_vm(FIRST, sources=[_NoDoor()]))
        assert _marks(vm) == [(1, ())]

    async def test_a_raising_source_is_journalled_and_the_neighbour_survives(
        self, caplog
    ):
        broken = _Source({1}, raises=True)
        healthy = _Source({2}, token="other")
        with caplog.at_level(logging.WARNING):
            vm = await _loaded(_vm(FIRST, SECOND, sources=[broken, healthy]))
        assert _marks(vm) == [(1, ()), (2, ("other",))]
        assert any("источник пометок отказал" in r.getMessage() for r in caplog.records)

    async def test_tokens_stack_in_source_order(self):
        first = _Source({1}, token="encounter")
        second = _Source({1}, token="second")
        vm = await _loaded(_vm(FIRST, sources=[first, second]))
        assert _marks(vm) == [(1, ("encounter", "second"))]

    async def test_construction_with_sources_marks_the_first_load(self):
        vm = await _loaded(_vm(FIRST, SECOND, sources=[_Source({1})]))
        assert _marks(vm) == [(1, ("encounter",)), (2, ())]
        assert len(vm.external_sources) == 1


class TestMarksAndTheMemo:
    async def test_a_swap_that_paints_nothing_keeps_the_rows_object(self):
        vm = await _loaded(_vm(FIRST, SECOND, sources=[_Source()]))
        before = vm.rows
        vm.set_external_sources([_Source(), _NoDoor()])  # nobody marks here
        assert vm.rows is before

    async def test_a_saved_encounter_remodels_exactly_once(self):
        source = _Source()
        vm = await _loaded(_vm(FIRST, SECOND, sources=[source]))
        before = vm.rows
        # The save path: the source reconciles its cache (apply_saved), the
        # wiring reloads the ladder — the marks ride the ordinary reload.
        source.encountered.add(2)
        await _loaded(vm)
        assert vm.rows is not before
        assert _marks(vm) == [(1, ()), (2, ("encounter",))]
        # An unrelated reload with nobody's marks moved changes nothing.
        settled = vm.rows
        await _loaded(vm)
        assert vm.rows is settled

    async def test_clearing_the_encounter_invalidates_again(self):
        source = _Source({2})
        vm = await _loaded(_vm(FIRST, SECOND, sources=[source]))
        marked = vm.rows
        source.encountered.discard(2)
        await _loaded(vm)
        assert vm.rows is not marked
        assert _marks(vm) == [(1, ()), (2, ())]
