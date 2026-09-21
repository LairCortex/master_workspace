"""DB tests for CalendarSettingsService (pieces C2 + C3a tasks 3.1–3.2).

Cover the spec requirements «Перенос устаревшей настройки названий месяцев»,
«Повреждённое значение календарь-ключа», «Ключи записей в согласии с активным
календарём» and «Применение календаря к записям игры» on the in-memory
aiosqlite fixtures — no Qt, no dialogs (design D4 keeps warning display in
the caller).  Since C3a the service traversal goes through the storage
resolver: the startup sweep repairs coordinate columns, shifts invalid
coordinates through :func:`assign_coord` and reconciles keys (design D8),
while ``apply_to_records`` migrates whole storages — custom fills the
coordinate columns, the preset moves coordinates back to the date ones.
"""
from __future__ import annotations

import json
import logging
from dataclasses import replace
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
    CALENDAR_DRAFT_KEY,
    CALENDAR_DRAFT_VERSION,
    CALENDAR_STORAGE_VERSION,
    CALENDAR_WIZARD_SEEN_KEY,
    CALENDAR_WIZARD_SEEN_NO,
    DEFAULT_MONTH_NAMES,
    DRAFT_STAGE_INTERCALARY,
    DRAFT_STAGE_MONTHS,
    CalendarDraft,
    CalendarSpec,
    CustomCalendar,
    DateField,
    IntercalarySpec,
    MonthDay,
    MonthSpec,
    ShiftReason,
    StandardCalendar,
    current_calendar,
    encode_calendar,
    encode_coord,
    encode_draft,
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
    resolve_coord,
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

# Three months of 10 + 30 + 10 days: its second month holds days the real
# February has never seen — the coordinate the storage migration of task 3.2
# shifts on the way back to the «Стандартный» preset.
_SPEC_B = CalendarSpec(
    months=(
        MonthSpec("Медвежарь", 10),
        MonthSpec("Ледокол", 30),
        MonthSpec("Травень", 10),
    ),
    week_names=("пн", "вт", "ср", "чт", "пт", "сб", "вс"),
)
_CUSTOM_B = CustomCalendar(_SPEC_B)

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
    """Raw stored state of every dated table, straight from SQL columns
    (since C3a including the coordinate columns — they migrate too)."""
    tables = {}
    for model in _ERA_TABLES:
        rows = (
            await session.execute(
                select(
                    model.id,
                    # Raw physical columns via the table object: since C3a the
                    # public ``start_date``/``end_date`` names are coord-aware
                    # properties, while this snapshot deliberately compares the
                    # stored bytes of both storages.
                    model.__table__.c.start_date,
                    model.start_bc,
                    model.start_key,
                    model.start_coord,
                    model.__table__.c.end_date,
                    model.end_bc,
                    model.end_key,
                    model.end_coord,
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


# ── C3a 3.1: the startup sweep (design D8) ────────────────────────────────

class TestStartupSweep:
    """Spec «Ключи записей в согласии с активным календарём»: repair of the
    coordinate columns → shift of the invalid coordinates through
    ``assign_coord`` (logged) → key reconcile, one ordered and idempotent
    pass running right after the calendar load."""

    async def test_standard_game_sweep_is_a_no_op(self, async_session, caplog):
        # A standard game never notices the sweep: valid month-day
        # coordinates read from the date columns, empty coordinate columns,
        # bit-identical keys — the whole pass changes nothing at all.
        await _add_event(async_session, date(2023, 5, 17), date(2023, 6, 1))
        bc_character = CharacterModel(
            name="character", start_date=date(300, 3, 1), end_date=None,
            start_bc=1,
        )
        async_session.add(bc_character)
        await async_session.commit()
        before = await _snapshot(async_session)
        service = CalendarSettingsService()

        with caplog.at_level(logging.INFO):
            report = await service.sweep_dated_records(async_session)

        assert report.shift_count == 0
        assert caplog.records == []  # nothing to log: no moves, nothing corrupted
        after = await _snapshot(async_session)
        assert after == before
        # The no-op reading of the untouched storage is still the preset
        # truth: standard keys, coordinate columns empty.
        (row,) = after["events"]
        assert row[1] == date(2023, 5, 17) and row[3] == date(2023, 5, 17).toordinal()
        assert row[4] is None and row[8] is None

    async def test_manual_mismatch_is_cured_by_the_start(self, async_session, caplog):
        # Spec scenario «Ручное рассогласование лечится стартом»: the
        # setting was hand-set to a custom calendar while the rows still
        # carry dates invalid in it (day past the month length, month past
        # the month count).  The game opens without an error: every invalid
        # coordinate is shifted to the last valid day, each move is logged,
        # the keys become correct and the next start moves nothing.
        await _put_setting(async_session, CALENDAR_SETTINGS_KEY, encode_calendar(_CUSTOM))
        event = await _add_event(async_session, date(2023, 1, 15), date(2023, 6, 1))
        event_id = event.id
        service = CalendarSettingsService()

        with caplog.at_level(logging.INFO):  # the full game-open sequence
            await service.load_and_apply(async_session)
            report = await service.sweep_dated_records(async_session)

        assert [(e.table, e.row_id, e.field, e.reason) for e in report.records] == [
            ("events", event.id, DateField.START, ShiftReason.DAY_OVERFLOW),
            ("events", event.id, DateField.END, ShiftReason.MONTH_OUT_OF_RANGE),
        ]
        messages = " \n".join(record.getMessage() for record in caplog.records)
        for old, new in (("M:2023:1:15", "M:2023:1:10"), ("M:2023:6:1", "M:2023:3:10")):
            assert old in messages and new in messages
        assert "events" in messages and str(event.id) in messages

        (row,) = (
            await async_session.execute(
                select(
                    EventModel.__table__.c.start_date, EventModel.start_coord, EventModel.start_key,
                    EventModel.__table__.c.end_date, EventModel.end_coord, EventModel.end_key,
                ).where(EventModel.id == event.id)
            )
        ).all()
        # The active calendar is custom ⇒ the shifts were routed into the
        # coordinate columns; the dead legacy date columns keep their values.
        assert row.start_coord == encode_coord(MonthDay(2023, 1, 10))
        assert row.end_coord == encode_coord(MonthDay(2023, 3, 10))
        assert row.start_date == date(2023, 1, 15) and row.end_date == date(2023, 6, 1)
        # Keys come from the shifted coordinates through the active calendar.
        assert row.start_key == _CUSTOM.to_key(MonthDay(2023, 1, 10))
        assert row.end_key == _CUSTOM.to_key(MonthDay(2023, 3, 10))
        assert _CUSTOM.is_valid(resolve_coord(await async_session.get(EventModel, event.id), "start"))

        before = await _snapshot(async_session)
        await service.load_and_apply(async_session)
        second = await service.sweep_dated_records(async_session)
        assert second.records == ()  # «повторный старт переносов не порождает»
        assert await _snapshot(async_session) == before

    async def test_sweep_is_idempotent_after_repairs_and_shifts(
        self, async_session, caplog
    ):
        # One row with corrupted coordinate text, one with a coordinate
        # invalid in the active custom calendar: the first sweep repairs and
        # shifts (both facts in the log), the second changes nothing.
        await _put_setting(async_session, CALENDAR_SETTINGS_KEY, encode_calendar(_CUSTOM))
        corrupt = EventModel(name="corrupt", start_date=date(2023, 2, 5), end_date=None)
        moved = EventModel(name="moved", start_date=date(2023, 2, 9), end_date=None)
        async_session.add_all([corrupt, moved])
        await async_session.commit()
        await async_session.execute(
            update(EventModel).where(EventModel.id == corrupt.id)
            .values(start_coord="44-03-05")
        )
        await async_session.execute(
            update(EventModel).where(EventModel.id == moved.id)
            .values(start_coord=encode_coord(MonthDay(2023, 2, 11)))
        )
        await async_session.commit()
        async_session.expunge_all()
        service = CalendarSettingsService()
        await service.load_and_apply(async_session)

        with caplog.at_level(logging.INFO):
            first = await service.sweep_dated_records(async_session)

        assert [(e.row_id, e.reason) for e in first.records] == [
            (moved.id, ShiftReason.DAY_OVERFLOW),
        ]
        assert any(
            "corrupt" not in record.getMessage()  # rows are addressed by table+id
            and "events" in record.getMessage() and str(corrupt.id) in record.getMessage()
            for record in caplog.records
        )  # the corruption repair was itself logged (resolver line)
        async_session.expunge_all()
        reloaded_corrupt = await async_session.get(EventModel, corrupt.id)
        assert reloaded_corrupt.start_coord is None  # repair survived the commit
        assert resolve_coord(reloaded_corrupt, "start") == MonthDay(2023, 2, 5)
        reloaded_moved = await async_session.get(EventModel, moved.id)
        assert resolve_coord(reloaded_moved, "start") == MonthDay(2023, 2, 10)

        # ── the second pass is the «Идемпотентный старт» scenario ──
        before = await _snapshot(async_session)
        second = await service.sweep_dated_records(async_session)
        assert second.records == ()
        assert await _snapshot(async_session) == before

    async def test_sweep_clears_and_logs_corrupted_text_at_open(
        self, async_session, caplog
    ):
        # Spec scenario «Битый текст колонки не ломает старт» on the service
        # level: the game opens, the row reads through its date columns, the
        # column is cleared and persisted, the log names table and id.
        event = EventModel(name="hand-edited", start_date=date(1200, 1, 1))
        async_session.add(event)
        await async_session.commit()
        await async_session.execute(
            update(EventModel).where(EventModel.id == event.id)
            .values(start_coord="не координата")
        )
        await async_session.commit()
        async_session.expunge_all()
        service = CalendarSettingsService()

        with caplog.at_level(logging.WARNING):
            report = await service.sweep_dated_records(async_session)

        assert report.shift_count == 0
        (row,) = (
            await async_session.execute(
                select(EventModel.start_coord, EventModel.__table__.c.start_date).where(
                    EventModel.id == event.id
                )
            )
        ).all()
        assert row.start_coord is None
        assert row.start_date == date(1200, 1, 1)
        assert any(
            "events" in record.getMessage() and str(event.id) in record.getMessage()
            for record in caplog.records
        )


# ── C3a 3.2: apply_to_records on the coordinate traversal (design D8) ─────

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
        both_bad_id, character_id = both_bad.id, character.id
        before = await _snapshot(async_session)
        service = CalendarSettingsService()

        report = await service.apply_to_records(async_session, _CUSTOM)  # dry_run default

        assert report.shift_count == 3
        assert [(e.table, e.row_id, e.field, e.reason) for e in report.records] == [
            ("events", both_bad_id, DateField.START, ShiftReason.DAY_OVERFLOW),
            ("events", both_bad_id, DateField.END, ShiftReason.MONTH_OUT_OF_RANGE),
            ("characters", character_id, DateField.START, ShiftReason.DAY_OVERFLOW),
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
        # Spec scenario «Применение совпадает с проверкой», and since C3a
        # the application goes to the coordinate columns: the applied moves
        # are exactly the previewed ones, every stored coordinate is valid
        # in ``calendar``, the keys are its own — and the legacy date
        # columns are left exactly as they were.
        valid, both_bad, character = await self._fixture_rows(async_session)
        valid_id, both_bad_id, character_id = valid.id, both_bad.id, character.id
        service = CalendarSettingsService()
        preview = await service.apply_to_records(
            async_session, _CUSTOM, dry_run=True
        )

        applied = await service.apply_to_records(
            async_session, _CUSTOM, dry_run=False
        )

        assert applied.records == preview.records
        rows = {
            r[0]: r
            for r in (
                await async_session.execute(
                    select(
                        EventModel.id,
                        EventModel.__table__.c.start_date,
                        EventModel.start_coord,
                        EventModel.start_key,
                        EventModel.__table__.c.end_date,
                        EventModel.end_coord,
                        EventModel.end_key,
                    )
                )
            ).all()
        }
        moved = rows[both_bad_id]
        assert moved.start_coord == encode_coord(MonthDay(2023, 1, 10))
        assert moved.end_coord == encode_coord(MonthDay(2023, 3, 10))
        # «прежние колонки дат SHALL оставить как есть» — the invalid dates
        # the shift moved away from are still sitting in the legacy columns.
        assert moved.start_date == date(2023, 1, 15)
        assert moved.end_date == date(2023, 6, 1)
        assert moved.start_key == _CUSTOM.to_key(MonthDay(2023, 1, 10))
        assert moved.end_key == _CUSTOM.to_key(MonthDay(2023, 3, 10))
        # A valid record migrates its storage too (the whole game switches
        # calendars), with the very same coordinate and a custom key.
        stayed = rows[valid_id]
        assert stayed.start_coord == encode_coord(MonthDay(2023, 2, 5))
        assert stayed.start_date == date(2023, 2, 5)
        assert stayed.start_key == _CUSTOM.to_key(MonthDay(2023, 2, 5))
        char_row = (
            await async_session.execute(
                select(
                    CharacterModel.__table__.c.start_date,
                    CharacterModel.start_coord,
                    CharacterModel.start_bc,
                    CharacterModel.start_key,
                ).where(CharacterModel.id == character_id)
            )
        ).one()
        assert tuple(char_row) == (
            date(2023, 2, 11),
            encode_coord(MonthDay(2023, 2, 10)),
            1,
            _CUSTOM.to_key(MonthDay(2023, 2, 10), True),
        )

        # Every coordinate as the app now reads it is valid in the calendar.
        async_session.expunge_all()
        for model in (EventModel, CharacterModel):
            for row in (await async_session.execute(select(model))).scalars():
                for field in ("start", "end"):
                    coord = resolve_coord(row, field)
                    if coord is not None:
                        assert _CUSTOM.is_valid(coord)

    async def test_error_midway_rolls_the_whole_application_back(
        self, async_session
    ):
        _valid, both_bad, character = await self._fixture_rows(async_session)
        character_id = character.id
        before = await _snapshot(async_session)
        # The traversal reaches the characters table only after both event
        # rows were updated — the boom strikes mid-traversal (spec «Ошибка
        # применения откатывает всё»).
        service = CalendarSettingsService()
        boom = _BoomCalendar(_CUSTOM, MonthDay(2023, 2, 10))

        with pytest.raises(RuntimeError):
            await service.apply_to_records(async_session, boom, dry_run=False)

        assert await _snapshot(async_session) == before
        # The rolled-back row is re-readable exactly as it was stored.
        async_session.expunge_all()
        char_row = await async_session.get(CharacterModel, character_id)
        assert char_row.start_coord is None


class TestStorageMigrationAcrossCalendar:
    """Spec scenario «Хранилища переезжают вместе с календарём» — both
    phases: applying a custom calendar fills the coordinate columns (the
    date columns stay as they were), returning to the preset moves the
    coordinates into the date columns — shifting what the preset cannot
    hold — and empties the coordinate columns."""

    async def test_custom_apply_then_preset_return_move_the_storage(
        self, async_session
    ):
        # Active-calendar state does not drive the migration — the applied
        # calendar parameter does (C4 activates after saving; the traversal
        # reads through the resolver either way).
        event = await _add_event(async_session, date(2023, 2, 15), date(2023, 3, 25))
        holdout = await _add_event(async_session, date(2023, 1, 1), None)
        # A coordinate the custom calendar holds but February never did —
        # hand-placed the way a long custom game would leave it.
        await async_session.execute(
            update(EventModel).where(EventModel.id == holdout.id)
            .values(start_coord=encode_coord(MonthDay(2023, 2, 30)), start_key=None)
        )
        await async_session.commit()
        async_session.expunge_all()
        service = CalendarSettingsService()

        # ── phase 1: apply the custom calendar ──
        applied = await service.apply_to_records(
            async_session, _CUSTOM_B, dry_run=False
        )
        assert [(e.field, e.reason, e.new) for e in applied.records] == [
            (DateField.END, ShiftReason.DAY_OVERFLOW, (MonthDay(2023, 3, 10), False)),
        ]
        async_session.expunge_all()
        first = await async_session.get(EventModel, event.id)
        assert first.start_coord == encode_coord(MonthDay(2023, 2, 15))
        assert first.end_coord == encode_coord(MonthDay(2023, 3, 10))
        # «прежние колонки дат не изменены применением» — including the day
        # the shifted end coordinate moved away from; the legacy columns are
        # inspected on their storage slot, because the public attributes
        # already read the coord truth (spec «Истина следует за
        # заполненностью»).
        assert first.start_date_raw == date(2023, 2, 15)
        assert first.end_date_raw == date(2023, 3, 25)
        assert first.start_date == MonthDay(2023, 2, 15)
        assert first.end_date == MonthDay(2023, 3, 10)
        assert first.start_key == _CUSTOM_B.to_key(MonthDay(2023, 2, 15))
        assert first.end_key == _CUSTOM_B.to_key(MonthDay(2023, 3, 10))
        holdout_row = await async_session.get(EventModel, holdout.id)
        assert resolve_coord(holdout_row, "start") == MonthDay(2023, 2, 30)
        assert holdout_row.start_key == _CUSTOM_B.to_key(MonthDay(2023, 2, 30))

        # ── phase 2: return to the «Стандартный» preset ──
        preview = await service.apply_to_records(
            async_session, StandardCalendar(), dry_run=True
        )
        # Only the hand coordinate is invalid for February — exactly one
        # move, and the preview still did not touch the storage.
        assert [(e.row_id, e.field, e.reason) for e in preview.records] == [
            (holdout.id, DateField.START, ShiftReason.DAY_OVERFLOW),
        ]
        assert preview.records[0].new == (MonthDay(2023, 2, 28), False)

        applied_back = await service.apply_to_records(
            async_session, StandardCalendar(), dry_run=False
        )
        assert applied_back.records == preview.records
        async_session.expunge_all()
        first = await async_session.get(EventModel, event.id)
        # The coordinates — shifted ones included — now live in the date
        # columns again, and the coordinate columns are empty.
        assert first.start_date == date(2023, 2, 15)
        assert first.end_date == date(2023, 3, 10)  # shifted back in phase 1
        assert first.start_coord is None and first.end_coord is None
        assert first.start_key == date(2023, 2, 15).toordinal()
        assert first.end_key == date(2023, 3, 10).toordinal()
        holdout_row = await async_session.get(EventModel, holdout.id)
        # The impossible February day was shifted to its last real day.
        assert holdout_row.start_date == date(2023, 2, 28)
        assert holdout_row.start_coord is None
        assert holdout_row.start_key == date(2023, 2, 28).toordinal()

        # A third pass over the preset storage stays byte-identical — the
        # migration is idempotent, the standard game is back to no-op.
        before = await _snapshot(async_session)
        third = await service.apply_to_records(
            async_session, StandardCalendar(), dry_run=False
        )
        assert third.records == ()
        assert await _snapshot(async_session) == before


# ── C4 4.2/4.5: wizard draft storage (design D6) ──────────────────────────

_DRAFT = CalendarDraft(
    spec=CalendarSpec(
        months=(MonthSpec("Черновершь", 12), MonthSpec("Разливань", 18)),
        week_names=("Буд", "Ведь", "Творец", "Грозник", "Светлай"),
        intercalary=(IntercalarySpec("Гром", 1),),
    ),
    stage=DRAFT_STAGE_MONTHS,
)


async def _seeded_draft(session) -> None:
    """Store the module draft through the service so a test sees exactly the
    row the wizard would have written."""
    await CalendarSettingsService().save_draft(session, _DRAFT)


def _draft_envelope(months: list, intercalary: list) -> str:
    """A draft envelope whose spec body the kernel itself rejects — built by
    hand because the encoder refuses to write what it cannot re-read."""
    return json.dumps(
        {
            "v": CALENDAR_DRAFT_VERSION,
            "spec": {
                "v": CALENDAR_STORAGE_VERSION,
                "kind": "custom",
                "months": months,
                "week_names": ["а", "б", "в", "г", "д", "е", "ё"],
                "intercalary": intercalary,
            },
            "stage": "months",
        },
        ensure_ascii=False,
    )


class TestCalendarDraftStorage:
    """Key ``game_calendar_draft`` round-trips through the service, a damaged
    value reads as «no draft» with a log line while the row stays (spec
    «Битой черновик — как его нет»), and neither reading nor opening a game
    ever lets the draft warm the active calendar."""

    async def test_missing_draft_reads_as_none(self, async_session):
        service = CalendarSettingsService()
        assert await service.load_draft(async_session) is None

    async def test_save_then_load_round_trips_and_overwrites(self, async_session):
        service = CalendarSettingsService()
        await service.save_draft(async_session, _DRAFT)
        assert await _setting(async_session, CALENDAR_DRAFT_KEY) == encode_draft(_DRAFT)

        newer = replace(_DRAFT, stage=DRAFT_STAGE_INTERCALARY)
        await service.save_draft(async_session, newer)

        assert await service.load_draft(async_session) == newer
        rows = (
            await async_session.execute(
                select(GameSettingsModel.value).where(
                    GameSettingsModel.key == CALENDAR_DRAFT_KEY
                )
            )
        ).scalars().all()
        assert list(rows) == [encode_draft(newer)]  # one row, not one per save

    async def test_broken_draft_json_reads_as_absent_with_a_log(
        self, async_session, caplog
    ):
        raw = '{этого нет, "stage": "week"}'
        await _put_setting(async_session, CALENDAR_DRAFT_KEY, raw)
        service = CalendarSettingsService()

        with caplog.at_level(logging.WARNING):
            assert await service.load_draft(async_session) is None

        # the fact is logged under the key…
        assert any(
            CALENDAR_DRAFT_KEY in record.message and "corrupt_json" in record.message
            for record in caplog.records
        )
        # …while the row itself is left for inspection, like the C2 rule
        assert await _setting(async_session, CALENDAR_DRAFT_KEY) == raw

    async def test_spec_the_kernel_rejects_is_the_same_absence(
        self, async_session, caplog
    ):
        # version and envelope are readable; the body names a host month the
        # spec does not have — «invalid draft = no draft», same branch
        raw = _draft_envelope(
            [{"name": "А", "length": 10}], [{"name": "В", "after_month": 5}]
        )
        await _put_setting(async_session, CALENDAR_DRAFT_KEY, raw)
        service = CalendarSettingsService()

        with caplog.at_level(logging.WARNING):
            assert await service.load_draft(async_session) is None

        assert any(
            "intercalary_unknown_month" in record.message
            for record in caplog.records
        )

    async def test_draft_never_warms_the_active_calendar(self, async_session):
        # spec scenario «Черновик не греет активный календарь»: the game opens
        # on the «Стандартный» preset, the draft keeps its bytes, no key of
        # the open (or of any record) was touched by it
        service = CalendarSettingsService()
        await service.save_draft(async_session, _DRAFT)

        outcome = await service.load_and_apply(async_session)

        assert isinstance(outcome.calendar, StandardCalendar)
        assert await _setting(async_session, CALENDAR_DRAFT_KEY) == encode_draft(_DRAFT)
        assert await _setting(async_session, CALENDAR_SETTINGS_KEY) is None

    async def test_discard_removes_the_row_and_tolerates_its_absence(
        self, async_session
    ):
        await _put_setting(async_session, CALENDAR_SETTINGS_KEY, "что-то")
        service = CalendarSettingsService()
        await service.save_draft(async_session, _DRAFT)

        await service.discard_draft(async_session)

        assert await _setting(async_session, CALENDAR_DRAFT_KEY) is None
        assert await _setting(async_session, CALENDAR_SETTINGS_KEY) == "что-то"
        await service.discard_draft(async_session)  # second pass: silent no-op

    async def test_load_wizard_seen_exposes_the_raw_flag_text(self, async_session):
        service = CalendarSettingsService()
        # a game without the key is an old game (absence, not "0")
        assert await service.load_wizard_seen(async_session) is None
        await _put_setting(
            async_session, CALENDAR_WIZARD_SEEN_KEY, CALENDAR_WIZARD_SEEN_NO
        )
        assert await service.load_wizard_seen(async_session) == CALENDAR_WIZARD_SEEN_NO


# ── C4 4.3: promote_draft — one atomic transaction (design D9) ────────────

class TestPromoteDraft:
    """Spec «Поднятие черновик чистит черновик» / «Перезапись вместо
    ремонта» + design D9: the C2 record transfer, the settings overwrite, the
    draft deletion and the optional seen-flag commit as one unit; the applied
    calendar becomes active only after that commit."""

    async def test_promotion_writes_the_key_and_frees_the_draft(
        self, async_session
    ):
        # settings as the C2 open saw them: damaged main key, a live draft
        await _put_setting(async_session, CALENDAR_SETTINGS_KEY, "{ повреждённая строка")
        await _seeded_draft(async_session)
        service = CalendarSettingsService()

        report = await service.promote_draft(async_session, _CUSTOM)

        assert report.records == ()  # no dated rows here — apply part trivial
        # main key overwritten with the readable encoding of the same spec
        assert await _setting(
            async_session, CALENDAR_SETTINGS_KEY
        ) == encode_calendar(_CUSTOM)
        # the draft is gone — one truth remains
        assert await _setting(async_session, CALENDAR_DRAFT_KEY) is None
        # activation only after the commit succeeded (D9)
        assert isinstance(current_calendar(), CustomCalendar)
        assert current_calendar().spec == _SPEC

    async def test_promotion_applies_records_and_matches_the_preview(
        self, async_session
    ):
        event = await _add_event(async_session, date(2023, 1, 15), date(2023, 6, 1))
        event_id = event.id
        service = CalendarSettingsService()
        await service.save_draft(async_session, _DRAFT)
        preview = await service.apply_to_records(async_session, _CUSTOM, dry_run=True)
        assert preview.shift_count == 2

        applied = await service.promote_draft(async_session, _CUSTOM)

        assert applied.records == preview.records  # «Применение совпадает с проверкой»
        # the promotion expired the identity map — re-read from the base
        row = await async_session.get(EventModel, event_id)
        assert row.start_coord == encode_coord(MonthDay(2023, 1, 10))
        assert row.end_coord == encode_coord(MonthDay(2023, 3, 10))
        assert row.start_key == _CUSTOM.to_key(MonthDay(2023, 1, 10))
        assert row.end_key == _CUSTOM.to_key(MonthDay(2023, 3, 10))
        assert await _setting(
            async_session, CALENDAR_SETTINGS_KEY
        ) == encode_calendar(_CUSTOM)
        assert await _setting(async_session, CALENDAR_DRAFT_KEY) is None

    async def test_flag_is_set_only_when_asked(self, async_session):
        service = CalendarSettingsService()

        await service.promote_draft(async_session, _CUSTOM)
        # without the mark the first-entry flow keeps its own decision pending
        assert await service.load_wizard_seen(async_session) is None

        await service.promote_draft(
            async_session, _CUSTOM_B, mark_wizard_seen=True
        )
        assert await service.load_wizard_seen(async_session) == "1"

    async def test_promotion_of_the_preset_needs_no_draft_or_records(
        self, async_session
    ):
        # design D8 branch «крест первого входа»: promote the preset over a
        # seeded standard game without any draft — trivial transaction
        service = CalendarSettingsService()
        await _put_setting(
            async_session, CALENDAR_WIZARD_SEEN_KEY, CALENDAR_WIZARD_SEEN_NO
        )

        report = await service.promote_draft(
            async_session, StandardCalendar(), mark_wizard_seen=True
        )

        assert report.records == ()
        assert await _setting(
            async_session, CALENDAR_SETTINGS_KEY
        ) == encode_calendar(StandardCalendar())
        assert await service.load_wizard_seen(async_session) == "1"
        assert isinstance(current_calendar(), StandardCalendar)

    async def test_preview_discards_the_repair_and_apply_persists_it(
        self, async_session
    ):
        # The resolver repairs a corrupted coordinate text while reading; the
        # preview must discard that write, the application must keep it (spec
        # «Проверка ничего не меняет»).  The corrupted row goes into ratings —
        # the fixed traversal reads tables in order, and only the table read
        # last still holds the repair un-autoflushed at the dirty-check.
        rating = RatingModel(start_date=date(1200, 1, 1), level=1)
        async_session.add(rating)
        await async_session.commit()
        rating_id = rating.id
        await async_session.execute(
            update(RatingModel).where(RatingModel.id == rating_id)
            .values(start_coord="не координата")
        )
        await async_session.commit()
        async_session.expunge_all()
        service = CalendarSettingsService()
        preset = StandardCalendar()

        preview = await service.apply_to_records(async_session, preset, dry_run=True)

        # the unreadable text resolves to nothing ⇒ nothing to list, and the
        # in-memory clearing went back with the rollback
        assert preview.records == ()
        async_session.expunge_all()
        assert (await async_session.get(RatingModel, rating_id)).start_coord == \
            "не координата"

        applied = await service.apply_to_records(async_session, preset, dry_run=False)

        # the same reading pass, now committing, keeps the cure and re-keys
        # the row straight from its readable date column
        assert applied.records == ()
        async_session.expunge_all()
        row = await async_session.get(RatingModel, rating_id)
        assert row.start_coord is None
        assert row.start_key == date(1200, 1, 1).toordinal()

    async def test_error_midway_rolls_back_records_settings_and_draft(
        self, async_session
    ):
        event = await _add_event(async_session, date(2023, 1, 15), None)
        await _put_setting(async_session, CALENDAR_SETTINGS_KEY, '{"v": 1, "kind": "standard"}')
        await _put_setting(
            async_session, CALENDAR_WIZARD_SEEN_KEY, CALENDAR_WIZARD_SEEN_NO
        )
        service = CalendarSettingsService()
        await service.save_draft(async_session, _DRAFT)
        snapshot_before = await _snapshot(async_session)
        draft_before = await _setting(async_session, CALENDAR_DRAFT_KEY)
        # the boom strikes at the very custom key of the shifted start, i.e.
        # after some rows were already updated — mid-transaction
        boom = _BoomCalendar(_CUSTOM, MonthDay(2023, 1, 10))

        with pytest.raises(RuntimeError):
            await service.promote_draft(
                async_session, boom, mark_wizard_seen=True
            )

        # nothing survived: not the shifted rows, not the settings, not the
        # draft deletion, not the flag (spec «запись нового ключа … SHALL
        # пережить ту же атомарность, что и перенос записей»)
        assert await _snapshot(async_session) == snapshot_before
        assert await _setting(
            async_session, CALENDAR_SETTINGS_KEY
        ) == '{"v": 1, "kind": "standard"}'
        assert await _setting(async_session, CALENDAR_DRAFT_KEY) == draft_before
        assert await service.load_wizard_seen(async_session) == CALENDAR_WIZARD_SEEN_NO
        assert not isinstance(current_calendar(), CustomCalendar)
