"""The two new «События» columns end to end (NRI-0027, tasks 3.1–3.2, 4.1–4.2).

Covers the analyze half of «Время начала» and «Родительское событие»:

* 3.1 — the time draft: a valid cell (text «HH:MM», native time cell with the
  seconds dropped, minutes off the card's step of 5, a BC-date row) lands as
  the domain ``TimeOfDay`` in ``row.fields["start_time"]``; an unreadable or
  out-of-calendar value sets ``bad_start_time`` and puts no key (the row
  survives, the apply pass will print the warning); an empty cell puts
  neither. The merge keeps the slot's truth: the last writing cell decides
  the warning, a bad cell never erases a valid time.
* 3.2 — parent resolution in the fixpoint pass of ``resolve_links``: unique
  live file row → unique DB record → row problem, with every refusal voiced
  by the common ``app.domain.event_nesting`` judge (self / parent-declared
  sub-event = three levels and every cycle / DB root that is a sub-event /
  not found — never a ghost parent), ambiguous DB names a problem, and a
  skipped parent dragging its children down through the same iteration.
* 4.1 — the apply half of the time: a valid cell rides the plain setattr
  cycle through the model's public ``start_time`` property, an empty cell
  keeps the stored time, a refused cell imports the event without time and
  puts the sheet/row/value warning into ``report.warnings``.
* 4.2 — the deferred parent phase: after all entities exist a LINK_TO_FILE
  parent is written from its flushed instance (row below the child included),
  a LINK_TO_DB parent straight by the name-index id; the empty cell neither
  touches nor unbinds, a value sets and re-sets the parent.
"""
from __future__ import annotations

from datetime import date, time

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.application.services.xlsx_analyze import LINK_TO_DB, LINK_TO_FILE
from app.application.services.xlsx_import_service import XlsxImportService
from app.application.services.xlsx_report_text import start_time_warning
from app.domain.event_nesting import (
    CODE_IS_SUBEVENT,
    CODE_NOT_FOUND,
    CODE_SELF_PARENT,
    parent_refusal_message,
)
from app.domain.game_calendar import (
    CalendarSpec,
    CustomCalendar,
    MonthDay,
    MonthSpec,
    reset_current_calendar,
    set_current_calendar,
)
from app.domain.time_of_day import TimeOfDay
from app.infrastructure.db.models import EventModel, OrganizationModel
from app.infrastructure.db.uow import GameSessionUoW

# A world with 18-hour days of 40-minute hours (spec «Час не влезает в игровой
# календарь»): 20:00 is out of the day, 17:40 out of the hour, 17:39 valid.
_SHORT_SPEC = CalendarSpec(
    months=tuple(
        MonthSpec(name, 30) for name in ("Медвежарь", "Ледокол", "Травень", "Цветень")
    ),
    week_names=("пн", "вт", "ср", "чт", "пт", "сб", "вс"),
    day_hours=18,
    minutes_per_hour=40,
)
_SHORT = CustomCalendar(_SHORT_SPEC)


@pytest.fixture(autouse=True)
def _standard_active_calendar():
    """An imported custom calendar must not leak in or out of any test here."""
    reset_current_calendar()
    yield
    reset_current_calendar()


def _svc() -> XlsxImportService:
    return XlsxImportService()


def _new_workbook() -> Workbook:
    wb = Workbook()
    wb.remove(wb.active)
    return wb


def _sheet(wb: Workbook, title: str, headers, rows) -> None:
    ws = wb.create_sheet(title)
    ws.append(headers)
    for row in rows:
        ws.append(row)


def _save(tmp_path, wb: Workbook, name: str = "nesting.xlsx"):
    path = tmp_path / name
    wb.save(path)
    return path


BASE_HEADERS = ["Имя", "Дата начала"]
TIME_HEADERS = ["Имя", "Дата начала", "Время начала"]
PARENT_HEADERS = ["Имя", "Дата начала", "Родительское событие"]


# ── 3.1 — the «Время начала» draft ─────────────────────────────────────────


class TestStartTimeDraft:
    async def test_valid_time_lands_as_domain_time_of_day(self, tmp_path):
        # Spec «Время импортируется и печатается» + «Минуты вне шага 5
        # принимаются»: the draft already carries the domain TimeOfDay.
        wb = _new_workbook()
        _sheet(wb, "События", TIME_HEADERS,
               [["Бал", "1820-05-01", "19:00"], ["Поход", "1820-06-01", "14:37"]])
        plan = await _svc().analyze_file(_save(tmp_path, wb))
        assert not plan.has_fatal and plan.skipped_rows == []
        assert plan.lookup_row("event", "Бал").fields["start_time"] == TimeOfDay(19, 0)
        assert plan.lookup_row("event", "Поход").fields["start_time"] == TimeOfDay(14, 37)
        for row in plan.planned_rows:
            assert row.bad_start_time is None

    async def test_native_time_cell_drops_seconds(self, tmp_path):
        # Spec «Нативная ячейка времени Excel»: 06:30:45 → 06:30.
        wb = _new_workbook()
        _sheet(wb, "События", TIME_HEADERS, [["Рассвет", "1820-05-01", time(6, 30, 45)]])
        plan = await _svc().analyze_file(_save(tmp_path, wb))
        assert plan.skipped_rows == []
        assert plan.lookup_row("event", "Рассвет").fields["start_time"] == TimeOfDay(6, 30)

    async def test_unreadable_time_warns_without_losing_the_row(self, tmp_path):
        # Spec «Нечитаемое время не стоит строки»: the row stays in the pool,
        # the key is absent and the flag carries the cell value for the report.
        wb = _new_workbook()
        _sheet(wb, "События", TIME_HEADERS, [["Полдень", "1820-05-01", "полдень"]])
        plan = await _svc().analyze_file(_save(tmp_path, wb))
        assert not plan.has_fatal and plan.skipped_rows == []
        row = plan.lookup_row("event", "Полдень")
        assert "start_time" not in row.fields
        assert row.bad_start_time == "полдень"

    async def test_empty_time_cell_puts_no_key_and_no_flag(self, tmp_path):
        # Spec «Пустая ячейка не затирает время» at the draft level: neither
        # the key nor the warning — the saved time stays untouched on apply.
        wb = _new_workbook()
        _sheet(wb, "События", TIME_HEADERS, [["Тихий вечер", "1820-05-01", "   "]])
        plan = await _svc().analyze_file(_save(tmp_path, wb))
        assert plan.skipped_rows == []
        row = plan.lookup_row("event", "Тихий вечер")
        assert "start_time" not in row.fields
        assert row.bad_start_time is None

    async def test_time_beyond_the_game_calendar_warns_in_stead_of_refusing(self, tmp_path):
        # Spec «Час не влезает в игровой календарь» on the 18/40 world: hour
        # and minute bounds come from the active calendar, valid minutes in
        # its own unit land as the matching TimeOfDay.
        set_current_calendar(_SHORT)
        wb = _new_workbook()
        _sheet(wb, "События", TIME_HEADERS,
               [
                   ["Поздно", "2020-01-01", "20:00"],
                   ["Минута-не-бывает", "2020-01-02", "17:40"],
                   ["Последняя-минута", "2020-01-03", "17:39"],
               ])
        plan = await _svc().analyze_file(_save(tmp_path, wb))
        assert plan.skipped_rows == []
        assert plan.lookup_row("event", "Поздно").bad_start_time == "20:00"
        assert plan.lookup_row("event", "Минута-не-бывает").bad_start_time == "17:40"
        last = plan.lookup_row("event", "Последняя-минута")
        assert last.fields["start_time"] == TimeOfDay(17, 39)
        assert last.bad_start_time is None

    async def test_bc_date_and_time_are_independent(self, tmp_path):
        # Design risks (НRI-0023 lineage): the time counts minutes of the day
        # regardless of the date's era — a BC row keeps both fields.
        wb = _new_workbook()
        _sheet(wb, "События", TIME_HEADERS, [["Заговор", "-0044-03-15", "06:00"]])
        plan = await _svc().analyze_file(_save(tmp_path, wb))
        fields = plan.lookup_row("event", "Заговор").fields
        assert (fields["start_date"], fields["start_bc"]) == (MonthDay(44, 3, 15), True)
        assert fields["start_time"] == TimeOfDay(6, 0)

    async def test_merge_later_valid_time_clears_the_bad_flag(self, tmp_path):
        wb = _new_workbook()
        _sheet(wb, "События", TIME_HEADERS,
               [["Пир", "1820-05-01", "полдень"], ["пир", "1820-05-02", "19:00"]])
        plan = await _svc().analyze_file(_save(tmp_path, wb))
        merged = plan.lookup_row("event", "Пир")
        assert len(plan.planned_rows) == 1
        assert merged.fields["start_time"] == TimeOfDay(19, 0)
        assert merged.bad_start_time is None

    async def test_merge_bad_time_never_erases_a_valid_time_and_stays_quiet(self, tmp_path):
        # The later bad cell behaves like an empty one (it cannot unwrite the
        # earlier valid time), and a slot that WILL be written never warns.
        wb = _new_workbook()
        _sheet(wb, "События", TIME_HEADERS,
               [["Пир", "1820-05-01", "19:00"], ["пир", "1820-05-02", "полдень"]])
        plan = await _svc().analyze_file(_save(tmp_path, wb))
        merged = plan.lookup_row("event", "Пир")
        assert merged.fields["start_time"] == TimeOfDay(19, 0)
        assert merged.bad_start_time is None

    async def test_merge_two_bad_times_keeps_the_later_value(self, tmp_path):
        wb = _new_workbook()
        _sheet(wb, "События", TIME_HEADERS,
               [["Пир", "1820-05-01", "полдень"], ["пир", "1820-05-02", "полночь"]])
        plan = await _svc().analyze_file(_save(tmp_path, wb))
        merged = plan.lookup_row("event", "Пир")
        assert "start_time" not in merged.fields
        assert merged.bad_start_time == "полночь"


# ── 3.2 — «Родительское событие» resolution ────────────────────────────────


async def _seed_events(async_session, *specs: EventModel) -> list[EventModel]:
    async_session.add_all(specs)
    await async_session.flush()
    return list(specs)


def _event(name: str, parent: EventModel | None = None) -> EventModel:
    return EventModel(
        name=name, start_date=date(1800, 1, 1),
        parent_id=None if parent is None else parent.id,
    )


class TestParentResolution:
    async def test_parent_is_a_file_row_written_lower(self, tmp_path):
        # Spec «Родитель — строка того же файла, идущая ниже»: the merged file
        # is unique by lower(name), the row order does not matter.
        wb = _new_workbook()
        _sheet(wb, "События", PARENT_HEADERS,
               [["Дуэль", "1815-01-11", "Бал"], ["бал", "1815-01-10", None]])
        plan = await _svc().analyze_file(_save(tmp_path, wb))
        assert not plan.has_fatal and plan.skipped_rows == [] and plan.ghosts == {}
        duel = plan.lookup_row("event", "Дуэль")
        assert duel.parent_ref is not None
        assert duel.parent_ref.target_key == ("event", "бал")
        assert duel.parent_ref.resolution == LINK_TO_FILE
        assert duel.parent_ref.db_id is None
        assert plan.lookup_row("event", "бал").parent_ref is None  # the empty cell

    async def test_multiple_children_share_one_file_parent(self, tmp_path):
        # Spec «Несколько детей одного родителя» at the plan level: three
        # refs to the same live row, the tree stays two levels (children
        # themselves carry no parent cell).
        wb = _new_workbook()
        _sheet(wb, "События", PARENT_HEADERS,
               [
                   ["Дуэль", "1815-01-11", "Бал"],
                   ["Поединок", "1815-01-12", "бал"],
                   ["Схватка", "1815-01-13", "БАЛ"],
                   ["Бал", "1815-01-10", None],
               ])
        plan = await _svc().analyze_file(_save(tmp_path, wb))
        assert plan.skipped_rows == []
        for name in ("Дуэль", "Поединок", "Схватка"):
            ref = plan.lookup_row("event", name).parent_ref
            assert ref is not None and ref.target_key == ("event", "бал")
            assert ref.resolution == LINK_TO_FILE
        assert len(plan.planned_rows) == 4

    async def test_parent_is_a_db_event(self, tmp_path, async_session):
        # Spec «Родитель — существующее событие базы».
        (ball,) = await _seed_events(async_session, _event("Бал"))
        wb = _new_workbook()
        _sheet(wb, "События", PARENT_HEADERS, [["Дуэль", "1815-01-11", "бал"]])
        plan = await _svc().analyze_file(
            _save(tmp_path, wb), GameSessionUoW(async_session)
        )
        assert plan.skipped_rows == [] and plan.ghosts == {}
        duel = plan.lookup_row("event", "Дуэль")
        assert duel.parent_ref.resolution == LINK_TO_DB
        assert duel.parent_ref.db_id == ball.id
        assert not duel.is_update  # the child itself is new

    async def test_parent_not_found_is_a_problem_never_a_ghost(self, tmp_path, async_session):
        # Spec «Родитель не найден»: the row is a problem with the shared
        # not_found wording; no parent-ghost, no flat import of the child.
        await _seed_events(async_session, _event("Бал"))
        wb = _new_workbook()
        _sheet(wb, "События", PARENT_HEADERS, [["Охота", "1815-02-01", "Никогда"]])
        plan = await _svc().analyze_file(
            _save(tmp_path, wb), GameSessionUoW(async_session)
        )
        assert plan.planned_rows == [] and plan.ghosts == {}
        issue, = plan.skipped_rows
        assert (issue.sheet, issue.row_number) == ("События", 2)
        assert parent_refusal_message(CODE_NOT_FOUND, "«Никогда»") in issue.reason
        assert "событие «Охота» (строка 2)" in issue.reason

    async def test_parent_not_found_without_db_is_a_problem_not_fatal(self, tmp_path):
        # Without a session there is no DB to hide the name in: the honest
        # verdict is «not found», the analysis itself stays applicable.
        wb = _new_workbook()
        _sheet(wb, "События", PARENT_HEADERS, [["Охота", "1815-02-01", "Никогда"]])
        plan = await _svc().analyze_file(_save(tmp_path, wb))
        assert not plan.has_fatal and plan.ghosts == {}
        issue, = plan.skipped_rows
        assert "не найдено" in issue.reason

    async def test_three_levels_refused_with_the_card_wording(self, tmp_path):
        # Spec «Три уровня запрещены»: В falls (its parent У is declared a
        # child by its own cell), У and Т survive the two-level tree.
        wb = _new_workbook()
        _sheet(wb, "События", PARENT_HEADERS,
               [
                   ["В", "1815-01-01", "У"],
                   ["У", "1815-01-02", "Т"],
                   ["Т", "1815-01-03", None],
               ])
        plan = await _svc().analyze_file(_save(tmp_path, wb))
        assert [i.row_number for i in plan.skipped_rows] == [2]
        issue, = plan.skipped_rows
        assert parent_refusal_message(CODE_IS_SUBEVENT) in issue.reason
        assert "событие «В»" in issue.reason
        assert plan.lookup_row("event", "У").parent_ref.target_key == ("event", "т")
        assert plan.lookup_row("event", "Т").parent_ref is None

    async def test_db_parent_already_a_subevent_refused(self, tmp_path, async_session):
        # Spec «Родитель уже подсобытие в базе» — «той же формулировкой, чем
        # карточка отказывает такой сохран» (the shared module text).
        (top,) = await _seed_events(async_session, _event("Т"))
        await _seed_events(async_session, _event("У", parent=top))
        wb = _new_workbook()
        _sheet(wb, "События", PARENT_HEADERS, [["В", "1815-01-01", "У"]])
        plan = await _svc().analyze_file(
            _save(tmp_path, wb), GameSessionUoW(async_session)
        )
        assert plan.planned_rows == [] and plan.ghosts == {}
        issue, = plan.skipped_rows
        assert parent_refusal_message(CODE_IS_SUBEVENT) in issue.reason
        assert "событие «В» (строка 2)" in issue.reason

    async def test_self_reference_refused(self, tmp_path, async_session):
        # Spec «Самоссылка и цикл», first half: the cell names the row's own
        # event (case-insensitively) — the card's self refusal answers.
        wb = _new_workbook()
        _sheet(wb, "События", PARENT_HEADERS, [["Дуэль", "1815-01-11", "дуэль"]])
        plan = await _svc().analyze_file(
            _save(tmp_path, wb), GameSessionUoW(async_session)
        )
        assert plan.planned_rows == []
        issue, = plan.skipped_rows
        assert parent_refusal_message(CODE_SELF_PARENT) in issue.reason

    async def test_cycle_refuses_every_participant(self, tmp_path, async_session):
        # Spec «Самоссылка и цикл», second half: A→B and B→A — each
        # participating row falls with the shared parent-is-a-subevent verdict.
        wb = _new_workbook()
        _sheet(wb, "События", PARENT_HEADERS,
               [["А", "1815-01-01", "Б"], ["Б", "1815-01-02", "А"]])
        plan = await _svc().analyze_file(
            _save(tmp_path, wb), GameSessionUoW(async_session)
        )
        assert plan.planned_rows == [] and plan.ghosts == {}
        assert [i.row_number for i in plan.skipped_rows] == [2, 3]
        for issue in plan.skipped_rows:
            assert parent_refusal_message(CODE_IS_SUBEVENT) in issue.reason

    async def test_ambiguous_db_parent_name_is_a_problem(self, tmp_path, async_session):
        # Spec «Неоднозначное имя родителя».
        await _seed_events(async_session, _event("Князь"), _event("князь"))
        wb = _new_workbook()
        _sheet(wb, "События", PARENT_HEADERS, [["Дуэль", "1815-01-11", "Князь"]])
        plan = await _svc().analyze_file(
            _save(tmp_path, wb), GameSessionUoW(async_session)
        )
        assert plan.planned_rows == [] and plan.ghosts == {}
        issue, = plan.skipped_rows
        assert "разрешения не имеет" in issue.reason
        assert "«Князь»" in issue.reason

    async def test_unique_file_row_beats_an_ambiguous_db_name(self, tmp_path, async_session):
        await _seed_events(async_session, _event("Турнир"), _event("турнир"))
        wb = _new_workbook()
        _sheet(wb, "События", PARENT_HEADERS,
               [["Дуэль", "1815-01-11", "турнир"], ["Турнир", "1815-01-01", None]])
        plan = await _svc().analyze_file(
            _save(tmp_path, wb), GameSessionUoW(async_session)
        )
        assert plan.skipped_rows == []
        duel = plan.lookup_row("event", "Дуэль")
        assert duel.parent_ref.resolution == LINK_TO_FILE
        assert duel.parent_ref.target_key == ("event", "турнир")

    async def test_parent_of_a_skipped_row_falls_with_it(self, tmp_path, async_session):
        # Design Д4 risk: «Ярмарка» drowns in an ambiguous link; its child
        # «Открытие» loses the live file parent on the next fixpoint pass and
        # falls as not_found too — the same iterative mechanism, no leftovers.
        async_session.add_all(
            [
                OrganizationModel(name="Цех", start_date=date(1850, 1, 1)),
                OrganizationModel(name="цех", start_date=date(1851, 1, 1)),
            ]
        )
        await async_session.flush()
        wb = _new_workbook()
        _sheet(wb, "События", PARENT_HEADERS + ["Связь организациями"],
               [
                   ["Ярмарка", "1810-01-01", None, "цех"],
                   ["Открытие", "1811-01-01", "Ярмарка", None],
               ])
        plan = await _svc().analyze_file(
            _save(tmp_path, wb), GameSessionUoW(async_session)
        )
        assert plan.planned_rows == []
        assert [(i.sheet, i.row_number) for i in plan.skipped_rows] == [
            ("События", 2),
            ("События", 3),
        ]
        child_issue = plan.skipped_rows[1]
        assert "событие «Открытие» (строка 3)" in child_issue.reason
        assert parent_refusal_message(CODE_NOT_FOUND, "«Ярмарка»") in child_issue.reason

    async def test_update_with_empty_parent_cell_keeps_parent_ref_none(
        self, tmp_path, async_session
    ):
        # Spec «Пустая ячейка не трогает и не отвязывает» at the plan level:
        # the update row carries no parent_ref at all, so apply never touches
        # the stored parent.
        (top,) = await _seed_events(async_session, _event("Бал"))
        await _seed_events(async_session, _event("Дуэль", parent=top))
        wb = _new_workbook()
        _sheet(wb, "События", PARENT_HEADERS, [["Дуэль", "1815-01-11", None]])
        plan = await _svc().analyze_file(
            _save(tmp_path, wb), GameSessionUoW(async_session)
        )
        duel = plan.lookup_row("event", "Дуэль")
        assert duel.is_update and duel.parent_ref is None

    async def test_reparent_update_resolves_the_new_db_parent(
        self, tmp_path, async_session
    ):
        # Spec «Перестановка под другого родителя» at the plan level: the
        # other name resolves to its unique DB record.
        ball = _event("Бал")
        await _seed_events(async_session, ball, _event("Поединок"))
        wb = _new_workbook()
        _sheet(wb, "События", PARENT_HEADERS, [["поединок", "1815-01-11", "Бал"]])
        plan = await _svc().analyze_file(
            _save(tmp_path, wb), GameSessionUoW(async_session)
        )
        row = plan.lookup_row("event", "поединок")
        assert row.is_update
        assert row.parent_ref.resolution == LINK_TO_DB
        assert row.parent_ref.db_id == ball.id

    async def test_parent_header_on_another_sheet_is_ignored(self, tmp_path):
        # The column belongs to «События» only — on «Персонажи» it is just an
        # unknown header: ignored, no parent machinery on characters.
        wb = _new_workbook()
        _sheet(wb, "Персонажи", BASE_HEADERS + ["Родительское событие"],
               [["Иван", "1800-01-01", "Кто-то"]])
        plan = await _svc().analyze_file(_save(tmp_path, wb))
        assert not plan.has_fatal and plan.skipped_rows == []
        character = plan.lookup_row("character", "Иван")
        assert character.parent_ref is None
        assert "parent_event" not in character.fields


# ── 4.1/4.2 — applying the two columns (designs Д3/Д4) ─────────────────────


async def _by_name(session, model, name):
    return (
        await session.execute(select(model).where(model.name == name))
    ).scalars().one()


class TestApplyStartTime:
    async def test_valid_time_rides_plain_setattr_through_the_property(
        self, tmp_path, async_session
    ):
        # Design Д3: the plan already carries the domain TimeOfDay and the
        # setattr cycle writes it via the public property — the storage pair
        # reads back identical to what the card would have stored.
        wb = _new_workbook()
        _sheet(wb, "События", TIME_HEADERS, [["Бал", "1820-05-01", "19:00"]])
        plan = await _svc().analyze_file(
            _save(tmp_path, wb), GameSessionUoW(async_session)
        )
        report = await _svc().apply_plan(plan, GameSessionUoW(async_session))
        assert (report.created, report.updated, report.links) == (1, 0, 0)
        assert report.warnings == []
        event = await _by_name(async_session, EventModel, "Бал")
        assert event.start_time_raw == 19 * 60
        assert event.start_time == TimeOfDay(19, 0)

    async def test_bad_time_imports_the_event_without_time_and_warns(
        self, tmp_path, async_session
    ):
        # Spec «Нечитаемое время не стоит строки» at the report level (task
        # 4.1): the row is NOT lost — the event exists without time and the
        # final report carries the sheet/row/value warning verbatim.
        wb = _new_workbook()
        _sheet(wb, "События", TIME_HEADERS, [["Полдень", "1820-05-01", "полдень"]])
        plan = await _svc().analyze_file(
            _save(tmp_path, wb), GameSessionUoW(async_session)
        )
        report = await _svc().apply_plan(plan, GameSessionUoW(async_session))
        assert report.created == 1
        event = await _by_name(async_session, EventModel, "Полдень")
        assert event.start_time_raw is None and event.start_time is None
        assert report.warnings == [start_time_warning("События", 2, "полдень")]

    async def test_time_beyond_the_game_calendar_warns_on_apply(self, tmp_path, async_session):
        # Spec «Час не влезает в игровой календарь» end to end on the 18/40
        # world: the pre-analysis flags the cell, the apply pass imports the
        # event without time and puts the value into the report.
        set_current_calendar(_SHORT)
        wb = _new_workbook()
        _sheet(wb, "События", TIME_HEADERS, [["Поздно", "2020-01-01", "20:00"]])
        plan = await _svc().analyze_file(
            _save(tmp_path, wb), GameSessionUoW(async_session)
        )
        report = await _svc().apply_plan(plan, GameSessionUoW(async_session))
        assert report.created == 1
        event = await _by_name(async_session, EventModel, "Поздно")
        assert event.start_time_raw is None
        assert report.warnings == [start_time_warning("События", 2, "20:00")]

    async def test_empty_time_cell_keeps_the_stored_time(self, tmp_path, async_session):
        # Spec «Пустая ячейка не затирает время»: the update row carries no
        # start_time key, so the stored time survives untouched.
        existing = EventModel(name="Бал", start_date=date(1800, 1, 1))
        existing.start_time = TimeOfDay(7, 5)
        async_session.add(existing)
        await async_session.flush()
        wb = _new_workbook()
        _sheet(wb, "События", TIME_HEADERS, [["бал", "1800-02-02", None]])
        plan = await _svc().analyze_file(
            _save(tmp_path, wb), GameSessionUoW(async_session)
        )
        assert plan.lookup_row("event", "бал").is_update
        report = await _svc().apply_plan(plan, GameSessionUoW(async_session))
        assert (report.created, report.updated) == (0, 1)
        event = await _by_name(async_session, EventModel, "Бал")  # name not renamed
        assert event.start_time == TimeOfDay(7, 5)


class TestApplyParent:
    async def test_parent_row_written_below_the_child(self, tmp_path, async_session):
        # Spec «Родитель — строка того же файла, идущая ниже» — the deferred
        # phase is exactly what makes the sheet order irrelevant: «Бал» is
        # only flushed after «Дуэль», yet the child gets its parent id.
        wb = _new_workbook()
        _sheet(wb, "События", PARENT_HEADERS,
               [["Дуэль", "1815-01-11", "Бал"], ["бал", "1815-01-10", None]])
        plan = await _svc().analyze_file(
            _save(tmp_path, wb), GameSessionUoW(async_session)
        )
        report = await _svc().apply_plan(plan, GameSessionUoW(async_session))
        assert (report.created, report.links) == (2, 0)
        assert report.warnings == []
        ball = await _by_name(async_session, EventModel, "бал")
        duel = await _by_name(async_session, EventModel, "Дуэль")
        assert duel.parent_id == ball.id
        assert ball.parent_id is None
        # The column key names no attribute — it never rode the setattr cycle.
        assert not hasattr(duel, "parent_event")

    async def test_three_children_share_one_file_parent(self, tmp_path, async_session):
        # Spec «Несколько детей одного родителя»: all three land under the
        # same flushed parent, the tree stays two levels (none of the children
        # itself has a parent row).
        wb = _new_workbook()
        _sheet(wb, "События", PARENT_HEADERS,
               [
                   ["Дуэль", "1815-01-11", "Бал"],
                   ["Поединок", "1815-01-12", "бал"],
                   ["Схватка", "1815-01-13", "БАЛ"],
                   ["Бал", "1815-01-10", None],
               ])
        plan = await _svc().analyze_file(
            _save(tmp_path, wb), GameSessionUoW(async_session)
        )
        report = await _svc().apply_plan(plan, GameSessionUoW(async_session))
        assert report.created == 4
        ball = await _by_name(async_session, EventModel, "Бал")
        for name in ("Дуэль", "Поединок", "Схватка"):
            child = await _by_name(async_session, EventModel, name)
            assert child.parent_id == ball.id
        assert ball.parent_id is None

    async def test_db_parent_written_by_the_name_index_id(self, tmp_path, async_session):
        # Spec «Родитель — существующее событие базы», apply level: the FK is
        # the id the index carried — no extra event row is created for it.
        (ball,) = await _seed_events(async_session, _event("Бал"))
        wb = _new_workbook()
        _sheet(wb, "События", PARENT_HEADERS, [["Дуэль", "1815-01-11", "бал"]])
        plan = await _svc().analyze_file(
            _save(tmp_path, wb), GameSessionUoW(async_session)
        )
        report = await _svc().apply_plan(plan, GameSessionUoW(async_session))
        assert (report.created, report.updated) == (1, 0)
        duel = await _by_name(async_session, EventModel, "Дуэль")
        assert duel.parent_id == ball.id
        assert (await _by_name(async_session, EventModel, "Бал")).parent_id is None

    async def test_empty_parent_cell_neither_touches_nor_unbinds(
        self, tmp_path, async_session
    ):
        # Spec «Пустая ячейка не трогает и не отвязывает» at the storage level:
        # the update changes the date, the stored parent stays — an import
        # cannot turn a sub-event back into a root.
        (ball,) = await _seed_events(async_session, _event("Бал"))
        await _seed_events(async_session, _event("Дуэль", parent=ball))
        wb = _new_workbook()
        _sheet(wb, "События", PARENT_HEADERS, [["дуэль", "1816-01-01", None]])
        plan = await _svc().analyze_file(
            _save(tmp_path, wb), GameSessionUoW(async_session)
        )
        report = await _svc().apply_plan(plan, GameSessionUoW(async_session))
        assert (report.created, report.updated) == (0, 1)
        duel = await _by_name(async_session, EventModel, "Дуэль")
        assert duel.start_date == date(1816, 1, 1)  # the update did land…
        assert duel.parent_id == ball.id            # …and the parent survived

    async def test_reparent_update_moves_the_child_under_the_named_event(
        self, tmp_path, async_session
    ):
        # Spec «Перестановка под другого родителя»: the named event's index
        # id replaces the stored parent on the update.
        ball = _event("Бал")
        _, tournament = await _seed_events(async_session, ball, _event("Турнир"))
        await _seed_events(async_session, _event("Поединок", parent=ball))
        wb = _new_workbook()
        _sheet(wb, "События", PARENT_HEADERS, [["Поединок", "1816-01-01", "Турнир"]])
        plan = await _svc().analyze_file(
            _save(tmp_path, wb), GameSessionUoW(async_session)
        )
        report = await _svc().apply_plan(plan, GameSessionUoW(async_session))
        assert (report.created, report.updated) == (0, 1)
        fight = await _by_name(async_session, EventModel, "Поединок")
        assert fight.parent_id == tournament.id
