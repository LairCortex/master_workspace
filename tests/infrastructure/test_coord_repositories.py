"""Repository-level coordinate mapping tests (C3a task 2.4, design D3/D4).

The six dated repositories map ORM storage to domain game coordinates in
both directions through the storage resolver: a payload keeps its legacy
``start_date``/``end_date`` names but starts carrying ``GameCoord`` (a plain
``date`` remains its special case); reads hand the truth back as
coordinates.  With the «Стандартный» preset active every coordinate column
of every saved row stays NULL — a standard game behaves and stores exactly
as before — while under an active custom calendar the coordinate survives a
reload byte for byte and the legacy date columns are never updated.

The module-scenario «Вставной день переживает перезапуск» (task 2.5) closes
the file as the cross-layer insurance: domain coordinate → repository →
SQLite → fresh session → same coordinate, same keys, same order.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.domain.game_calendar import (
    CalendarSpec,
    CustomCalendar,
    IntercalaryDay,
    IntercalarySpec,
    MonthDay,
    MonthSpec,
    encode_coord,
    reset_current_calendar,
    set_current_calendar,
)
from app.infrastructure.db.database import create_session_factory
from app.domain.game_calendar import DateField
from app.infrastructure.db.models import resolve_coord
from app.infrastructure.repositories.character_repository import (
    CharacterRepository,
)
from app.infrastructure.repositories.event_repository import EventRepository
from app.infrastructure.repositories.item_repository import ItemRepository
from app.infrastructure.repositories.location_repository import (
    LocationRepository,
)
from app.infrastructure.repositories.organization_repository import (
    OrganizationRepository,
)
from app.infrastructure.repositories.rating_repository import RatingRepository

# Same fixture calendar as the resolver tests: 10+10+30 days, one masked
# intercalary day after the first (host) month.
CUSTOM_SPEC = CalendarSpec(
    months=(
        MonthSpec("Медвежарь", 10),
        MonthSpec("Ледокол", 10),
        MonthSpec("Травень", 30),
    ),
    week_names=("пн", "вт", "ср", "чт", "пт", "сб", "вс"),
    intercalary=(IntercalarySpec("День Маски", 1),),
)
CUSTOM = CustomCalendar(CUSTOM_SPEC)

# (repository class, extra kwargs making the model constructible) for all
# six dated entities — every repository of the mapping is exercised.
DATED_REPOS = [
    pytest.param(EventRepository, {"name": "E"}, id="event"),
    pytest.param(OrganizationRepository, {"name": "O"}, id="organization"),
    pytest.param(CharacterRepository, {"name": "C"}, id="character"),
    pytest.param(ItemRepository, {"name": "I"}, id="item"),
    pytest.param(LocationRepository, {"name": "L"}, id="location"),
    pytest.param(RatingRepository, {"level": 3}, id="rating"),
]


@pytest.fixture(autouse=True)
def _pristine_active_calendar():
    """No test inherits another game's active calendar (the accessor is a
    process global; the standard-route assertions require the preset)."""
    reset_current_calendar()
    yield
    reset_current_calendar()


@pytest.fixture
def custom_calendar():
    set_current_calendar(CUSTOM)
    yield CUSTOM


# ── writing domain coordinates through the repositories (both kinds) ──────


class TestRepositoryCoordinateRoundTrip:
    """Сохранение координат обычного и вставного дня с эрой и побитовое
    чтение после перезагрузки (task 2.4)."""

    @pytest.mark.parametrize("repo_cls,extra", DATED_REPOS)
    async def test_custom_calendar_saves_both_coord_kinds_with_era(
        self, async_session, custom_calendar, repo_cls, extra
    ):
        repo = repo_cls(async_session)
        created = await repo.create(
            start_date=IntercalaryDay(44, 0),
            start_bc=1,
            end_date=MonthDay(44, 3, 10),
            end_bc=1,
            **extra,
        )
        await async_session.commit()

        # Reload through fresh ORM state — the DB round trip, not attributes.
        async_session.expunge_all()
        row = await repo.get_by_id(created.id)

        # Truth reads back as the very same coordinates (побитово):
        assert repo.resolve_coord(row, DateField.START) == IntercalaryDay(44, 0)
        assert repo.resolve_coord(row, DateField.END) == MonthDay(44, 3, 10)
        # stored as the codec texts — the canonical form of both kinds:
        assert row.start_coord == encode_coord(IntercalaryDay(44, 0)) == "I:44:0"
        assert row.end_coord == encode_coord(MonthDay(44, 3, 10)) == "M:44:3:10"
        # eras and derived keys followed the custom calendar:
        assert (row.start_bc, row.end_bc) == (1, 1)
        assert row.start_key == CUSTOM.to_key(IntercalaryDay(44, 0), True)
        assert row.end_key == CUSTOM.to_key(MonthDay(44, 3, 10), True)
        # the legacy preset slot never received a value: the INSERT route
        # only satisfied its NOT NULL with the placeholder — «мёртвое
        # наследие, не зеркало» (design D1).  The public attribute is the
        # coordinate itself now (the audit's app-seam contract): the dead
        # placeholder is only visible on the raw storage slot.
        assert row.start_date == IntercalaryDay(44, 0)
        assert row.start_date_raw == date(1, 1, 1)


    @pytest.mark.parametrize("repo_cls,extra", DATED_REPOS)
    async def test_custom_calendar_saves_plain_day_coordinate(
        self, async_session, custom_calendar, repo_cls, extra
    ):
        repo = repo_cls(async_session)
        created = await repo.create(
            start_date=MonthDay(100, 2, 5), end_date=None, **extra
        )
        await async_session.commit()
        async_session.expunge_all()
        row = await repo.get_by_id(created.id)

        assert repo.resolve_coord(row, DateField.START) == MonthDay(100, 2, 5)
        assert row.start_coord == "M:100:2:5"
        assert row.end_coord is None  # «дата живёт в прежних колонках» is vacuous here
        assert repo.resolve_coord(row, DateField.END) is None
        assert row.start_key == CUSTOM.to_key(MonthDay(100, 2, 5), False)
        assert row.end_key is None


# ── the standard preset keeps the pre-C3a storage byte-familiar ───────────


class TestStandardCalendarStorageUnchanged:
    """Сценарий «Стандартная игра не видит нового хранилища»: coord-колонки
    всех её строк пусты, чтение даёт прежние значения (task 2.4)."""

    @pytest.mark.parametrize("repo_cls,extra", DATED_REPOS)
    async def test_dates_written_under_standard_leave_coord_columns_null(
        self, async_session, repo_cls, extra
    ):
        repo = repo_cls(async_session)
        created = await repo.create(
            start_date=date(1200, 1, 1), end_date=date(1200, 12, 31), **extra
        )
        await async_session.commit()
        async_session.expunge_all()
        row = await repo.get_by_id(created.id)

        assert row.start_coord is None
        assert row.end_coord is None
        # the resolver reads the legacy columns as their own coordinates
        assert row.start_date == date(1200, 1, 1)
        assert repo.resolve_coord(row, DateField.START) == MonthDay(1200, 1, 1)
        assert repo.resolve_coord(row, DateField.END) == MonthDay(1200, 12, 31)

    @pytest.mark.parametrize("repo_cls,extra", DATED_REPOS)
    async def test_coordinate_input_under_standard_still_lands_in_dates(
        self, async_session, repo_cls, extra
    ):
        # D4 route: «стандартный → date» даже когдаHigher layer уже
        # оперирует координатой (payload-имена прежние).
        repo = repo_cls(async_session)
        created = await repo.create(
            start_date=MonthDay(1200, 5, 1),
            end_date=MonthDay(1200, 12, 31),
            **extra,
        )
        await async_session.commit()
        assert created.start_date == date(1200, 5, 1)
        assert created.start_coord is None
        assert created.end_date == date(1200, 12, 31)
        assert created.end_coord is None


class TestRepositoryWriteRoutes:
    """Маршруты записи через repository.update в обоих режимах (task 2.3/2.4
    сценарий «custom-запись не трогает наследие»)."""

    async def test_update_under_custom_routes_to_coord_and_keeps_legacy(
        self, async_session
    ):
        repo = EventRepository(async_session)
        created = await repo.create(
            name="pre-switch", start_date=date(1200, 1, 1), end_date=None
        )
        await async_session.commit()

        set_current_calendar(CUSTOM)
        try:
            updated = await repo.update(created.id, start_date=MonthDay(44, 2, 7))
            await async_session.commit()
        finally:
            reset_current_calendar()

        assert updated.start_coord == "M:44:2:7"
        # Наследие не тронуто — на сырой колонке; публичный атрибут уже
        # читает координату-истину (spec «Истина следует за заполненностью»).
        assert updated.start_date_raw == date(1200, 1, 1)
        assert updated.start_date == MonthDay(44, 2, 7)
        assert updated.start_key == CUSTOM.to_key(MonthDay(44, 2, 7), False)

    async def test_update_under_standard_routes_coord_into_date_columns(
        self, async_session
    ):
        repo = EventRepository(async_session)
        created = await repo.create(
            name="standard", start_date=date(1200, 1, 1), end_date=None
        )
        await async_session.commit()

        updated = await repo.update(created.id, start_date=MonthDay(1300, 6, 1))
        await async_session.commit()

        assert updated.start_date == date(1300, 6, 1)
        assert updated.start_coord is None


# ── cross-layer insurance: the intercalary day survives a restart (2.5) ───


async def test_intercalary_day_survives_session_restart(async_engine):
    """Сквозной тест домен↔ORM при подменённом кастомном календаре: запись
    создаётся вставным днём, переживает закрытие/открытие сессии с той же
    координатой и неизменным порядком ключей (spec «Вставной день
    переживает перезапуск»)."""
    reset_current_calendar()
    set_current_calendar(CUSTOM)
    try:
        session_factory = create_session_factory(async_engine)

        async with session_factory() as session:
            repo = EventRepository(session)
            host_last = await repo.create(
                name="Host month last day", start_date=MonthDay(44, 1, 10)
            )
            mask = await repo.create(
                name="Day of the Mask",
                start_date=IntercalaryDay(44, 0),
                end_date=MonthDay(44, 2, 10),
            )
            await session.commit()
            keys_before = (
                (host_last.start_key, host_last.end_key),
                (mask.start_key, mask.end_key),
            )

        # «Restart»: a fresh calendar load (C2 would re-decode the stored
        # key and re-activate the same custom calendar) and new sessions.
        reset_current_calendar()
        set_current_calendar(CUSTOM)
        async with session_factory() as session:
            repo = EventRepository(session)
            host_row = await repo.get_by_id(host_last.id)
            mask_row = await repo.get_by_id(mask.id)

            # same coordinates, read through the repository mapping
            assert repo.resolve_coord(host_row, DateField.START) == MonthDay(44, 1, 10)
            assert repo.resolve_coord(mask_row, DateField.START) == IntercalaryDay(44, 0)
            assert repo.resolve_coord(mask_row, DateField.END) == MonthDay(44, 2, 10)

            # same keys, unchanged order between the host month and the mask
            assert (
                host_row.start_key,
                host_row.end_key,
            ) == keys_before[0]
            assert (mask_row.start_key, mask_row.end_key) == keys_before[1]
            assert mask_row.start_coord == "I:44:0"
            ordered = [event.name for event in await repo.get_all_ordered()]
            assert ordered == ["Host month last day", "Day of the Mask"]
            assert (
                CUSTOM.to_key(MonthDay(44, 1, 10), False)
                < CUSTOM.to_key(IntercalaryDay(44, 0), False)
            )
    finally:
        reset_current_calendar()
