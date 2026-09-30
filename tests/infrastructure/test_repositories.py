"""Tests for repositories — TDD: tests first."""
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.date_era import era_key
from app.domain.game_calendar import (
    CalendarSpec,
    CustomCalendar,
    MonthSpec,
    StandardCalendar,
    current_calendar,
    set_current_calendar,
)
from app.domain.time_of_day import TimeOfDay
from app.infrastructure.db.models import (
    DescriptionModel, EventModel, OrganizationModel,
    CharacterModel, ImageModel, ItemModel, LocationModel,
)
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.coord_mapping import CoordMappingMixin
from app.infrastructure.repositories.dated_repository import dated_repository
from app.infrastructure.repositories.event_repository import EventRepository
from app.infrastructure.repositories.organization_repository import OrganizationRepository
from app.infrastructure.repositories.character_repository import CharacterRepository
from app.infrastructure.repositories.item_repository import ItemRepository
from app.infrastructure.repositories.location_repository import LocationRepository
from app.infrastructure.repositories.rating_repository import RatingRepository
from app.presentation.views.timeline_rows import build_rows


# ── helpers ───────────────────────────────────────────────────────────────

async def _make_desc(session: AsyncSession, chars: str = "x", back: str = "y") -> DescriptionModel:
    d = DescriptionModel(characteristics=chars, backstory=back)
    session.add(d)
    await session.flush()
    return d


# ── BaseRepository ────────────────────────────────────────────────────────

class TestBaseRepository:
    @pytest.mark.asyncio
    async def test_create_and_get_by_id(self, async_session: AsyncSession):
        repo = BaseRepository(async_session, DescriptionModel)
        obj = await repo.create(characteristics="Strong", backstory="Old")
        assert obj.id is not None
        result = await repo.get_by_id(obj.id)
        assert result.characteristics == "Strong"

    @pytest.mark.asyncio
    async def test_get_all(self, async_session: AsyncSession):
        repo = BaseRepository(async_session, DescriptionModel)
        await repo.create(characteristics="A", backstory="1")
        await repo.create(characteristics="B", backstory="2")
        items = await repo.get_all()
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_update(self, async_session: AsyncSession):
        repo = BaseRepository(async_session, DescriptionModel)
        obj = await repo.create(characteristics="Old", backstory="x")
        updated = await repo.update(obj.id, characteristics="New")
        assert updated.characteristics == "New"

    @pytest.mark.asyncio
    async def test_delete(self, async_session: AsyncSession):
        repo = BaseRepository(async_session, DescriptionModel)
        obj = await repo.create(characteristics="Del", backstory="x")
        await repo.delete(obj.id)
        result = await repo.get_by_id(obj.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, async_session: AsyncSession):
        repo = BaseRepository(async_session, DescriptionModel)
        result = await repo.get_by_id(999)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_not_found(self, async_session: AsyncSession):
        repo = BaseRepository(async_session, DescriptionModel)
        assert await repo.delete(999) is False

    @pytest.mark.asyncio
    async def test_search_by_name(self, async_session: AsyncSession):
        repo = BaseRepository(async_session, ItemModel)
        await repo.create(name="Sword of Dawn", start_date=date(500, 1, 1))
        await repo.create(name="Shield", start_date=date(500, 1, 1))
        results = await repo.search_by_name("sword")
        assert len(results) == 1
        assert results[0].name == "Sword of Dawn"


# ── BaseRepository.search: one parameterized set for the 4 entity types ──

ENTITY_REPOS = [
    (OrganizationRepository, OrganizationModel),
    (CharacterRepository, CharacterModel),
    (ItemRepository, ItemModel),
    (LocationRepository, LocationModel),
]


@pytest.mark.parametrize(("repo_cls", "model"), ENTITY_REPOS, ids=["organization", "character", "item", "location"])
class TestEntitySearch:
    """BaseRepository.search is inherited by all entity repositories."""

    @pytest.mark.asyncio
    async def test_search_by_name(self, async_session: AsyncSession, repo_cls, model):
        desc = await _make_desc(async_session)
        repo = repo_cls(async_session)
        await repo.create(name="Battle of Plains", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        await repo.create(name="Siege of Castle", description_id=desc.id,
            start_date=date(1201, 1, 1), end_date=date(1201, 12, 31))
        results = await repo.search("Battle")
        assert len(results) == 1
        assert results[0].name == "Battle of Plains"

    @pytest.mark.asyncio
    async def test_search_is_case_insensitive(self, async_session: AsyncSession, repo_cls, model):
        desc = await _make_desc(async_session)
        repo = repo_cls(async_session)
        await repo.create(name="Battle of Plains", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        assert len(await repo.search("bAtTlE")) == 1

    @pytest.mark.asyncio
    async def test_search_by_characteristics(self, async_session: AsyncSession, repo_cls, model):
        desc = await _make_desc(async_session, chars="Massive cavalry charge", back="y")
        repo = repo_cls(async_session)
        await repo.create(name="Entry1", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        results = await repo.search("cavalry")
        assert len(results) == 1
        assert results[0].name == "Entry1"

    @pytest.mark.asyncio
    async def test_search_by_backstory(self, async_session: AsyncSession, repo_cls, model):
        desc = await _make_desc(async_session, chars="x", back="Two ancient kingdoms clashed")
        repo = repo_cls(async_session)
        await repo.create(name="Entry2", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        results = await repo.search("ancient")
        assert len(results) == 1
        assert results[0].name == "Entry2"

    @pytest.mark.asyncio
    async def test_search_no_duplicates_on_multiple_hits(self, async_session: AsyncSession, repo_cls, model):
        # Matches name AND description in one row -> still a single result
        desc = await _make_desc(async_session, chars="Dragon attack", back="Dragon era")
        repo = repo_cls(async_session)
        await repo.create(name="Dragon war", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        assert len(await repo.search("Dragon")) == 1


# ── EventRepository ───────────────────────────────────────────────────────

class TestEventRepository:
    @pytest.mark.asyncio
    async def test_create_event(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        event = await repo.create(
            name="Battle", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31),
        )
        assert event.id is not None
        assert event.name == "Battle"

    @pytest.mark.asyncio
    async def test_get_event_with_relations(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        event = await repo.create(
            name="E1", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31),
        )
        result = await repo.get_by_id(event.id)
        assert result is not None
        assert hasattr(result, "organizations")

    @pytest.mark.asyncio
    async def test_search_events_by_name(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        await repo.create(name="Battle of Plains", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        await repo.create(name="Siege of Castle", description_id=desc.id,
            start_date=date(1201, 1, 1), end_date=date(1201, 12, 31))
        results = await repo.search("Battle")
        assert len(results) == 1
        assert results[0].name == "Battle of Plains"

    @pytest.mark.asyncio
    async def test_search_events_by_partial_name_2_chars(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        await repo.create(name="Battle of Plains", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        results = await repo.search("Ba")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_events_by_characteristics(self, async_session: AsyncSession):
        desc = await _make_desc(async_session, chars="Massive cavalry charge", back="y")
        repo = EventRepository(async_session)
        await repo.create(name="Event1", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        results = await repo.search("cavalry")
        assert len(results) == 1
        assert results[0].name == "Event1"

    @pytest.mark.asyncio
    async def test_search_events_by_backstory(self, async_session: AsyncSession):
        desc = await _make_desc(async_session, chars="x", back="Two ancient kingdoms clashed")
        repo = EventRepository(async_session)
        await repo.create(name="Event2", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        results = await repo.search("ancient")
        assert len(results) == 1
        assert results[0].name == "Event2"

    @pytest.mark.asyncio
    async def test_search_events_no_duplicates(self, async_session: AsyncSession):
        desc = await _make_desc(async_session, chars="Dragon attack", back="Dragon era")
        repo = EventRepository(async_session)
        await repo.create(name="Dragon war", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        results = await repo.search("Dragon")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_get_all_ordered_by_start_date(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        await repo.create(name="Later", description_id=desc.id,
            start_date=date(1300, 1, 1), end_date=date(1300, 12, 31))
        await repo.create(name="Earlier", description_id=desc.id,
            start_date=date(1100, 1, 1), end_date=date(1100, 12, 31))
        events = await repo.get_all_ordered()
        assert events[0].name == "Earlier"
        assert events[1].name == "Later"

    @pytest.mark.asyncio
    async def test_get_events_at_date(self, async_session: AsyncSession):
        d1 = await _make_desc(async_session)
        d2 = await _make_desc(async_session)
        repo = EventRepository(async_session)
        await repo.create(name="Closed", description_id=d1.id, start_date=date(1200, 1, 1), end_date=date(1200, 6, 30))
        await repo.create(name="Infinite", description_id=d2.id, start_date=date(1300, 1, 1), end_date=None)
        names = {e.name for e in await repo.get_events_at_date(era_key(date(1200, 6, 15)))}
        assert names == {"Closed"}
        names = {e.name for e in await repo.get_events_at_date(era_key(date(1300, 3, 1)))}
        assert names == {"Infinite"}

    @pytest.mark.asyncio
    async def test_mixed_era_ordering(self, async_session: AsyncSession):
        # Spec «Единый хронологический порядок» / Scenario «Смешанная сортировка»:
        # 500 г. до н.э. → 1 г. н.э. → 2026, не по возрастанию чисел года.
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        await repo.create(name="New", description_id=desc.id,
            start_date=date(2026, 1, 1), end_date=None)
        await repo.create(name="Ancient", description_id=desc.id,
            start_date=date(500, 1, 1), start_bc=1, end_date=None)
        await repo.create(name="Threshold", description_id=desc.id,
            start_date=date(1, 1, 5), end_date=None)
        names = [e.name for e in await repo.get_all_ordered()]
        assert names == ["Ancient", "Threshold", "New"]

    @pytest.mark.asyncio
    async def test_bc_open_ended_covered_by_ce_window(self, async_session: AsyncSession):
        # Scenario «Бессрочное из доисторического прошлого накрыто окном н.э.»
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        await repo.create(name="Ancient cult", description_id=desc.id,
            start_date=date(300, 6, 1), start_bc=1, end_date=None)
        names = {e.name for e in await repo.get_events_at_date(era_key(date(2026, 9, 15)))}
        assert names == {"Ancient cult"}

    @pytest.mark.asyncio
    async def test_bc_event_before_ce_window_excluded(self, async_session: AsyncSession):
        # Closed in BC — must NOT surface in a CE query: with raw date text
        # the interval would look "future" and (end_date >= target) would
        # wrongly pass; keys order it before every CE moment instead.
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        await repo.create(name="Fallen kingdom", description_id=desc.id,
            start_date=date(400, 1, 1), start_bc=1,
            end_date=date(350, 1, 1), end_bc=1)
        names = {e.name for e in await repo.get_events_at_date(era_key(date(2026, 9, 15)))}
        assert names == set()

    # ── start_time (NRI-0023 task 1.3, design Д2): the ORM row maps the one
    # nullable INTEGER of minutes from the day start to the domain TimeOfDay;
    # NULL ⟷ None and the minute unit is the ACTIVE calendar's hour.

    async def test_start_time_defaults_to_none(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        event = await repo.create(name="All-day market", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=None)
        assert event.start_time is None  # «весь день, с утра», never a 00:00

    async def test_create_stores_minutes_and_reads_the_time_back(
        self, async_session: AsyncSession
    ):
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        event = await repo.create(name="Battle", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=None,
            start_time=TimeOfDay(14, 30))
        assert event.start_time == TimeOfDay(14, 30)
        # the column itself holds the single linear number the SQL order uses
        raw = await async_session.scalar(
            select(EventModel.__table__.c.start_time).where(
                EventModel.__table__.c.id == event.id
            )
        )
        assert raw == 14 * 60 + 30
        # a reload reads the same time through the row attribute
        reloaded = await repo.get_by_id(event.id)
        assert reloaded.start_time == TimeOfDay(14, 30)

    async def test_update_sets_then_clears_the_time(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        event = await repo.create(name="Feast", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=None)
        updated = await repo.update(event.id, start_time=TimeOfDay(9, 5))
        assert updated.start_time == TimeOfDay(9, 5)
        cleared = await repo.update(event.id, start_time=None)
        assert cleared.start_time is None
        raw = await async_session.scalar(
            select(EventModel.__table__.c.start_time).where(
                EventModel.__table__.c.id == event.id
            )
        )
        assert raw is None  # clearing writes NULL, not 0

    async def test_minutes_count_in_the_active_calendar_hour(
        self, async_session: AsyncSession
    ):
        # spec «Нездешние сутки»: in a 10-hour, 100-minute world 2:30 is the
        # 230th minute, and the same stored 230 stays 2:30 while that
        # calendar is active; under the earthly preset the row re-reads its
        # number in 60-minute hours (the spec's calendar-swap reading, Д2)
        alien = CustomCalendar(CalendarSpec(
            months=(MonthSpec("Зимостой", 30),),
            week_names=("Восход", "Тень"),
            day_hours=10,
            minutes_per_hour=100,
        ))
        saved = current_calendar()
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        try:
            set_current_calendar(alien)
            event = await repo.create(name="Alien rite", description_id=desc.id,
                start_date=date(1200, 1, 1), end_date=None,
                start_time=TimeOfDay(2, 30))
            assert event.start_time == TimeOfDay(2, 30)
            raw = await async_session.scalar(
                select(EventModel.__table__.c.start_time).where(
                    EventModel.__table__.c.id == event.id
                )
            )
            assert raw == 2 * 100 + 30
            # the stored number never migrated — under the earthly unit the
            # very same 230 reads as that unit's own hour+minute split
            set_current_calendar(StandardCalendar())
            assert event.start_time == TimeOfDay(3, 50)
        finally:
            set_current_calendar(saved)

    async def test_null_time_survives_a_calendar_swap(
        self, async_session: AsyncSession
    ):
        # NULL means «без времени» in every world: widening or narrowing the
        # day must not invent a value for an absent time
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        event = await repo.create(name="Timeless", description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=None)
        saved = current_calendar()
        try:
            set_current_calendar(CustomCalendar(CalendarSpec(
                months=(MonthSpec("Зимостой", 30),),
                week_names=("Восход", "Тень"),
                day_hours=10,
                minutes_per_hour=100,
            )))
            assert event.start_time is None
        finally:
            set_current_calendar(saved)
        assert event.start_time is None

    # ── parent_id + within-day time order (NRI-0023 task 3.1, design Д1/Д3):
    # create/update take both new columns through the plain kwargs, and every
    # listing query orders a day as (untimed first, time, id).

    async def test_create_update_accept_parent_id(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        fair = await repo.create(name="Fair", description_id=desc.id,
            start_date=date(1200, 9, 12), end_date=None)
        feast = await repo.create(name="Feast", description_id=desc.id,
            start_date=date(1200, 9, 12), end_date=None)
        toast = await repo.create(name="Toast", description_id=desc.id,
            start_date=date(1200, 9, 12), end_date=None,
            parent_id=fair.id, start_time=TimeOfDay(18, 0))
        assert toast.parent_id == fair.id
        assert toast.start_time == TimeOfDay(18, 0)  # both kwargs in one create
        # перецепка — update moves the link to another parent…
        moved = await repo.update(toast.id, parent_id=feast.id)
        assert moved.parent_id == feast.id
        # …and подъём в основные — an explicit NULL detaches it again.
        # The two-level guard on this write is EventService's (task 3.2).
        promoted = await repo.update(toast.id, parent_id=None)
        assert promoted.parent_id is None

    async def test_within_day_untimed_first_then_time_then_id(
        self, async_session: AsyncSession
    ):
        # spec event-time «Бесвремянные первыми»: one day, ids 1/2/3 in the
        # scenario's creation order — «Без времени», 14:30, then 9:00.
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        day = date(1200, 9, 12)
        await repo.create(name="Без времени", description_id=desc.id,
            start_date=day, end_date=None)
        await repo.create(name="В 14:30", description_id=desc.id,
            start_date=day, end_date=None, start_time=TimeOfDay(14, 30))
        await repo.create(name="В 9:00", description_id=desc.id,
            start_date=day, end_date=None, start_time=TimeOfDay(9, 0))
        names = [e.name for e in await repo.get_all_ordered()]
        assert names == ["Без времени", "В 9:00", "В 14:30"]

    async def test_full_time_tie_orders_by_id(self, async_session: AsyncSession):
        # spec «Полное совпадение не сливает и не спорит»: same day + same
        # time (and two untimed ones) stay separate rows in ascending id.
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        day = date(1200, 9, 12)
        first_untimed = await repo.create(name="Market", description_id=desc.id,
            start_date=day, end_date=None)
        second_untimed = await repo.create(name="Muster", description_id=desc.id,
            start_date=day, end_date=None)
        first_nine = await repo.create(name="Council", description_id=desc.id,
            start_date=day, end_date=None, start_time=TimeOfDay(9, 0))
        second_nine = await repo.create(name="Duel", description_id=desc.id,
            start_date=day, end_date=None, start_time=TimeOfDay(9, 0))
        ids = [e.id for e in await repo.get_all_ordered()]
        # the untimed bucket first (each by id), then the timed one (by id)
        assert ids == [first_untimed.id, second_untimed.id,
                       first_nine.id, second_nine.id]

    async def test_day_boundary_order_ignores_time(
        self, async_session: AsyncSession
    ):
        # spec «Порядок разных дней не трогает»: the 12th at 23:00 still
        # precedes the 13th at 8:00 — start_key rules across days, the hour
        # is only the within-day tiebreaker.
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        await repo.create(name="В 8:00", description_id=desc.id,
            start_date=date(1200, 9, 13), end_date=None, start_time=TimeOfDay(8, 0))
        await repo.create(name="В 23:00", description_id=desc.id,
            start_date=date(1200, 9, 12), end_date=None, start_time=TimeOfDay(23, 0))
        names = [e.name for e in await repo.get_all_ordered()]
        assert names == ["В 23:00", "В 8:00"]

    async def test_get_events_at_date_shares_the_within_day_order(
        self, async_session: AsyncSession
    ):
        # the window query reuses the same secondary key: covering events of
        # one day come back untimed-first, then by time (spec «Время участвует
        # в порядке внутри дня» holds on every listing, not only the ladder's)
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        day = date(1200, 9, 12)
        await repo.create(name="В 14:30", description_id=desc.id,
            start_date=day, end_date=None, start_time=TimeOfDay(14, 30))
        await repo.create(name="Без времени", description_id=desc.id,
            start_date=day, end_date=None)
        await repo.create(name="В 9:00", description_id=desc.id,
            start_date=day, end_date=None, start_time=TimeOfDay(9, 0))
        names = [
            e.name for e in await repo.get_events_at_date(era_key(day))
        ]
        assert names == ["Без времени", "В 9:00", "В 14:30"]

    async def test_sql_order_agrees_with_the_core_rule_on_one_sample(
        self, async_session: AsyncSession
    ):
        # design Д3 (risk «двойной источник порядка»): the SQL tuple of
        # EventRepository is only the optimization, the Qt-free core's
        # ``(start_key, время, id)`` is the rule — this test walks BOTH paths
        # over the SAME stored sample (a day mixing untimed/timed rows and a
        # full time tie, a later day where the hour must not pull, a BC row
        # that must lead) and pins that the two orders never diverge.
        desc = await _make_desc(async_session)
        repo = EventRepository(async_session)
        day = date(1200, 9, 12)
        await repo.create(name="Без времени", description_id=desc.id,
            start_date=day, end_date=None)
        await repo.create(name="В 14:30", description_id=desc.id,
            start_date=day, end_date=None, start_time=TimeOfDay(14, 30))
        await repo.create(name="В 9:00", description_id=desc.id,
            start_date=day, end_date=None, start_time=TimeOfDay(9, 0))
        await repo.create(name="Дуэль, id-второй", description_id=desc.id,
            start_date=day, end_date=None, start_time=TimeOfDay(9, 0))
        await repo.create(name="В 8:00 назавтра", description_id=desc.id,
            start_date=date(1200, 9, 13), end_date=None, start_time=TimeOfDay(8, 0))
        await repo.create(name="Падение", description_id=desc.id,
            start_date=date(400, 1, 1), start_bc=1,
            end_date=date(350, 1, 1), end_bc=1)
        sample = list(await repo.get_all_ordered())
        sql_ids = [e.id for e in sample]
        # the core path on the very same rows (input order reversed on
        # purpose: build_rows sorts, the feed order must not matter)
        core_ids = [row.event_id for row in build_rows(list(reversed(sample)))]
        assert core_ids == sql_ids
        # and the agreed order itself is the spec's (era, day, untimed
        # first, time, id) — not merely self-consistent
        by_id = {e.id: e.name for e in sample}
        assert [by_id[event_id] for event_id in sql_ids] == [
            "Падение", "Без времени", "В 9:00", "Дуэль, id-второй",
            "В 14:30", "В 8:00 назавтра",
        ]


# ── dated_repository factory (C4: one body, four models) ─────────────────

class TestDatedRepositoryFactory:
    def test_factory_is_model_stable_and_alias_matches(self):
        # Same model → same class (is-identity): factory callers and the
        # four module aliases never end up with two classes per model.
        assert dated_repository(CharacterModel) is CharacterRepository
        # Distinct models → distinct classes named after the model.
        assert dated_repository(ItemModel) is not dated_repository(LocationModel)
        assert CharacterRepository.__name__ == "CharacterModelRepository"

    @pytest.mark.asyncio
    async def test_factory_instances_keep_the_dated_contract(self, async_session: AsyncSession):
        repo = dated_repository(LocationModel)(async_session)
        assert isinstance(repo, CoordMappingMixin)  # dates route through C3a
        assert repo.model is LocationModel
        desc = await _make_desc(async_session)
        loc = await repo.create(
            name="Tower", description_id=desc.id,
            start_date=date(100, 1, 1), end_date=date(300, 1, 1),
        )
        assert (await repo.get_by_id(loc.id)).name == "Tower"


# ── OrganizationRepository ────────────────────────────────────────────────

class TestOrganizationRepository:
    @pytest.mark.asyncio
    async def test_crud(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = OrganizationRepository(async_session)
        org = await repo.create(
            name="Guild", description_id=desc.id,
            start_date=date(1000, 1, 1), end_date=date(1500, 12, 31),
            tasks="Protect",
        )
        assert org.name == "Guild"
        result = await repo.get_by_id(org.id)
        assert result.tasks == "Protect"


# ── CharacterRepository ──────────────────────────────────────────────────

class TestCharacterRepository:
    @pytest.mark.asyncio
    async def test_crud(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = CharacterRepository(async_session)
        char = await repo.create(
            name="Hero", description_id=desc.id,
            start_date=date(1100, 1, 1), end_date=date(1200, 1, 1),
            personality="Brave", image="/img/hero.png", tasks="Save",
        )
        assert char.name == "Hero"
        result = await repo.get_by_id(char.id)
        assert result.personality == "Brave"


# ── ItemRepository ────────────────────────────────────────────────────────

class TestItemRepository:
    @pytest.mark.asyncio
    async def test_crud(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = ItemRepository(async_session)
        item = await repo.create(name="Sword", description_id=desc.id,
            start_date=date(500, 1, 1), end_date=date(3000, 12, 31))
        assert item.name == "Sword"

    @pytest.mark.asyncio
    async def test_image_ref_save_read_null(self, async_session: AsyncSession):
        """NRI-0022: the item repository stores/returns the images link the
        same way the organization repository does (image_id + eager image_ref)."""
        desc = await _make_desc(async_session)
        img = ImageModel(sha256="1" * 64, ext="png", width=1, height=1, size_bytes=1)
        async_session.add(img)
        await async_session.flush()

        repo = ItemRepository(async_session)
        item = await repo.create(
            name="Lamp", description_id=desc.id,
            start_date=date(500, 1, 1), image_id=img.id,
        )
        fetched = await repo.get_by_id(item.id)
        assert fetched.image_id == img.id
        # eager selectin (the org pattern): the row arrives with the reference
        assert fetched.image_ref is not None
        assert fetched.image_ref.id == img.id

        updated = await repo.update(item.id, image_id=None)
        assert updated.image_id is None
        await async_session.refresh(updated)  # the stale-identity half: reload
        assert updated.image_ref is None


# ── LocationRepository ────────────────────────────────────────────────────

class TestLocationRepository:
    @pytest.mark.asyncio
    async def test_crud(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = LocationRepository(async_session)
        loc = await repo.create(
            name="Mordor", description_id=desc.id,
            start_date=date(100, 1, 1), end_date=date(3000, 12, 31),
            tasks="Defend", image="/maps/mordor.png",
        )
        assert loc.name == "Mordor"


# ── RatingRepository ──────────────────────────────────────────────────────

class TestRatingRepository:
    @pytest.mark.asyncio
    async def test_crud(self, async_session: AsyncSession):
        desc = await _make_desc(async_session)
        repo = RatingRepository(async_session)
        rating = await repo.create(description_id=desc.id,
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31), level=5)
        assert rating.level == 5
        result = await repo.get_by_id(rating.id)
        assert result.level == 5
