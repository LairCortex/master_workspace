"""Tests for GameSettingsRepository, LlmSettingsRepository (task 6.2) and the
typed «now» storage wrapper (NRI-0021 task 2.1).

The key/value trio is now the single place the ``game_settings`` table is
touched; these unit tests pin its get/upsert/delete semantics, the typed
LLM facade over it, and the current-date wrapper over both (roundtrip,
corruption, out-of-calendar rejection, per-game isolation).
"""
from __future__ import annotations

import json
import logging

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.game_calendar import (
    CalendarSpec,
    CustomCalendar,
    IntercalaryDay,
    IntercalarySpec,
    MonthDay,
    MonthSpec,
    reset_current_calendar,
    set_current_calendar,
)
from app.infrastructure.db.database import create_engine
from app.infrastructure.db.models import GameSettingsModel
from app.infrastructure.repositories.game_settings_repository import (
    CURRENT_DATE_KEY,
    DND_DATASETS_KEY,
    DND_GRIMOIRES_KEY,
    DND_MODULE_KEY,
    DND_SEARCH_SHOW_REFERENCE_KEY,
    PREVIEW_PINS_KEY,
    CurrentDateRepository,
    CurrentDateValue,
    DndDatasetsRepository,
    DndGrimoiresRepository,
    DndModuleFlag,
    DndSearchShowReferenceRepository,
    decode_dnd_search_show_reference,
    GameSettingsRepository,
    PreviewPinsRepository,
    decode_dnd_module_flag,
)
from app.infrastructure.repositories.llm_settings_repository import (
    FIELD_PROMPTS_KEY,
    WORLD_PROMPT_KEY,
    LlmSettingsRepository,
)


class TestGameSettingsRepository:
    async def test_get_absent_key_returns_none(self, async_session: AsyncSession):
        assert await GameSettingsRepository(async_session).get("missing") is None

    async def test_upsert_inserts_then_updates_in_place(
        self, async_session: AsyncSession
    ):
        settings = GameSettingsRepository(async_session)
        await settings.upsert("k", "one")
        assert await settings.get("k") == "one"
        await settings.upsert("k", "two")
        assert await settings.get("k") == "two"
        rows = (
            await async_session.execute(
                select(GameSettingsModel).where(GameSettingsModel.key == "k")
            )
        ).scalars().all()
        assert len(rows) == 1  # updated in place, not a second row
        assert rows[0].value == "two"

    async def test_delete_present_and_absent_are_no_crash(
        self, async_session: AsyncSession
    ):
        settings = GameSettingsRepository(async_session)
        await settings.upsert("k", "v")
        await settings.delete("k")
        assert await settings.get("k") is None
        await settings.delete("k")  # absent key: silent no-op


class TestLlmSettingsRepository:
    async def test_missing_keys_read_as_none(self, async_session: AsyncSession):
        repo = LlmSettingsRepository(async_session)
        assert await repo.load_world_prompt() is None
        assert await repo.load_field_prompts() is None

    async def test_roundtrip_through_the_shared_settings_trio(
        self, async_session: AsyncSession
    ):
        repo = LlmSettingsRepository(async_session)
        await repo.save_world_prompt('{"text": "world"}')
        await repo.save_field_prompts('{"a.b": {}}')
        assert await repo.load_world_prompt() == '{"text": "world"}'
        assert await repo.load_field_prompts() == '{"a.b": {}}'
        # the keys landed in the shared table, on the historical key names
        keys = {
            row.key
            for row in (
                await async_session.execute(select(GameSettingsModel))
            ).scalars().all()
        }
        assert keys == {WORLD_PROMPT_KEY, FIELD_PROMPTS_KEY}

    async def test_save_overwrites_previous_text(self, async_session: AsyncSession):
        repo = LlmSettingsRepository(async_session)
        await repo.save_world_prompt("first")
        await repo.save_world_prompt("second")
        assert await repo.load_world_prompt() == "second"


# ── NRI-0021 task 2.1: typed «now» storage over the same trio ───────────────


class _Boom(Exception):
    """Marker error for the rollback paths."""


def _custom_calendar() -> CustomCalendar:
    """A two-month calendar with one intercalary rule — enough to host an
    ``IntercalaryDay`` the standard preset refuses."""
    return CustomCalendar(
        CalendarSpec(
            months=(MonthSpec("А", 10), MonthSpec("Б", 10)),
            week_names=("пн", "вт", "ср", "чт", "пт", "сб", "вс"),
            intercalary=(IntercalarySpec("В", 1),),
        )
    )


def _ten_hour_calendar() -> CustomCalendar:
    """The same two-month world narrowed to 10-hour days (NRI-0023 task 2.3):
    every hour the 24-hour preset hosted from 10 up is out of its day."""
    return CustomCalendar(
        CalendarSpec(
            months=(MonthSpec("А", 10), MonthSpec("Б", 10)),
            week_names=("пн", "вт", "ср", "чт", "пт", "сб", "вс"),
            intercalary=(IntercalarySpec("В", 1),),
            day_hours=10,
        )
    )


class TestCurrentDateRepository:
    @pytest.fixture(autouse=True)
    def _fresh_active_calendar(self):
        """The wrapper consults the process-global active calendar for the
        range check — no test inherits another's calendar."""
        reset_current_calendar()
        yield
        reset_current_calendar()

    async def _stored_text(self, session: AsyncSession) -> str | None:
        return (
            await session.execute(
                select(GameSettingsModel.value).where(
                    GameSettingsModel.key == CURRENT_DATE_KEY
                )
            )
        ).scalars().first()

    async def test_absent_key_reads_none_silently(self, async_session, caplog):
        with caplog.at_level(logging.WARNING):
            assert await CurrentDateRepository(async_session).load() is None
        assert not caplog.records  # absence is the normal state, not corruption

    async def test_roundtrip_month_day_with_era(self, async_session):
        repo = CurrentDateRepository(async_session)
        await repo.save(MonthDay(2088, 5, 1), is_bc=True)
        # design Д1 wire format pinned verbatim: coord codec text + 0|1 era
        assert json.loads(await self._stored_text(async_session)) == {
            "coord": "M:2088:5:1",
            "bc": 1,
        }
        assert await repo.load() == CurrentDateValue(MonthDay(2088, 5, 1), True)
        await repo.save(MonthDay(2088, 5, 1), is_bc=False)
        assert await repo.load() == CurrentDateValue(MonthDay(2088, 5, 1), False)

    async def test_save_overwrites_in_one_row(self, async_session):
        repo = CurrentDateRepository(async_session)
        await repo.save(MonthDay(2088, 5, 1), False)
        await repo.save(MonthDay(2090, 1, 2), True)
        rows = (
            await async_session.execute(
                select(GameSettingsModel).where(
                    GameSettingsModel.key == CURRENT_DATE_KEY
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert await repo.load() == CurrentDateValue(MonthDay(2090, 1, 2), True)

    async def test_intercalary_coord_roundtrips_under_its_calendar(self, async_session):
        set_current_calendar(_custom_calendar())
        repo = CurrentDateRepository(async_session)
        await repo.save(IntercalaryDay(44, 0), is_bc=True)
        assert await repo.load() == CurrentDateValue(IntercalaryDay(44, 0), True)

    # ── NRI-0023 task 2.3: необязательный час «сейчас» (design Д5) ──────────

    async def test_hour_writes_the_h_key_and_round_trips(self, async_session):
        repo = CurrentDateRepository(async_session)
        await repo.save(MonthDay(2088, 5, 1), is_bc=True, hour=14)
        # the extended wire format: the v1 body with one trailing "h" key
        assert json.loads(await self._stored_text(async_session)) == {
            "coord": "M:2088:5:1",
            "bc": 1,
            "h": 14,
        }
        assert await repo.load() == CurrentDateValue(MonthDay(2088, 5, 1), True, 14)

    async def test_hour_zero_is_a_written_hour_not_absence(self, async_session):
        # «0» is a real hour of the day — the codec must not confuse it with
        # «не выставлен» on either side of the wire.
        repo = CurrentDateRepository(async_session)
        await repo.save(MonthDay(2088, 5, 1), False, hour=0)
        assert json.loads(await self._stored_text(async_session)) == {
            "coord": "M:2088:5:1",
            "bc": 0,
            "h": 0,
        }
        assert await repo.load() == CurrentDateValue(MonthDay(2088, 5, 1), False, 0)

    async def test_no_hour_writes_the_pre_0023_body_byte_identical(
        self, async_session
    ):
        # v1-совместимость кодека: date-only edits keep writing exactly the
        # old two-key JSON — an older app version still reads every write.
        await CurrentDateRepository(async_session).save(MonthDay(2088, 5, 1), False)
        assert await self._stored_text(async_session) == (
            '{"coord": "M:2088:5:1", "bc": 0}'
        )

    async def test_narrow_day_clears_the_stored_hour_silently(
        self, async_session, caplog
    ):
        # Spec «Сужение суток чистит недоступный час»: hour 23 survived under
        # the 24-hour preset, a 10-hour calendar no longer hosts it — the
        # date keeps serving, the hour reads as unset, nothing is written
        # back and no warning is raised (design Д5: «чистит подпись без
        # записи»).
        repo = CurrentDateRepository(async_session)
        await repo.save(MonthDay(2088, 1, 5), is_bc=True, hour=23)
        set_current_calendar(_ten_hour_calendar())
        try:
            with caplog.at_level(logging.WARNING):
                value = await repo.load()
        finally:
            reset_current_calendar()
        assert value == CurrentDateValue(MonthDay(2088, 1, 5), True, None)
        assert not caplog.records
        # the row stays byte-identical — the clearing is a reading rule only
        assert json.loads(await self._stored_text(async_session))["h"] == 23

    async def test_negative_stored_hour_reads_as_unset(self, async_session):
        # «вне 0 … day_hours−1» covers the under-edge too: a hand-written
        # minus is not an hour of any day.
        async_session.add(
            GameSettingsModel(
                key=CURRENT_DATE_KEY,
                value='{"coord": "M:2088:5:1", "bc": 0, "h": -1}',
            )
        )
        await async_session.commit()
        assert await CurrentDateRepository(async_session).load() == (
            CurrentDateValue(MonthDay(2088, 5, 1), False, None)
        )

    @pytest.mark.parametrize(
        "raw",
        [
            "not json at all",          # unparseable JSON
            "[1, 2, 3]",                # JSON, but not an object
            '{"coord": "M:2088:5:1"}',  # era flag missing
            '{"coord": "M:2088:5:1", "bc": 2}',     # era flag outside 0|1
            '{"coord": "M:2088:5:1", "bc": true}',  # bool is never the flag
            '{"coord": "M:2088:5:1", "bc": "0"}',   # text is not the flag
            '{"coord": "Q:1:2", "bc": 0}',          # codec rejects the kind
            '{"coord": 7, "bc": 0}',                # coord is not text
            '{"coord": "M:2088:5:1", "bc": 0, "h": "14"}',   # hour is not an int
            '{"coord": "M:2088:5:1", "bc": 0, "h": true}',   # bool is never the hour
            '{"coord": "M:2088:5:1", "bc": 0, "h": 14.5}',   # neither is a float
        ],
    )
    async def test_corrupted_value_reads_none_with_a_warning(
        self, async_session, caplog, raw
    ):
        async_session.add(GameSettingsModel(key=CURRENT_DATE_KEY, value=raw))
        await async_session.commit()
        with caplog.at_level(logging.WARNING):
            assert await CurrentDateRepository(async_session).load() is None
        warnings = [
            r for r in caplog.records if CURRENT_DATE_KEY in r.getMessage()
        ]
        assert len(warnings) == 1
        assert warnings[0].levelname == "WARNING"
        # the damaged row is neither rewritten nor deleted (design Д1)
        assert await self._stored_text(async_session) == raw

    async def test_out_of_calendar_coord_reads_none_with_a_warning(
        self, async_session, caplog
    ):
        # Standard preset is active (fresh fixture): 30 February cannot exist.
        repo = CurrentDateRepository(async_session)
        await repo.save(MonthDay(2020, 2, 30), False)
        with caplog.at_level(logging.WARNING):
            assert await repo.load() is None
        assert any(
            "does not exist in the active calendar" in r.getMessage()
            for r in caplog.records
        )

    async def test_repository_never_commits_rollback_drops_the_write(
        self, async_session, uow
    ):
        # «репозиторий сам не коммитит»: the wrapper writes through the
        # uncommitted trio, so an aborted transaction leaves no key behind.
        async def _write_then_fail() -> None:
            async with uow.transaction():
                await CurrentDateRepository(uow.session).save(MonthDay(2088, 5, 1), False)
                raise _Boom

        with pytest.raises(_Boom):
            await _write_then_fail()
        assert await CurrentDateRepository(async_session).load() is None
        assert await self._stored_text(async_session) is None

    async def test_values_are_isolated_between_game_dbs(self):
        # One SQLite file per game (AGENTS.md): what game A saved, game B
        # never sees — two independent in-memory databases.
        from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession
        from sqlalchemy.ext.asyncio import async_sessionmaker

        engines = []
        makers = []
        for _ in range(2):
            engine = create_engine("sqlite+aiosqlite:///:memory:")
            async with engine.begin() as conn:
                await conn.run_sync(GameSettingsModel.metadata.create_all)
            engines.append(engine)
            makers.append(async_sessionmaker(engine, class_=_AsyncSession))
        try:
            async with makers[0]() as session_a:
                await CurrentDateRepository(session_a).save(
                    MonthDay(2088, 5, 1), is_bc=True
                )
                await session_a.commit()
            async with makers[1]() as session_b:
                assert await CurrentDateRepository(session_b).load() is None
            async with makers[0]() as session_a:
                assert await CurrentDateRepository(session_a).load() == (
                    CurrentDateValue(MonthDay(2088, 5, 1), True)
                )
        finally:
            for engine in engines:
                await engine.dispose()


# ── NRI-0025 task 1.1: typed preview-pins storage over the same trio ────────


class TestPreviewPinsRepository:
    async def _stored_text(self, session: AsyncSession) -> str | None:
        return (
            await session.execute(
                select(GameSettingsModel.value).where(
                    GameSettingsModel.key == PREVIEW_PINS_KEY
                )
            )
        ).scalars().first()

    async def test_absent_key_reads_empty_list_silently(
        self, async_session, caplog
    ):
        with caplog.at_level(logging.WARNING):
            assert await PreviewPinsRepository(async_session).load() == []
        assert not caplog.records  # absence is the normal state, not corruption

    async def test_roundtrip_preserves_order_and_duplicates(self, async_session):
        pins = [("character", 3), ("item", 1), ("character", 3)]
        repo = PreviewPinsRepository(async_session)
        await repo.save(pins)
        # design Д3 wire format pinned verbatim: the array order IS the pin
        # order, the «t»/«i» keys carry the pair
        assert await self._stored_text(async_session) == (
            '[{"t": "character", "i": 3}, {"t": "item", "i": 1}, '
            '{"t": "character", "i": 3}]'
        )
        assert await repo.load() == pins

    async def test_empty_list_writes_empty_array_and_reads_empty(
        self, async_session
    ):
        # «last pin unpinned» stays an explicit clean write, not a key delete
        repo = PreviewPinsRepository(async_session)
        await repo.save([])
        assert await self._stored_text(async_session) == "[]"
        assert await repo.load() == []

    async def test_save_overwrites_in_one_row(self, async_session):
        repo = PreviewPinsRepository(async_session)
        await repo.save([("character", 1)])
        await repo.save([("item", 2), ("location", 3)])
        rows = (
            await async_session.execute(
                select(GameSettingsModel).where(
                    GameSettingsModel.key == PREVIEW_PINS_KEY
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert await repo.load() == [("item", 2), ("location", 3)]

    async def test_string_ids_round_trip(self, async_session):
        # add-dnd-game-face task 6.2 (spec preview-pins delta): the external
        # half of the codec — a record id is a STRING («srd51/cleric»), the
        # kernel half stays numeric; save→load carries both shapes whole.
        repo = PreviewPinsRepository(async_session)
        await repo.save([("dd_feat", "srd51/lucky"), ("dd_spell", "srd51/fire-ball")])
        assert await self._stored_text(async_session) == (
            '[{"t": "dd_feat", "i": "srd51/lucky"},'
            ' {"t": "dd_spell", "i": "srd51/fire-ball"}]'
        )
        assert await repo.load() == [
            ("dd_feat", "srd51/lucky"),
            ("dd_spell", "srd51/fire-ball"),
        ]

    async def test_mixed_kernel_and_external_pairs_round_trip(self, async_session):
        # One list, both id species — the order of the pins is significant
        # (the column restores in it), the codec preserves it verbatim.
        repo = PreviewPinsRepository(async_session)
        await repo.save([("character", 1), ("dd_class", "srd51/cleric"), ("item", 2)])
        assert await repo.load() == [
            ("character", 1),
            ("dd_class", "srd51/cleric"),
            ("item", 2),
        ]

    async def test_unknown_type_text_reads_back_untouched(
        self, async_session, caplog
    ):
        # The codec is structural only: an off-registry type is NOT its
        # corruption class — dropping unresolvable pairs is the connector's
        # restore rule (design Д3), so this row reads back silently.
        raw = '[{"t": "bogus", "i": 1}]'
        async_session.add(GameSettingsModel(key=PREVIEW_PINS_KEY, value=raw))
        await async_session.commit()
        with caplog.at_level(logging.WARNING):
            assert await PreviewPinsRepository(async_session).load() == [
                ("bogus", 1)
            ]
        assert not caplog.records

    @pytest.mark.parametrize(
        "raw",
        [
            "not json at all",              # unparseable JSON
            "5",                            # JSON, but not an array
            "{}",                           # object, not array
            '{"t": "character", "i": 1}',   # a lone object, not a list of them
            "[1, 2]",                       # entry is not an object
            '[["character", 1]]',           # entry is an array, not an object
            '[{"i": 1}]',                   # type missing
            '[{"t": 5, "i": 1}]',           # type is not text
            '[{"t": null, "i": 1}]',        # neither is null
            '[{"t": "character"}]',         # id missing
            '[{"t": "character", "i": true}]',   # bool is never the id
            '[{"t": "character", "i": 1.5}]',    # neither is a float
            '[{"t": "dd_feat", "i": ""}]',       # empty text names no record
            '[{"t": "character", "i": 1}, {}]',  # a broken later entry spoils all
        ],
    )
    async def test_corrupted_value_reads_empty_list_with_a_warning(
        self, async_session, caplog, raw
    ):
        async_session.add(GameSettingsModel(key=PREVIEW_PINS_KEY, value=raw))
        await async_session.commit()
        with caplog.at_level(logging.WARNING):
            assert await PreviewPinsRepository(async_session).load() == []
        warnings = [
            r for r in caplog.records if PREVIEW_PINS_KEY in r.getMessage()
        ]
        assert len(warnings) == 1
        assert warnings[0].levelname == "WARNING"
        # the damaged row is neither rewritten nor deleted (design Д3: the
        # next explicit pin/unpin is the one that cleans it)
        assert await self._stored_text(async_session) == raw

    async def test_repository_never_commits_rollback_drops_the_write(
        self, async_session, uow
    ):
        # «репозиторий сам не коммитит»: the wrapper writes through the
        # uncommitted trio, so an aborted transaction leaves no key behind.
        async def _write_then_fail() -> None:
            async with uow.transaction():
                await PreviewPinsRepository(uow.session).save([("character", 3)])
                raise _Boom

        with pytest.raises(_Boom):
            await _write_then_fail()
        assert await PreviewPinsRepository(async_session).load() == []
        assert await self._stored_text(async_session) is None


# ── add-dnd-module-foundation task 1.2: the typed D&D-module flag codec ─────


class TestDndModuleFlagCodec:
    """Pure-decoder pins for ``dnd_module``: valid bodies decode, everything
    unreadable logs the one journal warning and answers ``None`` (the caller
    then lives by the absence rule, design Д1). The row itself is the
    composition point's business — the codec never touches storage."""

    def test_valid_enabled_flag_decodes(self):
        assert decode_dnd_module_flag(
            '{"enabled": true, "version": 1}'
        ) == DndModuleFlag(enabled=True, version=1)

    def test_valid_disabled_flag_decodes(self):
        # A stored «off» is a readable value, not corruption — the lifecycle
        # service (group 2) re-reads exactly this state to switch the module.
        assert decode_dnd_module_flag(
            '{"enabled": false, "version": 2}'
        ) == DndModuleFlag(enabled=False, version=2)

    def test_unknown_extra_keys_pass_untouched(self):
        # The format grows additively (design Д1): a newer writer's extra
        # keys must not turn a readable game into a corrupted one.
        assert decode_dnd_module_flag(
            '{"enabled": true, "future": {"a": 1}, "version": 3}'
        ) == DndModuleFlag(enabled=True, version=3)

    @pytest.mark.parametrize(
        "raw, reason_needle",
        [
            ("not json at all", "not parseable JSON"),
            ("5", "JSON object, got int"),
            ('["enabled"]', "JSON object, got list"),
            ("{}", "enabled flag None is not a boolean"),
            ('{"version": 1}', "enabled flag None is not a boolean"),
            ('{"enabled": "true", "version": 1}', "not a boolean"),
            ('{"enabled": 1, "version": 1}', "not a boolean"),
            ('{"enabled": true}', "version None is not a positive integer"),
            ('{"enabled": true, "version": "2"}', "not a positive integer"),
            ('{"enabled": true, "version": true}', "not a positive integer"),
            ('{"enabled": true, "version": 0}', "not a positive integer"),
            ('{"enabled": true, "version": -3}', "not a positive integer"),
            ('{"enabled": true, "version": 1.5}', "not a positive integer"),
        ],
    )
    def test_corrupted_value_reads_none_with_one_warning(self, caplog, raw, reason_needle):
        with caplog.at_level(logging.WARNING):
            assert decode_dnd_module_flag(raw) is None
        warnings = [r for r in caplog.records if DND_MODULE_KEY in r.getMessage()]
        assert len(warnings) == 1
        assert warnings[0].levelname == "WARNING"
        assert reason_needle in warnings[0].getMessage()

    @pytest.mark.parametrize(
        "raw",
        ['{"enabled": true, "version": 1}', '{"enabled": false, "version": 1}'],
    )
    def test_readable_values_log_nothing(self, caplog, raw):
        with caplog.at_level(logging.WARNING):
            assert decode_dnd_module_flag(raw) is not None
        assert not caplog.records


# ── add-dnd-module-foundation task 3.4: the per-game dataset connection list ─


class TestDndDatasetsRepository:
    """Typed wrapper for the ``dnd_datasets`` key (design Д4: порядок массива
    — порядок подключений). Отсутствие ключа — обычное «наборов не
    подключено» без журнала; испорченное значение читается пустым СПИСКОМ и с
    одной записью в журнал, строка остаётся байт-в-байт до явной записи."""

    async def test_absent_key_reads_empty_list_without_warning(
        self, async_session: AsyncSession, caplog
    ):
        with caplog.at_level(logging.WARNING):
            assert await DndDatasetsRepository(async_session).load() == []
        assert not caplog.records

    async def test_save_stores_json_array_order_kept(
        self, async_session: AsyncSession
    ):
        repo = DndDatasetsRepository(async_session)
        await repo.save(["srd52", "srd51", "my-pack"])
        raw = await GameSettingsRepository(async_session).get(DND_DATASETS_KEY)
        assert raw == '["srd52", "srd51", "my-pack"]'
        assert await repo.load() == ["srd52", "srd51", "my-pack"]

    async def test_save_empty_list_roundtrips(self, async_session: AsyncSession):
        repo = DndDatasetsRepository(async_session)
        await repo.save([])
        assert await repo.load() == []

    @pytest.mark.parametrize(
        "raw, reason_needle",
        [
            ("не json", "not parseable JSON"),
            ('{"a": 1}', "must be a JSON array, got dict"),
            ('"srd51"', "must be a JSON array, got str"),
            ("[1]", "entry 1 is not text"),
            ('["ok", null]', "entry None is not text"),
            ('[["nested"]]', "entry ['nested'] is not text"),
        ],
    )
    async def test_corrupted_value_reads_empty_with_one_warning(
        self, async_session: AsyncSession, caplog, raw, reason_needle
    ):
        await GameSettingsRepository(async_session).upsert(DND_DATASETS_KEY, raw)
        with caplog.at_level(logging.WARNING):
            assert await DndDatasetsRepository(async_session).load() == []
        warnings = [r for r in caplog.records if DND_DATASETS_KEY in r.getMessage()]
        assert len(warnings) == 1
        assert warnings[0].levelname == "WARNING"
        assert reason_needle in warnings[0].getMessage()

    async def test_corrupted_row_survives_until_explicit_write(
        self, async_session: AsyncSession
    ):
        """Никакого фонового ремонта: чтение не трогает строку, первый явный
        save перезаписывает её чистым списком (дисциплина preview_pins)."""
        settings = GameSettingsRepository(async_session)
        await settings.upsert(DND_DATASETS_KEY, "{битый")
        repo = DndDatasetsRepository(async_session)
        assert await repo.load() == []
        assert await settings.get(DND_DATASETS_KEY) == "{битый"
        await repo.save(["srd51"])
        assert await settings.get(DND_DATASETS_KEY) == '["srd51"]'


class TestDndGrimoiresRepository:
    """Типизированная обёртка ключа ``dnd_grimoires`` (add-dnd-game-face,
    task 4.2): тот же массив текстовых id и та же грамматика, что у
    ``dnd_datasets`` — кодек один на оба ключа, а журнал называет каждый ключ
    сам. Отсутствие ключа — «гримуары не подключены» без записи в журнал;
    испорченное значение читается пустым списком с одной записью, строка
    дожидается явной записи."""

    async def test_absent_key_reads_empty_list_without_warning(
        self, async_session: AsyncSession, caplog
    ):
        with caplog.at_level(logging.WARNING):
            assert await DndGrimoiresRepository(async_session).load() == []
        assert not caplog.records

    async def test_save_stores_json_array_order_kept(
        self, async_session: AsyncSession
    ):
        repo = DndGrimoiresRepository(async_session)
        await repo.save(["tina-grimoire", "world-items"])
        raw = await GameSettingsRepository(async_session).get(DND_GRIMOIRES_KEY)
        assert raw == '["tina-grimoire", "world-items"]'
        assert await repo.load() == ["tina-grimoire", "world-items"]

    async def test_save_empty_list_roundtrips(self, async_session: AsyncSession):
        repo = DndGrimoiresRepository(async_session)
        await repo.save([])
        assert await repo.load() == []

    async def test_non_ascii_id_survives_unescaped(self, async_session: AsyncSession):
        """Кириллический id (мастер назвал файл сам) пишется как текст, а не
        \\u-последовательностью — тот же codec, что у списков наборов."""
        repo = DndGrimoiresRepository(async_session)
        await repo.save(["гримуар-тины"])
        raw = await GameSettingsRepository(async_session).get(DND_GRIMOIRES_KEY)
        assert raw == '["гримуар-тины"]'
        assert await repo.load() == ["гримуар-тины"]

    @pytest.mark.parametrize(
        "raw, reason_needle",
        [
            ("не json", "not parseable JSON"),
            ('{"a": 1}', "must be a JSON array, got dict"),
            ("[1]", "entry 1 is not text"),
            ('["ok", 2]', "entry 2 is not text"),
        ],
    )
    async def test_corrupted_value_reads_empty_with_one_warning(
        self, async_session: AsyncSession, caplog, raw, reason_needle
    ):
        await GameSettingsRepository(async_session).upsert(DND_GRIMOIRES_KEY, raw)
        with caplog.at_level(logging.WARNING):
            assert await DndGrimoiresRepository(async_session).load() == []
        warnings = [r for r in caplog.records if DND_GRIMOIRES_KEY in r.getMessage()]
        assert len(warnings) == 1
        assert warnings[0].levelname == "WARNING"
        assert reason_needle in warnings[0].getMessage()
        # соседний ключ со своей грамматикой не при чём: журнал называет этот
        assert DND_DATASETS_KEY not in warnings[0].getMessage()

    async def test_corrupted_row_survives_until_explicit_write(
        self, async_session: AsyncSession
    ):
        settings = GameSettingsRepository(async_session)
        await settings.upsert(DND_GRIMOIRES_KEY, "{битый")
        repo = DndGrimoiresRepository(async_session)
        assert await repo.load() == []
        assert await settings.get(DND_GRIMOIRES_KEY) == "{битый"
        await repo.save(["tina-grimoire"])
        assert await settings.get(DND_GRIMOIRES_KEY) == '["tina-grimoire"]'


class TestDndSearchShowReferenceRepository:
    """add-dnd-game-face task 3.3: the reference-search toggle key — the
    spec default «показывать» for the absent AND the damaged row alike, one
    journal entry per damaged read, explicit write replaces any body."""

    async def test_absent_key_reads_show_default(
        self, async_session: AsyncSession
    ):
        assert await DndSearchShowReferenceRepository(async_session).load() is True

    async def test_roundtrip_true_and_false(self, async_session: AsyncSession):
        repo = DndSearchShowReferenceRepository(async_session)
        settings = GameSettingsRepository(async_session)
        await repo.save(False)
        assert await settings.get(DND_SEARCH_SHOW_REFERENCE_KEY) == "false"
        assert await repo.load() is False
        await repo.save(True)
        assert await settings.get(DND_SEARCH_SHOW_REFERENCE_KEY) == "true"
        assert await repo.load() is True

    @pytest.mark.parametrize(
        ("raw", "reason_needle"),
        [
            ("{битый", "not parseable JSON"),
            ('"true"', "must be a JSON boolean, got str"),
            ("1", "must be a JSON boolean, got int"),
            ("null", "must be a JSON boolean, got NoneType"),
        ],
    )
    async def test_damaged_row_reads_show_with_one_warning(
        self, async_session: AsyncSession, caplog, raw, reason_needle
    ):
        await GameSettingsRepository(async_session).upsert(
            DND_SEARCH_SHOW_REFERENCE_KEY, raw
        )
        with caplog.at_level(logging.WARNING):
            assert await DndSearchShowReferenceRepository(async_session).load() is True
        warnings = [
            r
            for r in caplog.records
            if DND_SEARCH_SHOW_REFERENCE_KEY in r.getMessage()
        ]
        assert len(warnings) == 1
        assert reason_needle in warnings[0].getMessage()

    def test_absent_raw_decodes_silently_show(self, caplog):
        """The pure codec half: ``None`` is the absent row — the default
        answer, no journal noise (only damaged bodies earn the entry)."""
        with caplog.at_level(logging.WARNING):
            assert decode_dnd_search_show_reference(None) is True
        assert not [
            r for r in caplog.records if DND_SEARCH_SHOW_REFERENCE_KEY in r.getMessage()
        ]

    async def test_corrupted_row_survives_until_explicit_write(
        self, async_session: AsyncSession
    ):
        """No background repair (the dnd_datasets discipline): reading a
        damaged row answers the default but leaves the bytes untouched; the
        first explicit save rewrites the row with a clean boolean."""
        settings = GameSettingsRepository(async_session)
        await settings.upsert(DND_SEARCH_SHOW_REFERENCE_KEY, "5")
        repo = DndSearchShowReferenceRepository(async_session)
        assert await repo.load() is True
        assert await settings.get(DND_SEARCH_SHOW_REFERENCE_KEY) == "5"
        await repo.save(False)
        assert await settings.get(DND_SEARCH_SHOW_REFERENCE_KEY) == "false"
