"""DB tests for CalendarSettingsService (piece C2, tasks 2.1–2.4).

Cover the spec requirements «Перенос устаревшей настройки названий месяцев»,
«Повреждённое значение календарь-ключа», «Ключи записей в согласии с активным
календарём» and «Применение календаря к записям игры» on the in-memory
aiosqlite fixtures — no Qt, no dialogs (design D4 keeps warning display in
the caller).
"""
from __future__ import annotations

import json
import logging
from datetime import date

import pytest
from sqlalchemy import select, update

from app.application.services.calendar_settings_service import (
    CALENDAR_SETTINGS_KEY,
    LEGACY_MONTHS_KEY,
    CalendarSettingsService,
)
from app.domain.date_era import BC_YEAR_STEP
from app.domain.game_calendar import (
    DEFAULT_MONTH_NAMES,
    CalendarSpec,
    CustomCalendar,
    DateField,
    MonthDay,
    MonthSpec,
    ShiftReason,
    StandardCalendar,
    current_calendar,
    encode_calendar,
    reset_current_calendar,
)
from app.infrastructure.db.models import (
    CharacterModel,
    EventModel,
    GameSettingsModel,
    ItemModel,
    LocationModel,
    OrganizationModel,
    RatingModel,
)

# Three months of ten days each: any stored day > 10 overflows, any stored
# month number > 3 is out of count — the two shift fixtures of design D4.
_SPEC = CalendarSpec(
    months=(
        MonthSpec("Медвежарь", 10),
        MonthSpec("Ледокол", 10),
        MonthSpec("Травень", 10),
    ),
    week_names=("пн", "вт", "ср", "чт", "пт", "сб", "вс"),
)
_CUSTOM = CustomCalendar(_SPEC)

_ERA_TABLES = (
    EventModel,
    OrganizationModel,
    CharacterModel,
    ItemModel,
    LocationModel,
    RatingModel,
)


@pytest.fixture(autouse=True)
def _fresh_active_calendar():
    """The service installs a process-global — no test inherits another's calendar."""
    reset_current_calendar()
    yield
    reset_current_calendar()


async def _put_setting(session, key: str, value: str) -> None:
    session.add(GameSettingsModel(key=key, value=value))
    await session.commit()


async def _setting(session, key: str) -> str | None:
    return (
        await session.execute(
            select(GameSettingsModel.value).where(GameSettingsModel.key == key)
        )
    ).scalars().first()


async def _snapshot(session) -> dict[str, list[tuple]]:
    """Raw stored state of every dated table, straight from SQL columns."""
    tables = {}
    for model in _ERA_TABLES:
        rows = (
            await session.execute(
                select(
                    model.id,
                    model.start_date,
                    model.start_bc,
                    model.start_key,
                    model.end_date,
                    model.end_bc,
                    model.end_key,
                ).order_by(model.id)
            )
        ).all()
        tables[model.__tablename__] = [tuple(row) for row in rows]
    return tables


async def _add_event(session, start, end, **flags) -> EventModel:
    event = EventModel(name="event", start_date=start, end_date=end, **flags)
    session.add(event)
    await session.commit()
    return event


# ── 2.1: load + one-shot custom_months migration (design D3) ──────────────

class TestLoadAndLegacyMigration:
    async def test_old_game_without_key_gets_preset_and_stays_keyless(
        self, async_session
    ):
        service = CalendarSettingsService()

        outcome = await service.load_and_apply(async_session)

        assert outcome.reasons == ()
        assert isinstance(outcome.calendar, StandardCalendar)
        assert current_calendar() is outcome.calendar
        assert outcome.calendar.month_names == dict(DEFAULT_MONTH_NAMES)
        # No key is stored "just in case" (spec «Старая игра без ключа»).
        assert await _setting(async_session, CALENDAR_SETTINGS_KEY) is None
        assert await _setting(async_session, LEGACY_MONTHS_KEY) is None
        # Standard preset reproduces the pre-setting key numbers.
        assert outcome.calendar.to_key(MonthDay(2024, 3, 7)) == date(2024, 3, 7).toordinal()

    async def test_renames_migrate_and_old_key_dies(self, async_session):
        await _put_setting(async_session, LEGACY_MONTHS_KEY, '{"3": "Медвежарь"}')
        service = CalendarSettingsService()

        outcome = await service.load_and_apply(async_session)

        assert await _setting(async_session, LEGACY_MONTHS_KEY) is None
        stored = json.loads(await _setting(async_session, CALENDAR_SETTINGS_KEY))
        assert stored == {
            "v": 1,
            "kind": "standard",
            "month_names": {"3": "Медвежарь"},
        }
        assert isinstance(outcome.calendar, StandardCalendar)
        assert current_calendar().month_names[3] == "Медвежарь"
        assert current_calendar().month_names[1] == "Январь"

    async def test_reopened_game_does_not_migrate_again(self, async_session):
        await _put_setting(async_session, LEGACY_MONTHS_KEY, '{"3": "Медвежарь"}')
        service = CalendarSettingsService()
        await service.load_and_apply(async_session)
        first_value = await _setting(async_session, CALENDAR_SETTINGS_KEY)

        await service.load_and_apply(async_session)

        assert await _setting(async_session, LEGACY_MONTHS_KEY) is None
        assert await _setting(async_session, CALENDAR_SETTINGS_KEY) == first_value

    async def test_default_equivalent_names_produce_no_new_key(self, async_session):
        gregorian = json.dumps(
            {str(number): name for number, name in DEFAULT_MONTH_NAMES.items()},
            ensure_ascii=False,
        )
        await _put_setting(async_session, LEGACY_MONTHS_KEY, gregorian)
        service = CalendarSettingsService()

        await service.load_and_apply(async_session)

        assert await _setting(async_session, LEGACY_MONTHS_KEY) is None
        assert await _setting(async_session, CALENDAR_SETTINGS_KEY) is None
        assert current_calendar().month_names[3] == "Март"

    async def test_corrupt_legacy_key_is_dropped_without_a_new_one(
        self, async_session, caplog
    ):
        await _put_setting(
            async_session, LEGACY_MONTHS_KEY, "{ это не json"
        )
        service = CalendarSettingsService()

        with caplog.at_level(logging.WARNING):
            outcome = await service.load_and_apply(async_session)

        assert await _setting(async_session, LEGACY_MONTHS_KEY) is None
        assert await _setting(async_session, CALENDAR_SETTINGS_KEY) is None
        assert isinstance(outcome.calendar, StandardCalendar)
        assert outcome.calendar.month_names == dict(DEFAULT_MONTH_NAMES)
        # The fact is logged (design D3), even without a dialog.
        assert any(LEGACY_MONTHS_KEY in record.message for record in caplog.records)

    @pytest.mark.parametrize(
        "raw",
        [
            pytest.param("[1, 2]", id="json-not-an-object"),
            pytest.param('"Январь"', id="json-string-not-an-object"),
            pytest.param('{"3": 7}', id="name-is-not-a-string"),
            pytest.param('{"первый": "Медвежарь"}', id="key-is-not-a-month-number"),
        ],
    )
    async def test_malformed_legacy_shapes_take_the_corrupt_branch(
        self, async_session, raw
    ):
        # Every shape ``_decode_legacy_months`` refuses — a parsed-but-not
        # object value, a non-string name, a non-integer month key — is the
        # same D3 corrupt branch as unparseable JSON: the old key dies, no
        # new key appears, the game opens on the default-named preset.
        await _put_setting(async_session, LEGACY_MONTHS_KEY, raw)
        service = CalendarSettingsService()

        outcome = await service.load_and_apply(async_session)

        assert await _setting(async_session, LEGACY_MONTHS_KEY) is None
        assert await _setting(async_session, CALENDAR_SETTINGS_KEY) is None
        assert isinstance(outcome.calendar, StandardCalendar)
        assert outcome.calendar.month_names == dict(DEFAULT_MONTH_NAMES)

    async def test_both_keys_new_wins_and_old_is_removed(self, async_session):
        custom_value = encode_calendar(_CUSTOM)
        await _put_setting(async_session, CALENDAR_SETTINGS_KEY, custom_value)
        await _put_setting(async_session, LEGACY_MONTHS_KEY, '{"1": "Древний"}')
        service = CalendarSettingsService()

        outcome = await service.load_and_apply(async_session)

        assert await _setting(async_session, LEGACY_MONTHS_KEY) is None
        assert await _setting(async_session, CALENDAR_SETTINGS_KEY) == custom_value
        assert isinstance(outcome.calendar, CustomCalendar)
        assert current_calendar().month_names[1] == "Медвежарь"


# ── 2.2: corrupted game_calendar value (design D4) ────────────────────────

class TestCorruptedCalendarKey:
    async def test_broken_custom_spec_opens_on_preset_and_keeps_the_row(
        self, async_session, caplog
    ):
        raw = json.dumps(
            {
                "v": 1,
                "kind": "custom",
                "months": [
                    {"name": "А", "length": 10},
                    {"name": "Б", "length": 10},
                ],
                "week_names": ["пн", "вт", "ср", "чт", "пт", "сб", "вс"],
                # Host month 5 does not exist — the core validation rejects it.
                "intercalary": [{"name": "В", "after_month": 5}],
            },
            ensure_ascii=False,
        )
        await _put_setting(async_session, CALENDAR_SETTINGS_KEY, raw)
        service = CalendarSettingsService()

        with caplog.at_level(logging.WARNING):
            outcome = await service.load_and_apply(async_session)

        assert {problem.code for problem in outcome.reasons} == {
            "intercalary_unknown_month"
        }
        assert isinstance(current_calendar(), StandardCalendar)
        assert current_calendar().month_names == dict(DEFAULT_MONTH_NAMES)
        # The damaged row is neither rewritten nor deleted.
        assert await _setting(async_session, CALENDAR_SETTINGS_KEY) == raw
        assert any("game_calendar" in record.message for record in caplog.records)

    async def test_unknown_version_takes_the_same_path(self, async_session, caplog):
        raw = '{"v": 2, "kind": "standard"}'
        await _put_setting(async_session, CALENDAR_SETTINGS_KEY, raw)
        service = CalendarSettingsService()

        with caplog.at_level(logging.WARNING):
            outcome = await service.load_and_apply(async_session)

        assert {problem.code for problem in outcome.reasons} == {"unknown_version"}
        assert isinstance(current_calendar(), StandardCalendar)
        assert await _setting(async_session, CALENDAR_SETTINGS_KEY) == raw
        assert caplog.records


# ── 2.3: reconcile_era_keys (design D5) ───────────────────────────────────

class TestReconcileEraKeys:
    async def test_fixes_external_tampering_then_is_idempotent(self, async_session):
        event = await _add_event(
            async_session, date(2023, 5, 17), date(2023, 6, 1)
        )
        # A direct UPDATE in the app's absence (spec «Исправление внешнего
        # вмешательства»): a wrong start key and a wiped (NULL, old-version
        # style) end key.
        await async_session.execute(
            update(EventModel)
            .where(EventModel.id == event.id)
            .values(start_key=42, end_key=None)
        )
        await async_session.commit()
        # The core UPDATE bypasses the identity map — force a reload so the
        # reconcile sees the tampered state exactly as a start-up open would.
        async_session.expire_all()
        service = CalendarSettingsService()

        changed = await service.reconcile_era_keys(async_session)

        assert changed == 1
        (row,) = (
            await async_session.execute(
                select(EventModel.start_key, EventModel.end_key).where(
                    EventModel.id == event.id
                )
            )
        ).all()
        assert row == (date(2023, 5, 17).toordinal(), date(2023, 6, 1).toordinal())

        before = await _snapshot(async_session)
        second = await service.reconcile_era_keys(async_session)
        assert second == 0
        assert await _snapshot(async_session) == before

    async def test_standard_numbers_match_the_old_gregorian_scheme(
        self, async_session
    ):
        start_bc, end_bc = date(300, 3, 1), date(250, 12, 31)
        bc_event = await _add_event(async_session, start_bc, end_bc, start_bc=1, end_bc=1)
        ce_event = await _add_event(async_session, date(2024, 2, 29), None)
        # Emulate pre-key rows (what the deleted SQL backfill used to fill).
        await async_session.execute(
            update(EventModel).values(start_key=None, end_key=None)
        )
        await async_session.commit()
        async_session.expire_all()
        service = CalendarSettingsService()

        changed = await service.reconcile_era_keys(async_session)

        assert changed == 2
        rows = {
            event_id: (start_key, end_key)
            for event_id, start_key, end_key in (
                await async_session.execute(
                    select(EventModel.id, EventModel.start_key, EventModel.end_key)
                )
            ).all()
        }
        # The exact numbers of the previous scheme (D2 of add-era-aware-dates):
        # ordinal for our era, mirrored minus 732·year for BC.
        assert rows[bc_event.id] == (
            start_bc.toordinal() - BC_YEAR_STEP * start_bc.year,
            end_bc.toordinal() - BC_YEAR_STEP * end_bc.year,
        )
        assert rows[ce_event.id] == (date(2024, 2, 29).toordinal(), None)

    async def test_dangling_key_of_a_dateless_end_is_cleared(self, async_session):
        # An open-ended row whose end_key a pre-C2 writer left behind while
        # end_date is NULL: the reconcile clears the orphan key (a date
        # without a coordinate keys nothing) and the row counts as corrected
        # exactly once — the next pass again changes nothing.
        event = await _add_event(async_session, date(2023, 5, 17), None)
        await async_session.execute(
            update(EventModel)
            .where(EventModel.id == event.id)
            .values(end_key=12345)
        )
        await async_session.commit()
        async_session.expire_all()
        service = CalendarSettingsService()

        changed = await service.reconcile_era_keys(async_session)

        assert changed == 1
        (row,) = (
            await async_session.execute(
                select(EventModel.start_key, EventModel.end_key).where(
                    EventModel.id == event.id
                )
            )
        ).all()
        assert row == (date(2023, 5, 17).toordinal(), None)
        assert await service.reconcile_era_keys(async_session) == 0


# ── 2.4: apply_to_records (design D6) ─────────────────────────────────────

class _BoomCalendar:
    """Forwards the protocol but refuses ``to_key`` on one coordinate —
    simulates an error struck mid-application (spec «Ошибка применения
    откатывает всё»)."""

    def __init__(self, inner, boom_coord):
        self._inner = inner
        self._boom_coord = boom_coord

    def to_key(self, coord, is_bc=False):
        if coord == self._boom_coord:
            raise RuntimeError("boom mid-migration")
        return self._inner.to_key(coord, is_bc)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class TestApplyToRecords:
    @staticmethod
    async def _fixture_rows(async_session):
        valid = await _add_event(async_session, date(2023, 2, 5), date(2023, 3, 10))
        both_bad = await _add_event(async_session, date(2023, 1, 15), date(2023, 6, 1))
        character = CharacterModel(
            name="character",
            start_date=date(2023, 2, 11),
            end_date=None,
            start_bc=1,
        )
        async_session.add(character)
        await async_session.commit()
        return valid, both_bad, character

    async def test_preview_lists_exactly_the_invalid_and_changes_nothing(
        self, async_session
    ):
        _valid, both_bad, character = await self._fixture_rows(async_session)
        before = await _snapshot(async_session)
        service = CalendarSettingsService()

        report = await service.apply_to_records(async_session, _CUSTOM)  # dry_run default

        assert report.shift_count == 3
        assert [(e.table, e.row_id, e.field, e.reason) for e in report.records] == [
            ("events", both_bad.id, DateField.START, ShiftReason.DAY_OVERFLOW),
            ("events", both_bad.id, DateField.END, ShiftReason.MONTH_OUT_OF_RANGE),
            ("characters", character.id, DateField.START, ShiftReason.DAY_OVERFLOW),
        ]
        assert report.records[0].old == (MonthDay(2023, 1, 15), False)
        assert report.records[0].new == (MonthDay(2023, 1, 10), False)
        # Clamp of design D4 lands on the last day of the last month…
        assert report.records[1].new == (MonthDay(2023, 3, 10), False)
        # …and the era is carried untouched on both sides.
        assert report.records[2].old == (MonthDay(2023, 2, 11), True)
        assert report.records[2].new == (MonthDay(2023, 2, 10), True)
        assert await _snapshot(async_session) == before

    async def test_apply_moves_exactly_what_preview_listed(
        self, async_session
    ):
        _valid, both_bad, character = await self._fixture_rows(async_session)
        service = CalendarSettingsService()
        preview = await service.apply_to_records(
            async_session, _CUSTOM, dry_run=True
        )

        applied = await service.apply_to_records(
            async_session, _CUSTOM, dry_run=False
        )

        assert applied.records == preview.records
        rows = {
            (event_id, start_date, start_bc, start_key)
            for event_id, start_date, start_bc, start_key in (
                await async_session.execute(
                    select(
                        EventModel.id,
                        EventModel.start_date,
                        EventModel.start_bc,
                        EventModel.start_key,
                    )
                )
            ).all()
        }
        assert (both_bad.id, date(2023, 1, 10), 0, _CUSTOM.to_key(MonthDay(2023, 1, 10))) in rows
        (end, end_key), = (
            await async_session.execute(
                select(EventModel.end_date, EventModel.end_key).where(
                    EventModel.id == both_bad.id
                )
            )
        ).all()
        assert end == date(2023, 3, 10)
        assert end_key == _CUSTOM.to_key(MonthDay(2023, 3, 10))
        char_row = (
            await async_session.execute(
                select(
                    CharacterModel.start_date,
                    CharacterModel.start_bc,
                    CharacterModel.start_key,
                ).where(CharacterModel.id == character.id)
            )
        ).one()
        assert tuple(char_row) == (
            date(2023, 2, 10),
            1,
            _CUSTOM.to_key(MonthDay(2023, 2, 10), True),
        )
        # Every stored coordinate is now valid in the new calendar.
        stored = await async_session.execute(
            select(EventModel.start_date, EventModel.end_date).union_all(
                select(CharacterModel.start_date, CharacterModel.end_date)
            )
        )
        for start, end in stored.all():
            for value in (start, end):
                if value is not None:
                    assert _CUSTOM.is_valid(MonthDay(value.year, value.month, value.day))

    async def test_error_midway_rolls_the_whole_application_back(
        self, async_session
    ):
        _valid, both_bad, character = await self._fixture_rows(async_session)
        before = await _snapshot(async_session)
        # The second report entry keys MonthDay(2023, 3, 10) — blow up on it,
        # i.e. after the first UPDATE has already reached the transaction.
        service = CalendarSettingsService()
        boom = _BoomCalendar(_CUSTOM, MonthDay(2023, 3, 10))

        with pytest.raises(RuntimeError):
            await service.apply_to_records(async_session, boom, dry_run=False)

        assert await _snapshot(async_session) == before
