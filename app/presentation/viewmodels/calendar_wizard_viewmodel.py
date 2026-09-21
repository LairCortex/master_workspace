"""CalendarWizardViewModel — the C4 wizard's flow, draft and application (designs D5/D6/D9/D10).

A frozen :class:`CalendarWizardState` snapshots everything the modal dialog
(group 6) has to show: the current step, the partial custom-form (week names,
months, intercalary rules), the ``can_advance``/``can_apply`` button gates, the
:class:`~app.domain.game_calendar.SpecProblem` list of the current step with
its Russian phrases (rendered through :mod:`app.presentation.utils.calendar_warnings`,
the domain never localizes), the pending shift report and its human-readable
lines, and the last-valid preview calendar.

Business rules live here, not in the dialog (the repo's review rule):

* every step of the custom flow is validated by the domain's ``validate()`` on
  the *partial* spec — stages the user has not closed stay at their defaults,
  so a broken week cannot be left, and a dangling intercalary rule (its host
  month was trimmed on the «Месяцы» screen) keeps «Далее» inactive while the
  rule itself is silently KEPT in the form (spec «Экран „Месяцы“»);
* the preview calendar follows the spec «Предпросмотр обновляется только на
  валидное состояние формы» — it is rebuilt only while the form validates, an
  invalid edit leaves the last valid grid on screen;
* passing a stage writes the draft through the service (spec
  «Черновик мастера»): the whole assembled spec with defaults for the unclosed
  stages plus the index of the first unclosed stage (design D6);
* application reuses the C2 machinery — ``apply_to_records(dry_run=True)``
  produces the report, an empty report applies immediately, a non-empty one
  opens the report screen whose «Перенести и применить» promotes through the
  atomic :meth:`CalendarSettingsService.promote_draft` (design D9); an error
  there leaves the state untouched (spec requirement «Первый вход…»).

Report lines stay presentational (design D10): the domain's ``ShiftReport`` is
untouched, this view model resolves ``(table, row_id)`` to a readable record
label and formats both date sides the way ``format_game_date`` does — the new
coordinate printed through the calendar being applied so it matches the
preview the user just saw.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.calendar_settings_service import CalendarSettingsService
from app.domain.game_calendar import (
    DEFAULT_MONTH_NAMES,
    DRAFT_STAGE_INTERCALARY,
    DRAFT_STAGE_MONTHS,
    DRAFT_STAGE_PREVIEW,
    DRAFT_STAGE_WEEK,
    CalendarDraft,
    CalendarSpec,
    CustomCalendar,
    DateField,
    GameCalendar,
    GameCoord,
    IntercalaryDay,
    IntercalarySpec,
    MonthSpec,
    ShiftReport,
    SpecProblem,
    StandardCalendar,
    current_calendar,
    validate,
)
from app.infrastructure.db.models import (
    CharacterModel,
    EventModel,
    ItemModel,
    LocationModel,
    OrganizationModel,
    RatingModel,
)
from app.presentation.utils.calendar_warnings import corruption_reason_phrase
from app.presentation.utils.date_utils import STANDARD_WEEK_NAMES, format_game_date

# ── kinds and steps ─────────────────────────────────────────────────────────

#: Wizard choice between the two calendar kinds (screen «выбор»).
KIND_STANDARD = "standard"
KIND_CUSTOM = "custom"

#: Wizard steps. The custom-flow step ids double as the draft stage codes so a
#: ``CalendarDraft.stage`` maps straight back onto :attr:`CalendarWizardState.step`.
STEP_CHOICE = "choice"
STEP_WEEK = DRAFT_STAGE_WEEK
STEP_MONTHS = DRAFT_STAGE_MONTHS
STEP_INTERCALARY = DRAFT_STAGE_INTERCALARY
STEP_PREVIEW = DRAFT_STAGE_PREVIEW
STEP_REPORT = "report"

#: The custom flow in «Далее» order; leaving a stage stores the following one
#: as the draft stage (design D6: the stage is the first NOT YET closed screen).
_CUSTOM_FLOW: tuple[str, ...] = (STEP_WEEK, STEP_MONTHS, STEP_INTERCALARY, STEP_PREVIEW)

# ── defaults standing in for the unclosed stages (design D6) ────────────────

#: New-month defaults of the «Месяцы» screen (spec «Экран „Месяцы“»).
_DEFAULT_MONTH_NAME = "Месяц"
_DEFAULT_MONTH_LENGTH = 30

#: Common-Gregorian month lengths — the «отправная сетка» of a first custom
#: assembly (years 1…9999 of the standard preset, February at its non-leap 28).
_COMMON_GREGORIAN_LENGTHS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

#: The partial-spec default for months: the twelve Gregorian months with the
#: domain-owned Russian names (never read back as a localization by the domain).
_DEFAULT_MONTHS: tuple[MonthSpec, ...] = tuple(
    MonthSpec(DEFAULT_MONTH_NAMES[number], length)
    for number, length in enumerate(_COMMON_GREGORIAN_LENGTHS, start=1)
)

#: The partial-spec default for a first custom week (piece C3b, design D2).
_DEFAULT_WEEK_NAMES: tuple[str, ...] = tuple(STANDARD_WEEK_NAMES)

# ── report caption vocabulary (presentation, design D10) ────────────────────

#: The six dated tables the C2 traversal reports on, as ORM models by key.
_TABLE_MODELS = {
    "events": EventModel,
    "organizations": OrganizationModel,
    "characters": CharacterModel,
    "items": ItemModel,
    "locations": LocationModel,
    "ratings": RatingModel,
}

#: Caption of a record without a (non-empty) name: «<таблица> №<id>».
_TABLE_CAPTIONS = {
    "events": "Событие",
    "organizations": "Организация",
    "characters": "Персонаж",
    "items": "Предмет",
    "locations": "Локация",
    "ratings": "Рейтинг",
}

#: Caption of a report line's date slot (spec «поле (начало/конец)»).
_FIELD_CAPTIONS = {DateField.START: "начало", DateField.END: "конец"}

#: The date caption of the BC era, the same suffix ``format_game_date`` appends.
_BC_SUFFIX = " г. до н.э."


@dataclass(frozen=True)
class ReportLine:
    """One row of the report screen with human-readable captions only."""

    record: str
    field: str
    old_date: str
    new_date: str


@dataclass(frozen=True)
class CalendarWizardState:
    """Everything the dialog renders, recomputed from the view model's internals.

    Frozen and value-comparable so the view's ``state_changed`` handler and the
    tests can assert against whole snapshots; it carries the same ``SpecProblem``
    codes the domain produced plus their Russian phrases for display.
    """

    step: str
    kind: str
    week_names: tuple[str, ...]
    months: tuple[MonthSpec, ...]
    intercalary: tuple[IntercalarySpec, ...]
    can_advance: bool
    can_apply: bool
    can_go_back: bool
    problems: tuple[SpecProblem, ...]
    problem_phrases: tuple[str, ...]
    report: ShiftReport | None
    report_lines: tuple[ReportLine, ...]
    preview_calendar: GameCalendar


def _format_date_in(calendar: GameCalendar, coord: GameCoord, is_bc: bool) -> str:
    """Format ``coord`` with ``calendar``'s own month/rule names.

    The caption follows :func:`~app.presentation.utils.date_utils.format_game_date`
    bit-for-bit ('dd Month yyyy[ г. до н.э.]', 'Rule yyyy[ …]' for intercalary
    days) but reads the names of the calendar *being applied*: while the report
    screen is up the active calendar is still the old one, and a new coordinate
    must read exactly as the preview grid the user just watched showed it.
    """
    era = _BC_SUFFIX if is_bc else ""
    if isinstance(coord, IntercalaryDay):
        rule = calendar.spec.intercalary[coord.index]  # type: ignore[attr-defined]
        return f"{rule.name} {coord.year}{era}"
    name = calendar.month_names.get(coord.month, str(coord.month))
    return f"{coord.day:02d} {name} {coord.year}{era}"


class CalendarWizardViewModel(QObject):
    """Qt transport layer of the calendar wizard: state out, intents in.

    The dialog (task group 6) owns only widgets and buttons: it reads
    :attr:`state`, connects the three lifecycle signals, and calls the intents
    below.  The service and the session arrive through the constructor so the
    same class serves the first-entry modal and the «Настройки → Календарь…»
    entry, with ``first_entry`` deciding whether a successful application closes
    the «seen» flag (design D8/D9).
    """

    state_changed = Signal()
    #: A successful application (also an empty-report immediate one): the dialog
    #: closes the wizard (spec «Применение… мастер закрылся сразу»).
    apply_succeeded = Signal()
    #: An application attempt failed: the argument is the displayable reason;
    #: the wizard state is left untouched (spec «Ошибки применения…»).
    apply_failed = Signal(str)

    def __init__(
        self,
        session: AsyncSession,
        calendar_service: CalendarSettingsService,
        *,
        first_entry: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._service = calendar_service
        self._first_entry = first_entry

        # Flow: the menu entry preselects the CURRENT calendar kind (spec
        # «Вход из меню доступен всегда»); a new game opens on the preset.
        self._step = STEP_CHOICE
        self._kind = (
            KIND_CUSTOM if isinstance(current_calendar(), CustomCalendar) else KIND_STANDARD
        )

        # The partial custom-form: unclosed stages hold their defaults (D6), so
        # the week/months/intercalary screens edit real defaults from the start.
        self._week_names: tuple[str, ...] = _DEFAULT_WEEK_NAMES
        self._months: tuple[MonthSpec, ...] = _DEFAULT_MONTHS
        self._intercalary: tuple[IntercalarySpec, ...] = ()

        # Report state (only non-default on the «Отчёт» screen).
        self._report: ShiftReport | None = None
        self._report_lines: tuple[ReportLine, ...] = ()
        self._report_return_step = STEP_CHOICE
        self._pending_target: GameCalendar | None = None

        # The last valid preview; on entry that is the calendar the game itself
        # is living on (spec «мастер, предвыбрав текущий календарь»).
        self._preview_calendar: GameCalendar = current_calendar()

    # ── state ───────────────────────────────────────────────────────────────

    @property
    def state(self) -> CalendarWizardState:
        """The frozen snapshot every dialog repaint reads.

        Validation runs against the whole current form on every read, so the
        «Далее» gate and the problem phrases can never lag behind an edit.
        """
        problems = tuple(validate(self._spec()))
        in_build_step = self._step in (STEP_WEEK, STEP_MONTHS, STEP_INTERCALARY)
        return CalendarWizardState(
            step=self._step,
            kind=self._kind,
            week_names=self._week_names,
            months=self._months,
            intercalary=self._intercalary,
            can_advance=(self._step == STEP_CHOICE and self._kind == KIND_CUSTOM)
            or (in_build_step and not problems),
            # «Применить» is available on the choice screen for the preset and on
            # the preview — that form is already a built calendar there (only a
            # validated intercalary screen can open it); a programmatic misuse
            # of a corrupted form is refused by :meth:`apply`'s own guard.
            can_apply=(self._step == STEP_CHOICE and self._kind == KIND_STANDARD)
            or self._step == STEP_PREVIEW,
            can_go_back=self._step in _CUSTOM_FLOW,
            problems=problems,
            problem_phrases=_problem_phrases(problems),
            report=self._report,
            report_lines=self._report_lines,
            preview_calendar=self._preview_calendar,
        )

    async def begin(self) -> None:
        """Open the wizard: continue from the stored draft, or start at the choice.

        A draft (read through the service, a damaged one already reduced to
        ``None``) decides the whole opening position: the flow resumes at the
        draft's first unclosed stage, prefilled with its spec, and the kind is
        custom by construction (spec «Черновик мастера»).  Without a draft the
        view stays on the kind-choice screen with the preselected kind.
        """
        draft = await self._service.load_draft(self._session)
        if draft is not None:
            self._kind = KIND_CUSTOM
            self._week_names = tuple(draft.spec.week_names)
            self._months = tuple(draft.spec.months)
            self._intercalary = tuple(draft.spec.intercalary)
            self._step = draft.stage
            self._recompute_preview()
        self.state_changed.emit()

    # ── form intents ────────────────────────────────────────────────────────

    def choose_kind(self, kind: str) -> None:
        """Select «Стандартный»/«Кастомный» on the choice screen."""
        if kind == self._kind:
            return
        self._kind = kind
        self._recompute_preview()
        self.state_changed.emit()

    def set_week_length(self, length: int) -> None:
        """Resize the week: growing appends empty fields, shrinking drops the tail."""
        length = max(length, 0)
        names = list(self._week_names)
        if length < len(names):
            del names[length:]
        else:
            names.extend("" for _ in range(length - len(names)))
        self._week_names = tuple(names)
        self._changed()

    def set_week_name(self, index: int, name: str) -> None:
        """Type one week-day name; an index outside the week is a no-op."""
        if not 0 <= index < len(self._week_names):
            return
        names = list(self._week_names)
        names[index] = name
        self._week_names = tuple(names)
        self._changed()

    def set_month_count(self, count: int) -> None:
        """Resize the months: new months appear as «Месяц N»/30, removed ones are
        the tail; intercalary rules pointing past the new tail are KEPT — the
        user deals with them on their own screen (spec: «чужие правила молча НЕ
        удаляются»)."""
        count = max(count, 0)
        months = list(self._months)
        while len(months) > count:
            months.pop()
        while len(months) < count:
            months.append(MonthSpec(_free_month_name(months), _DEFAULT_MONTH_LENGTH))
        self._months = tuple(months)
        self._changed()

    def set_month_name(self, index: int, name: str) -> None:
        """Edit one month name; an index outside the list is a no-op."""
        if not 0 <= index < len(self._months):
            return
        months = list(self._months)
        months[index] = _replace_month(months[index], name=name)
        self._months = tuple(months)
        self._changed()

    def set_month_length(self, index: int, length: int) -> None:
        """Edit one month length; an index outside the list is a no-op."""
        if not 0 <= index < len(self._months):
            return
        months = list(self._months)
        months[index] = _replace_month(months[index], length=length)
        self._months = tuple(months)
        self._changed()

    def add_intercalary(self, name: str = "", after_month: int | None = None) -> None:
        """Append an intercalary rule; its host defaults to the last month (the
        combo's preselection), keeping the list order as the slot order."""
        host = len(self._months) if after_month is None else after_month
        self._intercalary = (*self._intercalary, IntercalarySpec(name, host))
        self._changed()

    def remove_intercalary(self, index: int) -> None:
        """Delete one rule; an index outside the list is a no-op."""
        if not 0 <= index < len(self._intercalary):
            return
        rules = list(self._intercalary)
        del rules[index]
        self._intercalary = tuple(rules)
        self._changed()

    def move_rule(self, index: int, delta: int) -> None:
        """Move a rule up/down: the list order IS the position order (spec
        «порядок списка значим»); anything outside the list is a no-op."""
        target = index + delta
        if not (0 <= index < len(self._intercalary) and 0 <= target < len(self._intercalary)):
            return
        rules = list(self._intercalary)
        rules[index], rules[target] = rules[target], rules[index]
        self._intercalary = tuple(rules)
        self._changed()

    # ── flow intents ────────────────────────────────────────────────────────

    async def try_advance(self) -> None:
        """«Далее»: leave a validated stage forward, storing the draft.

        Blocked while the current partial spec is invalid (the button mirrors
        ``can_advance``, this guard just makes a stray call harmless).  Passing
        the choice screen opens the custom flow without a draft yet — the
        draft exists only once a custom stage closes (design D6).
        """
        if not self.state.can_advance:
            return
        if self._step == STEP_CHOICE:
            self._step = STEP_WEEK
            self.state_changed.emit()
            return
        self._step = _CUSTOM_FLOW[_CUSTOM_FLOW.index(self._step) + 1]
        await self._service.save_draft(self._session, CalendarDraft(self._spec(), self._step))
        self.state_changed.emit()

    def go_back(self) -> None:
        """«Назад» one screen; before week (and past preview) there is nowhere back."""
        if self._step not in _CUSTOM_FLOW:
            return
        position = _CUSTOM_FLOW.index(self._step)
        self._step = STEP_CHOICE if position == 0 else _CUSTOM_FLOW[position - 1]
        self.state_changed.emit()

    # ── application intents ─────────────────────────────────────────────────

    async def apply(self) -> None:
        """«Применить»: check the calendar, then apply or open the report screen.

        The check is the C2 dry run over the six dated tables (nothing changes).
        A clean report applies through the same atomic promotion right away
        (spec scenario «Пустой отчёт не плодит экран»); anything else parks on
        the report screen with the transfer list.
        """
        if not self.state.can_apply:
            return
        target = self._target_calendar()
        if target is None:  # a corrupted preview must never reach the button
            return
        report = await self._service.apply_to_records(self._session, target, dry_run=True)
        self._pending_target = target
        if report.shift_count == 0:
            await self._promote(target)
            return
        self._report_return_step = self._step
        self._report = report
        self._report_lines = await self._report_lines_for(report, target)
        self._step = STEP_REPORT
        self.state_changed.emit()

    async def confirm_transfer(self) -> None:
        """«Перенести и применить»: the one atomic promote the report screen promises."""
        if self._step != STEP_REPORT or self._pending_target is None:
            return
        await self._promote(self._pending_target)

    def cancel_report(self) -> None:
        """The report screen's «Отменить» — go back without having applied anything."""
        if self._step != STEP_REPORT:
            return
        self._step = self._report_return_step
        self._report = None
        self._report_lines = ()
        self._pending_target = None
        self.state_changed.emit()

    def cancel(self) -> None:
        """Close the wizard. By contract of spec «Черновик мастера» a closed flow
        keeps its draft for the next opening, so there is deliberately nothing to
        undo, discard or write here."""

    # ── internals ───────────────────────────────────────────────────────────

    def _spec(self) -> CalendarSpec:
        return CalendarSpec(
            months=self._months,
            week_names=self._week_names,
            intercalary=self._intercalary,
        )

    def _target_calendar(self) -> GameCalendar | None:
        """The calendar «Применить» would apply, or ``None`` if the form is not a
        calendar (the preview holds its last valid view meanwhile)."""
        if self._kind == KIND_STANDARD:
            return StandardCalendar()
        try:
            return CustomCalendar(self._spec())
        except ValueError:
            return None

    def _recompute_preview(self) -> None:
        """Refresh the preview calendar on the current form.

        A valid custom form rebuilds its grid's calendar; an invalid one keeps
        the last valid calendar (spec «Невалидная форма не рисует мусор»); the
        preset's preview is always the clean preset it would apply.
        """
        if self._kind == KIND_STANDARD:
            self._preview_calendar = StandardCalendar()
            return
        try:
            self._preview_calendar = CustomCalendar(self._spec())
        except ValueError:
            return

    def _changed(self) -> None:
        self._recompute_preview()
        self.state_changed.emit()

    async def _promote(self, target: GameCalendar) -> None:
        """The single atomic promote (design D9), with the failure branch of the
        «Первый вход» requirement: the reason goes out as a signal, the wizard
        keeps its state so the user can still react."""
        try:
            await self._service.promote_draft(
                self._session, target, mark_wizard_seen=self._first_entry
            )
        except Exception as exc:
            self.apply_failed.emit(str(exc))
            return
        self._report = None
        self._report_lines = ()
        self._pending_target = None
        self.apply_succeeded.emit()

    async def _report_lines_for(
        self, report: ShiftReport, target: GameCalendar
    ) -> tuple[ReportLine, ...]:
        """Turn the domain report into display rows (design D10): per entry the
        record's own name (else «<таблица> №<id>»), the slot caption, and old/new
        dates in the old (still active) and new (being applied) calendars."""
        names = await self._record_names(report)
        lines: list[ReportLine] = []
        for entry in report.records:
            record = names.get((entry.table, entry.row_id))
            if not record:
                record = f"{_TABLE_CAPTIONS[entry.table]} №{entry.row_id}"
            old, old_bc = entry.old
            new, new_bc = entry.new
            lines.append(
                ReportLine(
                    record=record,
                    field=_FIELD_CAPTIONS[entry.field],
                    old_date=format_game_date(old, is_bc=old_bc),
                    new_date=_format_date_in(target, new, new_bc),
                )
            )
        return tuple(lines)

    async def _record_names(self, report: ShiftReport) -> dict[tuple[str, int], str]:
        """Read the display names of the records one report touches — one
        ``GET`` per distinct row of the (already traversed) report."""
        names: dict[tuple[str, int], str] = {}
        for table, row_id in sorted({(e.table, e.row_id) for e in report.records}):
            row = await self._session.get(_TABLE_MODELS[table], row_id)
            name = getattr(row, "name", None)
            if row is not None and name:
                names[(table, row_id)] = name
        return names


def _replace_month(
    month: MonthSpec, *, name: str | None = None, length: int | None = None
) -> MonthSpec:
    """Copy a month spec with one field replaced (``MonthSpec`` is frozen)."""
    return MonthSpec(
        name=month.name if name is None else name,
        length=month.length if length is None else length,
    )


def _free_month_name(months: list[MonthSpec]) -> str:
    """«Месяц N» with the first number N no current month carries (spec: «со
    свободным номером N»)."""
    taken = {month.name for month in months}
    number = 1
    while f"{_DEFAULT_MONTH_NAME} {number}" in taken:
        number += 1
    return f"{_DEFAULT_MONTH_NAME} {number}"


def _problem_phrases(problems: tuple[SpecProblem, ...]) -> tuple[str, ...]:
    """Russian phrases of the form problems, deduped while keeping the order
    (several empty month names are one sentence to the user, as in
    :func:`~app.presentation.utils.calendar_warnings.calendar_corruption_body`)."""
    phrases: list[str] = []
    for problem in problems:
        phrase = corruption_reason_phrase(problem.code)
        if phrase not in phrases:
            phrases.append(phrase)
    return tuple(phrases)
