"""Tests for the coordinate storage resolver (C3a task 2.3, design D3).

Specs «Coordinates in dated table records» («Истина следует за
заполненностью», «custom-запись не трогает наследие») and «Corrupted
coordinate column» on plain ORM rows and saved rows: reading prefers the
coordinate column, corrupted text is cleared with a table+id log line and
the record reads through its date columns; the writing route sends values to
the coordinate slot (filled row or active custom calendar) or to the legacy
date columns (standard preset) — and the derived keys are re-synced from
the resolved coordinate truth.
"""
from __future__ import annotations

import logging
from datetime import date

import pytest
from sqlalchemy import text

from app.domain.date_era import era_key
from app.domain.game_calendar import (
    CalendarSpec,
    CustomCalendar,
    DateField,
    IntercalaryDay,
    IntercalarySpec,
    InvalidGameDateError,
    MonthDay,
    MonthSpec,
    encode_coord,
    reset_current_calendar,
    set_current_calendar,
)
from app.infrastructure.db.models import (
    EventModel,
    RatingModel,
    assign_coord,
    resolve_coord,
)

# Three months: 10 + 10 + 30 days with a masked intercalary day after the
# first month — the fixture calendar the writing route distinguishes from
# the standard preset (C3a design D3).
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


@pytest.fixture
def custom_calendar():
    """The accessor is a process global — swap it, hand it back pristine."""
    reset_current_calendar()
    set_current_calendar(CUSTOM)
    yield CUSTOM
    reset_current_calendar()


def _row(**kwargs) -> EventModel:
    """An unsaved ORM row is enough for the resolver's column arithmetic."""
    return EventModel(name="probe", **kwargs)


# ── reading: which slot is the truth ──────────────────────────────────────


class TestResolveCoordSources:
    """Spec «Истина следует за заполненностью»: coord filled ⇒ it, empty ⇒
    the date columns read as the MonthDay of their numbers."""

    def test_filled_coord_column_is_the_truth(self):
        row = _row(
            start_date=date(1200, 1, 1),
            start_coord="I:44:0",
            end_date=date(1200, 12, 31),
            end_coord="M:44:2:7",
        )
        assert resolve_coord(row, DateField.START) == IntercalaryDay(44, 0)
        assert resolve_coord(row, "end") == MonthDay(44, 2, 7)

    def test_empty_coord_reads_the_date_columns_as_month_day(self):
        row = _row(start_date=date(1200, 1, 1), end_date=date(1200, 12, 31))
        assert resolve_coord(row, "start") == MonthDay(1200, 1, 1)
        assert resolve_coord(row, DateField.END) == MonthDay(1200, 12, 31)

    def test_empty_slot_means_open_ended_not_absent_coord(self):
        # «Пустая координатная колонка = дата живёт в прежних колонках»:
        # end_date пустой ⇒ None, а не «даты нет в записи».
        row = _row(start_date=date(1200, 1, 1), end_date=None)
        assert resolve_coord(row, "end") is None

    def test_blank_coord_text_reads_date_columns(self):
        row = _row(start_date=date(1200, 1, 1), start_coord="")
        assert resolve_coord(row, "start") == MonthDay(1200, 1, 1)

    def test_unknown_slot_is_a_programming_error(self):
        with pytest.raises(ValueError, match="date slot"):
            resolve_coord(_row(start_date=date(1200, 1, 1)), "middle")


# ── corrupted coordinate text (spec «Повреждённая координатная колонка») ──


class TestCorruptedCoordinateText:
    """Hand-edited unreadable text: the row reads through its date columns,
    the broken column is cleared (and persisted), the table+id go to the
    log, and the game opening does not crash."""

    async def test_broken_text_falls_back_clears_column_and_logs(
        self, async_session, caplog
    ):
        row = EventModel(
            name="hand-edited", start_date=date(1200, 1, 1)
        )
        async_session.add(row)
        await async_session.commit()
        # The manual DB edit in its literal shape: an UPDATE straight to the
        # file, in the row the app wrote earlier (no ORM, no app path).
        await async_session.execute(
            text("UPDATE events SET start_coord = '44-03-05' WHERE id = :i"),
            {"i": row.id},
        )
        async_session.expunge_all()
        row = await async_session.get(EventModel, row.id)

        with caplog.at_level(
            logging.WARNING, logger="app.infrastructure.db.models"
        ):
            truth = resolve_coord(row, "start")

        assert truth == MonthDay(1200, 1, 1)  # read through the date column
        assert row.start_coord is None  # column cleared at the read
        assert len(caplog.records) == 1
        message = caplog.records[0].getMessage()
        assert "events" in message and str(row.id) in message  # table + id
        assert "unknown_kind" in message  # machine-readable codec reason

        # The repair survives the flush: the next load sees an empty column.
        await async_session.commit()
        async_session.expunge_all()
        reloaded = await async_session.get(EventModel, row.id)
        assert reloaded.start_coord is None
        assert reloaded.start_date == date(1200, 1, 1)

    async def test_non_numeric_coord_text_is_repaired_the_same_way(
        self, async_session, caplog
    ):
        row = RatingModel(start_date=date(1300, 1, 1), level=3)
        async_session.add(row)
        await async_session.commit()
        await async_session.execute(
            text("UPDATE ratings SET start_coord = 'M:x:1:1' WHERE id = :i"),
            {"i": row.id},
        )
        async_session.expunge_all()
        row = await async_session.get(RatingModel, row.id)

        with caplog.at_level(
            logging.WARNING, logger="app.infrastructure.db.models"
        ):
            truth = resolve_coord(row, DateField.START)

        assert truth == MonthDay(1300, 1, 1)
        assert row.start_coord is None
        assert "ratings" in caplog.records[0].getMessage()
        assert str(row.id) in caplog.records[0].getMessage()
        assert "non_numeric_field" in caplog.records[0].getMessage()


# ── writing: the routing branch lives in one place (design D3) ────────────


class TestAssignCoordRouting:
    """Сценарии «Стандартная игра не видит нового хранилища», «custom-запись
    не трогает наследие» и правило «coord заполнена → coord»."""

    def test_standard_preset_writes_date_columns_coord_stays_empty(self):
        row = _row()
        assign_coord(row, "start", MonthDay(1200, 5, 1))
        assert row.start_date == date(1200, 5, 1)
        assert row.start_coord is None

    def test_standard_preset_accepts_plain_date_input(self):
        # D4: date остаётся частным случаем координаты — прежний путь.
        row = _row()
        assign_coord(row, DateField.END, date(1200, 12, 31))
        assert row.end_date == date(1200, 12, 31)
        assert row.end_coord is None

    def test_custom_calendar_routes_to_coord_and_never_touches_date(
        self, custom_calendar
    ):
        # Scenario «custom-запись не трогает наследие»: date-колонка — мёртвое
        # наследие эпохи до переключения, значение в неё не уходит никогда.
        # Наследие проверяется на сырой колонке: публичный атрибут уже
        # отдаёт координату-истину (spec «Истина следует за заполненностью»).
        row = EventModel(name="probe", start_date=date(1200, 1, 1))
        assign_coord(row, "start", MonthDay(44, 2, 7))
        assert row.start_coord == "M:44:2:7"
        assert row.start_date_raw == date(1200, 1, 1)  # наследие не тронуто
        assert row.start_date == MonthDay(44, 2, 7)  # истина — в coord

    def test_custom_calendar_routes_date_input_to_coord_as_month_day(
        self, custom_calendar
    ):
        row = _row()
        assign_coord(row, "end", date(44, 3, 5))
        assert row.end_coord == "M:44:3:5"
        assert row.end_date_raw is None  # сырой слот наследия остался пустым

    def test_filled_coord_slot_wins_regardless_of_active_calendar(self):
        # Правило «coord заполнена ⇒ пишет в неё» действует и при пресете:
        # иначе истина распалась бы между двумя хранилищами.
        row = _row(start_date=date(1200, 1, 1), start_coord="M:44:1:5")
        assign_coord(row, "start", MonthDay(44, 1, 9))
        assert row.start_coord == "M:44:1:9"
        assert row.start_date_raw == date(1200, 1, 1)

    def test_clearing_a_filled_coord_leaves_the_legacy_value(self):
        row = _row(start_date=date(1200, 1, 1), start_coord="M:44:1:5")
        assign_coord(row, "start", None)
        assert row.start_coord is None
        assert row.start_date == date(1200, 1, 1)

    def test_custom_calendar_none_clears_coord_not_legacy_date(
        self, custom_calendar
    ):
        row = _row(end_date=date(1200, 12, 31), end_coord="M:44:2:7")
        assign_coord(row, "end", None)
        assert row.end_coord is None
        assert row.end_date == date(1200, 12, 31)

    def test_standard_none_clears_the_date_column(self):
        row = _row(end_date=date(1200, 12, 31))
        assign_coord(row, DateField.END, None)
        assert row.end_date is None

    def test_intercalary_coord_refused_for_the_standard_date_slot(self):
        # Григорианская колонка физически не вмещает вставной день —
        # отличимый отказ ядра, без тихой нормализации (D6).
        row = _row()
        with pytest.raises(InvalidGameDateError):
            assign_coord(row, "start", IntercalaryDay(44, 0))

    def test_non_gregorian_month_day_refused_for_the_date_slot(self):
        row = _row()
        with pytest.raises(InvalidGameDateError):
            assign_coord(row, "start", MonthDay(2026, 4, 31))

    def test_attribute_writes_route_by_value_type(self, custom_calendar):
        # The public ``start_date``/``end_date`` properties are the routed
        # entry themselves (design D3): assigning a GameCoord — from anywhere
        # above the repositories — physically lands where ``assign_coord``
        # sends it, while a plain ``date`` keeps the legacy direct write.
        row = EventModel(name="probe", start_date=date(1200, 1, 1))
        row.start_date = MonthDay(44, 2, 7)
        row.end_date = IntercalaryDay(44, 0)
        assert row.start_coord == "M:44:2:7"
        assert row.start_date_raw == date(1200, 1, 1)  # наследие не тронуто
        assert row.end_coord == "I:44:0"
        assert row.end_date == IntercalaryDay(44, 0)


# ── the key hook keys from the resolved coordinate truth ──────────────────


class TestEraKeyHookFollowsCoordTruth:
    """Сценарий «Истина следует за заполненностью» на хуке: start_key/
    end_key пересчитываются от resolve_coord, а не от date-колонки."""

    async def test_insert_key_comes_from_coordinate_not_legacy_date(
        self, async_session, custom_calendar
    ):
        row = EventModel(
            name="masked",
            start_date=date(1200, 1, 1),  # dead legacy value (placeholder)
            start_coord=encode_coord(IntercalaryDay(44, 0)),
            start_bc=1,
        )
        async_session.add(row)
        await async_session.commit()

        assert row.start_key == era_key(IntercalaryDay(44, 0), True)
        assert row.start_key != era_key(date(1200, 1, 1), True)

    async def test_update_resyncs_key_from_coord_truth(
        self, async_session, custom_calendar
    ):
        row = EventModel(name="later switch", start_date=date(1200, 1, 1))
        async_session.add(row)
        await async_session.commit()
        legacy_key = row.start_key
        assert legacy_key == era_key(date(1200, 1, 1), False)

        row.start_coord = encode_coord(MonthDay(44, 2, 7))
        await async_session.commit()

        async_session.expunge_all()
        reloaded = await async_session.get(EventModel, row.id)
        assert reloaded.start_key == era_key(MonthDay(44, 2, 7), False)
        # наследие цело на сырой колонке, а читаемая истина — координата:
        assert reloaded.start_date_raw == date(1200, 1, 1)
        assert reloaded.start_date == MonthDay(44, 2, 7)

    async def test_clearing_open_end_nulls_the_key(self, async_session):
        row = EventModel(
            name="closing",
            start_date=date(1200, 1, 1),
            end_date=date(1200, 12, 31),
        )
        async_session.add(row)
        await async_session.commit()
        assert row.end_key is not None

        row.end_date = None
        await async_session.commit()
        reloaded = await async_session.get(EventModel, row.id)
        assert reloaded.end_key is None
