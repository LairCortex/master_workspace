"""Tests for `CalendarWizardViewModel` (wizard tasks 5.1–5.3, spec calendar-wizard).

Every test drives the view model exactly as the group-6 dialog will: read the
frozen ``state`` snapshot, call intents, listen to the three lifecycle signals.
Draft and application tests run on the real service over the in-memory
aiosqlite session (fixtures from ``tests/conftest.py``) — the wizard's storage
promises are only trustworthy against the actual storage.

The default active calendar is the «Стандартный» preset (fixture
``_fresh_active_calendar``), so a fresh view model preselects «standard» exactly
like a newly seeded game; the kind preselection on a custom game is covered
explicitly.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.application.services.calendar_settings_service import (
    CALENDAR_SETTINGS_KEY,
    CalendarSettingsService,
)
from app.domain.game_calendar import (
    DEFAULT_MONTH_NAMES,
    CalendarSpec,
    CustomCalendar,
    IntercalaryDay,
    IntercalarySpec,
    MonthDay,
    MonthSpec,
    StandardCalendar,
    current_calendar,
    reset_current_calendar,
    set_current_calendar,
)
from app.infrastructure.calendar_storage import (
    CalendarDraft,
    DRAFT_STAGE_MONTHS,
    DRAFT_STAGE_PREVIEW,
    encode_calendar,
    encode_coord,
)
from app.infrastructure.repositories.game_settings_repository import (
    CALENDAR_DRAFT_KEY,
)
from app.infrastructure.db.models import EventModel, GameSettingsModel, RatingModel
from app.infrastructure.db.uow import GameSessionUoW
from app.presentation.utils.date_utils import STANDARD_WEEK_NAMES
from app.presentation.viewmodels.calendar_wizard_viewmodel import (
    KIND_CUSTOM,
    KIND_STANDARD,
    STEP_CHOICE,
    STEP_INTERCALARY,
    STEP_MONTHS,
    STEP_PREVIEW,
    STEP_REPORT,
    STEP_WEEK,
    CalendarWizardViewModel,
    ReportLine,
)

# ── fixtures / module-level helpers ────────────────────────────────────────


@pytest.fixture(autouse=True)
def _qt(qapp):
    yield


@pytest.fixture(autouse=True)
def _fresh_active_calendar():
    """The service and the VM share the process-global active calendar."""
    reset_current_calendar()
    yield
    reset_current_calendar()


# The three-months-of-ten-days custom calendar the «Месяцы»-screen tests assemble
# month by month through the intents — with the default prefill's week names, the
# exact calendar that «apply» builds out of such a form.
_CUSTOM_MONTHS = (
    MonthSpec("Медвежарь", 10),
    MonthSpec("Ледокол", 10),
    MonthSpec("Травень", 10),
)
_CUSTOM_SPEC = CalendarSpec(
    months=_CUSTOM_MONTHS,
    week_names=("пн", "вт", "ср", "чт", "пт", "сб", "вс"),
)
_CUSTOM = CustomCalendar(_CUSTOM_SPEC)
_TARGET_FORM = CustomCalendar(
    CalendarSpec(months=_CUSTOM_MONTHS, week_names=STANDARD_WEEK_NAMES)
)

_FLOW_ORDER = (STEP_WEEK, STEP_MONTHS, STEP_INTERCALARY, STEP_PREVIEW)


def _vm(session, service=None, *, first_entry: bool = False) -> CalendarWizardViewModel:
    return CalendarWizardViewModel(
        GameSessionUoW(session), service or CalendarSettingsService(), first_entry=first_entry
    )


async def _flow_to(vm: CalendarWizardViewModel, target_step: str) -> None:
    """Open the wizard and walk the custom flow to ``target_step`` on the default
    (valid) form — the same clicks the dialog will make on a fresh game."""
    await vm.begin()
    vm.choose_kind(KIND_CUSTOM)
    await vm.try_advance()  # choice → week
    for _ in range(_FLOW_ORDER.index(target_step)):
        await vm.try_advance()
    assert vm.state.step == target_step


async def _custom_months_on(vm: CalendarWizardViewModel) -> None:
    """Stand on «Месяцы» with the prefill rebuilt as the 3×10 custom set."""
    await _flow_to(vm, STEP_MONTHS)
    vm.set_month_count(3)
    for index, month in enumerate(_CUSTOM_MONTHS):
        vm.set_month_name(index, month.name)
        vm.set_month_length(index, month.length)


async def _add_event(session, name: str, start, end, **flags) -> EventModel:
    event = EventModel(name=name, start_date=start, end_date=end, **flags)
    session.add(event)
    await session.commit()
    return event


async def _setting(session, key: str) -> str | None:
    return (
        await session.execute(
            select(GameSettingsModel.value).where(GameSettingsModel.key == key)
        )
    ).scalars().first()


async def _event_rows(session) -> list:
    return list(
        (
            await session.execute(
                select(
                    EventModel.id,
                    EventModel.__table__.c.start_date,
                    EventModel.start_coord,
                    EventModel.start_key,
                    EventModel.__table__.c.end_date,
                    EventModel.end_coord,
                    EventModel.end_key,
                ).order_by(EventModel.id)
            )
        ).all()
    )


# ════════════════════════ task 5.1 — flow and validation ═════════════════════


class TestChoiceScreen:
    async def test_choice_preselects_kind_and_gates_buttons(self, async_session):
        vm = _vm(async_session)
        await vm.begin()

        state = vm.state
        assert state.step == STEP_CHOICE
        assert state.kind == KIND_STANDARD  # preset active ⇒ «Стандартный»
        assert state.can_apply and not state.can_advance  # preset: only «Применить»
        assert isinstance(state.preview_calendar, StandardCalendar)

    async def test_menu_entry_on_custom_game_preselects_custom(self, async_session):
        set_current_calendar(_CUSTOM)

        vm = _vm(async_session)
        await vm.begin()

        state = vm.state
        assert state.kind == KIND_CUSTOM
        assert state.can_advance and not state.can_apply  # custom: only «Далее»
        assert state.preview_calendar is _CUSTOM  # the game's own calendar

    async def test_choosing_custom_swaps_preview_and_same_choice_is_noop(
        self, async_session
    ):
        vm = _vm(async_session)
        await vm.begin()
        preset_preview = vm.state.preview_calendar

        vm.choose_kind(KIND_CUSTOM)
        custom_preview = vm.state.preview_calendar

        assert isinstance(custom_preview, CustomCalendar)
        assert custom_preview is not preset_preview
        assert vm.state.can_advance and not vm.state.can_apply

        vm.choose_kind(KIND_CUSTOM)  # same value — no churn
        assert vm.state.preview_calendar is custom_preview

        vm.choose_kind(KIND_STANDARD)  # the preview follows the selection back
        assert isinstance(vm.state.preview_calendar, StandardCalendar)


class TestWeekStep:
    # spec «Экран „Неделя“» scenarios
    async def test_eighth_day_arrives_empty_and_blocks_until_named(self, async_session):
        vm = _vm(async_session)
        await _flow_to(vm, STEP_WEEK)

        vm.set_week_length(8)

        state = vm.state
        assert len(state.week_names) == 8 and state.week_names[7] == ""
        assert not state.can_advance
        assert "у дня недели пустое название" in state.problem_phrases

        await vm.try_advance()  # a misfired «Далее» must not move the flow
        assert vm.state.step == STEP_WEEK

        vm.set_week_name(7, "Осьмидневик")
        assert vm.state.can_advance and vm.state.problems == ()

    async def test_week_below_two_is_refused_by_the_gate(self, async_session):
        vm = _vm(async_session)
        await _flow_to(vm, STEP_WEEK)

        vm.set_week_length(1)  # the spin itself never offers this (2…168),
        # but the domain gate still catches a programmatic misuse

        assert not vm.state.can_advance
        assert "в неделе меньше двух дней" in vm.state.problem_phrases

    async def test_duplicate_week_name_blocks(self, async_session):
        vm = _vm(async_session)
        await _flow_to(vm, STEP_WEEK)

        vm.set_week_length(2)  # the tail cut leaves the two first names
        vm.set_week_name(1, vm.state.week_names[0])

        assert not vm.state.can_advance
        assert "в календаре повторяются названия дней недели" in vm.state.problem_phrases

    async def test_out_of_range_week_edit_is_a_no_op(self, async_session):
        vm = _vm(async_session)
        await _flow_to(vm, STEP_WEEK)
        before = vm.state.week_names

        vm.set_week_name(99, "Мимо")
        vm.set_week_name(-1, "Мимо")

        assert vm.state.week_names == before

    async def test_out_of_range_month_name_edit_is_a_no_op(self, async_session):
        vm = _vm(async_session)
        await _flow_to(vm, STEP_MONTHS)
        before = vm.state.months

        vm.set_month_name(99, "Мимо")
        vm.set_month_name(-1, "Мимо")

        assert vm.state.months == before


class TestMonthsStep:
    # spec «Экран „Месяцы“» scenarios
    async def test_first_custom_assembly_prefills_gregorian_grid(self, async_session):
        vm = _vm(async_session)
        await _flow_to(vm, STEP_MONTHS)

        state = vm.state
        assert [month.name for month in state.months] == [
            DEFAULT_MONTH_NAMES[number] for number in range(1, 13)
        ]
        assert state.months[1].length == 28  # the common-year February
        assert state.can_advance  # the start grid is a valid calendar

    async def test_added_months_take_free_numbers_and_shrink_drops_the_tail(
        self, async_session
    ):
        vm = _vm(async_session)
        await _flow_to(vm, STEP_MONTHS)

        vm.set_month_count(0)
        assert vm.state.months == ()
        assert "в календаре нет ни одного месяца" in vm.state.problem_phrases

        vm.set_month_count(3)
        assert vm.state.months == (
            MonthSpec("Месяц 1", 30),
            MonthSpec("Месяц 2", 30),
            MonthSpec("Месяц 3", 30),
        )
        assert vm.state.can_advance

        vm.set_month_count(-4)  # below zero is still «no months», not a crash
        assert vm.state.months == ()

        vm.set_month_count(3)
        vm.set_month_count(1)  # «уменьшение числа отбрасывает хвостовые месяцы»
        assert vm.state.months == (MonthSpec("Месяц 1", 30),)

    async def test_empty_month_name_holds_next_and_the_last_valid_preview(
        self, async_session
    ):
        vm = _vm(async_session)
        await _flow_to(vm, STEP_MONTHS)
        last_valid = vm.state.preview_calendar

        vm.set_month_name(0, "")
        vm.set_month_name(1, "")  # two empties — one sentence to the user

        state = vm.state
        assert not state.can_advance
        assert state.problem_phrases.count("у месяца пустое название") == 1
        assert state.preview_calendar is last_valid  # «держит последний валидный»

        await vm.try_advance()
        assert vm.state.step == STEP_MONTHS

        vm.set_month_name(0, "Янь")
        vm.set_month_name(1, "Янь")
        assert "в календаре повторяются имена месяцев" in vm.state.problem_phrases
        assert not vm.state.can_advance
        assert vm.state.preview_calendar is last_valid  # still not repainted

    async def test_month_length_below_one_blocks(self, async_session):
        vm = _vm(async_session)
        await _flow_to(vm, STEP_MONTHS)
        before = vm.state.preview_calendar

        vm.set_month_length(5, 0)
        vm.set_month_length(99, 7)  # out of range — no-op

        assert "длина месяца меньше одного дня" in vm.state.problem_phrases
        assert not vm.state.can_advance
        assert vm.state.preview_calendar is before

        vm.set_month_length(5, 33)  # a valid repair repaints the preview
        assert vm.state.can_advance
        assert vm.state.preview_calendar.spec.months[5].length == 33

    async def test_dangling_intercalary_blocks_next_and_survives_in_the_form(
        self, async_session
    ):
        # The scenario «Висячий вставной день блокирует»: the rule lives in the
        # continued draft; trimming its host month must block «Далее» while the
        # rule itself is silently KEPT for the intercalary screen.
        # The draft must carry an already-stored rule, so it is written as the
        # full preview-stage package of the service codec.
        host_month = DEFAULT_MONTH_NAMES[12]  # a December-long tail
        gregorian = CalendarSpec(
            months=tuple(
                MonthSpec(host_month, 31) if n == 12 else MonthSpec(name, 1)
                for n, name in (
                    (number, DEFAULT_MONTH_NAMES[number]) for number in range(1, 13)
                )
            ),
            week_names=("Буд", "Ведь", "Творец", "Грозник", "Светлай"),
            intercalary=(IntercalarySpec("Громовик", 12),),
        )
        await CalendarSettingsService().save_draft(
            async_session, CalendarDraft(spec=gregorian, stage=DRAFT_STAGE_PREVIEW)
        )

        vm = _vm(async_session)
        await vm.begin()
        assert vm.state.step == STEP_PREVIEW  # continued from the saved stage

        vm.go_back()
        vm.go_back()
        assert vm.state.step == STEP_MONTHS

        vm.set_month_count(2)  # host month 12 is gone beneath the rule

        state = vm.state
        assert not state.can_advance
        assert (
            "вставной день ссылается на несуществующий месяц" in state.problem_phrases
        )
        assert state.intercalary == gregorian.intercalary  # «правило сохранено»
        await vm.try_advance()
        assert vm.state.step == STEP_MONTHS  # the gate holds

    async def test_dangling_rule_edit_out_of_range_is_a_no_op(self, async_session):
        vm = _vm(async_session)
        await _flow_to(vm, STEP_MONTHS)
        rules_before = vm.state.intercalary

        vm.remove_intercalary(0)  # the flow reached months with no rules at all

        assert vm.state.intercalary == rules_before


class TestIntercalaryStep:
    # spec «Экран „Вставные дни“»
    async def test_empty_and_duplicate_rule_names_block_next(self, async_session):
        vm = _vm(async_session)
        await _flow_to(vm, STEP_INTERCALARY)

        vm.add_intercalary()  # rule added with an empty name field
        assert vm.state.intercalary == (IntercalarySpec("", 12),)  # last-month host
        assert "у вставного дня пустое название" in vm.state.problem_phrases
        assert not vm.state.can_advance

        vm.remove_intercalary(0)
        vm.add_intercalary("Гром", 1)
        vm.add_intercalary("Гром", 2)
        assert "в календаре повторяются названия вставных дней" in vm.state.problem_phrases
        assert not vm.state.can_advance

        vm.remove_intercalary(1)
        vm.remove_intercalary(99)  # out of range — no-op
        assert vm.state.can_advance

    async def test_rule_order_is_the_slot_order(self, async_session):
        vm = _vm(async_session)
        await _flow_to(vm, STEP_INTERCALARY)

        vm.add_intercalary("Гром", 1)
        vm.add_intercalary("Молния", 2)
        vm.add_intercalary("Веха", 1)  # two rules of one host prove the ordering

        vm.move_rule(2, -1)  # «вверх» — positions follow the list order
        assert tuple(rule.name for rule in vm.state.intercalary) == (
            "Гром",
            "Веха",
            "Молния",
        )

        vm.move_rule(0, -1)  # off the top — no-op
        vm.move_rule(7, 1)  # off the list — no-op
        assert tuple(rule.name for rule in vm.state.intercalary) == (
            "Гром",
            "Веха",
            "Молния",
        )


class TestNavigationAndPreview:
    async def test_back_walks_the_flow_then_stops_at_the_choice(self, async_session):
        vm = _vm(async_session)
        await vm.begin()

        vm.go_back()  # the choice screen has no back
        assert vm.state.step == STEP_CHOICE

        await _flow_to(vm, STEP_MONTHS)
        assert vm.state.can_go_back

        vm.go_back()
        assert vm.state.step == STEP_WEEK
        vm.go_back()
        assert vm.state.step == STEP_CHOICE
        assert not vm.state.can_go_back

    async def test_preview_follows_valid_edits_and_survives_invalid_ones(
        self, async_session
    ):
        vm = _vm(async_session)
        await _flow_to(vm, STEP_MONTHS)
        first = vm.state.preview_calendar
        assert len(first.spec.months) == 12

        vm.set_month_count(4)
        second = vm.state.preview_calendar
        assert second is not first and len(second.spec.months) == 4

        vm.set_month_name(3, "")  # invalid: the grid keeps painting `second`
        assert vm.state.preview_calendar is second

        vm.set_month_name(3, "Хвостень")
        third = vm.state.preview_calendar
        assert third is not second
        assert third.spec.months[3].name == "Хвостень"


# ══════════════════════════ task 5.2 — draft semantics ═══════════════════════


class TestDraftSemantics:
    async def test_opening_without_a_draft_starts_at_the_choice(self, async_session):
        vm = _vm(async_session)
        await vm.begin()

        assert vm.state.step == STEP_CHOICE
        assert await CalendarSettingsService().load_draft(async_session) is None

    async def test_passing_week_stores_the_spec_with_defaults_and_next_stage(
        self, async_session
    ):
        service = CalendarSettingsService()
        vm = _vm(async_session, service)
        await vm.begin()
        vm.choose_kind(KIND_CUSTOM)
        await vm.try_advance()  # the choice itself is never drafted
        assert await service.load_draft(async_session) is None

        vm.set_week_length(3)  # the tail cut leaves the three first names…
        for index, name in enumerate(("Буд", "Ведь", "Творец")):
            vm.set_week_name(index, name)  # …which the user then renames
        await vm.try_advance()  # week → months writes the draft

        assert vm.state.step == STEP_MONTHS
        draft = await service.load_draft(async_session)
        assert draft is not None and draft.stage == DRAFT_STAGE_MONTHS
        assert draft.spec.week_names == ("Буд", "Ведь", "Творец")
        # the unclosed stages are stored as defaults (design D6)
        assert [m.name for m in draft.spec.months] == [
            DEFAULT_MONTH_NAMES[n] for n in range(1, 13)
        ]
        assert draft.spec.intercalary == ()
        # and it never warms the active calendar (spec «Черновик не греет…»)
        assert await _setting(async_session, CALENDAR_SETTINGS_KEY) is None
        assert isinstance(current_calendar(), StandardCalendar)

    async def test_each_passed_stage_repackages_the_draft_with_actual_form(
        self, async_session
    ):
        service = CalendarSettingsService()
        vm = _vm(async_session, service)
        await vm.begin()
        vm.choose_kind(KIND_STANDARD)  # preset game: user switches to custom
        vm.choose_kind(KIND_CUSTOM)
        await vm.try_advance()  # → week
        await vm.try_advance()  # → months (default week drafted)

        vm.set_month_count(2)
        vm.set_month_name(0, "Черновершь")
        vm.set_month_length(0, 20)
        vm.set_month_name(1, "Разливань")
        vm.set_month_length(1, 15)
        await vm.try_advance()  # → intercalary

        draft = await service.load_draft(async_session)
        assert draft.stage == STEP_INTERCALARY
        assert draft.spec.months == (
            MonthSpec("Черновершь", 20),
            MonthSpec("Разливань", 15),
        )
        assert draft.spec.week_names == STANDARD_WEEK_NAMES
        assert draft.spec.intercalary == ()

        vm.add_intercalary("Гром", 2)
        await vm.try_advance()  # → preview

        draft = await service.load_draft(async_session)
        assert draft.stage == DRAFT_STAGE_PREVIEW
        assert draft.spec.intercalary == (IntercalarySpec("Гром", 2),)

    async def test_reopening_continues_from_the_draft_prefilled(self, async_session):
        seed = CalendarDraft(
            spec=CalendarSpec(
                months=(MonthSpec("Черновершь", 20), MonthSpec("Разливань", 15)),
                week_names=("Буд", "Ведь", "Творец", "Грозник", "Светлай"),
                intercalary=(),
            ),
            stage=DRAFT_STAGE_MONTHS,
        )
        await CalendarSettingsService().save_draft(async_session, seed)

        vm = _vm(async_session)
        await vm.begin()

        state = vm.state
        assert state.step == STEP_MONTHS  # «продолжил с неё же»
        assert state.kind == KIND_CUSTOM
        assert state.week_names == seed.spec.week_names  # the stored week survived
        assert state.months == seed.spec.months
        assert state.can_advance
        assert isinstance(state.preview_calendar, CustomCalendar)
        assert state.preview_calendar.spec == seed.spec

    async def test_cancel_keeps_the_draft_for_the_next_opening(self, async_session):
        # Spec «Закрыл на середине — продолжил с неё же»: closing the wizard is
        # not a rollback — the draft survives until it is explicitly discarded.
        service = CalendarSettingsService()
        vm = _vm(async_session, service)
        await _flow_to(vm, STEP_WEEK)
        await vm.try_advance()  # week closes → the draft is stored

        stored_before = await _setting(async_session, CALENDAR_DRAFT_KEY)
        assert stored_before is not None

        vm.cancel()

        assert vm.state.step == STEP_MONTHS  # cancel neither moves nor unwinds
        assert await _setting(async_session, CALENDAR_DRAFT_KEY) == stored_before
        assert await _setting(async_session, CALENDAR_SETTINGS_KEY) is None

        # the contrast the task names explicitly: a real discard removes it
        await service.discard_draft(async_session)
        assert await service.load_draft(async_session) is None


# ═══════════════════════ task 5.3 — application intents ══════════════════════


class TestEmptyReportApplies:
    async def test_clean_game_applies_immediately_without_the_report(
        self, async_session
    ):
        service = CalendarSettingsService()
        vm = _vm(async_session, service)
        await vm.begin()
        succeeded: list[str] = []
        failed: list[str] = []
        vm.apply_succeeded.connect(lambda: succeeded.append("ok"))
        vm.apply_failed.connect(failed.append)

        await vm.apply()  # «Стандартный» from the choice screen, empty database

        assert succeeded == ["ok"] and failed == []
        assert await _setting(async_session, CALENDAR_SETTINGS_KEY) == (
            encode_calendar(StandardCalendar())
        )
        assert isinstance(current_calendar(), StandardCalendar)  # activated
        # from the menu the «seen» flag is nobody's business (spec «Флаг…»)
        assert await service.load_wizard_seen(async_session) is None

    async def test_first_entry_applies_draft_calendar_and_marks_the_flag(
        self, async_session
    ):
        service = CalendarSettingsService()
        await service.save_draft(
            async_session, CalendarDraft(spec=_CUSTOM_SPEC, stage=DRAFT_STAGE_PREVIEW)
        )
        vm = _vm(async_session, service, first_entry=True)
        await vm.begin()  # the draft pulls the flow straight to the preview
        assert vm.state.step == STEP_PREVIEW

        succeeded: list[str] = []
        vm.apply_succeeded.connect(lambda: succeeded.append("draft"))
        await vm.apply()  # no records at all — the empty report applies instantly

        assert succeeded == ["draft"]
        assert await _setting(async_session, CALENDAR_SETTINGS_KEY) == (
            encode_calendar(_CUSTOM)
        )
        assert await _setting(async_session, CALENDAR_DRAFT_KEY) is None
        assert await service.load_wizard_seen(async_session) == "1"
        assert isinstance(current_calendar(), CustomCalendar)


class TestReportScreen:
    async def test_nonempty_report_opens_screen_with_human_readable_lines(
        self, async_session
    ):
        await _add_event(
            async_session, "Бой у реки", date(2023, 1, 15), date(2023, 6, 1)
        )
        rating = RatingModel(start_date=date(2023, 4, 5), end_date=None, level=1)
        async_session.add(rating)
        await async_session.commit()
        rows_before = await _event_rows(async_session)

        vm = _vm(async_session)
        await _custom_months_on(vm)
        await vm.try_advance()  # months → intercalary
        await vm.try_advance()  # intercalary → preview
        assert vm.state.can_apply
        await vm.apply()

        state = vm.state
        assert state.step == STEP_REPORT
        assert state.report is not None and state.report.shift_count == 3
        # the dry run changed nothing (spec «Проверка ничего не меняет»)
        assert await _event_rows(async_session) == rows_before
        assert await _setting(async_session, CALENDAR_SETTINGS_KEY) is None

        assert state.report_lines == (
            ReportLine(
                record="Бой у реки",
                field="начало",
                old_date="15 Январь 2023",
                new_date="10 Медвежарь 2023",
            ),
            ReportLine(
                record="Бой у реки",
                field="конец",
                old_date="01 Июнь 2023",
                new_date="10 Травень 2023",
            ),
            # «безымянная таблица» — the rating row has no name column at all
            ReportLine(
                record=f"Рейтинг №{rating.id}",
                field="начало",
                old_date="05 Апрель 2023",
                new_date="10 Травень 2023",
            ),
        )

    async def test_report_line_carries_the_era_suffix_on_both_captions(
        self, async_session
    ):
        await _add_event(
            async_session, "Поход теней", date(300, 1, 15), None, start_bc=1
        )

        vm = _vm(async_session)
        await _custom_months_on(vm)
        await vm.try_advance()
        await vm.try_advance()
        await vm.apply()

        (line,) = vm.state.report_lines
        assert line.record == "Поход теней" and line.field == "начало"
        assert line.old_date == "15 Январь 300 г. до н.э."
        assert line.new_date == "10 Медвежарь 300 г. до н.э."

    async def test_new_intercalary_date_is_captioned_by_the_new_calendar(
        self, async_session
    ):
        # A coordinate stored under the old three-rule calendar, whose index the
        # target only survives by clamping to its last rule: the NEW caption must
        # read the target's rule names (design D10) while the OLD caption reads
        # the old calendar, which is still the active one on the report screen.
        old_custom = CustomCalendar(
            CalendarSpec(
                months=_CUSTOM_MONTHS,
                week_names=_CUSTOM_SPEC.week_names,
                intercalary=(
                    IntercalarySpec("Первый гром", 3),
                    IntercalarySpec("Второй гром", 3),
                    IntercalarySpec("Громовик", 3),
                ),
            )
        )
        set_current_calendar(old_custom)  # the menu preselects «custom» itself
        event = await _add_event(async_session, "Громовержец", date(5, 3, 1), None)
        await async_session.execute(
            EventModel.__table__.update()
            .where(EventModel.id == event.id)
            .values(start_coord=encode_coord(IntercalaryDay(5, 2)))
        )
        await async_session.commit()
        async_session.expunge_all()

        vm = _vm(async_session)
        await _custom_months_on(vm)
        await vm.try_advance()  # → intercalary
        vm.add_intercalary("Первый гром", 3)
        vm.add_intercalary("Второй гром", 3)  # the target keeps just two rules
        await vm.try_advance()  # → preview
        await vm.apply()

        (line,) = vm.state.report_lines
        assert line.record == "Громовержец" and line.field == "начало"
        assert line.old_date == "Громовик 5"  # the old calendar's third rule
        assert line.new_date == "Второй гром 5"  # the target's clamped landing

    async def test_confirm_transfer_promotes_moves_records_frees_draft(
        self, async_session
    ):
        service = CalendarSettingsService()
        await _add_event(
            async_session, "Бой у реки", date(2023, 1, 15), date(2023, 6, 1)
        )
        vm = _vm(async_session, service)
        await _custom_months_on(vm)
        await vm.try_advance()
        await vm.try_advance()
        await vm.apply()  # → the report screen
        # each passed stage of this very flow left a draft behind (task 5.2)
        assert await service.load_draft(async_session) is not None
        succeeded: list[str] = []
        vm.apply_succeeded.connect(lambda: succeeded.append("ok"))

        await vm.confirm_transfer()  # «Перенести и применить»

        assert succeeded == ["ok"]
        async_session.expunge_all()
        (row,) = await _event_rows(async_session)
        assert row.start_coord == encode_coord(MonthDay(2023, 1, 10))
        assert row.end_coord == encode_coord(MonthDay(2023, 3, 10))
        assert row.start_key == _TARGET_FORM.to_key(MonthDay(2023, 1, 10))
        assert row.end_key == _TARGET_FORM.to_key(MonthDay(2023, 3, 10))
        assert await _setting(async_session, CALENDAR_SETTINGS_KEY) == (
            encode_calendar(_TARGET_FORM)
        )
        assert await _setting(async_session, CALENDAR_DRAFT_KEY) is None
        assert isinstance(current_calendar(), CustomCalendar)
        assert vm.state.report is None

    async def test_cancel_from_report_changes_nothing_and_returns_home(
        self, async_session
    ):
        # The preset path with a report: February 30 is exactly what the
        # «Стандартный» calendar refuses to hold.
        event = await _add_event(
            async_session, "Несостоявшееся", date(2023, 1, 1), None
        )
        await async_session.execute(
            EventModel.__table__.update()
            .where(EventModel.id == event.id)
            .values(start_coord=encode_coord(MonthDay(2023, 2, 30)))
        )
        await async_session.commit()
        rows_before = await _event_rows(async_session)

        vm = _vm(async_session)
        await vm.begin()  # a preset game: «Стандартный» preselected, apply enabled
        await vm.apply()  # the report screen opened right from the CHOICE
        assert vm.state.step == STEP_REPORT
        (line,) = vm.state.report_lines
        assert line.record == "Несостоявшееся"
        assert line.old_date == "30 Февраль 2023"
        assert line.new_date == "28 Февраль 2023"

        vm.cancel_report()  # «Отменить» — ничего

        assert vm.state.step == STEP_CHOICE  # back where «Применить» was pressed
        assert vm.state.report is None and vm.state.report_lines == ()
        async_session.expunge_all()
        assert await _event_rows(async_session) == rows_before
        assert await _setting(async_session, CALENDAR_SETTINGS_KEY) is None

    async def test_apply_error_reports_the_reason_and_keeps_the_state(
        self, async_session, monkeypatch
    ):
        await _add_event(async_session, "Бой у реки", date(2023, 1, 15), None)
        service = CalendarSettingsService()

        async def boom(*args, **kwargs):
            raise RuntimeError("диск отказал")

        monkeypatch.setattr(service, "promote_draft", boom)
        vm = _vm(async_session, service)
        await _custom_months_on(vm)
        await vm.try_advance()
        await vm.try_advance()
        succeeded: list[str] = []
        failed: list[str] = []
        vm.apply_succeeded.connect(lambda: succeeded.append("ok"))
        vm.apply_failed.connect(failed.append)

        await vm.apply()  # the dry run works — the screen opens
        assert vm.state.step == STEP_REPORT
        await vm.confirm_transfer()  # the promote falls over

        assert succeeded == [] and failed == ["диск отказал"]
        # «окно с причиной, состояние остаётся»: the screen and its list live on
        assert vm.state.step == STEP_REPORT
        assert vm.state.report is not None and len(vm.state.report_lines) == 1

    async def test_guarded_intents_refuse_misuse(self, async_session):
        vm = _vm(async_session)
        await _flow_to(vm, STEP_WEEK)
        succeeded: list[str] = []
        failed: list[str] = []
        vm.apply_succeeded.connect(lambda: succeeded.append("ok"))
        vm.apply_failed.connect(failed.append)

        await vm.apply()  # not an applicable screen: nothing at all happens
        await vm.confirm_transfer()  # not a report screen: silence
        vm.cancel_report()  # nothing to cancel

        assert succeeded == [] and failed == [] and vm.state.step == STEP_WEEK

    async def test_corrupted_preview_refuses_application(self, async_session):
        # Only a validated intercalary screen can OPEN the preview, so a form
        # corrupted behind the dialog's back (programmatic misuse) is caught by
        # the guard «a corrupted preview must never reach the button».
        vm = _vm(async_session)
        await _flow_to(vm, STEP_PREVIEW)
        vm.set_month_name(0, "")  # the form rots while the screen stays open
        assert vm.state.preview_calendar.spec.months[0].name == "Январь"

        succeeded: list[str] = []
        failed: list[str] = []
        vm.apply_succeeded.connect(lambda: succeeded.append("ok"))
        vm.apply_failed.connect(failed.append)
        await vm.apply()

        assert succeeded == [] and failed == []
        assert vm.state.step == STEP_PREVIEW  # no report screen opened either
