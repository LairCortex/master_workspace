"""CalendarWizardDialog — widget tests for the wizard modal (task group 6).

The dialog is viewmodel-oriented, so these tests click widgets and assert the
screens, gates, captions and storage the frozen state dictates — never
re-implementing flow logic here.  Every test drives the dialog exactly like
the group-7 wiring will (radios, spins, fields, row buttons, footer) and uses
the ``wait_idle()`` seam for the fire-and-read intents, on the real service
over the in-memory aiosqlite session.

Scenario map (spec calendar-wizard, tasks 6.1–6.4):
* 6.1 — the stacked screens «выбор → неделя → месяцы → вставные дни →
  предпросмотр», the Назад/Далее/Применить/Отменить gates, the inert preview
  grid (era hidden, cells dead, navigation alive) opened on the current game
  date with the year-1 fallback, and draft continuation through ``begin``;
* 6.2 — the week spin 2…168 with the empty-tail grow / tail drop / seven-name
  prefill, the Gregorian months prefill, «Месяц N»/30 additions, the tail
  drop inside the scroll rows, the empty-name block;
* 6.3 — the intercalary list with delete/up/down, the host preselect and the
  honored explicit host, order-is-the-positions preview chips, the report
  with record names and its «Отменить»/«Перенести и применить», the
  empty-report skip and the failed-apply window;
* 6.4 — the catalog skin (chrome root, field/title/status roles, live QSS
  push) and a full wizard walk with the theme switched off.
"""
from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtWidgets import QDialog, QLabel, QScrollArea
from sqlalchemy import select

from app.application.services.calendar_settings_service import (
    CALENDAR_SETTINGS_KEY,
    CalendarSettingsService,
)
from app.domain.game_calendar import (
    CALENDAR_DRAFT_KEY,
    CalendarDraft,
    CalendarSpec,
    CustomCalendar,
    DRAFT_STAGE_MONTHS,
    MonthDay,
    MonthSpec,
    StandardCalendar,
    current_calendar,
    encode_calendar,
    encode_coord,
    reset_current_calendar,
    set_current_calendar,
)
from app.infrastructure.db.models import EventModel, GameSettingsModel
from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation.theme import ThemeRuntime
from app.presentation.theme.compiler import tokens_file_path
from app.presentation.utils.date_utils import STANDARD_WEEK_NAMES
from app.presentation.viewmodels.calendar_wizard_viewmodel import (
    STEP_CHOICE,
    STEP_INTERCALARY,
    STEP_MONTHS,
    STEP_PREVIEW,
    STEP_REPORT,
    STEP_WEEK,
    CalendarWizardViewModel,
)
from app.presentation.views import calendar_wizard
from app.presentation.views.calendar_grid import (
    GameCalendarCell,
    GameCalendarGrid,
    GameCalendarIntercalaryChip,
)
from app.presentation.views.calendar_wizard import (
    APPLY_ERROR_TITLE,
    WEEK_LENGTH_MAX,
    WEEK_LENGTH_MIN,
    WIZARD_TITLE,
    CalendarWizardDialog,
)

# ── fixtures / helpers ───────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh_active_calendar():
    """The active calendar is a process global the wizard swaps around."""
    reset_current_calendar()
    yield
    reset_current_calendar()


@pytest.fixture(autouse=True)
def _qt(qapp):
    yield


#: A three-month game where «today's» September cannot exist at all.
_SMALL_CUSTOM = CustomCalendar(
    CalendarSpec(
        months=(MonthSpec("Таяль", 10), MonthSpec("Колодень", 10), MonthSpec("Гребень", 10)),
        week_names=("А", "Б", "В"),
    )
)

_CUSTOM_ORDER = (STEP_WEEK, STEP_MONTHS, STEP_INTERCALARY, STEP_PREVIEW)


def _vm(session, service=None, *, first_entry: bool = False) -> CalendarWizardViewModel:
    return CalendarWizardViewModel(
        session, service or CalendarSettingsService(), first_entry=first_entry
    )


def _dialog(qtbot, vm, theme=None) -> CalendarWizardDialog:
    dlg = CalendarWizardDialog(vm, theme=theme)
    qtbot.addWidget(dlg)
    return dlg


async def _walk_to(dialog: CalendarWizardDialog, target_step: str) -> None:
    """Click the real buttons from the choice screen to ``target_step`` on the
    untouched custom defaults (a valid form at every stage)."""
    dialog._custom_radio.click()
    for _ in range(_CUSTOM_ORDER.index(target_step) + 1):
        dialog._next_button.click()
        await dialog.wait_idle()
    assert dialog._stack.currentWidget() is dialog._pages[target_step]


async def _custom_months_3x10_on(dialog: CalendarWizardDialog) -> None:
    """Stand on «Месяцы» with the rows rebuilt as the 3×10 custom set — the
    calendar the report tests apply (the view model test twin, dialog clicks)."""
    await _walk_to(dialog, STEP_MONTHS)
    dialog._month_count_spin.setValue(3)
    for index, (name, length) in enumerate(
        (("Медвежарь", 10), ("Ледокол", 10), ("Травень", 10))
    ):
        name_edit, length_spin = dialog._month_rows[index]
        name_edit.setText(name)
        length_spin.setValue(length)


async def _add_event(session, name: str, start, end) -> EventModel:
    event = EventModel(name=name, start_date=start, end_date=end)
    session.add(event)
    await session.commit()
    return event


async def _setting(session, key: str) -> str | None:
    return (
        await session.execute(
            select(GameSettingsModel.value).where(GameSettingsModel.key == key)
        )
    ).scalars().first()


async def _event_dates(session):
    return (
        await session.execute(
            select(
                EventModel.__table__.c.start_date,
                EventModel.__table__.c.end_date,
            )
        )
    ).one()


async def _event_coords(session):
    session.expunge_all()  # the promote expired identity maps; re-read the row
    return (
        await session.execute(
            select(
                EventModel.__table__.c.start_coord,
                EventModel.__table__.c.end_coord,
            )
        )
    ).one()


def grid_page(grid: GameCalendarGrid) -> tuple[int, int]:
    """(year, 1-based month) the preview grid currently shows."""
    return grid._year_spin.value(), grid._month_combo.currentIndex() + 1


def chip_texts(grid: GameCalendarGrid) -> list[str]:
    return [chip.text() for chip in grid.findChildren(GameCalendarIntercalaryChip)]


def iter_parents(widget):
    while widget is not None:
        yield widget
        widget = widget.parentWidget()


# ════════════════════════ task 6.1 — the stacked flow ════════════════════════


class TestStepNavigation:
    async def test_choice_gates_buttons_and_walks_the_stack(
        self, async_session, qtbot
    ):
        dlg = _dialog(qtbot, _vm(async_session))
        await dlg.begin()

        assert dlg.windowTitle() == WIZARD_TITLE
        assert dlg._stack.currentWidget() is dlg._pages[STEP_CHOICE]
        assert dlg._standard_radio.isChecked()  # a preset game preselects it
        assert dlg._apply_button.isEnabled()
        assert not dlg._next_button.isEnabled()  # standard: no build flow
        assert not dlg._back_button.isEnabled()
        assert dlg._footer.isVisibleTo(dlg)

        dlg._custom_radio.click()
        assert dlg._next_button.isEnabled()
        assert not dlg._apply_button.isEnabled()

        for target in _CUSTOM_ORDER:
            dlg._next_button.click()
            await dlg.wait_idle()
            assert dlg._stack.currentWidget() is dlg._pages[target]
            assert dlg._back_button.isEnabled()

        # On the preview the flow moves through «Применить», not «Далее».
        assert dlg._apply_button.isEnabled()
        assert not dlg._next_button.isEnabled()

        dlg._back_button.click()
        assert dlg._stack.currentWidget() is dlg._pages[STEP_INTERCALARY]

    async def test_cancel_closes_and_keeps_the_draft_for_the_next_open(
        self, async_session, qtbot
    ):
        dlg = _dialog(qtbot, _vm(async_session))
        await dlg.begin()
        await _walk_to(dlg, STEP_MONTHS)  # week closed → the draft exists

        dlg._cancel_button.click()

        assert dlg.result() == QDialog.DialogCode.Rejected
        # spec «Черновик мастера»: closing is not a rollback
        assert await _setting(async_session, CALENDAR_SETTINGS_KEY) is None
        assert await _setting(async_session, CALENDAR_DRAFT_KEY) is not None

    async def test_reopening_opens_on_the_draft_screen_prefilled(
        self, async_session, qtbot
    ):
        first = _dialog(qtbot, _vm(async_session))
        await first.begin()
        await _walk_to(first, STEP_MONTHS)
        first._cancel_button.click()

        again = _dialog(qtbot, _vm(async_session))
        await again.begin()

        # spec scenario «Закрыл на середине — продолжил с неё же»
        assert again._stack.currentWidget() is again._pages[STEP_MONTHS]
        assert again._month_count_spin.value() == 12  # the stored defaults…
        assert again._month_rows[0][0].text() == "Январь"  # …are preloaded

    async def test_preview_is_the_inert_grid_opened_on_the_current_game_date(
        self, async_session, qtbot
    ):
        dlg = _dialog(qtbot, _vm(async_session))
        await dlg.begin()

        grid = dlg._preview
        assert isinstance(grid, GameCalendarGrid)
        assert not grid._bc_check.isVisible()  # show_era=False
        cells = [cell for cell in grid.findChildren(GameCalendarCell) if cell.text()]
        assert cells and all(not cell.isEnabled() for cell in cells)  # inert

        # «текущая игровая дата»: today projected into the assembled preset —
        # its page shown and its very cell pre-filled (clicking it inertly
        # would emit nothing, but the pre-fill itself is the placement).
        today = date.today()
        assert grid_page(grid) == (today.year, today.month)
        assert grid.selection() == MonthDay(today.year, today.month, today.day)

        # navigation by months and years stays alive on the preview.
        pages: list = []
        grid.page_changed.connect(lambda y, m: pages.append((y, m)))
        grid._next_btn.click()
        assert pages == [(today.year, today.month % 12 + 1)]
        # …and a repaint of another form state never yanks the page back
        dlg._custom_radio.click()
        assert grid_page(grid) == (today.year, today.month % 12 + 1)

    async def test_preview_falls_back_to_year_one_when_today_does_not_fit(
        self, async_session, qtbot
    ):
        # The game lives on a three-month calendar; «today's» September cannot
        # exist there → the grid simply opens on year 1 (spec «иначе год 1»).
        set_current_calendar(_SMALL_CUSTOM)

        dlg = _dialog(qtbot, _vm(async_session))  # the menu preselects «custom»

        assert grid_page(dlg._preview) == (1, 1)
        assert dlg._preview.selection() is None

    async def test_draft_resume_replaces_the_opening_page(
        self, async_session, qtbot
    ):
        # The dialog is built on the preset («today» fits), the draft then
        # repoints the preview at a three-month assembly where September
        # cannot exist → the opening placement is re-evaluated to year 1.
        await CalendarSettingsService().save_draft(
            async_session,
            CalendarDraft(spec=_SMALL_CUSTOM.spec, stage=DRAFT_STAGE_MONTHS),
        )
        dlg = _dialog(qtbot, _vm(async_session))

        assert grid_page(dlg._preview) != (1, 1)  # preset: «today's» page

        await dlg.begin()

        assert dlg._stack.currentWidget() is dlg._pages[STEP_MONTHS]
        assert grid_page(dlg._preview) == (1, 1)
        assert dlg._preview.selection() is None

    async def test_the_whole_flow_never_moves_the_active_calendar(
        self, async_session, qtbot
    ):
        # The preview's global swap (``_paint_preview``) must be invisible to
        # the game: the process-global is the preset before, during, after.
        dlg = _dialog(qtbot, _vm(async_session))
        await dlg.begin()
        assert isinstance(current_calendar(), StandardCalendar)
        await _walk_to(dlg, STEP_PREVIEW)
        assert isinstance(current_calendar(), StandardCalendar)
        # …while the preview panel itself painted the assembled custom form.
        assert isinstance(dlg._vm.state.preview_calendar, CustomCalendar)


# ════════════════════ task 6.2 — «Неделя» и «Месяцы» ═════════════════════════


class TestWeekScreen:
    async def test_seven_names_prefill_then_grow_empty_and_shrink_tail(
        self, async_session, qtbot
    ):
        dlg = _dialog(qtbot, _vm(async_session))
        await _walk_to(dlg, STEP_WEEK)

        # «предполнение 7 текущими именами при первой сборке»
        assert [edit.text() for edit in dlg._week_fields] == list(STANDARD_WEEK_NAMES)
        assert (
            dlg._week_length_spin.minimum(),
            dlg._week_length_spin.maximum(),
        ) == (WEEK_LENGTH_MIN, WEEK_LENGTH_MAX)  # «спин 2…168»

        dlg._week_length_spin.setValue(8)  # scenario «Восемь дней недели»

        assert len(dlg._week_fields) == 8
        assert dlg._week_fields[7].text() == ""  # growing adds empty fields
        assert not dlg._next_button.isEnabled()
        assert "у дня недели пустое название" in dlg._problems_label.text()

        dlg._next_button.click()  # a misfired «Далее» must not move the flow
        await dlg.wait_idle()
        assert dlg._stack.currentWidget() is dlg._pages[STEP_WEEK]

        dlg._week_fields[7].setText("Осьмидневик")
        assert dlg._next_button.isEnabled()
        assert dlg._problems_label.text() == ""

        dlg._week_length_spin.setValue(3)  # shrinking drops the tail names
        assert [edit.text() for edit in dlg._week_fields] == list(
            STANDARD_WEEK_NAMES[:3]
        )

    async def test_week_below_two_is_not_even_offerable(self, async_session, qtbot):
        # Scenario «Неделя короче двух»: the spin value 1 is «недоступно».
        dlg = _dialog(qtbot, _vm(async_session))
        await _walk_to(dlg, STEP_WEEK)
        assert dlg._week_length_spin.minimum() == 2


class TestMonthsScreen:
    async def test_gregorian_prefill_lives_in_scroll_rows(self, async_session, qtbot):
        dlg = _dialog(qtbot, _vm(async_session))
        await _walk_to(dlg, STEP_MONTHS)

        assert [edit.text() for edit, _ in dlg._month_rows] == [
            "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
            "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
        ]  # «предполнение 12 григорианскими месяцами»
        assert dlg._month_rows[1][1].value() == 28  # the common-year February
        assert any(
            isinstance(ancestor, QScrollArea)
            for ancestor in iter_parents(dlg._months_box)
        )  # «строки „имя | длина“ со скроллом»

    async def test_adding_uses_free_number_and_shrink_drops_the_tail(
        self, async_session, qtbot
    ):
        dlg = _dialog(qtbot, _vm(async_session))
        await _walk_to(dlg, STEP_MONTHS)

        dlg._month_count_spin.setValue(13)
        assert dlg._month_rows[12][0].text() == "Месяц 1"  # «со свободным номером N»
        assert dlg._month_rows[12][1].value() == 30  # …длиной 30

        dlg._month_count_spin.setValue(10)  # scenario «Сокращение числа месяцев»
        assert len(dlg._month_rows) == 10  # tail months removed
        assert dlg._next_button.isEnabled()  # no intercalary rules → no dangling
        assert dlg._problems_label.text() == ""

    async def test_empty_month_name_blocks_and_freezes_the_preview(
        self, async_session, qtbot
    ):
        dlg = _dialog(qtbot, _vm(async_session))
        await _walk_to(dlg, STEP_MONTHS)
        months_before = dlg._preview._month_combo.count()

        dlg._month_rows[0][0].clear()  # scenario «Невалидная форма не рисует мусор»

        assert not dlg._next_button.isEnabled()
        assert "у месяца пустое название" in dlg._problems_label.text()
        assert dlg._preview._month_combo.count() == months_before  # last valid view

        dlg._next_button.click()
        await dlg.wait_idle()
        assert dlg._stack.currentWidget() is dlg._pages[STEP_MONTHS]  # gate holds


# ════════════════ task 6.3 — вставные дни, предпросмотр, отчёт ═══════════════


class TestIntercalaryScreen:
    async def test_add_preselects_last_month_and_lists_the_rule(
        self, async_session, qtbot
    ):
        dlg = _dialog(qtbot, _vm(async_session))
        await _walk_to(dlg, STEP_INTERCALARY)

        assert dlg._rule_rows == []
        combo = dlg._rule_month_combo
        assert [combo.itemText(index) for index in range(combo.count())][:2] == [
            "Январь",
            "Февраль",
        ]
        assert combo.currentText() == "Декабрь"  # «предвыбором последнего месяца»

        dlg._rule_name_edit.setText("Громовик")
        dlg._rule_add_button.click()

        assert len(dlg._rule_rows) == 1
        assert dlg._rule_rows[0][0].text() == "Громовик → Декабрь"
        assert dlg._rule_name_edit.text() == ""  # the field reopens empty

    async def test_explicit_host_wins_and_survives_the_combo_reseed(
        self, async_session, qtbot
    ):
        dlg = _dialog(qtbot, _vm(async_session))
        await _walk_to(dlg, STEP_INTERCALARY)

        dlg._rule_month_combo.setCurrentIndex(1)  # «Февраль» chosen explicitly
        dlg._rule_name_edit.setText("Веха")
        dlg._rule_add_button.click()

        # the explicitly chosen host won over the preselect…
        assert dlg._vm.state.intercalary[0].after_month == 2
        # …and the reseeding render keeps the selection (no dragged tail)
        assert dlg._rule_month_combo.currentText() == "Февраль"

    async def test_rule_order_is_the_position_order_in_the_preview(
        self, async_session, qtbot
    ):
        dlg = _dialog(qtbot, _vm(async_session))
        await _walk_to(dlg, STEP_INTERCALARY)

        for name in ("Первый гром", "Второй гром"):
            dlg._rule_name_edit.setText(name)
            dlg._rule_add_button.click()
        assert [row[0].text() for row in dlg._rule_rows] == [
            "Первый гром → Декабрь",
            "Второй гром → Декабрь",
        ]

        # The two chips of one host live on the host-month page, in list order.
        dlg._preview._month_combo.setCurrentIndex(11)  # Декабрь
        assert chip_texts(dlg._preview) == ["Первый гром", "Второй гром"]

        # Scenario «Порядок правил значим»: swap via the row's «↑».
        dlg._rule_rows[1][2].click()
        assert [row[0].text() for row in dlg._rule_rows] == [
            "Второй гром → Декабрь",
            "Первый гром → Декабрь",
        ]
        assert chip_texts(dlg._preview) == ["Второй гром", "Первый гром"]

        dlg._rule_rows[0][1].click()  # «Удалить» the first row
        assert [row[0].text() for row in dlg._rule_rows] == ["Первый гром → Декабрь"]
        assert chip_texts(dlg._preview) == ["Первый гром"]

    async def test_host_trimmed_away_captions_by_number_and_blocks_next(
        self, async_session, qtbot
    ):
        # Scenario «Висячий вставной день блокирует» at the dialog level: the
        # kept-but-dangling rule stays listed (captioned by number of its lost
        # host) while «Далее» of the months screen refuses to move.
        dlg = _dialog(qtbot, _vm(async_session))
        await _walk_to(dlg, STEP_INTERCALARY)
        dlg._rule_name_edit.setText("Громовик")
        dlg._rule_add_button.click()  # host Декабрь (12), the preselect
        dlg._back_button.click()  # → месяцы

        dlg._month_count_spin.setValue(5)  # host month 12 is gone beneath it

        assert dlg._vm.state.intercalary[0].after_month == 12  # rule silently KEPT
        assert not dlg._next_button.isEnabled()
        assert (
            "вставной день ссылается на несуществующий месяц"
            in dlg._problems_label.text()
        )

        # The dangling rule still shows on its own screen when reached — the
        # host number now resolves into the re-added tail month («Месяц 1»…).
        dlg._vm.set_month_count(12)  # same list rebuilt → «Далее» valid again
        dlg._next_button.click()
        await dlg.wait_idle()
        assert dlg._stack.currentWidget() is dlg._pages[STEP_INTERCALARY]
        assert dlg._rule_rows[0][0].text() == "Громовик → Месяц 7"

        dlg._vm.add_intercalary("Дыра", 99)  # a host no list can offer
        assert dlg._rule_rows[1][0].text() == "Дыра → месяц №99"

    async def test_invalid_intercalary_name_blocks_next(
        self, async_session, qtbot
    ):
        dlg = _dialog(qtbot, _vm(async_session))
        await _walk_to(dlg, STEP_INTERCALARY)

        dlg._rule_add_button.click()  # adding with the name field left empty

        assert not dlg._next_button.isEnabled()
        assert "у вставного дня пустое название" in dlg._problems_label.text()
        assert dlg._rule_rows[0][0].text() == "«без названия» → Декабрь"


# ════════════════════════ report screen and application ══════════════════════


class TestReportAndApply:
    async def test_empty_report_applies_instantly_without_the_screen(
        self, async_session, qtbot
    ):
        # Scenario «Пустой отчёт не плодит экран» / «Пустая новая игра на пресете».
        dlg = _dialog(qtbot, _vm(async_session))
        await dlg.begin()
        assert dlg._apply_button.isEnabled()  # «Стандартный» preselected

        dlg._apply_button.click()
        await dlg.wait_idle()

        assert dlg.result() == QDialog.DialogCode.Accepted
        assert dlg._stack.currentWidget() is dlg._pages[STEP_CHOICE]  # never left it
        assert await _setting(async_session, CALENDAR_SETTINGS_KEY) == (
            encode_calendar(StandardCalendar())
        )
        assert isinstance(current_calendar(), StandardCalendar)  # activated

    async def test_report_carries_record_names_then_moves_on_confirm(
        self, async_session, qtbot
    ):
        await _add_event(
            async_session, "Бой у реки", date(2023, 1, 15), date(2023, 6, 1)
        )
        dlg = _dialog(qtbot, _vm(async_session))
        await dlg.begin()
        await _custom_months_3x10_on(dlg)
        await _walk_from_months_to_preview(dlg)

        dlg._apply_button.click()
        await dlg.wait_idle()

        assert dlg._stack.currentWidget() is dlg._pages[STEP_REPORT]
        assert not dlg._footer.isVisibleTo(dlg)  # the report carries its own pair
        table = dlg._report_table
        assert [
            [table.item(row, column).text() for column in range(4)]
            for row in range(table.rowCount())
        ] == [
            ["Бой у реки", "начало", "15 Январь 2023", "10 Медвежарь 2023"],
            ["Бой у реки", "конец", "01 Июнь 2023", "10 Травень 2023"],
        ]  # scenario «Отчёт с именами записей»

        dlg._transfer_cancel_button.click()  # «Отменить» — back, nothing applied
        assert dlg._stack.currentWidget() is dlg._pages[STEP_PREVIEW]
        assert dlg._footer.isVisibleTo(dlg)
        assert await _setting(async_session, CALENDAR_SETTINGS_KEY) is None
        assert await _event_dates(async_session) == (
            date(2023, 1, 15),
            date(2023, 6, 1),
        )  # the dry run changed nothing

        dlg._apply_button.click()
        await dlg.wait_idle()
        dlg._transfer_apply_button.click()  # «Перенести и применить»
        await dlg.wait_idle()

        assert dlg.result() == QDialog.DialogCode.Accepted
        assert await _event_coords(async_session) == (
            encode_coord(MonthDay(2023, 1, 10)),
            encode_coord(MonthDay(2023, 3, 10)),
        )
        assert await _setting(async_session, CALENDAR_DRAFT_KEY) is None
        assert isinstance(current_calendar(), CustomCalendar)

    async def test_apply_error_opens_the_reason_window_and_keeps_the_report(
        self, async_session, qtbot, monkeypatch
    ):
        await _add_event(async_session, "Бой у реки", date(2023, 1, 15), None)
        service = CalendarSettingsService()

        async def boom(*args, **kwargs):
            raise RuntimeError("диск отказал")

        monkeypatch.setattr(service, "promote_draft", boom)
        shown: list[tuple[str, str]] = []
        monkeypatch.setattr(
            calendar_wizard.QMessageBox,
            "warning",
            staticmethod(
                lambda parent, title, text, *a, **k: shown.append((title, text))
            ),
        )

        dlg = _dialog(qtbot, _vm(async_session, service))
        await dlg.begin()
        await _custom_months_3x10_on(dlg)
        await _walk_from_months_to_preview(dlg)
        dlg._apply_button.click()
        await dlg.wait_idle()
        assert dlg._stack.currentWidget() is dlg._pages[STEP_REPORT]

        dlg._transfer_apply_button.click()  # the promote falls over
        await dlg.wait_idle()

        # spec «Ошибки применения… окно с причиной»: the reason verbatim…
        assert shown == [(APPLY_ERROR_TITLE, "диск отказал")]
        # …and the wizard stays open on the report screen, list intact.
        assert dlg._stack.currentWidget() is dlg._pages[STEP_REPORT]
        assert dlg._report_table.rowCount() == 1
        assert await _setting(async_session, CALENDAR_SETTINGS_KEY) is None


async def _walk_from_months_to_preview(dlg: CalendarWizardDialog) -> None:
    dlg._next_button.click()  # months → intercalary
    await dlg.wait_idle()
    dlg._next_button.click()  # intercalary → preview
    await dlg.wait_idle()
    assert dlg._stack.currentWidget() is dlg._pages[STEP_PREVIEW]


# ═══════════════════════ task 6.4 — кожа и отключённая тема ═════════════════


def _runtime(tmp_path, *, broken: bool) -> ThemeRuntime:
    tokens = tmp_path / "tokens.json"
    if not broken:
        tokens.write_text(
            tokens_file_path().read_text(encoding="utf-8"), encoding="utf-8"
        )
    return ThemeRuntime(prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=tokens)


class TestSkin:
    async def test_dialog_is_a_chrome_root_of_catalog_roles(
        self, async_session, qtbot, tmp_path
    ):
        runtime = _runtime(tmp_path, broken=False)
        dlg = _dialog(qtbot, _vm(async_session), theme=runtime)
        await dlg.begin()
        await _walk_to(dlg, STEP_MONTHS)

        assert dlg.property("uiRole") == "chrome"  # attach_theme'd dialog root
        runtime.apply()
        assert dlg.styleSheet() == runtime.qss()  # the generated sheet reaches it
        # every input is a catalog «field», the problems readout «status-error»,
        # the screen caption a catalog title — no bespoke styling anywhere
        assert dlg._month_rows[0][0].property("uiRole") == "field"
        assert dlg._month_rows[0][1].property("uiRole") == "field"
        assert dlg._problems_label.property("uiRole") == "status-error"
        month_title = next(
            label
            for label in dlg._stack.currentWidget().findChildren(QLabel)
            if label.property("uiRole") == "title"
        )
        assert month_title.text() == "Месяцы"
        # the preview grid ships the style-facing class names for the popup sheet
        assert isinstance(dlg._preview, GameCalendarGrid)
        popup_sheet = runtime.popup_qss()
        for name in (
            "GameCalendarGrid",
            "GameCalendarCell",
            "GameCalendarIntercalaryChip",
            "GameCalendarDayName",
        ):
            assert name in popup_sheet

    async def test_off_skin_theme_does_not_break_the_flow(
        self, async_session, qtbot, tmp_path
    ):
        runtime = _runtime(tmp_path, broken=True)
        assert runtime.is_valid is False  # theme switched off (design D7)

        dlg = _dialog(qtbot, _vm(async_session), theme=runtime)
        runtime.apply()  # off-skin apply is a no-op, not a crash
        await dlg.begin()

        await _walk_to(dlg, STEP_INTERCALARY)
        dlg._rule_name_edit.setText("Громовик")
        dlg._rule_add_button.click()
        dlg._next_button.click()
        await dlg.wait_idle()
        dlg._apply_button.click()  # empty report → instant apply on preview
        await dlg.wait_idle()

        assert dlg.result() == QDialog.DialogCode.Accepted
        assert await _setting(async_session, CALENDAR_SETTINGS_KEY) is not None
        assert isinstance(current_calendar(), CustomCalendar)
